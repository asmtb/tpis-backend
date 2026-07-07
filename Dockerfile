# ใช้ official Playwright image ที่มี Chromium + system deps ครบแล้ว
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# คัดลอกโค้ด crawler ทั้งหมด (รวม VERSION ไฟล์ด้วย — uploader.py อ่านตอน insert crawler_runs)
COPY . .

# ให้สิทธิ์รัน entrypoint script
RUN chmod +x entrypoint.sh

# รัน crawler แล้วต่อด้วย uploader ในการทำงานเดียวกัน
# สำคัญ: ต้องทำก่อน container ถูกทำลาย เพราะดิสก์ของ Cloud Run Job เป็นแบบชั่วคราว
ENTRYPOINT ["./entrypoint.sh"]
