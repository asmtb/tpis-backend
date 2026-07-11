"""
analyze_not_found.py — วิเคราะห์ข้อมูลที่ LandsMaps ดึงไม่สำเร็จ
จากไฟล์ landsmaps_not_found.jsonl

Features:
  - กรอง duplicate อัตโนมัติ (log เดียวกันบันทึกทับหลายรอบ)
    → unique key = (_reason, asset_id)  ถ้าไม่มี asset_id ใช้ (_reason, _cache_key)
  - แสดงสรุปแยกตาม reason / จังหวัด / อำเภอ / ประเภททรัพย์
  - export CSV สำหรับ analysis ต่อ

Usage:
  python analyze_not_found.py
  python analyze_not_found.py --file path/to/landsmaps_not_found.jsonl
  python analyze_not_found.py --csv  (export CSV ด้วย)
"""

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

# ===== mapping =====
ASSET_TYPE = {
    "001": "ที่ดินเปล่า",
    "002": "ห้องชุด/คอนโด",
    "003": "ที่ดิน+สิ่งปลูกสร้าง",
    "004": "สิ่งปลูกสร้าง",
}
REASON_LABEL = {
    "not_found":  "LandsMaps ไม่พบโฉนด",
    "no_amphur":  "แปลงอำเภอไม่ได้",
    "no_province": "แปลงจังหวัดไม่ได้",
    "no_deedno":  "ไม่มีเลขโฉนด",
    "error":      "Error (network/API)",
}


def load_unique(filepath: str) -> list[dict]:
    """
    โหลด JSONL และกรอง duplicate ออก
    ไฟล์เดียวเก็บต่อเนื่องหลาย run → record เดิมอาจปรากฏหลายครั้ง
    unique key = (reason, asset_id) หรือ (reason, cache_key) ถ้าไม่มี asset_id
    """
    seen = set()
    records = []
    total_lines = 0
    skipped_dup = 0

    with open(filepath, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            total_lines += 1
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue

            reason     = d.get("_reason", "?")
            asset_id   = d.get("led", {}).get("id")
            cache_key  = d.get("_cache_key", "")
            deedno     = d.get("_deedno", "")

            # unique key ต่อ 1 โฉนดต่อ reason
            # ใช้ (reason, asset_id, deedno) เพราะ 1 asset อาจมีหลายโฉนด
            uid = (reason, asset_id, deedno) if asset_id else (reason, cache_key)

            if uid in seen:
                skipped_dup += 1
                continue
            seen.add(uid)
            records.append(d)

    print(f"  ไฟล์: {filepath}")
    print(f"  บรรทัดทั้งหมด : {total_lines:,}")
    print(f"  Duplicate     : {skipped_dup:,}")
    print(f"  Unique records: {len(records):,}")
    return records


def analyze(records: list[dict]) -> dict:
    """วิเคราะห์และ return dict ผลลัพธ์"""

    by_reason      = Counter()
    by_province    = Counter()      # จังหวัด
    by_amphur      = Counter()      # จังหวัด + อำเภอ
    by_asset_type  = Counter()      # ประเภททรัพย์
    by_prov_reason = defaultdict(Counter)   # จังหวัด → reason count
    by_prov_type   = defaultdict(Counter)   # จังหวัด → asset_type count
    no_amphur_list = []             # รายการที่แปลงอำเภอไม่ได้

    for d in records:
        reason    = d.get("_reason", "?")
        led       = d.get("led", {})
        city      = led.get("deedcity") or led.get("city") or "-"
        amphur    = led.get("deedampur") or led.get("ampur") or d.get("_amphur") or "-"
        atype_id  = led.get("asset_type_id") or "-"
        atype     = ASSET_TYPE.get(atype_id, atype_id)

        by_reason[reason] += 1
        by_province[city] += 1
        by_amphur[f"{city} / {amphur}"] += 1
        by_asset_type[f"{atype_id}: {atype}"] += 1
        by_prov_reason[city][reason] += 1
        by_prov_type[city][atype] += 1

        if reason == "no_amphur":
            no_amphur_list.append({
                "city":    city,
                "amphur":  amphur,
                "provid":  d.get("_provid"),
                "deedno":  led.get("deedno_raw"),
                "atype":   atype,
            })

    return {
        "by_reason":      by_reason,
        "by_province":    by_province,
        "by_amphur":      by_amphur,
        "by_asset_type":  by_asset_type,
        "by_prov_reason": by_prov_reason,
        "by_prov_type":   by_prov_type,
        "no_amphur_list": no_amphur_list,
        "total":          len(records),
    }


def print_report(res: dict):
    total = res["total"]
    sep = "=" * 60

    print(f"\n{sep}")
    print(f"  สรุปผล: ทรัพย์ที่ LandsMaps ดึงไม่สำเร็จ")
    print(f"  รวม {total:,} รายการ (unique)")
    print(sep)

    # ---- 1. สาเหตุ ----
    print("\n📌 แยกตามสาเหตุ (reason)")
    print(f"  {'สาเหตุ':<35} {'จำนวน':>8}  {'%':>6}")
    print(f"  {'-'*35} {'-'*8}  {'-'*6}")
    for reason, cnt in res["by_reason"].most_common():
        label = REASON_LABEL.get(reason, reason)
        print(f"  {label:<35} {cnt:>8,}  {cnt/total*100:>5.1f}%")

    # ---- 2. จังหวัด (top 20) ----
    print("\n📌 แยกตามจังหวัด (top 20)")
    print(f"  {'จังหวัด':<25} {'จำนวน':>8}  {'%':>6}")
    print(f"  {'-'*25} {'-'*8}  {'-'*6}")
    for city, cnt in res["by_province"].most_common(20):
        print(f"  {city:<25} {cnt:>8,}  {cnt/total*100:>5.1f}%")

    # ---- 3. ประเภททรัพย์ ----
    print("\n📌 แยกตามประเภททรัพย์")
    print(f"  {'ประเภท':<35} {'จำนวน':>8}  {'%':>6}")
    print(f"  {'-'*35} {'-'*8}  {'-'*6}")
    for atype, cnt in res["by_asset_type"].most_common():
        print(f"  {atype:<35} {cnt:>8,}  {cnt/total*100:>5.1f}%")

    # ---- 4. จังหวัด × reason ----
    print("\n📌 จังหวัด × สาเหตุ (top 15 จังหวัด)")
    print(f"  {'จังหวัด':<25}", end="")
    reasons = list(res["by_reason"].keys())
    for r in reasons:
        short = r[:10]
        print(f"  {short:>10}", end="")
    print(f"  {'รวม':>8}")
    print(f"  {'-'*25}", end="")
    for _ in reasons:
        print(f"  {'-'*10}", end="")
    print(f"  {'-'*8}")
    for city, total_city in res["by_province"].most_common(15):
        print(f"  {city:<25}", end="")
        for r in reasons:
            cnt = res["by_prov_reason"][city].get(r, 0)
            print(f"  {cnt:>10,}", end="")
        print(f"  {total_city:>8,}")

    # ---- 5. จังหวัด × ประเภททรัพย์ (top 10) ----
    print("\n📌 จังหวัด × ประเภททรัพย์ (top 10 จังหวัด)")
    types = [v for v in ASSET_TYPE.values()]
    print(f"  {'จังหวัด':<25}", end="")
    for t in types:
        print(f"  {t[:8]:>10}", end="")
    print()
    print(f"  {'-'*25}", end="")
    for _ in types:
        print(f"  {'-'*10}", end="")
    print()
    for city, _ in res["by_province"].most_common(10):
        print(f"  {city:<25}", end="")
        for t in types:
            cnt = res["by_prov_type"][city].get(t, 0)
            print(f"  {cnt:>10,}", end="")
        print()

    # ---- 6. อำเภอ ที่มีปัญหามากสุด (top 20) ----
    print("\n📌 อำเภอ/เขต ที่ดึงไม่สำเร็จมากสุด (top 20)")
    print(f"  {'จังหวัด / อำเภอ':<45} {'จำนวน':>8}")
    print(f"  {'-'*45} {'-'*8}")
    for amphur, cnt in res["by_amphur"].most_common(20):
        print(f"  {amphur:<45} {cnt:>8,}")

    # ---- 7. no_amphur detail ----
    if res["no_amphur_list"]:
        print(f"\n📌 รายการที่แปลงอำเภอไม่ได้ ({len(res['no_amphur_list'])} รายการ)")
        print(f"  {'จังหวัด':<20} {'อำเภอ':<25} {'ประเภท'}")
        print(f"  {'-'*20} {'-'*25} {'-'*20}")
        for item in res["no_amphur_list"]:
            print(f"  {item['city']:<20} {item['amphur']:<25} {item['atype']}")

    print(f"\n{sep}")


def export_csv(records: list[dict], out_path: str):
    """Export รายการทั้งหมดเป็น CSV"""
    rows = []
    for d in records:
        led   = d.get("led", {})
        atype = led.get("asset_type_id", "-")
        rows.append({
            "reason":        d.get("_reason", ""),
            "reason_label":  REASON_LABEL.get(d.get("_reason", ""), d.get("_reason", "")),
            "asset_id":      led.get("id", ""),
            "cache_key":     d.get("_cache_key", ""),
            "provid":        d.get("_provid", ""),
            "amph2":         d.get("_amph2", ""),
            "deedno":        d.get("_deedno", ""),
            "city":          led.get("deedcity") or led.get("city") or "",
            "amphur":        led.get("deedampur") or led.get("ampur") or d.get("_amphur", ""),
            "asset_type_id": atype,
            "asset_type":    ASSET_TYPE.get(atype, atype),
            "rai":           led.get("rai", ""),
            "ngan":          led.get("ngan", ""),
            "wa":            led.get("wa", ""),
            "deedno_raw":    led.get("deedno_raw", ""),
            "timestamp":     d.get("_timestamp", ""),
        })

    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n💾 Export CSV → {out_path} ({len(rows):,} rows)")


def main():
    ap = argparse.ArgumentParser(description="วิเคราะห์ landsmaps_not_found.jsonl")
    ap.add_argument("--file", default="landsmaps_not_found.jsonl",
                    help="path ของ JSONL file")
    ap.add_argument("--csv", action="store_true",
                    help="export CSV ด้วย (ชื่อไฟล์เดียวกัน .csv)")
    args = ap.parse_args()

    filepath = args.file
    if not Path(filepath).exists():
        print(f"❌ ไม่พบไฟล์: {filepath}")
        return

    print("\n🔍 กำลังโหลดและกรอง duplicate...")
    records = load_unique(filepath)

    if not records:
        print("❌ ไม่มีข้อมูลในไฟล์")
        return

    res = analyze(records)
    print_report(res)

    if args.csv:
        csv_path = str(Path(filepath).with_suffix(".csv"))
        export_csv(records, csv_path)


if __name__ == "__main__":
    main()
