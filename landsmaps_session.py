"""
landsmaps_session.py — จัดการ session/JWT/cookies อัตโนมัติด้วย Playwright
(กลุ่ม 4: แทนที่ Copy_as_cURL.txt ที่ต้อง copy cookies ด้วยมือทุกครั้งที่หมดอายุ)

เปิด Chromium ผ่าน Playwright ไปที่ landsmaps.dol.go.th ให้ผ่าน
Imperva/Incapsula challenge เอง แล้วดึง cookies จาก browser context
มาใช้กับ requests.Session ต่อ — pattern เดียวกับ session.py ของ LED
(ที่แก้ CAPTCHA อัตโนมัติ) แต่ต่างกันตรงที่นี่ไม่มี CAPTCHA ให้กรอก
แค่ต้องรอให้ JS challenge ของ Incapsula รันจบแล้วดึง cookies ที่ได้มา

⚠️ ข้อจำกัดที่ต้องรู้: Incapsula ออกแบบมาเพื่อตรวจจับ headless browser
โดยเฉพาะ — ไม่การันตีว่าจะผ่านทุกครั้งเหมือน CAPTCHA ของ LED ต้องทดสอบจริง
ถ้าไม่ผ่านบ่อย ให้ลอง headless=False ก่อน (ใช้ Xvfb บน Cloud Run) หรือดู
ทางเลือกสำรองที่แจ้งไว้ตอนส่งไฟล์นี้
"""

import re
import time

import requests
from playwright.sync_api import sync_playwright

from landsmaps_config import API_BASE, BASE, JWT_EP, RETRY_MAX, RETRY_DELAY

_USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")


class SessionManager:
    def __init__(self, logger, headless: bool = True):
        self.logger      = logger
        self.headless    = headless
        self.session     = requests.Session()
        self.renew_count = 0
        self._amphur_cache: dict[str, dict] = {}

    def init_session(self) -> bool:
        """
        เปิด Playwright ไปที่ landsmaps.dol.go.th ให้ผ่าน Incapsula เอง
        แล้วโอน cookies เข้า requests.Session จากนั้นขอ JWT token ต่อทันที
        เรียกซ้ำได้ทุกครั้งที่ cookies หมดอายุ (ไม่ต้องมีคน copy cURL อีกต่อไป)
        """
        self.renew_count += 1
        self.logger.info(f"🔑 เปิด Playwright ขอ session ใหม่ (ครั้งที่ {self.renew_count})")

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=self.headless,
                    args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
                )
                ctx = browser.new_context(
                    user_agent=_USER_AGENT,
                    viewport={"width": 1280, "height": 800},
                    locale="th-TH",
                )
                page = ctx.new_page()
                page.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
                )

                page.goto(f"{BASE}/", wait_until="networkidle", timeout=30_000)
                # รอให้ Incapsula JS challenge (ถ้ามี) ทำงานจนออก cookies ให้ครบ
                time.sleep(3)

                cookies = ctx.cookies()
                browser.close()
        except Exception as e:
            self.logger.error(f"❌ เปิดหน้า landsmaps ด้วย Playwright ไม่สำเร็จ: {e}")
            return False

        self.session.cookies.clear()
        for c in cookies:
            self.session.cookies.set(
                c["name"], c["value"], domain=c.get("domain", "").lstrip(".")
            )

        self.session.headers.update({
            "User-Agent":      _USER_AGENT,
            "Accept":          "application/json, text/plain, */*",
            "Accept-Language": "th-TH,th;q=0.9,en;q=0.8",
            "Referer":         f"{BASE}/",
            "Origin":          BASE,
        })

        ok = self.refresh_jwt()
        if ok:
            self.logger.info("✅ ได้ session + JWT ใหม่จาก Playwright สำเร็จ")
        else:
            self.logger.warning("⚠️  ได้ cookies แล้วแต่ขอ JWT ไม่ผ่าน — อาจโดน Incapsula บล็อกอยู่")
        return ok

    def refresh_jwt(self) -> bool:
        """ขอ JWT access token ใหม่ด้วย cookies ที่มีอยู่ (ไม่เปิด Playwright ซ้ำ)"""
        try:
            r = self.session.get(JWT_EP, timeout=15)
            r.encoding = "utf-8"
            if "_Incapsula" in r.text:
                return False
            m = re.search(r'"access_token"\s*:\s*"(eyJ[^"]+)"', r.text)
            if m:
                self.session.headers["Authorization"] = f"Bearer {m.group(1)}"
                return True
        except Exception:
            pass
        return False

    def fetch_parcel(self, provid: str, amph2: str, deedno: str):
        """
        ดึงข้อมูล parcel เดียว คืน:
          - dict ถ้าเจอ
          - {} ถ้าไม่เจอ (ยิงสำเร็จแต่ผลว่าง)
          - None ถ้า error (network/retry ครบแล้วยังไม่ผ่าน)
        ถ้าเจอ Incapsula กลางทาง จะเปิด Playwright ใหม่อัตโนมัติ (ไม่ใช่แค่ refresh_jwt
        เพราะปัญหาจริงคือ cookies หมดอายุ ไม่ใช่แค่ JWT)
        """
        url = f"{API_BASE}/GetParcelByParcelNo/{provid}/{amph2}/{deedno}"
        for attempt in range(1, RETRY_MAX + 1):
            try:
                r = self.session.get(url, timeout=15)
                r.encoding = "utf-8"
                if "_Incapsula" in r.text:
                    self.logger.warning("  ⚠️  Incapsula/session หมดอายุ — เปิด Playwright ใหม่")
                    if self.init_session():
                        time.sleep(2)
                        continue
                    return None
                if r.status_code == 200:
                    results = r.json().get("result", [])
                    return results[0] if results else {}
            except Exception as e:
                if attempt < RETRY_MAX:
                    time.sleep(RETRY_DELAY)
                else:
                    self.logger.error(f"  ❌ Error {provid}/{amph2}/{deedno}: {e}")
        return None

    @staticmethod
    def clean_amphur(name: str) -> str:
        """ตัดวงเล็บและข้อความพิเศษออก เช่น 'ดุสิต(บางซื่อ)' → 'ดุสิต'"""
        name = name.strip()
        name = re.sub(r'\s*[\(\（][^\)\）]*[\)\）]', '', name)
        name = re.sub(r'\s*,.*$', '', name)
        return name.strip()

    def get_amph2(self, provid: str, amphur_name: str, bkk_amph_dol: dict) -> str | None:
        """แปลงชื่ออำเภอ → dol code 2 หลัก"""
        cleaned = self.clean_amphur(amphur_name)

        if provid == "10":
            code = bkk_amph_dol.get(cleaned)
            if code:
                return code
            for k, v in bkk_amph_dol.items():
                if cleaned in k or k in cleaned:
                    return v
            return None

        if provid not in self._amphur_cache:
            try:
                r = self.session.get(f"{BASE}/apiService/Master/GetAmphoe/{provid}", timeout=10)
                r.encoding = "utf-8"
                if "_Incapsula" in r.text:
                    self.logger.warning("  ⚠️  Incapsula ตอนขอ amphur list — เปิด Playwright ใหม่")
                    if self.init_session():
                        r = self.session.get(f"{BASE}/apiService/Master/GetAmphoe/{provid}", timeout=10)
                        r.encoding = "utf-8"

                cache = {}
                if r.status_code == 200 and "_Incapsula" not in r.text:
                    data = r.json()
                    items = data.get("result", []) if isinstance(data, dict) else data
                    for a in (items if isinstance(items, list) else []):
                        n = (a.get("amphur_name_th") or a.get("amphurname") or
                             a.get("name_th") or a.get("name") or "")
                        c = (a.get("amphur_id") or a.get("amphurid") or
                             a.get("id") or a.get("code") or "")
                        if n and c:
                            cache[n] = str(c).zfill(4)[-2:]
                self._amphur_cache[provid] = cache
            except Exception:
                self._amphur_cache[provid] = {}
            time.sleep(0.3)

        cache = self._amphur_cache.get(provid, {})
        code = cache.get(cleaned)
        if not code:
            for k, v in cache.items():
                if cleaned in k or k in cleaned:
                    return v
        return code
