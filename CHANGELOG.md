# TPIS Changelog

รูปแบบเวอร์ชัน: `YYYY.MM.DD-N` (วันที่ deploy + ลำดับที่ deploy ในวันนั้น)
แต่ละบรรทัดระบุ component ที่กระทบใน `[ ]` เพราะหลาย component ผูกกันแน่น
(แก้โค้ดฝั่งหนึ่งมักต้องแก้ schema คู่กันด้วย)

`[WIP]` = ยังทำไม่ครบทุกกลุ่มที่วางแผนไว้ ยังไม่ deploy จริง

---

## 2026.08.05-1

### Fixed — led_uploader: AdminPage show new list for each new crawler run

- `[led_uploader]` เพิ่ม `_count_new_assets(gte, lte)` นับ asset ที่ `created_at` อยู่ในช่วง `started_at`–`finished_at` ของ run นั้น (ใช้ได้เพราะ `created_at` ตั้งครั้งเดียวตอน insert แรก ไม่ถูกเขียนทับตอน upsert ซ้ำ)
- `[led_uploader]` เขียนค่านี้ลง `crawler_runs.total_records_new` — คอลัมน์นี้มีอยู่แล้วใน schema baseline แค่ไม่เคยถูกเซ็ตค่า ไม่ต้องรัน migration เพิ่ม
- `[email_summary]` โชว์ในทั้ง console log และ email summary โดยเพิ่มแถว "🆕 รายการใหม่"

---

## 2026.07.18-1

### Fixed — Location: ใช้ deed fields เป็นหลักทุกหน้า + ราคาเต็มใน GIS Map

#### Schema (`0011_add_deed_fields_to_assets_map.sql`)
- `[schema]` migration `0011` — เพิ่ม `deedcity`, `deedampur`, `deedtumbol` เข้า `assets_map` view
  เหตุผล: view เดิมมีแค่ `city/ampur/tumbol` (ที่อยู่จริง) ซึ่งหลายรายการว่างเปล่า
  ทำให้ frontend ไม่สามารถ fallback ไป deed fields ได้เมื่อ query จาก assets_map

---

## 2026.07.14-1

### Fixed — Schema: province_summary view group by ผิด ทำให้ข้อมูลซ้ำ

- `[schema]` migration `0010_fix_province_summary_view.sql` — สร้าง view ใหม่ทับ view เดิม
  สาเหตุ: view เดิม (0001) group by `led_province_id, led_province_name, city` 3 column
  ทำให้ 1 จังหวัดแตกเป็นหลาย row ตามค่าของ `city` field ในทรัพย์
  (กรุงเทพมหานคร 4,976 / null 4,077 / กรุงเทพา 9 — แทนที่จะเป็น 9,062 row เดียว)
  แก้โดย group by เฉพาะ `led_province_id, led_province_name` และลบ `city` ออก
  ไม่มีผลกับข้อมูลใน table — เป็นแค่การเปลี่ยน view definition

  รัน SQL นี้ใน Supabase SQL Editor ไฟล์เดียวจบ — ทำ 5 ขั้นตอนติดกัน:
  1. DROP assets_map, auction_today, province_summary
  2. สร้าง province_summary ใหม่ (group by province เท่านั้น)
  3. สร้าง assets_map คืน (จาก 0005)
  4. สร้าง auction_today คืน (จาก 0001)
  5. GRANT SELECT ให้ anon ทั้ง 3 view (กัน permission denied หลัง recreate)
---

## 2026.07.13-1

### Fixed — LandsMaps: rate limit / bot detection จาก LandsMaps เมื่อรัน collector

- `[landsmaps_config.py]` ปรับค่า delay และ retry ให้ human-like มากขึ้น:
  ```
  DELAY_SEC    0.5  → 2.0   วินาที  (เพิ่ม 4x)
  DELAY_JITTER —   → 1.0   วินาที  (ใหม่ — random jitter เพิ่มอีก 0–1.0 วิ)
  RETRY_DELAY  5   → 10    วินาที  (เพิ่ม 2x)
  SAVE_EVERY   200 → 100   records (save บ่อยขึ้น กันหายถ้า crash)
  ```
  สาเหตุ: DELAY_SEC = 0.5 ทำให้ script ยิง API ทุก 0.5 วินาทีต่อเนื่อง 75+ นาที
  LandsMaps ตรวจจับว่าเป็น bot แล้ว throttle IP ชั่วคราว ทำให้แม้ค้นหาด้วยมือก็ไม่เจอ
  ผลลัพธ์คือ parcel ที่โดน throttle ได้ผล not_found ผิดพลาดทั้งหมด

- `[landsmaps_collector_local.py]` เปลี่ยน `time.sleep(DELAY_SEC)` เป็น
  `time.sleep(DELAY_SEC + random.uniform(0, DELAY_JITTER))`
  → รอจริง 2.0–3.0 วินาทีต่อ request แบบสุ่ม
  random jitter = เพิ่มเวลารอแบบสุ่มเล็กน้อยทุกรอบ แทนที่จะรอตรงๆ ทุกครั้ง
  (bot detection จับ pattern เวลาคงที่ได้ง่ายกว่า pattern สุ่ม)

  ผลกระทบต่อเวลารัน:
  | รายการ | delay เดิม | delay ใหม่ |
  |---|---|---|
  | 9,062 assets | ~75 นาที | ~4.5–6 ชั่วโมง |

  หมายเหตุ: cookies อายุ ~1.5 ชม. — session renewal (init_session / refresh_jwt)
  จะ handle อัตโนมัติระหว่างรัน ไม่ต้อง manual intervene

---

## 2026.07.12-2

### Discovered — `get_new_assets()` คืน 0 asset หลัง reset parcels

- `[landsmaps]` พบว่าการ reset `verify_status = 'error'` ใน `parcels` table ไม่ทำให้ collector ดึง asset กลับมา เพราะ `get_new_assets()` กรอง asset โดยเทียบ `scraped_at > checkpoint` ไม่ได้ดูจาก `parcels` เลย ทำให้ asset 9,062 รายการที่ scrape ก่อน checkpoint ทั้งหมดไม่ถูกนับว่าเป็น "ใหม่"
- `[landsmaps]` การรัน `.bat` หลัง reset โดยไม่ลบ `progress.json` ทำให้ collector skip ทุก asset ทันที เพราะ `progress.json` จำว่าทำครบแล้ว ทั้ง 2 ปัญหาทำให้ได้ `Asset ที่ต้องประมวลผล: 0` ทุกรอบ

### Fixed (manual) — Reset checkpoint + progress เพื่อ retry

- `[Supabase SQL]` mark `crawler_runs` ที่ `status='completed'` และ `total_records_fetched=0` ให้เป็น `partial` ซ้ำจนไม่มี `completed` เหลือ → `get_checkpoint()` คืน `None` → `get_new_assets(None)` ดึงทุก asset โดยไม่กรองเวลา
- `[local]` ลบ `progress.json` ด้วยมือก่อนรัน เพื่อ reset `done_asset_ids`

### Added — `--retry-not-found` flag (วิธีที่ 1: ไม่ต้องแตะ DB)

- `[landsmaps_collector_local.py]` เพิ่ม `argparse` และ `--retry-not-found` flag
  - ignore checkpoint → `get_new_assets(None)` ดึงทุก asset
  - override cache policy → `not_found` retry ได้ทันที (ไม่ต้องรอ cooldown 30 วัน)
  - auto-reset `progress.json` ผ่าน `progress.reset()` ถ้ายังมี `done_asset_ids` ค้างอยู่
- `[landsmaps_progress.py]` เพิ่ม `reset()` method สำหรับล้าง state และลบ `progress.json` อัตโนมัติ
- `[run_landsmaps_local.bat]` รองรับ argument `--retry`

  ```
  run_landsmaps_local.bat
  run_landsmaps_local.bat --retry
  ```

### Fixed — import `argparse` หายไป

- `[landsmaps_collector_local.py]` เพิ่ม `import argparse` ที่ตกหล่นหลังเพิ่ม CLI argument

---

## 2026.07.12-1

### Added — Schema: ตาราง th_provinces, th_districts, th_subdistricts

- `[schema]` migration `0009_thai_geo_tables.sql` — ข้อมูลภูมิศาสตร์ไทยครบ 3 ระดับ
  ที่มา: [kongvut/thai-province-data](https://github.com/kongvut/thai-province-data) (MIT License)
  - `th_provinces`: 77 จังหวัด พร้อม `led_province_id` เชื่อมกับ `assets.led_province_id`
  - `th_districts`: 930 อำเภอ FK → th_provinces
  - `th_subdistricts`: 7,452 ตำบล FK → th_districts + zip_code
  - GIN index บน `name_th` ทั้ง districts และ subdistricts รองรับ ILIKE autocomplete
  - RLS public read + GRANT SELECT to anon ครบทุกตาราง
  - `alter default privileges` กัน table ใหม่ในอนาคต
  ใช้งาน: SearchFilters ดึง districts ผ่าน `th_provinces.led_province_id → th_districts.province_id`

---

## 2026.07.11-2

### Fixed — Schema: GRANT SELECT ให้ `anon` role (แก้ permission denied บนเว็บ)

- `[schema]` migration `0008_grant_anon_select.sql` — GRANT SELECT ให้ `anon` role สำหรับทุก table และ view ที่ TPIS Web ต้องอ่าน
  สาเหตุ: `VITE_SUPABASE_ANON_KEY` ใช้ role `anon` ของ PostgreSQL — RLS policy "public read" ตรวจสิทธิ์ได้ถูกต้อง แต่ต้องมี table-level GRANT ก่อน PostgreSQL จึงจะยอมให้ query ผ่าน
  อาการ: หน้าค้นหาแสดง `permission denied for table assets` ทันทีที่โหลด แม้ RLS จะเปิดอยู่
  อ้างอิง: เหมือน migration 0002 ที่แก้ปัญหาเดียวกันสำหรับ `service_role`
  เพิ่ม `alter default privileges` กัน table ใหม่ในอนาคตพังซ้ำโดยไม่ต้องรัน migration ซ้ำ

---

## 2026.07.11-1

### Added — Schema: RLS policy ให้ anon key อ่าน `crawler_runs` ได้

- `[schema]` migration `0007_anon_read_crawler_runs.sql` — เพิ่ม policy `"public read crawler_runs"` และ `"public read crawler_run_details"` ให้ anon/public Supabase key อ่านตารางทั้งสองได้
  เหตุผล: Admin page ของ TPIS Web ใช้ `VITE_SUPABASE_ANON_KEY` (ไม่ใช่ service role) — policy เดิม `"analyst read crawler_runs"` กำหนดเฉพาะ role analyst/admin ทำให้ตารางว่างเปล่าบน Admin page ทั้งที่มีข้อมูล
  ไฟล์ SQL มีทั้ง 2 ตัวเลือก: public read (แนะนำสำหรับ internal tool) หรือ authenticated-only

---

## 2026.07.10-5

### Fixed — LED: email แจ้งเตือนไม่ถูกส่งเมื่อ crawler fail

- `[entrypoint_led.sh]` ลบ `set -e` ออก แล้วเปลี่ยนเป็นเก็บ exit code ของ crawler ไว้แทน
  สาเหตุ: `set -e` ทำให้ shell หยุดทันทีถ้า `led_crawler.py` fail โดยไม่รัน `led_uploader.py`
  ต่อ ทำให้ `send_led_summary()` ไม่ถูกเรียกเลย — ไม่มี email แจ้งเตือนไม่ว่า crawler จะ
  success หรือ fail
  แก้โดยเก็บ exit code ไว้ใน `CRAWLER_EXIT` แล้วส่งต่อให้ uploader ผ่าน `--crawler-exit`
  เพื่อให้ uploader รู้ว่า crawler พังและ reflect ใน email ได้ถูกต้อง

- `[led_uploader.py]` เพิ่ม `--crawler-exit` argument รับ exit code จาก crawler
  และ wrap upload loop ด้วย `try/finally` เพื่อให้ `send_led_summary()` ถูกเรียก **เสมอ**
  ไม่ว่าจะเกิด exception กลางทางหรือไม่
  - ถ้า `crawler-exit != 0` → บันทึก error เพิ่มเข้า stats ทันที ให้ email แสดงว่า crawler fail
  - ถ้า uploader เองพัง → `finally` ยังส่ง email ได้ พร้อม error message ที่เกิดขึ้น
  - `crawler_run` record ใน Supabase จะถูก update เป็น `status=failed` ในกรณีพัง

  กรณีที่รองรับทั้งหมด:
  | crawler | uploader | email ส่งไหม (เดิม) | email ส่งไหม (ใหม่) |
  |---|---|---|---|
  | ✅ success | ✅ success | ❌ | ✅ |
  | ❌ fail | ✅ success | ❌ | ✅ พร้อมแจ้ง crawler error |
  | ✅ success | ❌ fail | ❌ | ✅ พร้อมแจ้ง uploader error |
  | ❌ fail | ❌ fail | ❌ | ✅ พร้อมแจ้งทั้งคู่ |

---

## 2026.07.10-4

### Fixed — LandsMaps: JWT expiry detection ใน `fetch_parcel()`

- `[landsmaps_session.py]` เพิ่ม **2-level session renewal** ใน `fetch_parcel()` แทนที่จะเปิด Playwright ใหม่ทุกครั้งที่ session มีปัญหา
  เดิมตรวจเฉพาะ `"_Incapsula"` ใน response แล้วเรียก `init_session()` ทันที ทำให้เปิด browser และ solve hCaptcha ใหม่แม้จะเป็นแค่ JWT หมดอายุ

  ปรับ logic ใหม่เป็น 2 ระดับตามสาเหตุจริง:

  **Level 1 — JWT หมดอายุก่อน cookies**
  - ตรวจจาก HTTP `401` หรือ API ส่ง error JSON ใน response body
  - เรียก `refresh_jwt()` ก่อน (ไม่ต้องเปิด browser และไม่ต้อง solve hCaptcha)
  - ถ้า refresh สำเร็จ → retry `fetch_parcel()` ของแปลงเดิมทันที
  - ถ้า refresh ไม่สำเร็จ → escalate ไป Level 2

  **Level 2 — Incapsula cookies หมดอายุ**
  - ตรวจจาก response ที่ถูก redirect ไปหน้า Incapsula (`"_Incapsula"` ใน response)
  - เรียก `init_session()` เปิด Playwright ใหม่และ solve hCaptcha อีกครั้ง
  - เมื่อสร้าง session สำเร็จ → retry `fetch_parcel()` ของแปลงเดิมทันที

### Changed — Session recovery behavior

- `[landsmaps_session.py]` JWT ที่หมดอายุระหว่างรัน (ซึ่งเกิดบ่อยกว่าการหมดอายุของ Incapsula cookies) จะถูก renew แบบเงียบ ๆ โดยไม่ interrupt ผู้ใช้ เปิด Playwright ใหม่เฉพาะเมื่อถูก Incapsula block จริงเท่านั้น ลดจำนวน browser restart และลดการ solve hCaptcha ที่ไม่จำเป็น

---

## 2026.07.10-3

### Fixed — LandsMaps: numeric fields ที่ API ส่งมาเป็น string คั่น comma

- `[landsmaps_supabase.py]` เพิ่ม `_clean_numeric()` helper และ `_NUMERIC_FIELDS` set
  สาเหตุ: LandsMaps API ส่ง `land_price_per_sqw` (และ `rai`, `ngan`, `wa`, `latitude`,
  `longitude`) เป็น string แบบ `"53,000"` (คั่น comma หลักพัน) แทนที่จะเป็นตัวเลข
  PostgreSQL column type `numeric` รับ string format นี้ไม่ได้ → 400 Bad Request ทุก record
  ตรวจพบจาก error log ที่เพิ่มในรอบก่อน:
  `{"code":"22P02","message":"invalid input syntax for type numeric: \"53,000\""}`
  การแก้: clean ทุก numeric field ก่อน upsert ใน `upsert_parcel()` โดยอัตโนมัติ
  ```
  "53,000"   → 53000.0   ✅
  "1,234.56" → 1234.56   ✅
  None       → None      ✅
  13.5       → 13.5      ✅
  ""         → None      ✅
  ```

- `[run_landsmaps_local.bat]` เปลี่ยนข้อความทั้งหมดเป็นภาษาอังกฤษ
  สาเหตุ: Windows cmd.exe ใช้ code page 850/437 (ไม่ใช่ UTF-8) ทำให้ภาษาไทยใน bat file
  แสดงเป็น garbage character แก้โดยเปลี่ยนข้อความทั้งหมดเป็นภาษาอังกฤษ
  (ไม่ได้ใช้ `chcp 65001` เพราะยังมีปัญหากับ font บาง terminal บน Windows)

### Confirmed — LandsMaps end-to-end ทำงานได้สมบูรณ์ครั้งแรก ✅

- `[landsmaps]` รัน `run_landsmaps_local.bat` สำเร็จครบ pipeline:
  Chromium → solve hCaptcha → JWT → ดึง 9,062 assets → upsert parcels/asset_parcels → Supabase ✅
  ข้อมูลพิกัด + ราคาที่ดินเข้า Supabase จริงเป็นครั้งแรกนับจากเริ่มโปรเจกต์

---

## 2026.07.10-2

### Added — Phase B: LandsMaps Local Runner (แก้ปัญหา IP binding)

- `[landsmaps_collector_local.py]` (ไฟล์ใหม่) — Local version ของ collector ที่ใช้
  `init_session()` เปิด Chromium บนเครื่องตัวเองแทน `load_cookies_from_supabase()`
  ความแตกต่างจาก `landsmaps_collector.py` (Cloud Run version):
  - บังคับ `headless=False` เสมอ เพื่อให้เห็น browser และ solve hCaptcha ได้
  - ไม่ต้องรัน `test_session.py` / `upload_cookies.py` ก่อน — ทำในครั้งเดียว
  - logic การ collect, retry policy, และ Supabase write เหมือน Cloud Run version ทุกอย่าง

- `[run_landsmaps_local.bat]` (ไฟล์ใหม่) — Windows batch script สำหรับ double-click รัน
  ตรวจสอบ `.env` และ Python ก่อนรัน, ใช้ `%~dp0` ให้ cd ไปที่ root ของโปรเจกต์เสมอ
  ไม่ว่าจะ double-click จาก directory ไหน

### Confirmed — Incapsula IP binding (พิสูจน์แล้ว)

- `[landsmaps]` ยืนยันด้วย one-liner test จากเครื่องตัวเอง (ไม่ depend กับโค้ดใดในโปรเจกต์):
  cookies ชุดเดียวกัน เวลาเดียวกัน:
  - เครื่องตัวเอง (Thailand IP) → `incapsula? False`, `got JWT? True` ✅
  - Cloud Run (Google Cloud IP)  → `incapsula? True`,  `got JWT? False` ❌
  Incapsula ฝัง IP fingerprint ลงใน cookies ตอนผ่าน JS challenge ครั้งแรก
  การนำ cookies ไปใช้บน IP อื่นถูก block ทันทีโดยไม่มี error message ชัดเจน
  สรุป: `load_cookies_from_supabase()` approach ไม่สามารถใช้บน Cloud Run ได้ถาวร

### Architecture — แยก LandsMaps เป็น 2 version ชัดเจน

| ไฟล์ | รันที่ไหน | Session | เหมาะกับ |
|---|---|---|---|
| `landsmaps_collector.py` | Cloud Run | `load_cookies_from_supabase()` | สำรองไว้ ถ้าหา workaround IP ได้ในอนาคต |
| `landsmaps_collector_local.py` | เครื่องตัวเอง | `init_session()` | **ใช้งานจริงตอนนี้** |

---

## [WIP] 2026.07.10-1

### Fixed — scripts: path และ import ที่พังเมื่อรันจากต่าง directory

- `[scripts/test_session.py]` แก้ `sys.path.insert(0, '.')` → ใช้ `Path(__file__).resolve().parent.parent` แทน
  เพราะ `.` ชี้ไปที่ cwd ตอนรัน ซึ่งเปลี่ยนตาม directory ที่ยืนอยู่ ทำให้เกิด 2 error สลับกัน:
  - รันจาก root (`python scripts/test_session.py`) → `AttributeError: 'SessionManager' object has no attribute 'init_session'`
    (Python โหลด `landsmaps_session.py` ผิดตัว หรือโหลด `__pycache__` เวอร์ชันเก่า)
  - รันจาก scripts/ (`python test_session.py`) → `ModuleNotFoundError: No module named 'landsmaps_logger'`
    (`.` ชี้ที่ `scripts/` ซึ่งไม่มีไฟล์ `landsmaps_*`)
  หลังแก้แล้ว รันได้ถูกต้องทั้ง 2 วิธีโดยไม่ต้อง cd ก่อน

- `[scripts/test_session.py]` แก้ path ของ `test_cookies.json` จาก `open("test_cookies.json", "w")` (เซฟที่ cwd)
  → `Path(__file__).resolve().parent / "test_cookies.json"` (เซฟที่ `scripts/` เสมอ ไม่ว่าจะรันจากไหน)
  กันไม่ให้ `upload_cookies.py` หาไฟล์ไม่เจอ

- `[scripts/upload_cookies.py]` แก้ `COOKIE_FILE` จาก `parent.parent / "test_cookies.json"` (root)
  → `parent / "test_cookies.json"` (`scripts/`) ให้ตรงกับที่ `test_session.py` เซฟจริง

- `[landsmaps_session.py]` คืน `def init_session(self) -> bool:` ที่หายไปตอน Phase A refactor
  สาเหตุ: ตอนเพิ่ม `load_cookies_from_supabase()` เข้าไป บรรทัด `def init_session` หลุดออกไป
  เหลือแต่ docstring + body ของ Playwright ลอยอยู่นอก method — Python จึงไม่รู้จัก method นี้เลย
  ผลกระทบ: `fetch_parcel()` และ `get_amph2()` ที่เรียก `self.init_session()` ภายในพังด้วย
  ตรวจพบจาก: `dir(SessionManager)` ไม่มี `init_session` ใน list

- `[email_summary.py]` แก้ `FROM_EMAIL` จาก `noreply@tpis-notifications.com` (domain ที่ยังไม่ verify)
  → `onboarding@resend.dev` (test sender ของ Resend ใช้ได้ทันทีไม่ต้อง verify domain)
  เดิม Resend คืน 403 `"domain is not verified"` แล้ว job exit(1) ทันที ทำให้ collector ไม่ได้ทำงานเลย

- `[led_logger.py]` แก้ timezone ทุก timestamp จาก `datetime.now()` (UTC บน Cloud Run)
  → `_now()` ที่ใช้ `BKK_TZ` (UTC+7) และตั้ง `fmt.converter` ของ `logging.Formatter`
  ให้ `%(asctime)s` แสดงเวลาไทย ไม่ใช่ UTC ที่ Cloud Run container ใช้เป็น default
  พร้อมเปลี่ยน estimate section จาก "GitHub Actions free tier (2,000 นาที)"
  → "Cloud Run Job task timeout" + จำนวนรอบต่อเดือนตาม schedule ทุก 3 วัน

### Discovered — blocker หลักของ LandsMaps บน Cloud Run

- `[landsmaps]` **Incapsula ผูก cookies กับ IP ต้นทาง** — cookies ที่ได้จากเครื่องตัวเอง (Thailand IP)
  ใช้บน Cloud Run (Google Cloud IP / Singapore region) ไม่ได้เลย แม้จะ upload เข้า Supabase ทันทีก็ตาม
  `refresh_jwt()` คืน False ทันที เพราะ Incapsula ตรวจว่า IP ที่ใช้ cookies ต่างจาก IP ที่ขอมา
  สรุป: `load_cookies_from_supabase()` approach ไม่สามารถใช้งานได้กับ Cloud Run Job

### Planned — Phase B: ย้าย LandsMaps มารันบนเครื่องตัวเองแทน Cloud Run

- `[landsmaps_collector.py]` เพิ่ม `IS_CLOUD_RUN` detection ด้วย env var `K_SERVICE`
  (Cloud Run ตั้งให้อัตโนมัติ ไม่ต้องตั้งเอง) แล้วแยก session init ตาม environment:
  ```python
  IS_CLOUD_RUN = os.environ.get("K_SERVICE") is not None
  ok = session_mgr.load_cookies_from_supabase() if IS_CLOUD_RUN else session_mgr.init_session()
  ```
- `[scripts]` เพิ่ม `run_landsmaps_local.bat` (Windows) สำหรับรัน LandsMaps บนเครื่องตัวเอง
  `init_session()` เปิด browser solve hCaptcha → ดึงข้อมูล → upload ผลลัพธ์เข้า Supabase
  ในครั้งเดียว ไม่ต้องแยก step solve/upload cookies ก่อนแล้วค่อยรัน collector
- `[email_summary.py]` เปลี่ยน `FROM_EMAIL` เป็น domain จริงเมื่อ verify DNS กับ Resend เสร็จ
  (ปัจจุบันใช้ `onboarding@resend.dev` ไปก่อน ส่งได้ปกติแต่แสดง sender เป็น Resend)

---

## [WIP] 2026.07.09-1

### Added — Phase A: Email Summary + Cookie Management

- `[email_summary.py]` (ไฟล์ใหม่) module กลาง Resend API — `send_led_summary()` ส่งสรุปหลัง LED รันเสร็จ (รวมจำนวน asset ที่ยังไม่มีพิกัด LandsMaps), `send_landsmaps_summary()` ส่งสรุปหลัง LandsMaps รันเสร็จ (พร้อมแจ้งเตือนว่า cookies ถูกใช้แล้ว)
- `[scripts/upload_cookies.py]` (ไฟล์ใหม่) รันบนเครื่องตัวเองหลัง solve hCaptcha เพื่อ deactivate cookies เดิมและเขียน cookies ชุดใหม่เข้า Supabase `landsmaps_sessions`
- `[schema]` migration `0006_landsmaps_sessions.sql` — ตารางเก็บ hCaptcha cookies, enforce ว่ามีแค่ 1 active row ด้วย partial unique index, RLS admin-only

### Changed — Phase A

- `[led_uploader.py]` เพิ่ม `_count_pending_landsmaps()` (query asset ที่ยังไม่มีใน `asset_parcels`) + เรียก `send_led_summary()` ท้าย `main()`
- `[landsmaps_collector.py]` เรียก `send_landsmaps_summary()` ใน `finally` + เปลี่ยนมาใช้ `load_cookies_from_supabase()` แทน Playwright `init_session()` เป็นหลัก
- `[landsmaps_session.py]` เพิ่ม `load_cookies_from_supabase()` — อ่าน active cookies จากตาราง `landsmaps_sessions` แทนไฟล์ local (รองรับ Cloud Run ที่ไม่มี local file), Playwright `init_session()` ยังอยู่เป็น fallback
- `[led_logger.py]` ลบ section "GitHub Actions estimate" ออก (ย้ายมาใช้ Cloud Run แล้ว) เหลือแค่ "ประมาณครบ 77 จังหวัด: ~X นาที"

### Added — Infra: แยก Cloud Run Job สำหรับ LandsMaps

- `[entrypoint_led.sh]` rename จาก `entrypoint.sh` เดิม (เนื้อหาเหมือนกัน)
- `[entrypoint_landsmaps.sh]` (ไฟล์ใหม่) entrypoint สำหรับ LandsMaps Job โดยเฉพาะ
- `[Dockerfile]` แก้ `ENTRYPOINT` จาก `entrypoint.sh` → `entrypoint_led.sh`, เพิ่ม `chmod +x` ให้ทั้งสองไฟล์
- `[infra]` สร้าง Cloud Run Job `tpis-landsmaps` แยกจาก `tpis-cron-weekly` (LED) — manual trigger ได้ทุกเมื่อ ไม่ผูกกับ Cloud Scheduler, region `asia-southeast3`, memory 2Gi, timeout 3600s
- `[infra]` เพิ่ม env vars `RESEND_API_KEY` และ `NOTIFY_EMAIL` ใน Cloud Run Jobs ทั้งสองตัว

### ยังไม่เสร็จ
- `[admin]` Admin UI สำหรับ upload cookies และ trigger run ผ่านหน้าเว็บ — รอทำตอนสร้างเว็บหลัก TPIS (Phase B/C)

---

## 2026.07.08-1

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
- `[landsmaps_supabase.py]` (ไฟล์ใหม่) — `get_checkpoint()`/`get_new_assets()` ดึงเฉพาะ asset ใหม่กว่ารอบที่สำเร็จล่าสุด, `get_cached_parcels()` โหลด cache จากตาราง `parcels` เอง, `is_retryable()` แยก retry policy ตาม `verify_status`
- `[landsmaps_collector.py]` เขียนใหม่ทั้งหมดให้พูดกับ Supabase โดยตรง เลิกใช้ไฟล์ local JSON ทั้งคู่
- `[landsmaps_progress.py]` เปลี่ยนจาก track ด้วย index ของไฟล์ JSON → track ด้วย `asset_id` จริงจาก Supabase

### Changed — แยก `supabase_common.py` กลาง
- `[supabase_common.py]` (ไฟล์ใหม่) รวม env loading, `HEADERS`, `BKK_TZ`, `_request_with_retry`, `sb_upsert`, `sb_insert_run`, `sb_update_run`, และ `paginated_select()`
- `[led_uploader.py]` ลบ env loading/retry wrapper/`sb_*` ที่ย้ายออกแล้ว → import จาก `supabase_common`, `get_asset_ids()` เขียนใหม่ให้ใช้ `paginated_select()` (25 บรรทัด → 8 บรรทัด)
- `[landsmaps_supabase.py]` เปลี่ยนจาก import `led_uploader` → import `supabase_common` ตัดการพึ่งพาข้ามฝั่งที่ไม่จำเป็น

---

## 2026.07.07-1

### Added
- `[infra]` ย้าย crawler จาก GitHub Actions → Google Cloud Run Jobs (Bangkok region, `asia-southeast3`) — แก้ปัญหา IP ถูกบล็อกโดย `asset.led.go.th`
- `[infra]` Cloud Scheduler ตั้งรันอัตโนมัติทุก 3 วัน ตี 2 เวลาไทย (`Asia/Bangkok` timezone)
- `[docker]` `entrypoint_led.sh` รัน `led_crawler.py` ต่อด้วย `led_uploader.py` ในการทำงานเดียวกัน
- `[versioning]` เพิ่มไฟล์ `VERSION`, migration folder (`supabase/migrations/`), เลิกใช้เลข version ต่อท้ายชื่อไฟล์

### Fixed
- `[schema]` GRANT สิทธิ์ `service_role` ที่ขาดหายตั้งแต่สร้าง schema — แก้ 403 Forbidden (migration `0002`)
- `[led_uploader.py]` เพิ่ม `dedupe_records()` — แก้ Postgres error 21000
- `[led_uploader.py]` เพิ่ม pagination ให้ `get_asset_ids()` — แก้บั๊กจังหวัดที่มี record เกิน 1,000
- `[led_uploader.py]` เพิ่ม `_request_with_retry()` — retry สูงสุด 3 ครั้งแบบ backoff

### Changed
- `[led_uploader.py]` `triggered_by` แก้จาก `"github_actions"` → `"cloud_run"`
- `[versioning]` เพิ่ม prefix `led_` ให้ไฟล์ LED ทั้งหมด แยกชัดเจนจาก `landsmaps_*`

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
