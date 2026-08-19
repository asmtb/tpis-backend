"""
landsmaps_parser.py — parsing logic เฉพาะของ LandsMaps
ข้อ 3.2: parse_deedno() ใช้ตัวเดียวกับ LED โดยตรง ไม่ copy โค้ดซ้ำ
(เช็คแล้วโค้ดเดิมของ landsmaps_collector_v6.py กับ parser.py ของ LED
 เป็น logic เดียวกันเป๊ะทั้ง _expand_range และ parse_deedno)
"""

from led_parser import parse_deedno  # 👈 ใช้ตัวเดียวกับ LED — ไม่มี copy ซ้ำอีกต่อไป

__all__ = ["parse_deedno", "parse_area", "validate_area"]


def parse_area(val):
    """แปลงค่า rai/ngan/wa เป็น float
    None หรือค่าว่าง ถือเป็น 0.0 เสมอ — LED ไม่กรอก rai/ngan แปลว่า "0" ไม่ใช่
    "ไม่ทราบค่า" (ปกติมาเป็นชุด rai/ngan/wa คู่กัน ถ้าตัวไหนไม่กรอกคือมันเป็น 0)
    เดิม dict.get(key, 0) ไม่ช่วยอะไรตรงนี้เพราะ key มีอยู่จริงแค่ค่าเป็น None
    (.get ใช้ default เฉพาะตอนไม่มี key เลย ไม่ใช่ตอนค่าเป็น None) ทำให้
    parse_area(None) เดิมคืน None แล้วไปเทียบกับ LandsMaps ที่คืน 0.0 จริงๆ
    กลายเป็น None != 0.0 → mismatch ทั้งที่ข้อมูลตรงกันทุกอย่าง

    แปลงไม่ได้จริงๆ (ข้อมูลเสีย ไม่ใช่ None/ว่าง) ยังคงคืน None เหมือนเดิม เพื่อให้
    เคสนี้ไป mismatch ให้ admin ตรวจสอบต่อ แทนที่จะเดาว่าตรงกันเฉยๆ
    """
    if val is None or (isinstance(val, str) and val.strip() == ""):
        return 0.0
    try:
        return float(str(val).replace(",", "").strip())
    except Exception:
        return None


def validate_area(led: dict, lm: dict, asset_type_id: str = "") -> dict:
    """
    เปรียบเทียบพื้นที่จาก LED กับ LandsMaps
    LED fields: rai, ngan, wa
    LandsMaps fields: rai, ngan, wa

    ⚠️ ห้องชุด (asset_type_id == "002"): LED แสดงพื้นที่ห้อง (unit area)
    แต่ LandsMaps แสดงพื้นที่ที่ดินทั้งแปลงที่ตึกตั้งอยู่ — คนละมิติ
    เทียบกันไม่ได้โดยธรรมชาติ ต้อง "ข้าม" การเทียบ ไม่ใช่แค่ผ่อนเกณฑ์
    คืนค่า match=None เพื่อแยกออกจาก True/False ชัดเจน (ไม่ใช่ match ก็ไม่ใช่ mismatch)

    return: {"match": True/False/None, "led": {...}, "lm": {...}, "reason": str}
    """
    if asset_type_id == "002":
        return {
            "match":  None,
            "reason": "condo_area_not_comparable",
            "led":    {"rai": parse_area(led.get("rai", 0)),
                       "ngan": parse_area(led.get("ngan", 0)),
                       "wa": parse_area(led.get("wa", 0))},
            "lm":     {"rai": parse_area(lm.get("rai", 0)),
                       "ngan": parse_area(lm.get("ngan", 0)),
                       "wa": parse_area(lm.get("wa", 0))},
        }

    led_rai  = parse_area(led.get("rai", 0))
    led_ngan = parse_area(led.get("ngan", 0))
    led_wa   = parse_area(led.get("wa", 0))
    lm_rai   = parse_area(lm.get("rai", 0))
    lm_ngan  = parse_area(lm.get("ngan", 0))
    lm_wa    = parse_area(lm.get("wa", 0))

    match = (led_rai == lm_rai and led_ngan == lm_ngan and led_wa == lm_wa)
    return {
        "match":  match,
        "reason": "compared",
        "led":    {"rai": led_rai, "ngan": led_ngan, "wa": led_wa},
        "lm":     {"rai": lm_rai,  "ngan": lm_ngan,  "wa": lm_wa},
    }
