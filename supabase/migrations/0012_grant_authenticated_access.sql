-- =====================================================================
-- Migration 0012 — GRANT สิทธิ์ตารางให้ authenticated role (แก้ permission denied)
--
-- สาเหตุ: เหมือนกับ migration 0002 (service_role) และ 0008 (anon) เป๊ะๆ —
-- RLS policy มีอยู่แล้วถูกต้อง แต่ PostgreSQL ต้องมี table-level GRANT ก่อน
-- RLS จะถูกเช็คด้วยซ้ำ ไม่มี migration ไหนเคย GRANT ให้ authenticated role เลย
--
-- อาการที่เจอจริง: login ผ่าน Supabase Auth สำเร็จ (role='admin' ใน public.users
-- ถูกต้อง) แต่หน้า Admin ขึ้น "บัญชีนี้ไม่มีสิทธิ์เข้าหน้า Admin (role ปัจจุบัน:
-- ไม่ทราบ)" เพราะ AuthContext.jsx query `select role from public.users where
-- id = auth.uid()` โดน "permission denied for table users" เงียบๆ (จับ error
-- แล้ว fallback เป็น role: null)
--
-- ครอบคลุมเผื่อหน้า "จัดการโฉนด" ที่จะทำต่อด้วย (ต้อง UPDATE parcels +
-- landsmaps_sessions ซึ่งมี RLS policy "admin verify..." รออยู่แล้วแต่ขาด
-- GRANT เหมือนกัน)
-- =====================================================================

-- ── users: อ่าน role ตัวเองได้ (แก้บั๊กหลักที่เจอ) + admin แก้ role คนอื่นได้ ──
grant select, update on public.users to authenticated;

-- ── landsmaps_sessions: admin อ่าน/upload cookies ผ่านหน้าเว็บได้ ──
-- (RLS policy "admin read/insert/update sessions" จาก migration 0006 มีอยู่แล้ว
-- แต่ไม่เคยมี table grant คู่กันเลย)
grant select, insert, update on public.landsmaps_sessions to authenticated;

-- ── parcels: admin แก้ lat/long/tag เองได้ (หน้า "จัดการโฉนด" ที่กำลังจะทำ) ──
-- (RLS policy "admin verify parcels" จาก migration 0005 มีอยู่แล้ว แต่ไม่เคยมี
-- table grant คู่กันเลยเช่นกัน)
grant select, update on public.parcels to authenticated;

-- ── user_* tables: เจ้าของ row จัดการของตัวเองได้ (watchlist/saved_searches/
-- alerts/notes/recent_views) — RLS policy "own ..." มีอยู่แล้วตั้งแต่ baseline
-- แต่ไม่เคยมี table grant คู่กันเลย ยังไม่มีหน้าเว็บใช้งานจริงตอนนี้ แต่ grant
-- ไว้ล่วงหน้ากันเจอบั๊กเดิมซ้ำตอนทำหน้าที่ใช้ตารางพวกนี้ในอนาคต
grant select, insert, update, delete on public.user_watchlists     to authenticated;
grant select, insert, update, delete on public.user_saved_searches to authenticated;
grant select, insert, update, delete on public.user_alerts         to authenticated;
grant select, insert, update, delete on public.user_notes          to authenticated;
grant select, insert, update, delete on public.user_recent_views   to authenticated;

-- ── กันปัญหาเดิมเกิดซ้ำกับตารางใหม่ในอนาคต (ตามแนวเดียวกับ 0002/0008) ──
alter default privileges in schema public grant select, insert, update, delete on tables to authenticated;
