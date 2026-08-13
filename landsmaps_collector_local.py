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

โหมดพิเศษ:
  --retry-not-found   ดึงทุก asset ใหม่ (ไม่สนใจ checkpoint) แล้ว retry parcel ที่
                       เคย not_found โดยไม่สนใจ cooldown
  --file <path.json>  รันเฉพาะ asset ในไฟล์ (จากปุ่ม "⬇ Export JSON" ในหน้า Admin
                       modal "รายการใหม่" ของแต่ละ crawler run) — ข้าม checkpoint
                       ไปเลย เช่น: python landsmaps_collector_local.py --file tpis_new_assets_run123_2026-08-10.json

หมายเหตุ: ต้องมี .env ที่มี SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY,
           RESEND_API_KEY, NOTIFY_EMAIL ครบก่อนรัน
"""

import argparse
import json
import random
import sys
import time

from landsmaps_config import (
    PROVINCE_CODE, DELAY_SEC, DELAY_JITTER, SAVE_EVERY, BLOCK_SUSPECT_STREAK,
    load_bangkok_amphur,
)
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


def _seed_canary_from_cache(parcel_cache: dict) -> tuple[str, str, str] | None:
    """
    หา canary เริ่มต้นจาก cache ที่โหลดจาก Supabase ตอนต้น run (parcel ที่เคย
    matched/mismatch จากรอบก่อนๆ) — ใช้ตอนยังไม่มีรายการไหนสำเร็จเลยในรอบนี้
    (เผื่อ block ตั้งแต่ต้น run) คืน None ถ้าไม่มีอะไรใน cache ให้ใช้เลย
    (provid, amph2, deedno) จาก cache_key รูปแบบ "provid_amph2_deedno"
    """
    for key, entry in parcel_cache.items():
        if entry.get("verify_status") in ("matched", "mismatch"):
            parts = key.split("_", 2)
            if len(parts) == 3:
                return parts[0], parts[1], parts[2]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--retry-not-found", action="store_true",
        help=(
            "ยิง API ซ้ำสำหรับ parcel ที่เคย not_found โดย ignore cooldown "
            "และ ignore checkpoint (ดึง assets ทั้งหมด) — ใช้เมื่อสงสัยว่า "
            "LandsMaps ไม่เสถียรรอบที่แล้ว"
        ),
    )
    ap.add_argument(
        "--file",
        help=(
            "ไฟล์ JSON ที่ export จากหน้า Admin (ปุ่ม '⬇ Export JSON' ใน modal "
            "'รายการใหม่' ของแต่ละ crawler run) — รันเฉพาะ asset ในไฟล์นี้เท่านั้น "
            "ข้าม checkpoint/get_new_assets ปกติไปเลย เหมาะกับตอนอยากดึงพิกัดเฉพาะ "
            "รอบ LED ที่เพิ่งรันไปแบบเจาะจง โดยไม่ปนกับ asset ใหม่รอบอื่น"
        ),
    )
    args = ap.parse_args()
    retry_not_found: bool = args.retry_not_found
    file_path: str | None = args.file

    logger = LandsMapsLogger()
    run_id = None
    success = False
    stats = {
        "total": 0, "processed": 0,
        "found": 0, "not_found": 0, "cache_hit": 0,
        "no_deedno": 0, "no_amphur": 0, "errors": 0,
        "area_match": 0, "area_mismatch": 0, "area_not_applicable": 0,
        "suspected_ip_block": False, "stopped_at_index": None, "stopped_at_asset_id": None,
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

        # ----- 5.1: ดึง assets -----
        if file_path:
            logger.info(f"📂 โหลด assets จากไฟล์ {file_path} (ข้าม checkpoint ปกติ)")
            with open(file_path, encoding="utf-8") as f:
                payload = json.load(f)
            # รองรับทั้ง 2 รูปแบบ: {"assets": [...]} (จากปุ่ม Export JSON ในหน้า Admin)
            # หรือ list ตรงๆ เผื่อใครสร้างไฟล์เองแบบง่ายๆ
            assets = payload.get("assets", []) if isinstance(payload, dict) else payload
            logger.info(f"Asset จากไฟล์: {len(assets):,} รายการ")
        elif retry_not_found:
            # ignore checkpoint — ดึงทุก asset แล้วให้ cache policy ใหม่จัดการเอง
            logger.info("🔁 --retry-not-found: ignore checkpoint ดึง assets ทั้งหมด")
            checkpoint = None
            assets = get_new_assets(checkpoint)
        else:
            checkpoint = get_checkpoint()
            logger.info(f"Checkpoint (รอบล่าสุดที่สำเร็จ): {checkpoint or 'ไม่มี — รอบแรก ดึงทั้งหมด'}")
            assets = get_new_assets(checkpoint)

        stats["total"] = len(assets)
        logger.info(f"Asset ที่ต้องประมวลผล: {len(assets):,}")

        if not assets:
            logger.info("ไม่มี asset — จบงานทันที")
            success = True
            return

        # ----- 5.2: โหลด parcel cache จาก Supabase ครั้งเดียว -----
        parcel_cache = get_cached_parcels()
        logger.info(f"Parcel cache จาก Supabase: {len(parcel_cache):,} แปลง")

        if retry_not_found:
            # นับ not_found ใน cache เพื่อแสดงว่าจะ retry กี่แปลง
            nf_count = sum(1 for v in parcel_cache.values() if v.get("verify_status") == "not_found")
            logger.info(f"🔁 --retry-not-found: จะ retry {nf_count:,} แปลงที่เคย not_found (ignore cooldown)")

        progress = LandsMapsProgressTracker("progress.json")
        if retry_not_found and progress.done_count > 0:
            logger.info(f"🔁 --retry-not-found: reset progress.json ({progress.done_count:,} asset) เพื่อ re-process ใหม่ทั้งหมด")
            progress.reset()
        else:
            logger.info(f"Progress (resume ถ้า crash รอบนี้): {progress.done_count:,} asset ทำแล้ว")

        logger.section(f"เริ่ม Collect ({len(assets):,} assets)")

        # ----- Block detection state (canary re-check) -----
        # last_good_key: (provid, amph2, deedno) ของ parcel ล่าสุดที่ดึงสำเร็จจริง
        # (matched หรือ mismatch ก็นับ — แปลว่า LandsMaps ตอบข้อมูลจริงมาให้)
        # seed จาก cache ก่อนถ้ายังไม่เจอความสำเร็จเลยในรอบนี้ (เผื่อ block ตั้งแต่ต้น)
        last_good_key: tuple[str, str, str] | None = _seed_canary_from_cache(parcel_cache)
        not_found_streak = 0
        # buffer not_found ที่ยังไม่ยืนยันว่าเป็นของจริง — รอ flush ตอน streak จบ
        # (เจอรายการสำเร็จ หรือ canary ผ่าน) ถ้าโดน block ยืนยันแล้วจะทิ้งทั้งหมด
        # ไม่เขียนลง DB เลย กัน false not_found ปนเข้าระบบแล้วโดน cooldown 30 วัน
        pending_not_found: list[tuple[str, str, str, str]] = []  # (cache_key, provid, amph2, deedno)
        block_detected = False

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
                # --retry-not-found: ถือว่า not_found retryable เสมอ (ignore cooldown)
                # ปกติ: ใช้ policy ปกติ (not_found มี cooldown 30 วัน)
                retryable = (
                    True
                    if retry_not_found and cached_entry and cached_entry.get("verify_status") == "not_found"
                    else is_retryable(cached_entry)
                )
                if not retryable:
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
                    not_found_streak += 1
                    pending_not_found.append((cache_key, provid, amph2, deedno))
                    logger.log_not_found("not_found", asset, cache_key=cache_key,
                                         extra={"provid": provid, "amph2": amph2, "deedno": deedno})

                    if not_found_streak >= BLOCK_SUSPECT_STREAK:
                        if last_good_key:
                            c_provid, c_amph2, c_deedno = last_good_key
                            logger.warning(
                                f"⚠️  not_found ติดกัน {not_found_streak:,} รายการ — "
                                f"เช็ค canary {c_provid}/{c_amph2}/{c_deedno} (เคยดึงสำเร็จมาก่อน) ซ้ำ"
                            )
                            time.sleep(DELAY_SEC)
                            canary_result = session_mgr.fetch_parcel(c_provid, c_amph2, c_deedno)
                            if canary_result == {} or canary_result is None:
                                logger.error(
                                    f"🚫 Canary ที่เคยดึงสำเร็จตอนนี้ก็ {'not_found' if canary_result == {} else 'error'} "
                                    f"ด้วย — สงสัยโดน IP block (Incapsula soft-block คืนผลว่างเงียบๆ "
                                    f"ไม่ขึ้น challenge page) หยุดการ run ทันที ไม่เขียน not_found "
                                    f"ที่สะสมไว้ {len(pending_not_found)} รายการลง DB (อาจเป็นผลจาก block "
                                    f"ไม่ใช่ของจริง)"
                                )
                                block_detected = True
                                pending_not_found.clear()
                                stats["stopped_at_index"] = i + 1
                                stats["stopped_at_asset_id"] = asset_id
                                break
                            logger.info("✅ Canary ยังดึงได้ปกติ — ไม่ใช่ block แค่ deed ชุดนี้ไม่มีอยู่จริงเยอะ")
                        else:
                            logger.error(
                                f"⚠️  not_found ติดกัน {not_found_streak:,} รายการ และยังไม่มี canary "
                                f"ให้เช็ค (ยังไม่เคยดึงสำเร็จเลยทั้งรอบนี้และไม่มี cache เก่า) — หยุดไว้ก่อน"
                                f"เพื่อความปลอดภัย สงสัยโดน block ตั้งแต่ต้น run"
                            )
                            block_detected = True
                            pending_not_found.clear()
                            stats["stopped_at_index"] = i + 1
                            stats["stopped_at_asset_id"] = asset_id
                            break

                        # streak ผ่าน canary แล้ว → flush ของจริงลง DB แล้วรีเซ็ต
                        for pkey, pprovid, pamph2, pdeedno in pending_not_found:
                            p_id = upsert_parcel(pprovid, pamph2, pdeedno, {"verify_status": "not_found"})
                            parcel_cache[pkey] = {"id": p_id, "verify_status": "not_found"}
                        pending_not_found.clear()
                        not_found_streak = 0

                else:
                    # เจอผลจริง — ยืนยันว่า session ยังปกติ, flush not_found ที่ค้างไว้เป็นของจริง
                    if pending_not_found:
                        for pkey, pprovid, pamph2, pdeedno in pending_not_found:
                            p_id = upsert_parcel(pprovid, pamph2, pdeedno, {"verify_status": "not_found"})
                            parcel_cache[pkey] = {"id": p_id, "verify_status": "not_found"}
                        pending_not_found.clear()
                    not_found_streak = 0
                    last_good_key = (provid, amph2, deedno)

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

                time.sleep(DELAY_SEC + random.uniform(0, DELAY_JITTER))

            if block_detected:
                # ไม่ mark_done asset นี้ — ให้ progress.json พา asset นี้กลับมา
                # retry เองในรอบหน้าโดยไม่ต้องมี logic พิเศษเพิ่ม
                break

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
        stats["suspected_ip_block"] = block_detected
        success = not block_detected

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

        if block_detected:
            logger.error(
                f"🚫 หยุดกลางคันเพราะสงสัยโดน IP block — ประมวลผลไปแล้ว "
                f"{stats['stopped_at_index']:,}/{stats['total']:,} asset ก่อนหยุด "
                f"(asset_id ที่ทำค้างไว้: {stats['stopped_at_asset_id']}) "
                f"cookies ชุดนี้อาจโดน block ~24 ชม. แนะนำพักแล้วรันใหม่วันถัดไป "
                f"หรือเปลี่ยนเครือข่าย/IP ก่อนรันซ้ำ"
            )
            logger.info("\n🚫 หยุดกลางคัน (สงสัย IP block) — asset ที่ยังไม่เสร็จจะถูก retry อัตโนมัติรอบหน้า")
        else:
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
