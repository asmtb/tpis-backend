"""
session.py — จัดการ Playwright session + cookie reuse
Strategy: reuse session ข้ามจังหวัด ถ้า expire ค่อย renew
"""

import re
import time

import requests
from playwright.sync_api import sync_playwright


class SessionManager:
    def __init__(self, logger, target_url: str, post_url: str, headless: bool = True):
        self.logger     = logger
        self.target_url = target_url
        self.post_url   = post_url
        self.headless   = headless
        self.session    = self._make_requests_session()
        self.renew_count = 0

    def _make_requests_session(self) -> requests.Session:
        s = requests.Session()
        s.headers.update({
            "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
            "Content-Type":    "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer":         self.target_url,
            "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "th,en;q=0.9",
        })
        return s

    def _read_captcha(self, page) -> str | None:
        """อ่าน CAPTCHA จากหน้าเว็บ — ลองหลาย selector"""
        for sel in ["#opass", "input[name=oseckey]"]:
            try:
                val = page.eval_on_selector(sel, "e => e.value")
                if val and val.strip():
                    return val.strip()
            except Exception:
                pass
        for sel in ["span[style*='color']", "b", "strong"]:
            try:
                for el in page.query_selector_all(sel):
                    txt = el.inner_text().strip()
                    if re.match(r"^\d{4,8}$", txt):
                        return txt
            except Exception:
                pass
        return None

    def _transfer_cookies(self, pw_cookies: list):
        """โอน cookies จาก Playwright → requests session"""
        self.session.cookies.clear()
        for c in pw_cookies:
            self.session.cookies.set(
                c["name"], c["value"],
                domain=c.get("domain", "").lstrip(".")
            )

    def init_session(self, province_id: str, province_name: str) -> str:
        """
        เปิด Playwright, แก้ CAPTCHA, submit ค้นหาจังหวัดนั้น
        คืน HTML ของหน้าแรกที่ได้
        """
        self.logger.session_init(province_id)
        self.renew_count += 1

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.headless,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            ctx = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
            )
            page = ctx.new_page()
            page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
            )

            page.goto(self.target_url, wait_until="networkidle", timeout=30_000)
            time.sleep(2)

            # ปิด popup ยอมรับ (ถ้ามี)
            try:
                btn = page.query_selector("button:has-text('ยอมรับ')")
                if btn and btn.is_visible():
                    btn.click()
                    time.sleep(1)
            except Exception:
                pass

            captcha = self._read_captcha(page)
            self.logger.log.info(f"  🔑 CAPTCHA = {captcha} (จังหวัด {province_id})")

            if not captcha:
                browser.close()
                raise RuntimeError(f"ไม่พบ CAPTCHA สำหรับจังหวัด {province_id}")

            # เลือกจังหวัดและ submit
            page.select_option("#provinces", value=province_id)
            time.sleep(2)
            page.evaluate(
                f"document.querySelector('input[name=province]').value = '{province_name}'"
            )
            page.fill("input[name=seckey]", captcha)

            # click แล้วรอให้ navigation เสร็จสมบูรณ์ก่อน
            # แก้ bug "Unable to retrieve content because the page is navigating"
            # ที่เกิดกับสมุทรสงครามและบางจังหวัดเพราะ page.content() ถูกเรียกเร็วเกินไป
            try:
                with page.expect_navigation(wait_until="networkidle", timeout=30_000):
                    page.evaluate("document.getElementById('GFG_Button')?.click()")
            except Exception:
                # บางจังหวัดไม่มี navigation event (โหลดในหน้าเดิม) รอแบบ fallback แทน
                page.wait_for_load_state("networkidle", timeout=15_000)

            page.wait_for_load_state("domcontentloaded")
            time.sleep(1)

            html_p1 = page.content()
            self._transfer_cookies(ctx.cookies())
            browser.close()

        return html_p1

    def post_page(self, params: dict, timeout: int = 20) -> requests.Response:
        """POST ไปดึงหน้าถัดไป ด้วย session ที่มีอยู่"""
        r = self.session.post(self.post_url, data=params, timeout=timeout)
        r.encoding = "utf-8"  # บังคับ UTF-8 กัน mojibake
        return r

    def is_session_alive(self, html: str) -> bool:
        """ตรวจว่า session ยังใช้งานได้ — เช็คว่ามี form ค้นหาอยู่ไหม"""
        return 'action="default.asp"' in html or '<form name="web' in html