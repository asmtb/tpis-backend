-- =====================================================================
-- Migration 0008 — GRANT SELECT ให้ anon role อ่านข้อมูลได้
--
-- เหตุผล: TPIS Web ใช้ VITE_SUPABASE_ANON_KEY (public key) ในการ query
-- RLS policy "public read" มีอยู่แล้ว แต่ขาด table-level GRANT ให้ anon role
-- ทำให้ได้รับ "permission denied for table assets" ตอนโหลดหน้าค้นหา
--
-- อ้างอิง: เหมือน migration 0002 ที่แก้ปัญหาเดียวกันสำหรับ service_role
-- =====================================================================

-- ── Tables ──────────────────────────────────────────────────────────
grant select on public.assets               to anon;
grant select on public.asset_bid_rounds     to anon;
grant select on public.asset_images         to anon;
grant select on public.asset_history        to anon;
grant select on public.parcels              to anon;
grant select on public.asset_parcels        to anon;
grant select on public.crawler_runs         to anon;
grant select on public.crawler_run_details  to anon;
grant select on public.landsmaps_sessions   to anon;

-- ── Views ────────────────────────────────────────────────────────────
grant select on public.assets_map           to anon;
grant select on public.province_summary     to anon;
grant select on public.auction_today        to anon;

-- ── Default privilege: กัน table ใหม่ในอนาคตพังซ้ำ ─────────────────
alter default privileges in schema public grant select on tables to anon;
