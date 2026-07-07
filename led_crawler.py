"""
crawler.py — TPIS LED Bulk Crawler (Test Run — ทุกจังหวัด)
===================================================================
วัตถุประสงค์ของ script นี้:
  ทดสอบดึงข้อมูลทุกจังหวัดบนเครื่องตัวเอง เพื่อเก็บตัวเลขจริง:
    - เวลาต่อจังหวัด / เวลาต่อหน้า
    - session หมดอายุหรือไม่ ถ้าหมด หมดตอนไหน
    - จำนวน records จริงทุกจังหวัด
    - ประมาณการ GitHub Actions minutes ที่ต้องใช้

ติดตั้ง:
    pip install playwright requests beautifulsoup4
    playwright install chromium

รัน (ทุกจังหวัด):
    python crawler.py

รัน (เฉพาะบางจังหวัด เพื่อทดสอบเร็ว):
    python crawler.py --provinces 10,11,12

รัน (เริ่มใหม่ทั้งหมด ไม่ resume):
    python crawler.py --reset

รัน (เฉพาะจังหวัดที่ fail ค้างไว้):
    python crawler.py --retry-failed
===================================================================
"""

import argparse
import json
import time
from pathlib import Path

from led_config import (
    DELAY_BETWEEN_PAGES,
    DELAY_BETWEEN_PROVINCES,
    MAX_RETRIES,
    POST_URL,
    PROVINCES,
    TARGET_URL,
    OUTPUT_DIR,
)
from led_logger import CrawlerLogger
from led_parser import parse_assets, parse_total_pages, parse_total_records
from led_progress import ProgressTracker
from led_session import SessionManager


# ================================================================
# Helpers
# ================================================================
def build_post_params(province_id: str, province_name: str, page: int) -> dict:
    return {
        "search":       "ok",
        "mode":         "asset",
        "region_name":  "",
        "province":     province_name,
        "ampur":        "",
        "tumbol":       "",
        "asset_type":   "",
        "person1":      "",
        "bid_date":     "",
        "price_begin":  "",
        "price_end":    "",
        "rai_if":       "1",
        "rai":          "",
        "quaterrai_if": "1",
        "quaterrai":    "",
        "wa_if":        "1",
        "Wa":           "",
        "page":         str(page),
    }


def save_province_json(assets: list, province_id: str,
                       province_name: str, output_dir: str,
                       province_name_en: str = "") -> Path:
    """บันทึก JSON แยกตามจังหวัด ทันทีที่จังหวัดนั้นเสร็จ
    ใช้ชื่อภาษาอังกฤษเป็นชื่อไฟล์เพื่อหลีกเลี่ยงปัญหา encoding
    รูปแบบ: {id}_{name_en}.json  เช่น 10_bangkok.json
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    name_part = province_name_en if province_name_en else province_name
    filename  = out / f"{province_id}_{name_part}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(assets, f, ensure_ascii=False, indent=2)
    return filename


# ================================================================
# Crawl 1 จังหวัด
# ================================================================
def crawl_province(
    province: dict,      # {"id", "name", "name_en"}
    session_mgr: SessionManager,
    logger: CrawlerLogger,
    output_dir: str,
) -> bool:
    """
    ดึงข้อมูลจังหวัดเดียว — ครบทุกหน้า
    คืน True ถ้าสำเร็จ, False ถ้าล้มเหลว
    """
    pid  = province["id"]
    name = province["name"]
    logger.province_start(pid, name)

    all_assets: list = []

    # ---------- หน้า 1: ต้องใช้ Playwright ----------
    try:
        html_p1 = session_mgr.init_session(pid, name)
    except Exception as e:
        logger.province_done(pid, success=False, error=str(e))
        return False

    total_pages   = parse_total_pages(html_p1)
    total_records = parse_total_records(html_p1)

    if total_pages == 0 or total_records == 0:
        # จังหวัดนี้ไม่มีทรัพย์ใน LED (เป็นไปได้สำหรับบางจังหวัด)
        logger.log.info(f"  ℹ️  [{pid}] {name} ไม่มีรายการ — ข้ามไป")
        logger.province_done(pid, success=True)
        save_province_json([], pid, name, output_dir, province_name_en=province.get("name_en", ""))
        return True

    logger.province_found_pages(pid, total_pages, total_records)

    # parse หน้า 1
    assets_p1 = parse_assets(html_p1, pid, name)
    all_assets.extend(assets_p1)
    logger.province_page_done(pid, 1, len(assets_p1), 0)

    # ---------- หน้า 2 → total_pages: ใช้ requests.post() ----------
    for page_no in range(2, total_pages + 1):
        params   = build_post_params(pid, name, page_no)
        success  = False
        t_start  = time.perf_counter()

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                r = session_mgr.post_page(params)

                # เช็ค session expire
                if not session_mgr.is_session_alive(r.text):
                    logger.session_expire_detected(pid, page_no)
                    html_p1_renew = session_mgr.init_session(pid, name)
                    # หลัง renew ลอง POST หน้านั้นใหม่อีกครั้ง
                    r = session_mgr.post_page(params)

                if r.status_code != 200 or len(r.text) < 3000:
                    raise ValueError(
                        f"Response ผิดปกติ status={r.status_code} size={len(r.text)}"
                    )

                elapsed = time.perf_counter() - t_start
                assets  = parse_assets(r.text, pid, name)
                all_assets.extend(assets)
                logger.province_page_done(pid, page_no, len(assets), elapsed)
                success = True
                break

            except Exception as e:
                logger.retry(pid, page_no, attempt, str(e))
                if attempt < MAX_RETRIES:
                    time.sleep(2 * attempt)  # exponential backoff

        if not success:
            logger.error(pid, page_no, RuntimeError("เกิน max retries"))

        time.sleep(DELAY_BETWEEN_PAGES)

    # ---------- บันทึก JSON ----------
    out_file = save_province_json(all_assets, pid, name, output_dir,
                                 province_name_en=province.get("name_en", ""))
    logger.log.info(f"  💾 [{pid}] บันทึก {len(all_assets):,} records → {out_file}")

    logger.province_done(pid, success=True)
    return True


# ================================================================
# Main
# ================================================================
def main():
    parser = argparse.ArgumentParser(description="TPIS LED Crawler — ทดสอบทุกจังหวัด")
    parser.add_argument(
        "--provinces",
        help="รันเฉพาะบาง province_id คั่นด้วยคอมมา เช่น 10,11,12",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="เริ่มใหม่ทั้งหมด ไม่ resume จาก progress เก่า",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="รันเฉพาะจังหวัดที่ fail ในรอบก่อน",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=True,
        help="รัน Playwright แบบ headless (default: True)",
    )
    args = parser.parse_args()

    logger   = CrawlerLogger(output_dir=OUTPUT_DIR)
    progress = ProgressTracker(output_dir=OUTPUT_DIR)

    if args.reset:
        progress.reset()

    # เลือกจังหวัดที่จะรัน
    if args.provinces:
        ids_filter = set(args.provinces.split(","))
        target_provinces = [p for p in PROVINCES if p["id"] in ids_filter]
    elif args.retry_failed:
        failed_ids = set(progress.failed)
        target_provinces = [p for p in PROVINCES if p["id"] in failed_ids]
        if not target_provinces:
            logger.log.info("ไม่มีจังหวัดที่ fail ค้างไว้")
            return
    else:
        # ทุกจังหวัด — ข้ามที่เสร็จแล้ว (resume)
        target_provinces = [
            p for p in PROVINCES if not progress.is_completed(p["id"])
        ]

    logger.log.info("=" * 60)
    logger.log.info("🚀 TPIS LED Crawler — เริ่มต้น")
    logger.log.info(f"   จังหวัดที่จะรัน: {len(target_provinces)}")
    logger.log.info(
        f"   เสร็จแล้ว (resume): {len(progress.completed)} จังหวัด"
    )
    logger.log.info("=" * 60)

    if not target_provinces:
        logger.log.info("✅ ทุกจังหวัดเสร็จสิ้นแล้ว ไม่มีงานเพิ่ม")
        return

    session_mgr = SessionManager(
        logger=logger,
        target_url=TARGET_URL,
        post_url=POST_URL,
        headless=args.headless,
    )

    for i, province in enumerate(target_provinces, 1):
        logger.log.info(
            f"\n[{i}/{len(target_provinces)}] กำลังดึง: "
            f"{province['id']} {province['name']}"
        )

        success = crawl_province(province, session_mgr, logger, OUTPUT_DIR)

        if success:
            progress.mark_done(province["id"])
        else:
            progress.mark_failed(province["id"])

        # delay ระหว่างจังหวัด (ยกเว้นตัวสุดท้าย)
        if i < len(target_provinces):
            logger.log.info(
                f"  ⏸  รอ {DELAY_BETWEEN_PROVINCES}s ก่อนจังหวัดถัดไป..."
            )
            time.sleep(DELAY_BETWEEN_PROVINCES)

    # ---------- สรุปผล ----------
    logger.finish()


if __name__ == "__main__":
    main()