"""
landsmaps_config.py — ค่าคงที่ + reference data สำหรับ LandsMaps collector
ตั้งชื่อไฟล์แยกจาก config.py ของ LED เพราะอยู่โฟลเดอร์เดียวกัน (กัน import ชนกัน)
"""

import json
import re
from pathlib import Path

# ========== FILE PATHS ==========
LED_FILE       = "led_all_assets.json"  # ไม่ใช้แล้วหลังกลุ่ม 5 (อ่านจาก Supabase แทน) — เก็บไว้เผื่ออ้างอิง
BKK_AMPH_FILE  = "BANGKOK_AMPHUR.json"
COORD_FILE     = "landsmaps_coordinates.json"  # ไม่ใช้แล้วหลังกลุ่ม 5 (cache อยู่ใน Supabase table parcels)
PROGRESS_FILE  = "progress.json"
NOT_FOUND_FILE = "landsmaps_not_found.jsonl"
# CURL_FILE ถูกลบแล้วในกลุ่ม 4 — session มาจาก Playwright อัตโนมัติแทน (ดู landsmaps_session.py)

# ========== TIMING ==========
DELAY_SEC   = 10.0   # เพิ่มจาก 0.5 → 2.0 วินาที ป้องกัน rate limit / bot detection
DELAY_JITTER = 10.0  # random เพิ่มอีก 0–1.0 วินาที → รอจริง 2.0–3.0 วินาทีต่อ request
RETRY_MAX   = 3
RETRY_DELAY = 10    # เพิ่มจาก 5 → 10 วินาที เวลา retry
SAVE_EVERY  = 100   # ลดจาก 200 → 100 save บ่อยขึ้น กันข้อมูลหายถ้า crash

# ========== NOT_FOUND RETRY COOLDOWN (กลุ่ม 5.3) ==========
NOT_FOUND_COOLDOWN_DAYS = 30  # ไม่ retry ซ้ำถ้าเพิ่งลองไปภายในกี่วัน

# ========== PLAYWRIGHT (กลุ่ม 4) ==========
# บน Cloud Run ต้องเป็น True เสมอ (ไม่มีจอ) — ปรับเป็น False ได้เฉพาะตอน debug บนเครื่องตัวเอง
HEADLESS = True

# ========== API ENDPOINTS ==========
BASE     = "https://landsmaps.dol.go.th"
API_BASE = f"{BASE}/apiService/LandsMaps"
JWT_EP   = f"{BASE}/apiService/JWT/GetJWTAccessToken"

# ========== MAX_RANGE_SIZE สำหรับ deedno range parsing ==========
MAX_RANGE_SIZE = 200

# -------------------------------------------------------
# Province code (จาก LandsMaps dropdown) — ต่างจากรหัส LED
# -------------------------------------------------------
PROVINCE_CODE = {
    "กระบี่":"81","กรุงเทพมหานคร":"10","กาญจนบุรี":"71","กาฬสินธุ์":"46",
    "กำแพงเพชร":"62","ขอนแก่น":"40","จันทบุรี":"22","ฉะเชิงเทรา":"24",
    "ชลบุรี":"20","ชัยนาท":"18","ชัยภูมิ":"36","ชุมพร":"86",
    "เชียงราย":"57","เชียงใหม่":"50","ตรัง":"92","ตราด":"23",
    "ตาก":"63","นครนายก":"26","นครปฐม":"73","นครพนม":"48",
    "นครราชสีมา":"30","นครศรีธรรมราช":"80","นครสวรรค์":"60","นนทบุรี":"12",
    "นราธิวาส":"96","น่าน":"55","บึงกาฬ":"38","บุรีรัมย์":"31",
    "ปทุมธานี":"13","ประจวบคีรีขันธ์":"77","ปราจีนบุรี":"25","ปัตตานี":"94",
    "พระนครศรีอยุธยา":"14","พะเยา":"56","พังงา":"82","พัทลุง":"93",
    "พิจิตร":"66","พิษณุโลก":"65","เพชรบุรี":"76","เพชรบูรณ์":"67",
    "แพร่":"54","ภูเก็ต":"83","มหาสารคาม":"44","มุกดาหาร":"49",
    "แม่ฮ่องสอน":"58","ยโสธร":"35","ยะลา":"95","ร้อยเอ็ด":"45",
    "ระนอง":"85","ระยอง":"21","ราชบุรี":"70","ลพบุรี":"16",
    "ลำปาง":"52","ลำพูน":"51","เลย":"42","ศรีสะเกษ":"33",
    "สกลนคร":"47","สงขลา":"90","สตูล":"91","สมุทรปราการ":"11",
    "สมุทรสงคราม":"75","สมุทรสาคร":"74","สระแก้ว":"27","สระบุรี":"19",
    "สิงห์บุรี":"17","สุโขทัย":"64","สุพรรณบุรี":"72","สุราษฎร์ธานี":"84",
    "สุรินทร์":"32","หนองคาย":"43","หนองบัวลำภู":"39","อ่างทอง":"15",
    "อำนาจเจริญ":"37","อุดรธานี":"41","อุตรดิตถ์":"53","อุทัยธานี":"61",
    "อุบลราชธานี":"34",
}


def load_bangkok_amphur(logger=None) -> dict:
    """
    โหลด BANGKOK_AMPHUR.json → dict {ชื่อเขต: dol_code}
    เก็บเฉพาะ dol code ที่เป็นตัวเลข 2 หลัก (ข้ามพวก ก1, ช1, ต4 ฯลฯ ที่ไม่ใช่รหัสมาตรฐาน)

    ข้อ 3.3: ทำให้ config.py เป็นจุดเดียวที่โหลดไฟล์นี้ แทนที่จะโหลดตรงในตัว collector
    """
    bkk_amph_dol = {}
    if not Path(BKK_AMPH_FILE).exists():
        if logger:
            logger.warning(f"ไม่พบไฟล์ {BKK_AMPH_FILE} — จังหวัดกรุงเทพจะ map amphur ไม่ได้เลย")
        return bkk_amph_dol

    with open(BKK_AMPH_FILE, encoding="utf-8") as f:
        bkk_raw = json.load(f)

    for name, codes in bkk_raw.items():
        dol_code = codes.get("dol", "")
        if re.match(r'^\d{2}$', dol_code):
            bkk_amph_dol[name] = dol_code

    if logger:
        logger.info(f"โหลด {BKK_AMPH_FILE}: {len(bkk_amph_dol)} เขต (dol code)")

    return bkk_amph_dol
