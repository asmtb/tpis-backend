# ทดสอบเดี่ยว ไม่ต้องรัน collector เต็ม
# รันได้จากทุก directory:
#   python scripts/test_session.py          (จาก root)
#   python test_session.py                  (จาก scripts/)
import sys
from pathlib import Path

# ชี้ไปที่ root (tpis_production/) เสมอ ไม่ว่าจะรันจากไหน
# __file__ = path ของไฟล์นี้ → .parent = scripts/ → .parent = root
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from landsmaps_logger import LandsMapsLogger
from landsmaps_session import SessionManager

logger = LandsMapsLogger()
mgr = SessionManager(logger, headless=False)  # เห็นหน้าจอจริง ดูว่าติด challenge อะไร
ok = mgr.init_session()
print("สำเร็จไหม:", ok)

# หลัง init_session() สำเร็จ → เซฟ cookies ไว้ใช้งานต่อ
import json

# เซฟลงที่ scripts/ (ข้างๆ ไฟล์นี้เอง) ไม่ใช่ cwd — กัน path เพี้ยนถ้ารันจาก root
SCRIPTS_DIR = Path(__file__).resolve().parent
cookies_path = SCRIPTS_DIR / "test_cookies.json"

cookies_dict = {c.name: c.value for c in mgr.session.cookies}
with open(cookies_path, "w") as f:
    json.dump(cookies_dict, f, indent=2)
print(f"เซฟ cookies แล้ว → {cookies_path}")
print("ลอง reuse พรุ่งนี้/ชั่วโมงถัดไปดูว่ายังผ่านไหม")
