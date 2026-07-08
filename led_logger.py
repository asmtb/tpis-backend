"""
logger.py — Structured logging สำหรับ TPIS LED Crawler
บันทึกข้อมูล:
  - เวลาเริ่ม/สิ้นสุดแต่ละขั้นตอน
  - จำนวน records ที่ได้
  - session expire events
  - error ทั้งหมด
  - summary สุดท้าย
"""

import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path


class CrawlerLogger:
    def __init__(self, output_dir: str = "led_output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.run_id   = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_start = time.perf_counter()
        self.run_start_dt = datetime.now()

        # ---- stats ที่จะ track ----
        self.stats = {
            "run_id":              self.run_id,
            "started_at":          self.run_start_dt.isoformat(),
            "finished_at":         None,
            "total_duration_sec":  None,
            "provinces_attempted": 0,
            "provinces_success":   0,
            "provinces_failed":    0,
            "total_pages_fetched": 0,
            "total_records":       0,
            "session_renews":      0,
            "retries":             0,
            "errors":              [],
            "provinces":           {},   # per-province breakdown
        }

        self._setup_logging()
        self.log = logging.getLogger("crawler")

    def _setup_logging(self):
        fmt = logging.Formatter(
            "%(asctime)s  %(levelname)-8s  %(message)s",
            datefmt="%H:%M:%S",
        )
        root = logging.getLogger("crawler")
        root.setLevel(logging.DEBUG)

        # Console — INFO ขึ้นไป
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.INFO)
        ch.setFormatter(fmt)
        root.addHandler(ch)

        # File — DEBUG ทั้งหมด (จะ debug ง่ายกว่า)
        log_path = self.output_dir / f"crawler_{self.run_id}.log"
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        root.addHandler(fh)

        self.log_file = log_path

    # ----------------------------------------------------------------
    # Province-level timing
    # ----------------------------------------------------------------
    def province_start(self, province_id: str, province_name: str):
        self.stats["provinces_attempted"] += 1
        self.stats["provinces"][province_id] = {
            "name":          province_name,
            "started_at":    datetime.now().isoformat(),
            "_start_perf":   time.perf_counter(),
            "total_pages":   None,
            "pages_fetched": 0,
            "records":       0,
            "session_renews":0,
            "retries":       0,
            "status":        "running",
            "errors":        [],
            "duration_sec":  None,
        }
        self.log.info(f"▶ เริ่ม [{province_id}] {province_name}")

    def province_found_pages(self, province_id: str, total_pages: int, total_records: int):
        p = self.stats["provinces"][province_id]
        p["total_pages"]   = total_pages
        p["total_records_in_site"] = total_records
        self.log.info(
            f"  📄 [{province_id}] พบ {total_records:,} รายการ / {total_pages} หน้า"
        )

    def province_page_done(self, province_id: str, page_no: int,
                           records: int, elapsed_sec: float):
        p = self.stats["provinces"][province_id]
        p["pages_fetched"] += 1
        p["records"]       += records
        self.stats["total_pages_fetched"] += 1
        self.stats["total_records"]       += records
        self.log.debug(
            f"  page {page_no:>4} | {records:>3} records | {elapsed_sec:.2f}s"
        )

    def province_done(self, province_id: str, success: bool, error: str = None):
        p = self.stats["provinces"][province_id]
        elapsed = time.perf_counter() - p.pop("_start_perf")
        p["duration_sec"]  = round(elapsed, 2)
        p["finished_at"]   = datetime.now().isoformat()
        p["status"]        = "success" if success else "failed"
        if error:
            p["errors"].append(error)
            self.stats["errors"].append(
                {"province_id": province_id, "error": error}
            )

        if success:
            self.stats["provinces_success"] += 1
            self.log.info(
                f"✅ เสร็จ [{province_id}] {p['name']} "
                f"| {p['pages_fetched']} หน้า "
                f"| {p['records']:,} records "
                f"| {elapsed:.1f}s "
                f"| renew={p['session_renews']}"
            )
        else:
            self.stats["provinces_failed"] += 1
            self.log.warning(
                f"❌ ล้มเหลว [{province_id}] {p['name']} | {error}"
            )

    # ----------------------------------------------------------------
    # Session events
    # ----------------------------------------------------------------
    def session_init(self, province_id: str = None):
        msg = "🔑 Playwright init session"
        if province_id:
            self.stats["provinces"][province_id]["session_renews"] += 1
            msg += f" (renew สำหรับ {province_id})"
        self.stats["session_renews"] += 1
        self.log.info(msg)

    def session_expire_detected(self, province_id: str, page_no: int):
        self.log.warning(
            f"⚠️  Session expire detected [{province_id}] หน้า {page_no} → กำลัง renew"
        )

    # ----------------------------------------------------------------
    # Retry / Error events
    # ----------------------------------------------------------------
    def retry(self, province_id: str, page_no: int, attempt: int, reason: str):
        self.stats["retries"] += 1
        if province_id in self.stats["provinces"]:
            self.stats["provinces"][province_id]["retries"] += 1
        self.log.warning(
            f"🔄 Retry #{attempt} [{province_id}] หน้า {page_no} | {reason}"
        )

    def error(self, province_id: str, page_no: int, exc: Exception):
        msg = f"[{province_id}] หน้า {page_no} | {type(exc).__name__}: {exc}"
        self.log.error(f"💥 Error {msg}")
        self.stats["errors"].append({"context": msg})

    # ----------------------------------------------------------------
    # Run summary — เรียกตอนสิ้นสุด
    # ----------------------------------------------------------------
    def finish(self):
        elapsed = time.perf_counter() - self.run_start
        self.stats["finished_at"]        = datetime.now().isoformat()
        self.stats["total_duration_sec"] = round(elapsed, 2)

        # คำนวณ derived metrics
        success_count = self.stats["provinces_success"]
        total_pages   = self.stats["total_pages_fetched"]
        total_records = self.stats["total_records"]
        elapsed_min   = elapsed / 60

        avg_sec_per_page = (
            elapsed / total_pages if total_pages else 0
        )
        avg_min_per_province = (
            elapsed_min / success_count if success_count else 0
        )
        est_all_provinces_min = avg_min_per_province * 77

        self.log.info("")
        self.log.info("=" * 60)
        self.log.info("📊 สรุปผลการ crawl")
        self.log.info("=" * 60)
        self.log.info(f"  ระยะเวลารวม      : {elapsed_min:.1f} นาที ({elapsed:.0f} วินาที)")
        self.log.info(f"  จังหวัดสำเร็จ    : {success_count}/{self.stats['provinces_attempted']}")
        self.log.info(f"  จังหวัดล้มเหลว   : {self.stats['provinces_failed']}")
        self.log.info(f"  หน้าที่ดึง       : {total_pages:,} หน้า")
        self.log.info(f"  รายการทั้งหมด    : {total_records:,} records")
        self.log.info(f"  Session renews   : {self.stats['session_renews']}")
        self.log.info(f"  Retries          : {self.stats['retries']}")
        self.log.info(f"  Errors           : {len(self.stats['errors'])}")
        self.log.info("--- Performance ---")
        self.log.info(f"  เฉลี่ยต่อหน้า     : {avg_sec_per_page:.2f} วินาที/หน้า")
        self.log.info(f"  เฉลี่ยต่อจังหวัด  : {avg_min_per_province:.1f} นาที/จังหวัด")
        self.log.info(f"  ประมาณครบ 77 จังหวัด: ~{est_all_provinces_min:.0f} นาที")
        self.log.info("=" * 60)

        # Per-province table
        self.log.info("")
        self.log.info(f"{'จังหวัด':<25} {'หน้า':>6} {'records':>8} {'เวลา(s)':>9} {'สถานะ'}")
        self.log.info("-" * 65)
        for pid, p in self.stats["provinces"].items():
            status_icon = "✅" if p["status"] == "success" else "❌"
            self.log.info(
                f"{p['name']:<25} {p['pages_fetched']:>6} "
                f"{p['records']:>8,} {p.get('duration_sec', 0):>9.1f} "
                f"{status_icon}"
            )

        # บันทึก JSON สรุป
        summary_path = self.output_dir / f"summary_{self.run_id}.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(self.stats, f, ensure_ascii=False, indent=2, default=str)
        self.log.info(f"\n💾 สรุป JSON → {summary_path}")
        self.log.info(f"📝 Log ทั้งหมด → {self.log_file}")
