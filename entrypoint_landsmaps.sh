#!/bin/bash
# entrypoint_landsmaps.sh — รัน LandsMaps collector
# อ่าน cookies จาก Supabase (landsmaps_sessions table)
# รัน manual ได้ทุกเมื่อ ไม่ผูกกับ Cloud Scheduler
set -e

echo "===== LandsMaps Collector ====="
python landsmaps_collector.py "$@"

echo "===== เสร็จสมบูรณ์ ====="
