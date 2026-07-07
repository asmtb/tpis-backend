"""
TPIS - LandsMaps Collector
โครงสร้างแยกไฟล์แล้วตาม pattern เดียวกับ LED crawler (กลุ่ม 3):
  landsmaps_config.py    — constants + BANGKOK_AMPHUR.json loader
  landsmaps_session.py   — JWT/cookies/fetch_parcel/amphur lookup
  landsmaps_parser.py    — parse_deedno (ใช้ร่วมกับ LED) + validate_area
  landsmaps_progress.py  — resume tracker
  landsmaps_logger.py    — logging (เลิก hack sys.stdout)

Input:
    led_all_assets.json   — LED records ทั้งประเทศ
    Copy_as_cURL.txt      — cURL จาก landsmaps.dol.go.th (ชั่วคราว รอกลุ่ม 4)
    BANGKOK_AMPHUR.json   — mapping เขตกรุงเทพ

Output:
    landsmaps_coordinates.json  — unique parcel cache (จะเลิกใช้หลังกลุ่ม 5)
    progress.json               — resume checkpoint
    landsmaps_collector.log     — log
"""

import json
import sys
import time
from pathlib import Path

from landsmaps_config import (
    COORD_FILE, LED_FILE, CURL_FILE, PROVINCE_CODE,
    DELAY_SEC, SAVE_EVERY, load_bangkok_amphur,
)
from landsmaps_logger import LandsMapsLogger
from landsmaps_parser import parse_deedno, validate_area
from landsmaps_progress import LandsMapsProgressTracker
from landsmaps_session import SessionManager


def main():
    logger = LandsMapsLogger()
    try:
        logger.section("TPIS - LandsMaps Collector")

        bkk_amph_dol = load_bangkok_amphur(logger)

        session_mgr = SessionManager(logger, CURL_FILE)
        if not session_mgr.init_from_curl_file():
            logger.error("❌ ไม่ได้ JWT — cookies อาจหมดอายุ ต้อง copy cURL ใหม่จาก browser")
            sys.exit(1)
        logger.info("✅ JWT OK")

        with open(LED_FILE, encoding="utf-8") as f:
            led_records = json.load(f)
        logger.info(f"LED records: {len(led_records):,}")

        coord_cache = {}
        if Path(COORD_FILE).exists():
            with open(COORD_FILE, encoding="utf-8") as f:
                coord_cache = json.load(f)
        logger.info(f"Coordinate cache: {len(coord_cache):,} parcels")

        progress = LandsMapsProgressTracker("progress.json")
        logger.info(f"Progress: {progress.done_count:,} records ทำแล้ว")

        stats = {
            "total": len(led_records), "processed": 0,
            "found": 0, "not_found": 0, "cache_hit": 0,
            "no_deedno": 0, "no_amphur": 0, "errors": 0,
            "area_match": 0, "area_mismatch": 0, "area_not_applicable": 0,
        }

        logger.section(f"เริ่ม Collect ({len(led_records):,} records)")

        for idx, record in enumerate(led_records):
            if progress.is_done(idx):
                continue

            deedno_raw    = (record.get("deedno") or "").strip()
            city          = (record.get("deedcity") or record.get("city") or "").strip()
            amphur        = (record.get("deedampur") or record.get("ampur") or "").strip()
            asset_type_id = (record.get("AssetTypeID") or record.get("asset_type_id") or "").strip()

            if not deedno_raw:
                stats["no_deedno"] += 1
                progress.mark_done(idx)
                logger.log_not_found("no_deedno", record)
                continue

            provid = PROVINCE_CODE.get(city) or record.get("_province_id", "").strip()
            if not provid:
                stats["no_amphur"] += 1
                progress.mark_done(idx)
                logger.log_not_found("no_province", record, extra={"city": city})
                continue

            amph2 = session_mgr.get_amph2(provid, amphur, bkk_amph_dol)
            if not amph2:
                stats["no_amphur"] += 1
                progress.mark_done(idx)
                logger.log_not_found("no_amphur", record,
                                      extra={"city": city, "amphur": amphur, "provid": provid})
                continue

            deedno_list = parse_deedno(deedno_raw)

            for deedno in deedno_list:
                cache_key = f"{provid}_{amph2}_{deedno}"

                if cache_key in coord_cache:
                    stats["cache_hit"] += 1
                    continue

                result = session_mgr.fetch_parcel(provid, amph2, deedno)
                stats["processed"] += 1

                if result is None:
                    stats["errors"] += 1
                    logger.log_not_found("error", record, cache_key=cache_key,
                                          extra={"provid": provid, "amph2": amph2, "deedno": deedno})
                elif result == {}:
                    stats["not_found"] += 1
                    coord_cache[cache_key] = None
                    logger.log_not_found("not_found", record, cache_key=cache_key,
                                          extra={"provid": provid, "amph2": amph2, "deedno": deedno})
                else:
                    area_check = validate_area(record, result, asset_type_id)

                    if area_check["reason"] == "condo_area_not_comparable":
                        stats["area_not_applicable"] += 1
                        verify_status = "not_verified"
                        verify_note = ("ห้องชุด — ไม่เทียบพื้นที่ (area เป็นพื้นที่ที่ดินทั้งแปลง "
                                       "ไม่ใช่พื้นที่ห้อง) รอ admin ยืนยัน")
                    elif area_check["match"]:
                        stats["area_match"] += 1
                        verify_status = "matched"
                        verify_note = None
                    else:
                        stats["area_mismatch"] += 1
                        verify_status = "mismatch"
                        verify_note = "พื้นที่ LED กับ LandsMaps ไม่ตรงกัน — ควรตรวจสอบว่าจับ parcel ถูกแปลงหรือไม่"

                    coord_cache[cache_key] = {
                        "parcellat":      result.get("parcellat"),
                        "parcellon":      result.get("parcellon"),
                        "utm":            result.get("utm"),
                        "n":              result.get("n"),
                        "e":              result.get("e"),
                        "zone":           result.get("zone"),
                        "landprice":      result.get("landprice"),
                        "tumbolname":     result.get("tumbolname"),
                        "amphurname":     result.get("amphurname"),
                        "provname":       result.get("provname"),
                        "landoffice":     result.get("landoffice"),
                        "landoffice_id":  result.get("landoffice_id"),
                        "rai":            result.get("rai"),
                        "ngan":           result.get("ngan"),
                        "wa":             result.get("wa"),
                        "parcel_type":    result.get("parcel_type"),
                        "parcel_seq":     result.get("parcel_seq"),
                        "lands_status":   result.get("lands_status"),
                        "provid":         result.get("provid"),
                        "amphurid":       result.get("amphurid"),
                        "tambol_id":      result.get("tambol_id"),
                        "qrcode_link":    result.get("qrcode_link"),
                        "_area_match":    area_check["match"],
                        "_area_led":      area_check["led"],
                        "_area_lm":       area_check["lm"],
                        "_verify_status": verify_status,
                        "_verify_note":   verify_note,
                    }
                    stats["found"] += 1

                time.sleep(DELAY_SEC)

            progress.mark_done(idx)

            if (stats["processed"] + stats["cache_hit"]) % SAVE_EVERY == 0:
                pct = (idx + 1) / stats["total"] * 100
                logger.info(
                    f"  [{idx+1:,}/{stats['total']:,}] {pct:.1f}% | "
                    f"✅{stats['found']:,} ❌{stats['not_found']:,} "
                    f"💾{stats['cache_hit']:,} ⚠️{stats['no_amphur']:,} "
                    f"📐match={stats['area_match']:,}/mismatch={stats['area_mismatch']:,}/"
                    f"n_a={stats['area_not_applicable']:,}"
                )
                with open(COORD_FILE, "w", encoding="utf-8") as f:
                    json.dump(coord_cache, f, ensure_ascii=False)
                progress.save(stats)

        # Final save
        with open(COORD_FILE, "w", encoding="utf-8") as f:
            json.dump(coord_cache, f, ensure_ascii=False, indent=2)
        progress.save(stats)

        logger.section("📊 สรุปผล")
        logger.info(f"  Total           : {stats['total']:,}")
        logger.info(f"  ✅ Found        : {stats['found']:,}")
        logger.info(f"  ❌ Not found    : {stats['not_found']:,}")
        logger.info(f"  💾 Cache hit    : {stats['cache_hit']:,}")
        logger.info(f"  ⚠️  No amphur   : {stats['no_amphur']:,}")
        logger.info(f"  🚫 No deedno    : {stats['no_deedno']:,}")
        logger.info(f"  🔴 Errors       : {stats['errors']:,}")
        logger.info(f"  Unique parcels  : {len(coord_cache):,}")
        logger.info(f"  📐 Area match   : {stats['area_match']:,}")
        logger.info(f"  📐 Area mismatch: {stats['area_mismatch']:,}")
        logger.info(f"  🏢 Area N/A (ห้องชุด, รอ verify): {stats['area_not_applicable']:,}")
        logger.info("\n✅ เสร็จสิ้น")

    finally:
        logger.close()   # ปิดไฟล์ log/not-found เสมอ ไม่ว่าจะจบแบบไหน (สำเร็จ/error/crash)


if __name__ == "__main__":
    main()
