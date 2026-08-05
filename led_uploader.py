"""
uploader.py — TPIS LED Crawler → Supabase Uploader
=====================================================
อ่าน JSON ที่ crawler บันทึกไว้ แล้ว upsert เข้า Supabase

flow:
  1. อ่าน JSON ทุกไฟล์ใน led_output/
  2. ตัด record ที่ key ซ้ำกัน (led_province_id, str_bid_num, deedno_raw)
     ป้องกัน Postgres error 21000 ตอน upsert (ทั้ง batch พังถ้าไม่กรองก่อน)
  3. map field จาก LED → schema v5
  4. upsert ลง assets (on conflict: led_province_id, str_bid_num, deedno_raw)
  5. upsert ลง asset_bid_rounds (round_no 1-8) — ดึง asset_id แบบ paginate
     (จังหวัดที่มี record เกิน 1,000 ต้องดึงหลายหน้า ไม่งั้นหาไม่เจอแล้วโดน skip)
  6. บันทึก crawler_runs summary

รัน:
  python uploader.py
  python uploader.py --dir led_output --batch 100
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from supabase_common import (
    SUPABASE_URL, HEADERS, BKK_TZ, _request_with_retry,
    sb_upsert, sb_insert_run, sb_update_run, paginated_select,
)
from email_summary import send_led_summary


def _read_code_version() -> str:
    """
    อ่านเวอร์ชันโค้ดจากไฟล์ VERSION ที่ root ของ image
    (COPY เข้า image ตอน docker build พร้อมกับโค้ดอื่น)
    ใช้ env var CODE_VERSION override ได้ถ้าอยากตั้งค่าจากตอน deploy แทน
    คืนค่า "unknown" ถ้าหาไม่เจอ — กันไม่ให้ uploader ล้มเพราะเรื่องนี้
    """
    if os.environ.get("CODE_VERSION"):
        return os.environ["CODE_VERSION"]
    version_path = Path(__file__).parent / "VERSION"
    try:
        return version_path.read_text(encoding="utf-8").strip()
    except Exception:
        return "unknown"


CODE_VERSION = _read_code_version()

# ================================================================
# issale code → text (เหมือนใน parser.py)
# ================================================================
ISSALE_STATUS = {
    "0":  "-",
    "1":  "ขายได้",
    "3":  "งดขายไม่มีผู้สู้ราคา",
    "13": "งดขาย",
    "25": "งดขาย",
}

def issale_to_text(code: str) -> str:
    return ISSALE_STATUS.get(str(code).strip(), f"ไม่ทราบ({code})")

def parse_thai_date(s: str):
    """แปลง "25690813" → "2026-08-13" """
    if not s or s == "0" or len(s) < 8:
        return None
    try:
        y = int(s[:4]) - 543
        m = int(s[4:6])
        d = int(s[6:8])
        return f"{y:04d}-{m:02d}-{d:02d}"
    except Exception:
        return None

def parse_bool(v: Any) -> bool | None:
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return v
    return str(v).strip().upper() in ("T", "TRUE", "1", "YES")

def parse_numeric(v: Any) -> float | None:
    if v is None or v == "" or v == "0":
        return None
    try:
        f = float(str(v).replace(",", "").strip())
        return f if f != 0 else None
    except Exception:
        return None

# ================================================================
# Dedupe — ตัด record ที่ key ซ้ำกันเป๊ะก่อน upsert
# ================================================================
def dedupe_records(records: list[dict]) -> list[dict]:
    """
    ตัด record ที่ key ซ้ำกัน (led_province_id, str_bid_num, deedno_raw)
    ทำตั้งแต่ raw record ก่อนแตกไป map_to_asset/map_to_bid_rounds
    เพื่อป้องกัน Postgres error 21000:
      "ON CONFLICT DO UPDATE command cannot affect row a second time"
    ซึ่งจะทำให้ทั้ง batch (assets หรือ asset_bid_rounds) พังยกก้อนถ้าไม่กรองก่อน
    เก็บ record หลังสุดในไฟล์ไว้ (ข้อมูลล่าสุดที่ crawler เจอ)
    """
    seen: dict[tuple, dict] = {}
    for r in records:
        province_id = r.get("_province_id") or r.get("led_province_id")
        key = (province_id, r.get("str_bid_num"), r.get("deedno_raw") or r.get("deedno", ""))
        seen[key] = r
    deduped = list(seen.values())
    dropped = len(records) - len(deduped)
    if dropped:
        print(f"  ⚠️  ตัดข้อมูลซ้ำ key เดิม {dropped} รายการ ก่อน upsert")
    return deduped


# ================================================================
# Map LED raw dict → assets row
# ================================================================
def map_to_asset(raw: dict) -> dict:
    return {
        # Identifiers
        "str_bid_num":      raw.get("str_bid_num"),
        "fbidnum":          raw.get("fbidnum"),
        "fbidnuml":         raw.get("fbidnuml"),
        "fsubbidnum":       raw.get("fsubbidnum"),

        # ขนาดที่ดิน
        "rai":              parse_numeric(raw.get("rai")),
        "ngan":             parse_numeric(raw.get("quaterrai") or raw.get("ngan")),
        "wa":               parse_numeric(raw.get("wa")),
        "landtype":         raw.get("landtype"),
        "landdesc":         raw.get("landdesc"),
        "deedno_raw":       raw.get("deedno_raw") or raw.get("deedno", ""),
        "deedno":           raw.get("deedno") if isinstance(raw.get("deedno"), list)
                            else ([raw.get("deedno")] if raw.get("deedno") else []),
        "deedno_count":     raw.get("deedno_count") or 0,
        "addrno":           raw.get("addrno"),

        # ที่ตั้ง
        "tumbol":           raw.get("tumbol"),
        "ampur":            raw.get("ampur"),
        "city":             raw.get("city"),
        "deedtumbol":       raw.get("deedtumbol"),
        "deedampur":        raw.get("deedampur"),
        "deedcity":         raw.get("deedcity"),

        # ประเภท
        "asset_type_id":    raw.get("AssetTypeID") or raw.get("asset_type_id"),
        "asset_type_desc":  (raw.get("assettypedesc") or raw.get("asset_type_desc", "")).strip(),

        # คดี
        "law_court_id":     raw.get("law_court_id"),
        "law_court_name":   raw.get("law_court_name"),
        "law_suit_no":      raw.get("law_suit_no"),
        "law_suit_year":    raw.get("law_suit_year"),
        "province_id":      raw.get("province_id"),
        "province_name":    raw.get("province_name"),

        # คู่ความ
        "person1":          raw.get("person1"),
        "person2":          raw.get("person2"),
        "owner_suit_name":  raw.get("owner_suit_name")
                            if isinstance(raw.get("owner_suit_name"), str)
                            else (raw.get("owner_suit_name", [None]) or [None])[0],
        "ownername":        raw.get("ownername"),
        "occupant":         raw.get("occupant"),

        # มัดจำ
        "reserve_fund":     parse_numeric(raw.get("ReserveFund") or raw.get("reserve_fund")),
        "reserve_fund1":    parse_numeric(raw.get("ReserveFund1") or raw.get("reserve_fund1")),

        # ราคา
        "assetprice1":      parse_numeric(raw.get("assetprice1")),
        "assetprice2":      parse_numeric(raw.get("assetprice2")),
        "assetprice3":      parse_numeric(raw.get("assetprice3")),
        "assetprice4":      parse_numeric(raw.get("assetprice4")),
        "assetprice5":      parse_numeric(raw.get("assetprice5")),
        "assetprice6":      parse_numeric(raw.get("assetprice6")),
        "assetprice7":      parse_numeric(raw.get("assetprice7")),
        "assetprice8":      parse_numeric(raw.get("assetprice8")),
        "assetprice9":      parse_numeric(raw.get("assetprice9")),

        # หนี้
        "debtname":         raw.get("debtname"),
        "debtprice":        parse_numeric(raw.get("debtprice")),
        "debtdetail":       raw.get("debtdetail"),

        # สถานะขาย
        "issale":           raw.get("issale"),
        "is_extra_pledgb":  parse_bool(raw.get("is_extra_pledgb")),
        "eauc":             parse_bool(raw.get("eauc")),
        "saletypename":     raw.get("saletypename"),
        "is_closed":        raw.get("is_closed"),
        "is_sold":          raw.get("is_sold"),
        "latest_status":    raw.get("latest_status"),
        "latest_round_no":  raw.get("latest_round_no"),

        # วันที่
        "ischeck_date":     parse_thai_date(raw.get("ischeck_date", "")),
        "remark":           raw.get("remark"),
        "remark1":          raw.get("remark1"),

        # สถานที่ขาย
        "sale_location1":   raw.get("sale_location1"),
        "sale_location2":   raw.get("sale_location2"),
        "sale_time1":       raw.get("sale_time1"),
        "sale_time2":       raw.get("sale_time2"),
        "tel":              raw.get("tel"),
        "auc_asset_gen":    raw.get("auc_asset_gen"),

        # URL รูป
        "url_picture":      raw.get("_url_picture") or raw.get("url_picture"),
        "url_map":          raw.get("_url_map") or raw.get("url_map"),
        "url_mapjot":       raw.get("_url_mapjot") or raw.get("url_mapjot"),
        "landpicture_path": raw.get("landpicture"),

        # Metadata
        "led_province_id":  raw.get("_province_id") or raw.get("led_province_id"),
        "led_province_name":raw.get("_province_name") or raw.get("led_province_name"),
        "form_action":      raw.get("_form_action") or raw.get("form_action"),

        # Timestamp จาก crawler
        "date_modified":    raw.get("date_modified"),
        "scraped_at":       datetime.now(BKK_TZ).isoformat(),
    }


def map_to_bid_rounds(raw: dict, asset_id: int) -> list[dict]:
    """แปลง biddate1-8 / issale1-8 → list of bid round rows"""
    rounds = []
    for i in range(1, 9):
        bid_date   = parse_thai_date(raw.get(f"biddate{i}", ""))
        issale     = str(raw.get(f"issale{i}", "")).strip()
        assetprice = parse_numeric(raw.get(f"assetprice{i}") or raw.get("assetprice3"))

        if not bid_date and not issale:
            continue

        rounds.append({
            "asset_id":    asset_id,
            "round_no":    i,
            "bid_date":    bid_date,
            "asset_price": assetprice,
            "issale_code": issale or "0",
            "status_text": issale_to_text(issale or "0"),
        })
    return rounds


# ================================================================
# Supabase REST helpers
# ================================================================
# ================================================================
# Supabase REST helpers
# ================================================================
# หมายเหตุ: sb_upsert / sb_insert_run / sb_update_run ย้ายไป supabase_common.py
# แล้ว (ใช้ร่วมกับ landsmaps_supabase.py) — import มาจากด้านบนของไฟล์นี้แล้ว

def get_asset_ids(province_id: str) -> dict[str, int]:
    """
    ดึง unique_key → asset_id สำหรับจังหวัดนั้น (สำหรับ upsert bid_rounds)
    ใช้ paginated_select จาก supabase_common — จัดการ pagination ให้อัตโนมัติแล้ว
    (จังหวัดที่มี record เกิน 1,000 เช่นกรุงเทพ 9,000+ ไม่งั้นหา asset_id ไม่เจอ
    บางส่วนแบบเงียบๆ ไม่มี error โผล่ใน log เลย)
    """
    rows = paginated_select(
        table="assets",
        select="id,str_bid_num,deedno_raw",
        filters={"led_province_id": f"eq.{province_id}"},
    )
    return {f"{row['str_bid_num']}|{row['deedno_raw']}": row["id"] for row in rows}


def _count_pending_landsmaps() -> int:
    """
    นับ asset ที่ยังไม่มีพิกัด (ไม่มีใน asset_parcels เลย)
    ใช้แจ้งใน LED email เพื่อเตือนให้ run LandsMaps
    """
    try:
        # นับ asset ทั้งหมด
        url = f"{SUPABASE_URL}/rest/v1/assets"
        r = _request_with_retry("GET", url,
                                 headers={**HEADERS, "Prefer": "count=exact"},
                                 params={"select": "id"}, timeout=30)
        total = int(r.headers.get("content-range", "*/0").split("/")[-1])

        # นับ asset ที่มีพิกัดแล้ว (มีใน asset_parcels อย่างน้อย 1 แถว)
        url2 = f"{SUPABASE_URL}/rest/v1/asset_parcels"
        r2 = _request_with_retry("GET", url2,
                                   headers={**HEADERS, "Prefer": "count=exact"},
                                   params={"select": "asset_id"}, timeout=30)
        r2.raise_for_status()
        rows = r2.json()
        has_parcel = len({row["asset_id"] for row in rows})

        return max(0, total - has_parcel)
    except Exception:
        return 0  # ถ้า query ไม่สำเร็จ ส่ง email ปกติโดยไม่มีตัวเลข


def _count_new_assets(gte_iso: str, lte_iso: str | None = None) -> int:
    """
    นับ asset ที่เป็น "รายการใหม่" ของรอบ run นี้จริงๆ (ไม่ใช่แค่ที่ถูก upsert)

    หลักการ: assets.created_at ตั้งค่าแค่ตอน insert ครั้งแรกเท่านั้น (default now())
    ไม่มี trigger ไหนเขียนทับตอน upsert ซ้ำ (trigger เดียวที่มีคือ trg_assets_updated_at
    ซึ่งแก้แค่ updated_at) — เพราะฉะนั้น asset ที่ "ใหม่จริง" ของรอบนี้ คือแถวที่
    created_at อยู่ในช่วง [started_at, finished_at] ของ run นั้น ส่วน asset เดิมที่ถูก
    upsert ซ้ำ (แค่อัพเดตราคา/สถานะ) จะยังมี created_at เป็นของรอบเก่า ไม่ถูกนับซ้ำ

    คืน 0 ถ้า query ไม่สำเร็จ (metric เสริม ไม่อยากให้ uploader ล้มเพราะเรื่องนี้)
    """
    try:
        url = f"{SUPABASE_URL}/rest/v1/assets"
        if lte_iso:
            params = {"select": "id", "and": f"(created_at.gte.{gte_iso},created_at.lte.{lte_iso})"}
        else:
            params = {"select": "id", "created_at": f"gte.{gte_iso}"}
        r = _request_with_retry(
            "GET", url,
            headers={**HEADERS, "Prefer": "count=exact"},
            params=params, timeout=30,
        )
        r.raise_for_status()
        return int(r.headers.get("content-range", "*/0").split("/")[-1])
    except Exception:
        return 0


# ================================================================
# Main upload logic
# ================================================================
def upload_province(
    json_path: Path,
    run_id: int,
    batch_size: int,
    stats: dict,
):
    print(f"\n📤 อัพโหลด {json_path.name}")
    t0 = time.perf_counter()

    with open(json_path, encoding="utf-8") as f:
        records = json.load(f)

    if not records:
        print(f"  ℹ️  ไม่มีรายการ — ข้าม")
        return

    province_id   = records[0].get("_province_id") or records[0].get("led_province_id", "?")
    province_name = records[0].get("_province_name") or records[0].get("led_province_name", "?")

    # ตัด record ที่ key ซ้ำกันก่อน — ทำที่นี่ทีเดียว ทั้ง assets และ bid_rounds
    # ที่แตกมาจาก records ชุดนี้จะไม่มี key ซ้ำกันอีกต่อไป
    records = dedupe_records(records)
    total   = len(records)   # นับหลัง dedupe ให้ตรงกับที่ upload จริง

    # ---- 1) Upsert assets ----
    asset_rows = [map_to_asset(r) for r in records]

    for i in range(0, total, batch_size):
        batch = asset_rows[i:i + batch_size]
        try:
            sb_upsert(
                "assets",
                batch,
                "led_province_id,str_bid_num,deedno_raw",
            )
            print(f"  assets batch {i//batch_size + 1}: {len(batch)} rows ✅")
        except Exception as e:
            print(f"  ❌ assets batch {i//batch_size + 1} error: {e}")
            stats["errors"].append({"province": province_id, "batch": i, "error": str(e)})

    # ---- 2) Upsert asset_bid_rounds ----
    # ดึง asset_id จาก DB ที่เพิ่ง upsert
    id_map = get_asset_ids(province_id)

    bid_rows: list[dict] = []
    for r in records:
        key      = f"{r.get('str_bid_num')}|{r.get('deedno_raw') or r.get('deedno', '')}"
        asset_id = id_map.get(key)
        if not asset_id:
            continue
        bid_rows.extend(map_to_bid_rounds(r, asset_id))

    if bid_rows:
        for i in range(0, len(bid_rows), batch_size):
            batch = bid_rows[i:i + batch_size]
            try:
                sb_upsert("asset_bid_rounds", batch, "asset_id,round_no")
                print(f"  bid_rounds batch {i//batch_size + 1}: {len(batch)} rows ✅")
            except Exception as e:
                print(f"  ❌ bid_rounds batch error: {e}")

    elapsed = time.perf_counter() - t0
    print(f"  ✅ {province_name} — {total:,} records | {elapsed:.1f}s")

    # สะสม stats
    stats["total_records"]   += total
    stats["total_provinces"] += 1


# ================================================================
# Entry point
# ================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir",   default="led_output", help="โฟลเดอร์ที่มี JSON")
    ap.add_argument("--batch", default=100, type=int, help="batch size per request")
    ap.add_argument("--province", help="อัพโหลดเฉพาะ province_id เช่น 10")
    ap.add_argument("--crawler-exit", default=0, type=int,
                    help="exit code ของ led_crawler.py (ส่งจาก entrypoint เพื่อรู้ว่า crawler fail)")
    args = ap.parse_args()

    crawler_failed = args.crawler_exit != 0

    output_dir = Path(args.dir)
    json_files = sorted(output_dir.glob("*.json"))
    # กรองเอาเฉพาะไฟล์ข้อมูลจังหวัด ไม่เอา progress.json / summary_*.json
    json_files = [
        f for f in json_files
        if not f.stem.startswith("summary_")
        and f.stem != "progress"
    ]

    if args.province:
        json_files = [f for f in json_files if f.stem.startswith(f"{args.province}_")]

    if not json_files:
        print("❌ ไม่พบ JSON files")
        sys.exit(1)

    print(f"🚀 TPIS Uploader — พบ {len(json_files)} ไฟล์จังหวัด")
    print(f"   Supabase URL: {SUPABASE_URL}")
    print(f"   Batch size:   {args.batch}")
    print(f"   Code version: {CODE_VERSION}")

    # สร้าง crawler_run record
    started_at = datetime.now(BKK_TZ).isoformat()
    run_id     = sb_insert_run({
        "started_at":   started_at,
        "status":       "running",
        "run_mode":     "upload",
        "code_version": CODE_VERSION,
        "triggered_by": "cloud_run",
    })
    print(f"   crawler_run id: {run_id}")

    stats = {
        "total_records":   0,
        "total_provinces": 0,
        "errors":          [],
    }

    # ถ้า crawler fail ให้บันทึกเป็น error ทันทีเพื่อให้ email แจ้งถูกต้อง
    if crawler_failed:
        stats["errors"].append({"province": "crawler", "error": f"led_crawler.py exited with code {args.crawler_exit}"})

    t_start = time.perf_counter()

    try:
        for json_file in json_files:
            upload_province(json_file, run_id, args.batch, stats)

        duration = time.perf_counter() - t_start

        # นับรายการใหม่จริง (created_at อยู่ในช่วงรอบนี้) — ใช้โชว์ในหน้า Admin
        finished_at = datetime.now(BKK_TZ).isoformat()
        new_count   = _count_new_assets(started_at, finished_at)
        stats["total_records_new"] = new_count
        print(f"   🆕 รายการใหม่จริง (created_at ในรอบนี้): {new_count:,}")

        # อัพ crawler_run summary
        if run_id:
            sb_update_run(run_id, {
                "finished_at":              finished_at,
                "status":                   "completed" if not stats["errors"] else "partial",
                "total_provinces_success":  stats["total_provinces"],
                "total_records_fetched":    stats["total_records"],
                "total_records_new":        new_count,
                "duration_sec":             round(duration, 2),
                "error_message":            json.dumps(stats["errors"], ensure_ascii=False)
                                            if stats["errors"] else None,
            })

        print(f"\n{'='*50}")
        print(f"✅ อัพโหลดเสร็จ")
        print(f"   จังหวัด:  {stats['total_provinces']}")
        print(f"   Records:  {stats['total_records']:,}")
        print(f"   🆕 ใหม่:  {new_count:,}")
        print(f"   เวลา:     {duration/60:.1f} นาที")
        print(f"   Errors:   {len(stats['errors'])}")
        if stats["errors"]:
            print(f"   ⚠️  มี error — ดูรายละเอียดใน crawler_runs table")
        print(f"{'='*50}")

    except Exception as e:
        duration = time.perf_counter() - t_start
        stats["errors"].append({"province": "uploader", "error": str(e)})
        if run_id:
            sb_update_run(run_id, {
                "finished_at":  datetime.now(BKK_TZ).isoformat(),
                "status":       "failed",
                "error_message": str(e),
            })
        print(f"💥 Uploader ล้มเหลว: {e}")
        raise

    finally:
        # ส่ง email เสมอ ไม่ว่า crawler หรือ uploader จะ fail หรือไม่
        pending = _count_pending_landsmaps()
        send_led_summary(
            stats={
                "total_provinces_success": stats["total_provinces"],
                "total_provinces_failed":  len(stats["errors"]),
                "total_records_fetched":   stats["total_records"],
                "total_records_new":       stats.get("total_records_new", 0),
                "duration_sec":            round(time.perf_counter() - t_start, 2),
                "error_message":           (json.dumps(stats["errors"], ensure_ascii=False)
                                            if stats["errors"] else None),
            },
            pending_landsmaps=pending,
        )


if __name__ == "__main__":
    main()