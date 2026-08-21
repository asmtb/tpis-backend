"""
wishlist_supabase.py — Query/write helpers เฉพาะของ wishlist reminder job
แยกไฟล์ตาม pattern เดียวกับ landsmaps_supabase.py (ของกลางอยู่ supabase_common.py
ที่ led_uploader.py / landsmaps_supabase.py ใช้ร่วมกันอยู่แล้ว)
"""

from datetime import date

from supabase_common import SUPABASE_URL, HEADERS, _request_with_retry, paginated_select


def get_notify_enabled_users() -> list[dict]:
    """หา user ทั้งหมดที่เปิด wishlist_notify_enabled=true (migration 0015)
    พร้อม wishlist_reminder_days ที่เลือกไว้เอง (เช่น [1,3,7])"""
    return paginated_select(
        table="users",
        select="id,email,wishlist_reminder_days",
        filters={"wishlist_notify_enabled": "eq.true"},
    )


def get_watchlist_pairs(user_ids: list[str]) -> list[dict]:
    """ดึงคู่ (user_id, asset_id) ทั้งหมดของ user ที่ระบุจาก user_watchlists"""
    if not user_ids:
        return []
    ids_csv = ",".join(user_ids)
    return paginated_select(
        table="user_watchlists",
        select="user_id,asset_id",
        filters={"user_id": f"in.({ids_csv})"},
    )


def get_upcoming_rounds(asset_ids: list[int]) -> dict[int, dict]:
    """
    หา 'นัดประมูลถัดไป' ของแต่ละ asset — round ที่ issale_code='0' (ยังไม่มีผล
    ยังไม่ถูกยกเลิก/ขายไป) และ bid_date >= วันนี้ ที่ใกล้ที่สุด
    คืน dict: asset_id -> {round_no, bid_date}
    ถ้า asset ไม่มีนัดค้างเลย (ขายแล้ว/ปิดเคส/ยังไม่มีนัดประกาศ) จะไม่มี key นั้นเลย
    """
    if not asset_ids:
        return {}
    ids_csv = ",".join(str(a) for a in asset_ids)
    today_str = date.today().isoformat()
    rows = paginated_select(
        table="asset_bid_rounds",
        select="asset_id,round_no,bid_date,issale_code",
        filters={
            "asset_id":     f"in.({ids_csv})",
            "issale_code":  "eq.0",
            "bid_date":     f"gte.{today_str}",
        },
        order="bid_date.asc",
    )
    nearest: dict[int, dict] = {}
    for r in rows:
        aid = r["asset_id"]
        if aid not in nearest:   # แถวแรกที่เจอต่อ asset คือใกล้สุดแล้ว (order bid_date.asc)
            nearest[aid] = {"round_no": r["round_no"], "bid_date": r["bid_date"]}
    return nearest


def get_assets_by_ids(asset_ids: list[int]) -> dict[int, dict]:
    """ดึงรายละเอียด asset สำหรับใช้แสดงในอีเมล (ชื่อ/ทำเล/ราคา)"""
    if not asset_ids:
        return {}
    ids_csv = ",".join(str(a) for a in asset_ids)
    rows = paginated_select(
        table="assets",
        select=(
            "id,str_bid_num,asset_type_desc,city,ampur,tumbol,"
            "assetprice3,url_picture,is_closed,is_sold"
        ),
        filters={"id": f"in.({ids_csv})"},
    )
    return {r["id"]: r for r in rows}


def get_already_sent_keys(user_ids: list[str]) -> set[tuple]:
    """
    โหลด log การแจ้งเตือนที่เคยส่งไปแล้วของ user เหล่านี้ทั้งหมดจาก
    wishlist_reminder_log (migration 0016) คืนเป็น set of
    (user_id, asset_id, round_no, bid_date, day_offset) เทียบกันไวกว่า
    query ทีละแถวระหว่างวนลูป
    """
    if not user_ids:
        return set()
    ids_csv = ",".join(user_ids)
    rows = paginated_select(
        table="wishlist_reminder_log",
        select="user_id,asset_id,round_no,bid_date,day_offset",
        filters={"user_id": f"in.({ids_csv})"},
    )
    return {
        (r["user_id"], r["asset_id"], r["round_no"], r["bid_date"], r["day_offset"])
        for r in rows
    }


def insert_log_rows(rows: list[dict]):
    """
    บันทึกว่าส่งแจ้งเตือนแล้ว — ใช้ resolution=ignore-duplicates กัน
    unique constraint ชน (uq_wishlist_reminder) กรณี run ซ้อนกันโดยไม่ตั้งใจ
    ไม่ raise error ถ้าชน แค่ข้ามแถวที่ซ้ำไปเงียบๆ
    """
    if not rows:
        return
    url = f"{SUPABASE_URL}/rest/v1/wishlist_reminder_log"
    hdrs = {**HEADERS, "Prefer": "resolution=ignore-duplicates"}
    r = _request_with_retry("POST", url, headers=hdrs, json=rows, timeout=30)
    r.raise_for_status()
