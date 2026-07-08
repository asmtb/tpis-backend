# ทดสอบเดี่ยว ไม่ต้องรัน collector เต็ม
import sys
sys.path.insert(0, '.')
from landsmaps_logger import LandsMapsLogger
from landsmaps_session import SessionManager

logger = LandsMapsLogger()
mgr = SessionManager(logger, headless=False)  # เห็นหน้าจอจริง ดูว่าติด challenge อะไร
ok = mgr.init_session()
print("สำเร็จไหม:", ok)

# ต่อจาก test_session.py หลัง init_session() สำเร็จ
import json
cookies_dict = {c.name: c.value for c in mgr.session.cookies}
with open("test_cookies.json", "w") as f:
    json.dump(cookies_dict, f)
print("เซฟ cookies แล้ว ลอง reuse พรุ่งนี้/ชั่วโมงถัดไปดูว่ายังผ่านไหม")