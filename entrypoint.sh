#!/bin/bash
# entrypoint.sh — รัน crawler แล้วอัพโหลดเข้า Supabase ต่อทันที
# ต้องทำในการทำงานเดียวกันเพราะ container ของ Cloud Run Job เป็นดิสก์ชั่วคราว
# ไฟล์ led_output/ จะหายไปทันทีที่ container ถูกทำลายหลัง job จบ
set -e   # หยุดทันทีถ้าขั้นตอนไหน error ไม่ต้องไปต่อขั้นถัดไป

echo "===== STEP 1: Crawl LED ====="
python led_crawler.py "$@"

echo "===== STEP 2: Upload เข้า Supabase ====="
python led_uploader.py --dir led_output

echo "===== เสร็จสมบูรณ์ทั้ง crawl + upload ====="
