-- =====================================================================
-- Migration 0002 — แก้ 403 Forbidden ตอน service_role insert/update
-- วันที่แก้จริง: 2026-07-06 (ผ่าน SQL Editor ระหว่าง debug Cloud Run deploy)
-- สาเหตุ: service_role ไม่มี GRANT สิทธิ์ระดับตาราง (table-level privilege)
--         มีแค่ TRUNCATE/REFERENCES/TRIGGER ที่ Postgres ให้มาโดย default
--         ไม่มี INSERT/SELECT/UPDATE/DELETE เลยตั้งแต่สร้าง schema
-- อ้างอิง: เจอตอนรัน uploader.py บน Cloud Run Job แล้ว sb_insert_run()
--         คืน 403 Client Error ที่ /rest/v1/crawler_runs
-- =====================================================================

-- ----- Grant สิทธิ์เต็มให้ service_role ทุกตารางที่มีอยู่แล้ว -----
grant all on all tables in schema public to service_role;
grant all on all sequences in schema public to service_role;

-- ----- ตั้ง default privilege ไว้ล่วงหน้า กันปัญหาเดิมเกิดซ้ำกับตารางใหม่ในอนาคต -----
alter default privileges in schema public grant all on tables to service_role;
alter default privileges in schema public grant all on sequences to service_role;

-- ----- NO FORCE ROW LEVEL SECURITY -----
-- ไม่ใช่สาเหตุจริงของ 403 (service_role มี BYPASSRLS ติดตัวอยู่แล้ว)
-- แต่ใส่ไว้ให้ชัดเจนกันเผื่อมีใครไปเปิด FORCE ทีหลังโดยไม่ตั้งใจ
alter table public.crawler_runs      no force row level security;
alter table public.assets            no force row level security;
alter table public.asset_bid_rounds  no force row level security;
alter table public.asset_coordinates no force row level security;
alter table public.asset_images      no force row level security;
