-- =====================================================================
-- Migration 0007 — เพิ่ม RLS policy ให้ anon key อ่าน crawler_runs ได้
--
-- เหตุผล: Admin page ของ TPIS Web ใช้ anon/public key (VITE_SUPABASE_ANON_KEY)
-- policy เดิม "analyst read crawler_runs" กำหนดให้เห็นเฉพาะ role analyst/admin
-- ทำให้ table ว่างเปล่าใน Admin page ทั้งที่มีข้อมูลอยู่
--
-- ทางเลือก 2 แบบ ใช้แค่แบบเดียว:
--   A) public read — ทุกคนเห็นได้ (เหมาะถ้า TPIS เป็น internal tool)
--   B) authenticated only — ต้อง login ก่อน (เหมาะถ้าจะเปิดสาธารณะในอนาคต)
-- =====================================================================

-- ── ตัวเลือก A: public read (แนะนำสำหรับ internal tool) ──────────────
create policy "public read crawler_runs"
    on public.crawler_runs for select using (true);

create policy "public read crawler_run_details"
    on public.crawler_run_details for select using (true);

-- ── ตัวเลือก B: authenticated users เท่านั้น (comment ออกถ้าใช้ A) ──
-- create policy "auth read crawler_runs"
--     on public.crawler_runs for select
--     using (auth.role() = 'authenticated');
--
-- create policy "auth read crawler_run_details"
--     on public.crawler_run_details for select
--     using (auth.role() = 'authenticated');
