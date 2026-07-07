#!/bin/bash
# build_and_push.sh — build + push image พร้อม tag ตาม VERSION file
# แก้ปัญหาเดิมที่ใช้ :latest อย่างเดียว → deploy พังแล้ว rollback ไม่ได้
#
# ใช้:
#   ./build_and_push.sh
#
# หลัง build เสร็จ image จะมี 2 tags:
#   led-crawler:2026.07.07-1   ← ใช้ตอน rollback (ระบุ version ตายตัว)
#   led-crawler:latest         ← ใช้ตอน deploy ปกติ

set -e

VERSION=$(cat VERSION)
REPO="asia-southeast3-docker.pkg.dev/tpis-led/tpis-repo/led-crawler"

echo "===== Building image version: ${VERSION} ====="
docker build -t "${REPO}:${VERSION}" -t "${REPO}:latest" .

echo "===== Pushing both tags ====="
docker push "${REPO}:${VERSION}"
docker push "${REPO}:latest"

echo "===== เสร็จแล้ว ====="
echo "Deploy เวอร์ชันนี้:  gcloud run jobs update tpis-cron-weekly --region=asia-southeast3 --image=${REPO}:${VERSION}"
echo "Rollback ไปตัวนี้ทีหลัง: gcloud run jobs update tpis-cron-weekly --region=asia-southeast3 --image=${REPO}:${VERSION}"
