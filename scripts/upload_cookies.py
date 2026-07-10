"""
scripts/upload_cookies.py — อ่าน test_cookies.json แล้วเขียนเข้า Supabase
รันบนเครื่องตัวเองหลังจาก solve hCaptcha สำเร็จและได้ test_cookies.json มาแล้ว

workflow:
  1. python scripts/test_session.py          → solve hCaptcha → test_cookies.json
  2. python scripts/upload_cookies.py        → เขียน cookies เข้า Supabase
  3. Cloud Run Job อ่านจาก Supabase ตอน run landsmaps

ต้องมี .env ที่มี SUPABASE_URL และ SUPABASE_SERVICE_ROLE_KEY
"""

import json
import sys
from pathlib import Path

# เพิ่ม project root เข้า path เพื่อ import supabase_common ได้
sys.path.insert(0, str(Path(__file__).parent.parent))

from supabase_common import SUPABASE_URL, HEADERS, _request_with_retry

COOKIE_FILE = Path(__file__).parent / "test_cookies.json"  # test_session.py เซฟไว้ที่ scripts/


def main():
    if not COOKIE_FILE.exists():
        print(f"❌ ไม่พบ {COOKIE_FILE}")
        print("   รัน scripts/test_session.py ก่อนเพื่อ solve hCaptcha และได้ cookies มา")
        sys.exit(1)

    with open(COOKIE_FILE, encoding="utf-8") as f:
        cookies = json.load(f)

    if not cookies:
        print("❌ ไฟล์ cookies ว่างเปล่า")
        sys.exit(1)

    print(f"📦 พบ {len(cookies)} cookies ใน {COOKIE_FILE.name}")
    print("   กำลังเขียนเข้า Supabase...")

    # mark active rows เดิมทั้งหมดเป็น inactive ก่อน
    url_deactivate = f"{SUPABASE_URL}/rest/v1/landsmaps_sessions?is_active=eq.true"
    r = _request_with_retry("PATCH", url_deactivate,
                             headers=HEADERS,
                             json={"is_active": False},
                             timeout=15)
    r.raise_for_status()
    print("   ✓ deactivate cookies เดิมแล้ว")

    # insert cookies ใหม่เป็น active
    url_insert = f"{SUPABASE_URL}/rest/v1/landsmaps_sessions"
    r2 = _request_with_retry("POST", url_insert,
                              headers={**HEADERS, "Prefer": "return=representation"},
                              json={"cookies_json": cookies, "is_active": True},
                              timeout=15)
    r2.raise_for_status()
    row = r2.json()[0]
    print(f"   ✅ upload สำเร็จ — session id: {row['id']}, uploaded_at: {row['uploaded_at'][:19]}")
    print(f"\n   พร้อมแล้ว — สั่ง run LandsMaps Collector ได้เลย")
    print(f"   (cookies อายุ ~1-1.5 ชม. นับจากตอน solve hCaptcha)")


if __name__ == "__main__":
    main()
