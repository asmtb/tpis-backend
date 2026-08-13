"""
landsmaps_supabase.py — เชื่อม LandsMaps collector กับ Supabase โดยตรง
แทนที่การอ่าน led_all_assets.json + landsmaps_coordinates.json แบบไฟล์ local

ครอบคลุมกลุ่ม 5 ทั้ง 3 ข้อ:
  5.1 — get_new_assets(): ดึงเฉพาะ asset ใหม่กว่า checkpoint ล่าสุดที่สำเร็จ
  5.2 — get_cached_parcels(): cache มาจากตาราง parcels ใน Supabase เอง
        (persistent ข้ามการรันได้จริง ต่างจากไฟล์ local ที่หายเวลารันบน
        Cloud Run เพราะดิสก์เป็นแบบชั่วคราว)
  5.3 — is_retryable(): matched/partial_match/not_verified ไม่ retry เลย,
        not_found retry ได้แต่มี cooldown (NOT_FOUND_COOLDOWN_DAYS วัน)

หมายเหตุการออกแบบ: import ฟังก์ชันพื้นฐาน (SUPABASE_URL, HEADERS,
_request_with_retry, sb_insert_run, sb_update_run, paginated_select)
จาก supabase_common.py — ไฟล์กลางที่ led_uploader.py ก็ใช้ร่วมกัน
แทนที่จะ copy โค้ดซ้ำหรือผูกกับ led_uploader.py โดยตรง
"""

from datetime import datetime, timedelta, timezone

from supabase_common import (
    SUPABASE_URL,
    HEADERS,
    BKK_TZ,
    _request_with_retry,
    sb_insert_run,
    sb_update_run,
    paginated_select,
)
from landsmaps_config import NOT_FOUND_COOLDOWN_DAYS


# ================================================================
# 5.1 — Checkpoint: ดึงเฉพาะ asset ใหม่กว่ารอบที่สำเร็จล่าสุด
# ================================================================
def get_checkpoint() -> str | None:
    """
    หา finished_at ล่าสุดของรอบ landsmaps ที่ status='completed'
    คืน None ถ้ายังไม่เคยรันสำเร็จเลย (รอบแรก — ดึงทั้งหมด)
    """
    url = f"{SUPABASE_URL}/rest/v1/crawler_runs"
    params = {
        "select":   "finished_at",
        "run_mode": "eq.landsmaps",
        "status":   "eq.completed",
        "order":    "finished_at.desc",
        "limit":    "1",
    }
    r = _request_with_retry("GET", url, headers=HEADERS, params=params, timeout=30)
    r.raise_for_status()
    rows = r.json()
    return rows[0]["finished_at"] if rows else None


def get_new_assets(checkpoint: str | None) -> list[dict]:
    """
    ดึง asset จาก Supabase ที่ scraped_at ใหม่กว่า checkpoint
    (หรือทั้งหมดถ้า checkpoint เป็น None — รอบแรก)
    ใช้ paginated_select จาก supabase_common — ไม่ต้องเขียน pagination loop เอง
    """
    fields = ("id,deedno,deedno_raw,city,ampur,deedcity,deedampur,"
              "asset_type_id,rai,ngan,wa,led_province_id,scraped_at")
    filters = {"scraped_at": f"gt.{checkpoint}"} if checkpoint else None
    return paginated_select(table="assets", select=fields, filters=filters)


# ================================================================
# 5.2 — Parcel cache จากตาราง parcels เอง (ไม่ใช้ไฟล์ local อีกต่อไป)
# ================================================================
def get_cached_parcels() -> dict[str, dict]:
    """
    โหลด parcels ทั้งหมดจาก Supabase มาเป็น dict ใน memory ครั้งเดียวตอนเริ่ม job
    key: f"{provid}_{amph2}_{parcelno}" — เหมือน cache_key เดิมที่ใช้กับไฟล์ local
    value: {"id": parcel_id, "verify_status": ..., "last_attempted_at": ...}
    """
    rows = paginated_select(
        table="parcels",
        select="id,provid,amph2,parcelno,verify_status,last_attempted_at",
    )
    return {f"{row['provid']}_{row['amph2']}_{row['parcelno']}": row for row in rows}


# ================================================================
# 5.3 — Retry policy แยกตาม verify_status
# ================================================================
def is_retryable(cached_entry: dict | None) -> bool:
    """
    ตัดสินว่า parcel นี้ควรยิง API ใหม่ไหม
      - ไม่เคยมีใน cache เลย                  → True (ยิงแน่นอน)
      - matched/partial_match/not_verified   → False (ไม่ retry เลย — เชื่อผลเดิม)
      - manual                                → False (แอดมินกรอกเอง — ห้ามทับเด็ดขาด)
      - mismatch/error                        → True (ลองใหม่ได้เสมอ — อาจแก้ไขแล้ว)
      - not_found                             → True เฉพาะถ้าเกิน cooldown แล้ว
    """
    if cached_entry is None:
        return True

    status = cached_entry.get("verify_status")
    if status in ("matched", "partial_match", "not_verified", "manual"):
        return False
    if status == "not_found":
        last_attempted = cached_entry.get("last_attempted_at")
        if not last_attempted:
            return True
        last_dt = datetime.fromisoformat(last_attempted.replace("Z", "+00:00"))
        cooldown_until = last_dt + timedelta(days=NOT_FOUND_COOLDOWN_DAYS)
        return datetime.now(timezone.utc) >= cooldown_until
    return True  # mismatch/error — ลองใหม่ได้เสมอ


def _clean_numeric(val):
    """
    แปลง numeric value ที่ LandsMaps API ส่งมาเป็น string คั่น comma
    ให้เป็น float ที่ PostgreSQL รับได้
    เช่น "53,000" → 53000.0, "1,234.56" → 1234.56, None → None
    """
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return val
    try:
        return float(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


# fields ที่เป็น numeric ใน parcels table — ต้องผ่าน _clean_numeric ก่อน upsert
_NUMERIC_FIELDS = {"land_price_per_sqw", "rai", "ngan", "wa", "latitude", "longitude"}


# ================================================================
# เขียนผลกลับเข้า Supabase
# ================================================================
def upsert_parcel(provid: str, amph2: str, parcelno: str, data: dict) -> int:
    """
    Upsert 1 แถวเข้า parcels คืน parcel_id
    data ต้องมี: verify_status, verify_note (optional), แล้วก็ field พิกัด/ราคาที่เหลือ
    """
    url = f"{SUPABASE_URL}/rest/v1/parcels?on_conflict=provid,amph2,parcelno"

    # clean numeric fields — LandsMaps API ส่งตัวเลขเป็น string คั่น comma เช่น "53,000"
    # PostgreSQL numeric column รับ format นี้ไม่ได้ ต้องแปลงก่อนส่ง
    cleaned_data = {
        k: (_clean_numeric(v) if k in _NUMERIC_FIELDS else v)
        for k, v in data.items()
    }

    row = {
        "provid": provid, "amph2": amph2, "parcelno": parcelno,
        "last_attempted_at": datetime.now(BKK_TZ).isoformat(),
        **cleaned_data,
    }
    hdrs = {**HEADERS, "Prefer": "resolution=merge-duplicates,return=representation"}
    r = _request_with_retry("POST", url, headers=hdrs, json=[row], timeout=30)
    if not r.ok:
        print(f"  ❌ upsert_parcel failed {r.status_code}: {r.text[:500]}")
        print(f"     row sent: provid={provid!r} amph2={amph2!r} parcelno={parcelno!r}")
        print(f"     data keys: {list(data.keys())}")
    r.raise_for_status()
    result = r.json()
    return result[0]["id"]


def link_asset_parcel(asset_id: int, parcel_id: int, area_match: bool | None, area_note: str | None):
    """Upsert ความสัมพันธ์ asset ↔ parcel เข้า asset_parcels"""
    url = f"{SUPABASE_URL}/rest/v1/asset_parcels?on_conflict=asset_id,parcel_id"
    row = {
        "asset_id": asset_id, "parcel_id": parcel_id,
        "area_match": area_match, "area_note": area_note,
    }
    hdrs = {**HEADERS, "Prefer": "resolution=merge-duplicates"}
    r = _request_with_retry("POST", url, headers=hdrs, json=[row], timeout=30)
    r.raise_for_status()


# ================================================================
# crawler_runs — ใช้ pattern เดียวกับ led_uploader (run_mode='landsmaps')
# ================================================================
def start_run() -> int | None:
    return sb_insert_run({
        "started_at":   datetime.now(BKK_TZ).isoformat(),
        "status":       "running",
        "run_mode":     "landsmaps",
        "triggered_by": "cloud_run",
    })


def finish_run(run_id: int, stats: dict, success: bool):
    if not run_id:
        return
    if stats.get("suspected_ip_block"):
        error_message = (
            f"suspected_ip_block=True stopped_at={stats.get('stopped_at_index')}/"
            f"{stats.get('total', 0)} last_asset_id={stats.get('stopped_at_asset_id')}"
        )
    elif not success:
        error_message = f"errors={stats.get('errors', 0)}"
    else:
        error_message = None

    sb_update_run(run_id, {
        "finished_at": datetime.now(BKK_TZ).isoformat(),
        "status":      "completed" if success else "partial",
        "total_records_fetched": stats.get("found", 0) + stats.get("not_found", 0),
        "error_message": error_message,
    })
