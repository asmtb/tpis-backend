# ทดสอบเดี่ยว ไม่ต้องรัน collector เต็ม
import sys
sys.path.insert(0, '.')
from landsmaps_logger import LandsMapsLogger
from landsmaps_session import SessionManager

logger = LandsMapsLogger()
mgr = SessionManager(logger, headless=False)  # เห็นหน้าจอจริง ดูว่าติด challenge อะไร
ok = mgr.init_session()
print("สำเร็จไหม:", ok)