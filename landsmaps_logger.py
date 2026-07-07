"""
landsmaps_logger.py — logging สำหรับ LandsMaps collector
แทนที่การ hack sys.stdout = Tee(...) ของเดิม ซึ่งเป็น global side-effect
ที่เปราะบาง (กระทบ print() ทุกที่ในโปรเซส รวมถึง library อื่นที่ import เข้ามา
และทำความสะอาดยาก — ลืม sys.stdout = sys.__stdout__ ตอนจบ โปรแกรมอื่นที่รันต่อ
ใน process เดียวกันจะเพี้ยนไปด้วย)
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from landsmaps_config import NOT_FOUND_FILE


class LandsMapsLogger:
    def __init__(self, log_file: str = "landsmaps_collector.log"):
        self.log_file = Path(log_file)

        fmt = logging.Formatter(
            "[%(asctime)s] %(message)s", datefmt="%H:%M:%S"
        )
        self._logger = logging.getLogger("landsmaps")
        self._logger.setLevel(logging.DEBUG)
        self._logger.handlers.clear()  # กัน handler ซ้ำถ้าสร้าง instance หลายรอบ

        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.INFO)
        ch.setFormatter(fmt)
        self._logger.addHandler(ch)

        fh = logging.FileHandler(self.log_file, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        self._logger.addHandler(fh)

        # not-found writer — เปิดไฟล์ครั้งเดียว ปิดตอน close()
        self._nf_f = open(NOT_FOUND_FILE, "a", encoding="utf-8")

    def info(self, msg: str):
        self._logger.info(msg)

    def warning(self, msg: str):
        self._logger.warning(msg)

    def error(self, msg: str):
        self._logger.error(msg)

    def section(self, title: str):
        self._logger.info("")
        self._logger.info("=" * 60)
        self._logger.info(f"  {title}")
        self._logger.info("=" * 60)

    def log_not_found(self, reason: str, record: dict, cache_key: str = "", extra: dict = None):
        """
        บันทึก record ที่ดึงไม่ได้ลง JSONL file
        reason: "no_deedno" | "no_amphur" | "not_found" | "error"
        """
        entry = {
            "_reason":    reason,
            "_cache_key": cache_key,
            "_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        if extra:
            entry.update({f"_{k}": v for k, v in extra.items()})
        entry["led"] = record
        self._nf_f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._nf_f.flush()

    def close(self):
        """ปิดไฟล์ที่เปิดไว้ทั้งหมด — เรียกตอนจบโปรแกรมเสมอ (ใช้กับ try/finally)"""
        self._nf_f.close()
        for h in self._logger.handlers:
            h.close()
