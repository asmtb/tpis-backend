# TPIS Changelog

รูปแบบเวอร์ชัน: `YYYY.MM.DD-N` (วันที่ deploy + ลำดับที่ deploy ในวันนั้น)
แต่ละบรรทัดระบุ component ที่กระทบใน `[ ]` เพราะหลาย component ผูกกันแน่น
(แก้โค้ดฝั่งหนึ่งมักต้องแก้ schema คู่กันด้วย)

`[WIP]` = ยังทำไม่ครบทุกกลุ่มที่วางแผนไว้ ยังไม่ deploy จริง รอกลุ่ม 4 (session
automation) เสร็จก่อนถึงจะปิดเป็นเลขเวอร์ชันจริงและ deploy ทั้งชุด

---

## [WIP] 2026.07.08-1

### Added — Group 1 (schema: เคสห้องชุด)
- `[schema]` migration `0004_condo_not_verified_status.sql` — เพิ่มค่า enum `not_verified` ให้ verify status, เพิ่ม column `verified_by`/`verified_at` (audit trail), เพิ่ม RLS policy ให้ admin update ผ่านหน้าเว็บได้, แก้ view `assets_map` ให้โชว์ `not_verified` บนแผนที่ด้วย *(หมายเหตุ: ภายหลัง migration 0005 แทนที่ตารางเป้าหมายจาก `asset_coordinates` เป็น `parcels` แล้ว — ดูด้านล่าง)*

### Added — Group 6 (landsmaps: เคสห้องชุด asset_type_id="002")
- `[landsmaps]` `validate_area()` รับ `asset_type_id` แล้วข้ามการเทียบพื้นที่ถ้าเป็นห้องชุด — พื้นที่ที่ LED แสดง (พื้นที่ห้อง) เทียบกับ LandsMaps (พื้นที่ที่ดินทั้งแปลง) ไม่ได้โดยธรรมชาติ
- `[landsmaps]` เพิ่มสถิติ `area_not_applicable` แยกจาก `area_mismatch` — กันตัวเลขสรุปท้าย run เบี้ยวเวลามีห้องชุดเยอะ
- `[landsmaps]` เพิ่ม `_verify_status`/`_verify_note` (`not_verified` + เหตุผล) สำหรับห้องชุด

### Added — Group 3 (landsmaps: แยกไฟล์ตาม pattern LED)
- `[landsmaps]` แยกจากไฟล์เดียว (`landsmaps_collector_v6.py`) เป็น 6 ไฟล์: `landsmaps_config.py`, `landsmaps_session.py`, `landsmaps_parser.py`, `landsmaps_progress.py`, `landsmaps_logger.py`, `landsmaps_collector.py`
- `[landsmaps_parser.py]` ใช้ `parse_deedno()` ร่วมกับ LED โดยตรง (import จาก `led_parser.py`) เลิก copy โค้ดซ้ำที่เคยมี 2 ที่
- `[landsmaps_logger.py]` เลิก hack `sys.stdout = Tee(...)` เปลี่ยนเป็น Python `logging` module มาตรฐาน ปิดไฟล์ปลอดภัยด้วย `try/finally`
- `[landsmaps_config.py]` เป็นจุดเดียวที่โหลด `BANGKOK_AMPHUR.json`

### Added — Group 5 (landsmaps: incremental fetching + parcel cache บน Supabase)
- `[schema]` migration `0005_split_parcels_table.sql` — **แทนที่ `asset_coordinates` เดิมทั้งหมด** ด้วย 2 ตารางใหม่: `parcels` (1 แถวต่อ 1 แปลงจริง) + `asset_parcels` (junction table many-to-many) แก้ปัญหา `asset_coordinates` เดิมที่ใช้ `asset_id` เป็น PK คู่กับ `UNIQUE(provid,amph2,parcelno)` ซึ่งพังทันทีถ้าห้องชุดหลายร้อยห้องอ้างอิงแปลงเดียวกัน
- `[landsmaps_supabase.py]` (ไฟล์ใหม่) — `get_checkpoint()`/`get_new_assets()` ดึงเฉพาะ asset ใหม่กว่ารอบที่สำเร็จล่าสุด (เลิกอ่าน `led_all_assets.json` ทั้งไฟล์), `get_cached_parcels()` โหลด cache จากตาราง `parcels` เอง (เลิกพึ่งไฟล์ local ที่หายตอนรันบน Cloud Run), `is_retryable()` แยก retry policy ตาม `verify_status` (matched/partial_match/not_verified ไม่ retry เลย, not_found retry ได้แต่มี cooldown 30 วัน)
- `[landsmaps_collector.py]` เขียนใหม่ทั้งหมดให้พูดกับ Supabase โดยตรง เลิกใช้ไฟล์ local JSON (`led_all_assets.json`, `landsmaps_coordinates.json`) ทั้งคู่
- `[landsmaps_progress.py]` เปลี่ยนจาก track ด้วย index ของไฟล์ JSON → track ด้วย `asset_id` จริงจาก Supabase

### Changed — แยก `supabase_common.py` กลาง
- `[supabase_common.py]` (ไฟล์ใหม่) รวม env loading, `HEADERS`, `BKK_TZ`, `_request_with_retry`, `sb_upsert`, `sb_insert_run`, `sb_update_run`, และ `paginated_select()` (pagination helper ใหม่) — ใช้ร่วมกันระหว่าง LED และ LandsMaps
- `[led_uploader.py]` ลบ env loading/retry wrapper/`sb_*` ที่ย้ายออกแล้ว → import จาก `supabase_common` แทน, `get_asset_ids()` เขียนใหม่ให้ใช้ `paginated_select()` (25 บรรทัด → 8 บรรทัด)
- `[landsmaps_supabase.py]` เปลี่ยนจาก import `led_uploader` โดยตรง → import `supabase_common` แทน ตัดการพึ่งพาข้ามฝั่ง LED/LandsMaps ที่เคยผูกกันไม่จำเป็น

### ยังไม่เสร็จ
- `[landsmaps]` ยังพึ่งพา `Copy_as_cURL.txt` แบบ copy-paste ด้วยมือ (cookies หมดอายุเร็ว ต้องมีคนคอยแก้) — เป็น blocker หลักที่ยังเอาขึ้น Cloud Run Jobs แบบอัตโนมัติเต็มรูปแบบไม่ได้ รอกลุ่ม 4 (session automation ด้วย Playwright)

---

## 2026.07.07-1

### Added
- `[infra]` ย้าย crawler จาก GitHub Actions → Google Cloud Run Jobs (Bangkok region, `asia-southeast3`) — แก้ปัญหา IP ถูกบล็อกโดย `asset.led.go.th` (บล็อกทั้ง ASN ของ Google Cloud region อื่นๆ แบบ silent TCP drop แต่ Bangkok region ผ่าน)
- `[infra]` Cloud Scheduler ตั้งรันอัตโนมัติทุก 3 วัน ตี 2 เวลาไทย (`Asia/Bangkok` timezone)
- `[docker]` `entrypoint.sh` รัน `led_crawler.py` ต่อด้วย `led_uploader.py` ในการทำงานเดียวกัน — จำเป็นเพราะดิสก์ของ Cloud Run Job เป็นแบบชั่วคราว (ephemeral) ไฟล์ JSON จะหายทันทีที่ container ถูกทำลายถ้าไม่อัพโหลดก่อน
- `[versioning]` เพิ่มไฟล์ `VERSION`, migration folder (`supabase/migrations/`), เลิกใช้เลข version ต่อท้ายชื่อไฟล์

### Fixed
- `[schema]` GRANT สิทธิ์ `service_role` ที่ขาดหายตั้งแต่สร้าง schema — แก้ 403 Forbidden ตอน insert `crawler_runs`/`assets` (migration `0002`)
- `[led_uploader.py]` เพิ่ม `dedupe_records()` ตัดข้อมูลซ้ำ key (`led_province_id`, `str_bid_num`, `deedno_raw`) ก่อน upsert — แก้ Postgres error 21000 (`ON CONFLICT DO UPDATE command cannot affect row a second time`) ที่ทำให้ทั้ง batch พังยกก้อน
- `[led_uploader.py]` เพิ่ม pagination ให้ `get_asset_ids()` ด้วย `Range` header — แก้บั๊กจังหวัดที่มี record เกิน 1,000 แถว (เช่นกรุงเทพ 9,055 รายการ) upload `asset_bid_rounds` ไม่ครบแบบเงียบๆ ไม่มี error โผล่ใน log
- `[led_uploader.py]` เพิ่ม `_request_with_retry()` ให้ทุกจุดที่คุย Supabase REST API — retry สูงสุด 3 ครั้งแบบ backoff เฉพาะ network error/5xx (ไม่ retry 4xx)

### Changed
- `[led_uploader.py]` `triggered_by` แก้จาก `"github_actions"` → `"cloud_run"` ให้ตรงกับที่รันจริง
- `[versioning]` เพิ่ม prefix `led_` ให้ไฟล์ LED ทั้งหมด (`led_config.py`, `led_session.py`, `led_parser.py`, `led_progress.py`, `led_logger.py`, `led_crawler.py`, `led_uploader.py`) แยกชัดเจนจาก `landsmaps_*`

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
