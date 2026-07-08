"""
test_reuse_cookies.py — ทดสอบว่า cookies ที่เซฟไว้ใน test_cookies.json ยัง reuse ได้ไหม
โดยไม่เปิด Playwright ใหม่ (ไม่ต้องแก้ captcha ซ้ำ) — เพื่อดูว่า cookies อยู่ได้นานแค่ไหน

วิธีใช้:
  1. รันครั้งแรกทันทีหลัง test_session.py เซฟ cookies ใหม่ → ควรผ่าน (baseline)
  2. รันซ้ำห่างออกไปเรื่อยๆ (1 ชม., 3 ชม., 6 ชม., วันถัดไป ...) จนกว่าจะไม่ผ่าน
     → ตัวเลขที่ได้คือ "อายุ cookies จริง" ใช้ตัดสินใจว่าต้อง cache/alert ถี่แค่ไหน

รัน:
    python test_reuse_cookies.py
"""

import json
import sys

sys.path.insert(0, '.')

from landsmaps_logger import LandsMapsLogger
from landsmaps_session import SessionManager, _USER_AGENT
from landsmaps_config import BASE

COOKIE_FILE = "test_cookies.json"

# ---- แก้ 3 ค่านี้เป็นเคสที่รู้ผลอยู่แล้ว (เช่นจากตอน run 9,000 รายการที่ผ่านมา) ----
# ยิ่งเป็น parcel ที่เคย "matched" มาก่อน ยิ่งมั่นใจได้ว่าผลลบ (result={}) ไม่ได้มาจากเลขผิด
TEST_PROVID = "10"
TEST_AMPH2  = "05"
TEST_DEEDNO = "1234"


def main():
    logger = LandsMapsLogger()
    mgr = SessionManager(logger, headless=True)  # ไม่สำคัญ เพราะไม่เปิด Playwright รอบนี้

    try:
        # ---------- 1) โหลด cookies จากไฟล์ ----------
        with open(COOKIE_FILE, encoding="utf-8") as f:
            cookies_dict = json.load(f)

        if not cookies_dict:
            print(f"❌ {COOKIE_FILE} ว่างเปล่า — ยังไม่มี cookies ให้ทดสอบ "
                  f"(รัน test_session.py ให้สำเร็จก่อน)")
            sys.exit(1)

        for name, value in cookies_dict.items():
            mgr.session.cookies.set(name, value, domain="landsmaps.dol.go.th")

        # headers ปกติจะถูกตั้งตอน init_session() ใน Playwright flow
        # แต่รอบนี้ข้าม Playwright ไปเลย ต้องตั้งเองให้เหมือนเดิม
        mgr.session.headers.update({
            "User-Agent":      _USER_AGENT,
            "Accept":          "application/json, text/plain, */*",
            "Accept-Language": "th-TH,th;q=0.9,en;q=0.8",
            "Referer":         f"{BASE}/",
            "Origin":          BASE,
        })

        print(f"📦 โหลด {len(cookies_dict)} cookies จาก {COOKIE_FILE} แล้ว")

        # ---------- 2) ทดสอบขอ JWT ใหม่ด้วย cookies เดิม (ไม่เปิด Playwright) ----------
        print("🔄 ทดสอบ refresh_jwt() ด้วย cookies เดิม...")
        ok = mgr.refresh_jwt()
        print(f"   refresh_jwt: {'✅ ผ่าน' if ok else '❌ ไม่ผ่าน — cookies หมดอายุ/ติด Incapsula แล้ว'}")

        if not ok:
            print("\n⚠️  สรุป: cookies ชุดนี้ใช้ไม่ได้แล้ว ณ เวลานี้ "
                  "→ ต้องเปิด Playwright + แก้ captcha ใหม่รอบหน้า")
            return

        # ---------- 3) ทดสอบยิง fetch_parcel จริง 1 รายการ ----------
        print(f"🔄 ทดสอบ fetch_parcel({TEST_PROVID}, {TEST_AMPH2}, {TEST_DEEDNO})...")
        result = mgr.fetch_parcel(TEST_PROVID, TEST_AMPH2, TEST_DEEDNO)

        if result is None:
            print("   ❌ Error — network หรือ retry ครบแล้วไม่ผ่าน (อาจไม่เกี่ยวกับ cookies)")
        elif result == {}:
            print("   ⚠️  ยิงสำเร็จ (session ยังใช้ได้!) แต่ไม่พบ parcel นี้ "
                  "— ลองแก้ TEST_PROVID/AMPH2/DEEDNO เป็นเคสที่เคย matched จริง")
        else:
            print("   ✅ ยิงสำเร็จ ได้ข้อมูลจริงกลับมา — cookies ยังใช้งานได้ปกติ:")
            print(f"      {json.dumps(result, ensure_ascii=False, indent=2)[:500]}")

        print("\n📝 บันทึกเวลาที่ทดสอบครั้งนี้ไว้ เทียบกับเวลาที่เซฟ cookies ครั้งแรก "
              "เพื่อคำนวณอายุ cookies จริง")

    finally:
        logger.close()


if __name__ == "__main__":
    main()
