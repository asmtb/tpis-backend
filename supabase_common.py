"""
supabase_common.py — ของกลางสำหรับคุยกับ Supabase REST API
ใช้ร่วมกันระหว่าง led_uploader.py (LED) และ landsmaps_supabase.py (LandsMaps)
เพื่อไม่ให้ต้อง copy env loading / retry wrapper / pagination ซ้ำกันสองที่

ทั้งสองฝั่งต้องคุย Supabase แบบเดียวกัน (REST API, service_role, retry policy
เดียวกัน) — การรวมไว้ที่นี่ทำให้แก้ retry policy หรือ auth ครั้งเดียวมีผลทั้งคู่
"""

import os
import sys
import time
from datetime import timezone, timedelta

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # ถ้าไม่ได้ติดตั้ง python-dotenv ก็ใช้ os.environ ตรง ๆ ได้เลย

SUPABASE_URL         = os.environ.get("SUPABASE_URL") or ""
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""

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
MAX_RETRIES   = 3
RETRY_BACKOFF = 2   # วินาที คูณ attempt (2, 4, 6)

PAGE_SIZE = 1000  # PostgREST default limit ต่อ request — ใช้ paginate ทุกจุดที่ดึงข้อมูลเยอะ


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
                raise
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF * attempt
                print(f"  🔄 retry #{attempt} ({method} {url.split('?')[0]}) "
                      f"หลัง {wait}s — {e}")
                time.sleep(wait)
    raise last_exc


def paginated_select(table: str, select: str, filters: dict | None = None,
                      order: str = "id") -> list[dict]:
    """
    ดึงข้อมูลทั้งหมดจากตาราง โดย paginate ด้วย Range header อัตโนมัติ
    (PostgREST จำกัดผลลัพธ์ default 1,000 แถวต่อ request — ตัดเงียบๆ ไม่ error
    ถ้าไม่ paginate จะได้ข้อมูลไม่ครบแบบไม่รู้ตัว)

    filters: dict ของ query param แบบ PostgREST เช่น {"led_province_id": "eq.10"}
    """
    url    = f"{SUPABASE_URL}/rest/v1/{table}"
    offset = 0
    rows: list[dict] = []

    while True:
        hdrs = {**HEADERS, "Range-Unit": "items",
                "Range": f"{offset}-{offset + PAGE_SIZE - 1}"}
        params = {"select": select, "order": order}
        if filters:
            params.update(filters)

        r = _request_with_retry("GET", url, headers=hdrs, params=params, timeout=60)
        r.raise_for_status()
        page = r.json()
        rows.extend(page)

        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    return rows


def sb_upsert(table: str, rows: list[dict], on_conflict: str) -> dict:
    """Upsert batch ไป Supabase REST API (พร้อม retry ถ้าเจอ network/5xx error ชั่วคราว)"""
    url = f"{SUPABASE_URL}/rest/v1/{table}?on_conflict={on_conflict}"
    r   = _request_with_retry("POST", url, headers=HEADERS, json=rows, timeout=60)
    r.raise_for_status()
    return {"inserted": len(rows), "status": r.status_code}


def sb_insert_run(run: dict) -> int | None:
    """Insert crawler_runs row คืน id (พร้อม retry) — ใช้ร่วมกันทั้ง LED และ LandsMaps"""
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
