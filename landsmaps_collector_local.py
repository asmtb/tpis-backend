"""
landsmaps_collector_local.py — รันบนเครื่องตัวเองแทน Cloud Run

ต่างจาก landsmaps_collector.py (Cloud Run version) ตรงนี้:
  - ใช้ init_session() เปิด Chromium ผ่าน Playwright แก้ hCaptcha บนเครื่องตัวเอง
    แทนที่จะอ่าน cookies จาก Supabase (ซึ่งผูกกับ IP ต้นทาง ใช้บน Cloud Run ไม่ได้)
  - headless=False บังคับเสมอ เพื่อให้เห็นหน้าต่าง browser และ solve hCaptcha ได้
  - ไม่ต้องรัน test_session.py / upload_cookies.py ก่อน — ทำทุกอย่างในครั้งเดียว

workflow:
  1. รัน: python landsmaps_collector_local.py
     (หรือ double-click run_landsmaps_local.bat)
  2. Browser Chromium จะเปิดขึ้นมา → solve hCaptcha (ถ้ามี) → ปิดอัตโนมัติ
  3. Collector เริ่มดึงข้อมูลจาก LandsMaps API ทันที
  4. ผลลัพธ์เขียนเข้า Supabase (parcels, asset_parcels)
  5. ได้รับ email สรุปผลหลัง run เสร็จ

หมายเหตุ: ต้องมี .env ที่มี SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY,
           RESEND_API_KEY, NOTIFY_EMAIL ครบก่อนรัน
"""

import sys
import time

from landsmaps_config import PROVINCE_CODE, DELAY_SEC, SAVE_EVERY, load_bangkok_amphur
from landsmaps_logger import LandsMapsLogger
from landsmaps_parser import parse_deedno, validate_area
from landsmaps_progress import LandsMapsProgressTracker
from landsmaps_session import SessionManager
from landsmaps_supabase import (
    get_checkpoint, get_new_assets, get_cached_parcels, is_retryable,
    upsert_parcel, link_asset_parcel, start_run, finish_run,
)
from email_summary import send_landsmaps_summary

# บังคับ headless=False เสมอเมื่อรัน local
# (Cloud Run version ใช้ HEADLESS=True จาก landsmaps_config.py)
HEADLESS_LOCAL = False


def main():
    logger = LandsMapsLogger()
    run_id = None
    success = False
    stats = {
        "total": 0, "processed": 0,
        "found": 0, "not_found": 0, "cache_hit": 0,
        "no_deedno": 0, "no_amphur": 0, "errors": 0,
        "area_match": 0, "area_mismatch": 0, "area_not_applicable": 0,
    }

    try:
        logger.section("TPIS - LandsMaps Collector (Local — init_session)")
        logger.info("🖥️  Local mode: เปิด Chromium บนเครื่องตัวเอง ไม่ใช้ cookies จาก Supabase")
        logger.info("    (เพราะ Incapsula ผูก cookies กับ IP ต้นทาง — Cloud Run IP ไม่ผ่าน)")

        run_id = start_run()
        logger.info(f"crawler_run id: {run_id}")

        bkk_amph_dol = load_bangkok_amphur(logger)

        # ใช้ init_session() โดยตรง — เปิด browser แล้ว solve hCaptcha บนเครื่องตัวเอง
        # ไม่ผ่าน load_cookies_from_supabase() เพราะ cookies ผูกกับ IP
        session_mgr = SessionManager(logger, headless=HEADLESS_LOCAL)
        logger.info("🔑 กำลังเปิด Chromium — solve hCaptcha แล้วกด Submit...")
        if not session_mgr.init_session():
            logger.error("❌ init_session() ไม่สำเร็จ — ดู log ด้านบนว่าติด challenge อะไร")
            sys.exit(1)
        logger.info("✅ Session พร้อม — เริ่ม collect ทันที (cookies ใช้ได้ ~1-1.5 ชม.)")

        # ----- 5.1: ดึงเฉพาะ asset ใหม่กว่า checkpoint -----
        checkpoint = get_checkpoint()
        logger.info(f"Checkpoint (รอบล่าสุดที่สำเร็จ): {checkpoint or 'ไม่มี — รอบแรก ดึงทั้งหมด'}")
        assets = get_new_assets(checkpoint)
        stats["total"] = len(assets)
        logger.info(f"Asset ใหม่ที่ต้องประมวลผล: {len(assets):,}")

        if not assets:
            logger.info("ไม่มี asset ใหม่ — จบงานทันที")
            success = True
            return

        # ----- 5.2: โหลด parcel cache จาก Supabase ครั้งเดียว -----
        parcel_cache = get_cached_parcels()
        logger.info(f"Parcel cache จาก Supabase: {len(parcel_cache):,} แปลง")

        progress = LandsMapsProgressTracker("progress.json")
        logger.info(f"Progress (resume ถ้า crash รอบนี้): {progress.done_count:,} asset ทำแล้ว")

        logger.section(f"เริ่ม Collect ({len(assets):,} assets ใหม่)")

        for i, asset in enumerate(assets):
            asset_id = asset["id"]
            if progress.is_done(asset_id):
                continue

            deedno_raw    = (asset.get("deedno_raw") or "").strip()
            city          = (asset.get("deedcity") or asset.get("city") or "").strip()
            amphur        = (asset.get("deedampur") or asset.get("ampur") or "").strip()
            asset_type_id = (asset.get("asset_type_id") or "").strip()

            if not deedno_raw:
                stats["no_deedno"] += 1
                progress.mark_done(asset_id)
                logger.log_not_found("no_deedno", asset)
                continue

            provid = PROVINCE_CODE.get(city) or (asset.get("led_province_id") or "").strip()
            if not provid:
                stats["no_amphur"] += 1
                progress.mark_done(asset_id)
                logger.log_not_found("no_province", asset, extra={"city": city})
                continue

            amph2 = session_mgr.get_amph2(provid, amphur, bkk_amph_dol)
            if not amph2:
                stats["no_amphur"] += 1
                progress.mark_done(asset_id)
                logger.log_not_found("no_amphur", asset,
                                     extra={"city": city, "amphur": amphur, "provid": provid})
                continue

            deedno_list = parse_deedno(deedno_raw)

            for deedno in deedno_list:
                cache_key    = f"{provid}_{amph2}_{deedno}"
                cached_entry = parcel_cache.get(cache_key)

                # ----- 5.3: เช็ค retry policy ก่อนตัดสินใจยิง API -----
                if not is_retryable(cached_entry):
                    stats["cache_hit"] += 1
                    if cached_entry and cached_entry.get("verify_status") != "not_found":
                        link_asset_parcel(asset_id, cached_entry["id"], None, None)
                    continue

                result = session_mgr.fetch_parcel(provid, amph2, deedno)
                stats["processed"] += 1

                if result is None:
                    stats["errors"] += 1
                    logger.log_not_found("error", asset, cache_key=cache_key,
                                         extra={"provid": provid, "amph2": amph2, "deedno": deedno})

                elif result == {}:
                    stats["not_found"] += 1
                    parcel_id = upsert_parcel(provid, amph2, deedno, {"verify_status": "not_found"})
                    parcel_cache[cache_key] = {"id": parcel_id, "verify_status": "not_found"}
                    logger.log_not_found("not_found", asset, cache_key=cache_key,
                                         extra={"provid": provid, "amph2": amph2, "deedno": deedno})

                else:
                    area_check = validate_area(asset, result, asset_type_id)

                    if area_check["reason"] == "condo_area_not_comparable":
                        stats["area_not_applicable"] += 1
                        verify_status = "not_verified"
                        area_match    = None
                        area_note     = ("ห้องชุด — ไม่เทียบพื้นที่ (area เป็นพื้นที่ที่ดินทั้งแปลง "
                                         "ไม่ใช่พื้นที่ห้อง) รอ admin ยืนยัน")
                    elif area_check["match"]:
                        stats["area_match"] += 1
                        verify_status = "matched"
                        area_match    = True
                        area_note     = None
                    else:
                        stats["area_mismatch"] += 1
                        verify_status = "mismatch"
                        area_match    = False
                        area_note     = ("พื้นที่ LED กับ LandsMaps ไม่ตรงกัน — "
                                         "ควรตรวจสอบว่าจับ parcel ถูกแปลงหรือไม่")

                    parcel_id = upsert_parcel(provid, amph2, deedno, {
                        "verify_status":      verify_status,
                        "verify_note":        area_note,
                        "latitude":           result.get("parcellat"),
                        "longitude":          result.get("parcellon"),
                        "land_price_per_sqw": result.get("landprice"),
                        "utm":                result.get("utm"),
                        "landoffice":         result.get("landoffice"),
                        "parcel_type":        result.get("parcel_type"),
                        "tambol_id":          result.get("tambol_id"),
                        "parcel_seq":         result.get("parcel_seq"),
                        "rai":                result.get("rai"),
                        "ngan":               result.get("ngan"),
                        "wa":                 result.get("wa"),
                    })
                    parcel_cache[cache_key] = {"id": parcel_id, "verify_status": verify_status}
                    link_asset_parcel(asset_id, parcel_id, area_match, area_note)
                    stats["found"] += 1

                time.sleep(DELAY_SEC)

            progress.mark_done(asset_id)

            if (stats["processed"] + stats["cache_hit"]) % SAVE_EVERY == 0:
                pct = (i + 1) / stats["total"] * 100
                logger.info(
                    f"  [{i+1:,}/{stats['total']:,}] {pct:.1f}% | "
                    f"✅{stats['found']:,} ❌{stats['not_found']:,} "
                    f"💾{stats['cache_hit']:,} ⚠️{stats['no_amphur']:,} "
                    f"📐match={stats['area_match']:,}/mismatch={stats['area_mismatch']:,}/"
                    f"n_a={stats['area_not_applicable']:,}"
                )
                progress.save(stats)

        progress.save(stats)
        success = True

        logger.section("📊 สรุปผล")
        logger.info(f"  Total asset ใหม่ : {stats['total']:,}")
        logger.info(f"  ✅ Found         : {stats['found']:,}")
        logger.info(f"  ❌ Not found     : {stats['not_found']:,}")
        logger.info(f"  💾 Cache hit     : {stats['cache_hit']:,}")
        logger.info(f"  ⚠️  No amphur    : {stats['no_amphur']:,}")
        logger.info(f"  🚫 No deedno     : {stats['no_deedno']:,}")
        logger.info(f"  🔴 Errors        : {stats['errors']:,}")
        logger.info(f"  📐 Area match    : {stats['area_match']:,}")
        logger.info(f"  📐 Area mismatch : {stats['area_mismatch']:,}")
        logger.info(f"  🏢 Area N/A (ห้องชุด, รอ verify): {stats['area_not_applicable']:,}")
        logger.info("\n✅ เสร็จสิ้น")

    except Exception:
        logger.error("💥 Collector ล้มเหลวกลางคัน — ดู traceback ด้านล่าง")
        raise
    finally:
        finish_run(run_id, stats, success)
        send_landsmaps_summary(stats)
        logger.close()


if __name__ == "__main__":
    main()
