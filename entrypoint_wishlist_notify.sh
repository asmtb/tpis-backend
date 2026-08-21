#!/bin/bash
# entrypoint_wishlist_notify.sh — รัน wishlist bid-date reminder job
# แยก Cloud Run Job ต่างหากจาก LED/LandsMaps รันทุกวันผ่าน Cloud Scheduler
# ไม่ผูกกับ schedule เดียวกับ LED (LED รันทุก 3 วัน แต่แจ้งเตือนนัดประมูล
# ต้องเช็คทุกวัน ไม่งั้นวันที่ตรงกับ reminder_days พอดีอาจถูกข้ามไป)
set -e

echo "===== Wishlist Reminder ====="
python wishlist_notify.py "$@"

echo "===== เสร็จสมบูรณ์ ====="
