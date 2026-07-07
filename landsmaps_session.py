"""
landsmaps_session.py — จัดการ session/JWT/cookies + amphur code lookup

⚠️ สถานะปัจจุบัน: ยังโหลด cookies จาก Copy_as_cURL.txt แบบ manual อยู่
(ต้องมีคน copy คำสั่ง cURL ใหม่จาก browser เองเวลา cookies หมดอายุ)
เป็น placeholder รอกลุ่ม 4 (session automation ด้วย Playwright) มาแทนที่ทั้งไฟล์นี้
"""

import re
import time

import requests

from landsmaps_config import API_BASE, BASE, JWT_EP, RETRY_MAX, RETRY_DELAY


class SessionManager:
    def __init__(self, logger, curl_file: str):
        self.logger    = logger
        self.curl_file = curl_file
        self.session   = requests.Session()
        self._amphur_cache: dict[str, dict] = {}

    def init_from_curl_file(self) -> bool:
        """
        โหลด cookies จากไฟล์ cURL ที่ copy มาจาก browser ด้วยมือ
        ⚠️ ชั่วคราว — cookies (Imperva/Incapsula) หมดอายุเร็ว ต้องมีคน copy ใหม่
        เมื่อทำกลุ่ม 4 เสร็จ ฟังก์ชันนี้จะถูกแทนที่ด้วยการเปิด Playwright เอง
        """
        with open(self.curl_file, encoding="utf-8") as f:
            curl_content = f.read()

        cookies = {}
        all_sets = re.findall(r"-b '([^']+)'", curl_content)
        if all_sets:
            for part in all_sets[-1].split(';'):
                if '=' in part:
                    k, v = part.strip().split('=', 1)
                    cookies[k.strip()] = v.strip()

        self.session.headers.update({
            "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/149.0.0.0 Safari/537.36",
            "Accept":          "application/json, text/plain, */*",
            "Accept-Language": "th-TH,th;q=0.9,en;q=0.8",
            "Referer":         f"{BASE}/",
            "Origin":          BASE,
        })
        for k, v in cookies.items():
            self.session.cookies.set(k, v, domain=".dol.go.th")

        return self.refresh_jwt()

    def refresh_jwt(self) -> bool:
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
        """
        url = f"{API_BASE}/GetParcelByParcelNo/{provid}/{amph2}/{deedno}"
        for attempt in range(1, RETRY_MAX + 1):
            try:
                r = self.session.get(url, timeout=15)
                r.encoding = "utf-8"
                if "_Incapsula" in r.text:
                    self.logger.warning("  ⚠️  Imperva — refresh JWT")
                    if self.refresh_jwt():
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
