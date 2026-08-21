"""
wishlist_notify.py — TPIS Wishlist Bid-Date Reminder
===================================================================
ส่งอีเมลแจ้งเตือนนัดประมูลของทรัพย์ใน wishlist (user_watchlists) ล่วงหน้า
ตามจำนวนวันที่ user เลือกไว้เอง (1/3/7 วันก่อนนัด เลือกได้หลายค่าพร้อมกัน)
ตั้งค่าไว้ที่หน้า /account ของเว็บ (public.users.wishlist_notify_enabled +
wishlist_reminder_days, migration 0015)

ออกแบบให้รันทุกวันผ่าน Cloud Scheduler + Cloud Run Job แยกจาก LED/LandsMaps
เดิม (แนะนำรันเวลาเดียวกันทุกวัน เช่น 08:00 เวลาไทย)

Logic หลัก:
  1. หา user ที่เปิด wishlist_notify_enabled=true
  2. หา asset ทั้งหมดใน watchlist ของ user เหล่านั้น
  3. หา "นัดประมูลถัดไป" (issale_code='0', bid_date ใกล้ที่สุดที่ >= วันนี้)
     ของแต่ละ asset — ถ้าไม่มีนัดค้าง (ขายแล้ว/ปิดเคส/ยังไม่มีนัด) ข้ามไป
  4. เทียบ (bid_date - วันนี้) กับ reminder_days ของ user แต่ละคน — ตรงเป๊ะ
     กับวันใดวันหนึ่งที่ user เลือกไว้ = ต้องแจ้งวันนี้
  5. เช็ค wishlist_reminder_log (migration 0016) กันส่งซ้ำ — unique key
     ครอบ (user, asset, round_no, bid_date, day_offset) รวม bid_date ด้วย
     เพราะถ้านัดเลื่อน ต้องแจ้งใหม่เสมือนเป็นนัดใหม่
  6. Group ทุกรายการที่ต้องแจ้งของ user เดียวกัน → อีเมลเดียว ไม่แยกส่ง
     ทีละทรัพย์
  7. บันทึก log เฉพาะรายการที่ "ส่งอีเมลสำเร็จจริง" เท่านั้น — ถ้าส่งอีเมล
     ของ user คนไหน fail จะไม่ log อะไรเลยสำหรับ user นั้น ปล่อยให้รอบถัดไป
     (พรุ่งนี้) ลองส่งใหม่อีกครั้งแทนที่จะข้ามไปเงียบๆ ตลอดกาล

รัน:
  python wishlist_notify.py
"""

import sys
from datetime import date, datetime

from supabase_common import BKK_TZ, sb_insert_run, sb_update_run
from wishlist_supabase import (
    get_notify_enabled_users, get_watchlist_pairs, get_upcoming_rounds,
    get_assets_by_ids, get_already_sent_keys, insert_log_rows,
)
from wishlist_email import send_wishlist_reminder


def main():
    run_id  = None
    success = False
    stats = {
        "users_checked":  0,
        "users_notified": 0,
        "reminders_sent": 0,
        "errors":         0,
    }

    try:
        run_id = sb_insert_run({
            "started_at":   datetime.now(BKK_TZ).isoformat(),
            "status":       "running",
            "run_mode":     "wishlist_notify",
            "triggered_by": "cloud_run",
        })
        print(f"crawler_run id: {run_id}")

        today = datetime.now(BKK_TZ).date()
        print(f"วันนี้ (Bangkok): {today.isoformat()}")

        users = get_notify_enabled_users()
        stats["users_checked"] = len(users)
        print(f"User ที่เปิดแจ้งเตือน: {len(users)} คน")

        if not users:
            print("ไม่มี user เปิดแจ้งเตือนไว้เลย — จบงานทันที")
            success = True
            return

        user_ids    = [u["id"] for u in users]
        users_by_id = {u["id"]: u for u in users}

        pairs = get_watchlist_pairs(user_ids)
        print(f"รายการ wishlist ทั้งหมดของ user เหล่านี้: {len(pairs)} รายการ")

        if not pairs:
            print("ไม่มีใครมี wishlist เลย — จบงานทันที")
            success = True
            return

        asset_ids       = sorted({p["asset_id"] for p in pairs})
        rounds_by_asset = get_upcoming_rounds(asset_ids)
        assets_by_id    = get_assets_by_ids(asset_ids)
        already_sent    = get_already_sent_keys(user_ids)

        # จับคู่ user -> list ของ asset_id ใน wishlist ตัวเอง
        assets_by_user: dict[str, list[int]] = {}
        for p in pairs:
            assets_by_user.setdefault(p["user_id"], []).append(p["asset_id"])

        confirmed_log_rows = []   # เฉพาะรายการที่ "ส่งอีเมลสำเร็จแล้ว" เท่านั้น

        for uid, aids in assets_by_user.items():
            user = users_by_id[uid]
            reminder_days = set(user.get("wishlist_reminder_days") or [])
            if not reminder_days:
                continue  # เปิด notify ไว้แต่ไม่ได้เลือกวันไหนเลย (UI validate กันไว้แล้ว แต่กันเผื่อ)

            to_notify        = []   # รายการที่จะใส่ในอีเมล
            prospective_log  = []   # log ที่จะบันทึก "ถ้า" ส่งอีเมลสำเร็จ

            for aid in aids:
                round_info = rounds_by_asset.get(aid)
                if not round_info:
                    continue   # ไม่มีนัดค้าง (ขายแล้ว/ยังไม่ประกาศนัด)

                bid_date_str = round_info["bid_date"]
                bid_date     = date.fromisoformat(bid_date_str)
                days_left    = (bid_date - today).days
                if days_left not in reminder_days:
                    continue

                key = (uid, aid, round_info["round_no"], bid_date_str, days_left)
                if key in already_sent:
                    continue

                asset = assets_by_id.get(aid)
                if not asset:
                    continue

                to_notify.append({
                    "asset":     asset,
                    "round_no":  round_info["round_no"],
                    "bid_date":  bid_date_str,
                    "days_left": days_left,
                })
                prospective_log.append({
                    "user_id":    uid,
                    "asset_id":   aid,
                    "round_no":   round_info["round_no"],
                    "bid_date":   bid_date_str,
                    "day_offset": days_left,
                })

            if not to_notify:
                continue

            ok = send_wishlist_reminder(user["email"], to_notify)
            if ok:
                stats["users_notified"] += 1
                stats["reminders_sent"] += len(to_notify)
                confirmed_log_rows.extend(prospective_log)
            else:
                stats["errors"] += 1
                print(f"  ❌ ส่งอีเมลไม่สำเร็จ: {user['email']} (จะลองใหม่รอบถัดไป)")

        insert_log_rows(confirmed_log_rows)
        success = True

        print("\n📊 สรุปผล")
        print(f"  User ที่เปิดแจ้งเตือน   : {stats['users_checked']}")
        print(f"  ส่งอีเมลสำเร็จ          : {stats['users_notified']} คน")
        print(f"  รายการที่แจ้งไปทั้งหมด  : {stats['reminders_sent']}")
        print(f"  Errors                  : {stats['errors']}")
        print("\n✅ เสร็จสิ้น")

    except Exception as e:
        print(f"💥 wishlist_notify ล้มเหลว: {e}")
        raise
    finally:
        if run_id:
            sb_update_run(run_id, {
                "finished_at":           datetime.now(BKK_TZ).isoformat(),
                "status":                "completed" if success else "failed",
                "total_records_fetched": stats["reminders_sent"],
                "error_message":         None if stats["errors"] == 0 else f"errors={stats['errors']}",
            })


if __name__ == "__main__":
    main()
