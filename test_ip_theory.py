import sys
sys.path.insert(0, '.')
from supabase_common import SUPABASE_URL, HEADERS, _request_with_retry
from landsmaps_session import SessionManager
from landsmaps_logger import LandsMapsLogger

logger = LandsMapsLogger()
mgr = SessionManager(logger, headless=True)
ok = mgr.load_cookies_from_supabase()   # ใช้ cookies เดียวกับที่ Cloud Run ใช้
print("load_cookies_from_supabase:", ok)
logger.close()