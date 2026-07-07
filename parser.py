"""
parser.py — Parse HTML → list of asset dicts
แยก hidden form fields + คำนวณ is_closed / is_sold / latest_status
"""

import re
from datetime import date, datetime
from typing import Optional
from urllib.parse import quote

from bs4 import BeautifulSoup


# ----------------------------------------------------------------
# deedno parser
# ----------------------------------------------------------------
_MAX_RANGE_SIZE = 200


def _expand_range(start_str: str, end_str: str) -> list:
    """
    Expand range พร้อมรองรับ short range:
      26782-84   → 26782-26784
      106391-415 → 106391-106415
    """
    start = int(start_str)
    end_s = end_str.strip()
    if len(end_s) < len(start_str):
        prefix   = start_str[:len(start_str) - len(end_s)]
        end_full = prefix + end_s
        end      = int(end_full)
        if end < start:
            prefix = start_str[:len(start_str) - len(end_s) - 1]
            end    = int(prefix + end_s)
    else:
        end = int(end_s)
    if start > end:
        start, end = end, start
    size = end - start + 1
    if size <= _MAX_RANGE_SIZE:
        return [str(n) for n in range(start, end + 1)]
    return [str(start), str(end)]  # range ใหญ่เกิน เก็บแค่ start/end


def parse_deedno(raw: str) -> list:
    """
    แปลง deedno string → list of deedno strings
    รองรับทุก format ที่พบใน LED data รวมถึง:
      - ฯ, ฯลฯ, (เดิม xxx), (บางส่วน), (ปัจจุบันคือ xxx)
      - ตัวคั่น , . space และ
      - range ปกติ และ short range (26782-84, 1601-02, 106391-415)
    """
    if not raw:
        return []
    s = raw.strip()
    # (ปัจจุบันคือ xxx) → ใช้เลขใหม่
    s = re.sub(r'\d+\s*\(\s*ปัจจุบันคือ\s*(\d+)\s*\)', lambda m: m.group(1), s)
    s = re.sub(r'\s*\([^)]*\)', '', s)   # ตัดวงเล็บอื่น
    s = re.sub(r'\s*เดิม\s*', ' ', s)
    s = re.sub(r'ฯลฯ|ฯ', '', s)
    s = re.sub(r'และ', ' ', s)
    s = re.sub(r'[^\d\-,\.\s]', '', s)  # ตัดอักขระไทยที่ไม่ใช่คำสั่ง
    s = re.sub(r'[,\.]', ' ', s)           # , . → space
    s = re.sub(r'(\d)\s+-\s+(\d)', r'\1-\2', s)  # "579 - 582" → "579-582"
    s = re.sub(r'\s+', ' ', s).strip()
    results = []
    for token in s.split(' '):
        token = token.strip()
        if not token:
            continue
        m = re.match(r'^(\d+)-(\d+)$', token)
        if m:
            results.extend(_expand_range(m.group(1), m.group(2)))
        elif re.match(r'^\d+$', token):
            results.append(token)
    seen, unique = set(), []
    for d in results:
        if d not in seen:
            seen.add(d)
            unique.append(d)
    return unique


# ----------------------------------------------------------------
# รหัส issaleN → ข้อความสถานะ
# ----------------------------------------------------------------
ISSALE_STATUS = {
    "0":  "-",
    "1":  "ขายได้",
    "3":  "งดขายไม่มีผู้สู้ราคา",
    "13": "งดขาย",
    "25": "งดขาย",
}


def issale_to_text(code: str) -> str:
    return ISSALE_STATUS.get(str(code).strip(), f"ไม่ทราบ({code})")


def led_path_to_url(raw_path: str) -> str:
    """
    แปลง internal path (Z:\\งานล้ม\\2568\\10-2568\\17\\21284p.jpg)
    → public URL (https://asset.led.go.th/PPKPicture/งานล้ม/2568/10-2568/17/21284p.jpg)
    ยืนยัน pattern จาก inspect หน้า detail จริง
    """
    if not raw_path:
        return ""
    cleaned = raw_path.split(":\\", 1)[-1] if ":\\" in raw_path else raw_path
    parts   = [p for p in cleaned.replace("\\", "/").split("/") if p]
    return "https://asset.led.go.th/PPKPicture/" + "/".join(quote(p) for p in parts)


def summarize_issale(raw: dict) -> dict:
    """
    คำนวณ is_closed / is_sold / latest_status / latest_round_no
    จาก issale1-8 (ยืนยัน logic จากตัวอย่างจริง 3 records เทียบกับ table-danger)
    """
    codes = [str(raw.get(f"issale{i}", "")).strip() for i in range(1, 9)]
    is_sold    = "1" in codes
    has_pending = "0" in codes
    is_closed  = is_sold or not has_pending

    latest_round, latest_status = None, None
    for i, code in enumerate(codes, 1):
        if code not in ("", "0"):
            latest_round  = i
            latest_status = issale_to_text(code)

    return {
        "is_closed":      is_closed,
        "is_sold":        is_sold,
        "latest_status":  latest_status,
        "latest_round_no": latest_round,
    }


def parse_total_pages(html: str) -> int:
    m = re.search(r"หน้าที่\s*</span>\s*\d+/(\d+)", html)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)/(\d+)", html)
    return int(m.group(2)) if m else 1


def parse_total_records(html: str) -> int:
    m = re.search(r"พบ\s*([\d,]+)\s*รายการ", html)
    return int(m.group(1).replace(",", "")) if m else 0


def parse_assets(html: str, province_id: str, province_name: str) -> list[dict]:
    """
    Parse HTML หน้าผลการค้นหา → list of asset dicts
    ดึงจาก <form name="webN"> hidden inputs ทั้งหมด
    เพิ่ม URL รูปภาพที่คำนวณจาก path
    """
    soup  = BeautifulSoup(html, "html.parser")
    forms = soup.find_all("form", attrs={"name": re.compile(r"^web\d+$")})
    assets = []

    for form in forms:
        raw: dict = {}

        # ดึง hidden inputs ทั้งหมด
        for inp in form.find_all("input", attrs={"type": "hidden"}):
            name = inp.get("name")
            if not name:
                continue
            value = inp.get("value", "")
            if name in raw:
                # กรณีมี name ซ้ำ: เก็บแค่ค่าแรก (เช่น owner_suit_name มี 2 input ในฟอร์ม)
                pass
            else:
                raw[name] = value

        if not raw:
            continue

        # เพิ่ม metadata
        raw["_province_id"]   = province_id
        raw["_province_name"] = province_name
        raw["_form_name"]     = form.get("name", "")
        raw["_form_action"]   = (
            "https://asset.led.go.th/newbidreg/"
            + form.get("action", "")
        )

        # คำนวณ URL รูปภาพจาก path (ยืนยัน pattern แล้ว)
        raw["_url_picture"] = led_path_to_url(raw.get("landpicture", ""))
        raw["_url_map"]     = led_path_to_url(raw.get("map", ""))
        raw["_url_mapjot"]  = led_path_to_url(raw.get("mapjot", ""))

        # แปลง deedno: raw string → list พร้อมใช้งาน
        deedno_raw          = raw.get("deedno", "")
        deedno_list         = parse_deedno(deedno_raw)
        raw["deedno_raw"]   = deedno_raw     # string ดิบ เก็บไว้ debug
        raw["deedno"]       = deedno_list    # list พร้อมใช้งาน
        raw["deedno_count"] = len(deedno_list)

        # timestamp ที่ fetch ข้อมูลนี้มา
        # UTC
        # raw["date_modified"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        # GMT+7
        from datetime import timezone, timedelta
        BKK_TZ = timezone(timedelta(hours=7))
        raw["date_modified"] = datetime.now(BKK_TZ).strftime("%Y-%m-%dT%H:%M:%S+07:00")

        # คำนวณ is_closed / is_sold / latest_status
        raw.update(summarize_issale(raw))

        assets.append(raw)

    return assets