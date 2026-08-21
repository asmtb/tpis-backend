# ใช้ official Playwright image ที่มี Chromium + system deps ครบแล้ว
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# คัดลอกโค้ดทั้งหมด (รวม VERSION ไฟล์ด้วย — uploader.py อ่านตอน insert crawler_runs)
COPY . .

# ให้สิทธิ์รัน entrypoint scripts ทั้งสามตัว
RUN chmod +x entrypoint_led.sh entrypoint_landsmaps.sh entrypoint_wishlist_notify.sh

# Default เป็น LED (Cloud Scheduler ใช้ตัวนี้)
# LandsMaps Job และ Wishlist Reminder Job จะ override ด้วย --entrypoint ตอน deploy
ENTRYPOINT ["./entrypoint_led.sh"]
