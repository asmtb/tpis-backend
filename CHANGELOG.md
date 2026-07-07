# TPIS Changelog

รูปแบบเวอร์ชัน: `YYYY.MM.DD-N` (วันที่ deploy + ลำดับที่ deploy ในวันนั้น)
แต่ละบรรทัดระบุ component ที่กระทบใน `[ ]` เพราะหลาย component ผูกกันแน่น
(แก้โค้ดฝั่งหนึ่งมักต้องแก้ schema คู่กันด้วย)

---

## 2026.07.07-1

### Added
- `[infra]` ย้าย crawler จาก GitHub Actions → Google Cloud Run Jobs (Bangkok region, `asia-southeast3`) — แก้ปัญหา IP ถูกบล็อกโดย `asset.led.go.th` (บล็อกทั้ง ASN ของ Google Cloud region อื่นๆ แบบ silent TCP drop แต่ Bangkok region ผ่าน)
- `[infra]` Cloud Scheduler ตั้งรันอัตโนมัติทุก 3 วัน ตี 2 เวลาไทย (`Asia/Bangkok` timezone)
- `[docker]` `entrypoint.sh` รัน `crawler.py` ต่อด้วย `uploader.py` ในการทำงานเดียวกัน — จำเป็นเพราะดิสก์ของ Cloud Run Job เป็นแบบชั่วคราว (ephemeral) ไฟล์ JSON จะหายทันทีที่ container ถูกทำลายถ้าไม่อัพโหลดก่อน
- `[versioning]` เพิ่มไฟล์ `VERSION`, migration folder (`supabase/migrations/`), เลิกใช้เลข version ต่อท้ายชื่อไฟล์

### Fixed
- `[schema]` GRANT สิทธิ์ `service_role` ที่ขาดหายตั้งแต่สร้าง schema — แก้ 403 Forbidden ตอน insert `crawler_runs`/`assets` (migration `0002`)
- `[uploader.py]` เพิ่ม `dedupe_records()` ตัดข้อมูลซ้ำ key (`led_province_id`, `str_bid_num`, `deedno_raw`) ก่อน upsert — แก้ Postgres error 21000 (`ON CONFLICT DO UPDATE command cannot affect row a second time`) ที่ทำให้ทั้ง batch พังยกก้อน
- `[uploader.py]` เพิ่ม pagination ให้ `get_asset_ids()` ด้วย `Range` header — แก้บั๊กจังหวัดที่มี record เกิน 1,000 แถว (เช่นกรุงเทพ 9,055 รายการ) upload `asset_bid_rounds` ไม่ครบแบบเงียบๆ ไม่มี error โผล่ใน log
- `[uploader.py]` เพิ่ม `_request_with_retry()` ให้ทุกจุดที่คุย Supabase REST API — retry สูงสุด 3 ครั้งแบบ backoff เฉพาะ network error/5xx (ไม่ retry 4xx)

### Changed
- `[uploader.py]` `triggered_by` แก้จาก `"github_actions"` → `"cloud_run"` ให้ตรงกับที่รันจริง

---

## Template สำหรับรอบถัดไป

```markdown
## YYYY.MM.DD-N

### Added
- `[component]` ...

### Fixed
- `[component]` ...

### Changed
- `[component]` ...
```
