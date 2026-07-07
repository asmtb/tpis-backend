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
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import requests

# ================================================================
# Config — โหลด .env ถ้ามี (local dev), ถ้าไม่มีใช้ os.environ (GitHub Actions)
# ================================================================
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # ถ้าไม่ได้ติดตั้ง python-dotenv ก็ใช้ os.environ ตรง ๆ ได้เลย


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

SUPABASE_URL          = os.environ.get("SUPABASE_URL") or ""
SUPABASE_SERVICE_KEY  = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    print("❌ ไม่พบ SUPABASE_URL หรือ SUPABASE_SERVICE_ROLE_KEY")
    print("   สร้างไฟล์ .env หรือ set environment variable ก่อนรัน")
    sys.exit(1)

HEADERS = {
    "apikey":        SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "resolution=merge-duplicates,return=representation",
}

BKK_TZ = timezone(timedelta(hours=7))

# retry config — เจอ network error ชั่วคราว (timeout, connection reset, 502/503 ฯลฯ) ให้ลองใหม่
MAX_RETRIES     = 3
RETRY_BACKOFF   = 2   # วินาที คูณ attempt (2, 4, 6)


def _request_with_retry(method: str, url: str, **kwargs) -> requests.Response:
    """
    เรียก requests.request() พร้อม retry แบบ exponential backoff
    ใช้กับทุกจุดที่คุยกับ Supabase REST API เพื่อทนต่อ network error ชั่วคราว
    (timeout, connection reset, DNS ชั่วคราว, 502/503/504 จากฝั่ง server)
    ไม่ retry ถ้าเป็น 4xx (เช่น 403/404) เพราะเป็น error ที่ retry ไปก็ไม่หาย ต้องแก้ config ก่อน
    """
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.request(method, url, **kwargs)
            # 5xx ถือเป็น error ชั่วคราว ลองใหม่ได้ / 4xx ไม่ต้อง retry ให้ raise ทันที
            if r.status_code >= 500:
                raise requests.exceptions.HTTPError(
                    f"{r.status_code} Server Error: {r.text[:200]}", response=r
                )
            return r
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.HTTPError) as e:
            last_exc = e
            is_server_error = isinstance(e, requests.exceptions.HTTPError) and \
                               getattr(e.response, "status_code", 0) >= 500
            is_network_error = isinstance(e, (requests.exceptions.ConnectionError,
                                               requests.exceptions.Timeout))
            if not (is_server_error or is_network_error):
                raise  # 4xx หรือ error อื่นที่ retry ไปก็ไม่หาย ให้ raise ทันที
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF * attempt
                print(f"  🔄 retry #{attempt} ({method} {url.split('?')[0]}) "
                      f"หลัง {wait}s — {e}")
                time.sleep(wait)
    raise last_exc

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
def sb_upsert(table: str, rows: list[dict], on_conflict: str) -> dict:
    """Upsert batch ไป Supabase REST API (พร้อม retry ถ้าเจอ network/5xx error ชั่วคราว)"""
    url = f"{SUPABASE_URL}/rest/v1/{table}?on_conflict={on_conflict}"
    r   = _request_with_retry("POST", url, headers=HEADERS, json=rows, timeout=60)
    r.raise_for_status()
    return {"inserted": len(rows), "status": r.status_code}


def sb_insert_run(run: dict) -> int | None:
    """Insert crawler_runs row คืน id (พร้อม retry)"""
    url  = f"{SUPABASE_URL}/rest/v1/crawler_runs"
    hdrs = {**HEADERS, "Prefer": "return=representation"}
    r    = _request_with_retry("POST", url, headers=hdrs, json=run, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data[0]["id"] if data else None


def sb_update_run(run_id: int, patch: dict):
    """อัพเดต crawler_runs summary (พร้อม retry)"""
    url = f"{SUPABASE_URL}/rest/v1/crawler_runs?id=eq.{run_id}"
    r   = _request_with_retry("PATCH", url, headers=HEADERS, json=patch, timeout=30)
    r.raise_for_status()


def get_asset_ids(province_id: str) -> dict[str, int]:
    """
    ดึง unique_key → asset_id สำหรับจังหวัดนั้น (สำหรับ upsert bid_rounds)
    ⚠️ PostgREST จำกัดผลลัพธ์ default ไว้ 1,000 แถวต่อ request (ตัดเงียบๆ ไม่ error)
    จังหวัดที่มี record เกิน 1,000 (เช่นกรุงเทพ 9,000+) ต้อง paginate ด้วย Range header
    ไม่งั้น record ที่เกิน 1,000 แถวแรกจะหา asset_id ไม่เจอ แล้วโดน skip
    ตอนสร้าง bid_rows แบบเงียบๆ ไม่มี error โผล่ใน log เลย
    """
    url        = f"{SUPABASE_URL}/rest/v1/assets"
    page_size  = 1000
    offset     = 0
    id_map: dict[str, int] = {}

    while True:
        hdrs = {
            **HEADERS,
            "Prefer": "count=exact",
            "Range-Unit": "items",
            "Range": f"{offset}-{offset + page_size - 1}",
        }
        params = {
            "select":          "id,str_bid_num,deedno_raw",
            "led_province_id": f"eq.{province_id}",
            "order":           "id",
        }
        r = _request_with_retry("GET", url, headers=hdrs, params=params, timeout=60)
        r.raise_for_status()
        page = r.json()

        for row in page:
            id_map[f"{row['str_bid_num']}|{row['deedno_raw']}"] = row["id"]

        if len(page) < page_size:
            break  # หน้าสุดท้ายแล้ว (ได้น้อยกว่า page_size แถว)
        offset += page_size

    return id_map


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
    args = ap.parse_args()

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

    t_start = time.perf_counter()

    for json_file in json_files:
        upload_province(json_file, run_id, args.batch, stats)

    duration = time.perf_counter() - t_start

    # อัพ crawler_run summary
    if run_id:
        sb_update_run(run_id, {
            "finished_at":              datetime.now(BKK_TZ).isoformat(),
            "status":                   "completed" if not stats["errors"] else "partial",
            "total_provinces_success":  stats["total_provinces"],
            "total_records_fetched":    stats["total_records"],
            "duration_sec":             round(duration, 2),
            "error_message":            json.dumps(stats["errors"], ensure_ascii=False)
                                        if stats["errors"] else None,
        })

    print(f"\n{'='*50}")
    print(f"✅ อัพโหลดเสร็จ")
    print(f"   จังหวัด:  {stats['total_provinces']}")
    print(f"   Records:  {stats['total_records']:,}")
    print(f"   เวลา:     {duration/60:.1f} นาที")
    print(f"   Errors:   {len(stats['errors'])}")
    if stats["errors"]:
        print(f"   ⚠️  มี error — ดูรายละเอียดใน crawler_runs table")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()