#!/bin/bash
# entrypoint_led.sh — รัน LED crawler แล้วอัพโหลดเข้า Supabase ต่อทันที
set -e

echo "===== STEP 1: Crawl LED ====="
python led_crawler.py "$@"

echo "===== STEP 2: Upload เข้า Supabase ====="
python led_uploader.py --dir led_output

echo "===== เสร็จสมบูรณ์ทั้ง crawl + upload ====="
