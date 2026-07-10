#!/bin/bash
# entrypoint_led.sh — รัน LED crawler แล้วอัพโหลดเข้า Supabase ต่อทันที
#
# ไม่ใช้ set -e เพราะต้องการให้ step 2 (uploader) รันเสมอแม้ crawler จะ fail
# เพื่อให้ send_led_summary() ใน uploader ส่ง email แจ้งเตือนได้ทุกกรณี

CRAWLER_EXIT=0

echo "===== STEP 1: Crawl LED ====="
python led_crawler.py "$@" || CRAWLER_EXIT=$?

if [ $CRAWLER_EXIT -ne 0 ]; then
    echo "⚠️  Crawler failed (exit $CRAWLER_EXIT) — uploading partial results and sending alert email"
fi

echo "===== STEP 2: Upload เข้า Supabase ====="
python led_uploader.py --dir led_output --crawler-exit $CRAWLER_EXIT

echo "===== เสร็จสมบูรณ์ทั้ง crawl + upload ====="
