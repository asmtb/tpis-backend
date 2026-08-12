-- =====================================================================
-- Migration 0013 — GRANT SELECT ให้ authenticated ครอบทุกตาราง/view ที่มีอยู่
--
-- สาเหตุ: หลัง migration 0012 ตอน login แล้ว Supabase client เปลี่ยนไปใช้ role
-- "authenticated" แทน "anon" โดยอัตโนมัติ — แต่ 0012 grant ให้ authenticated
-- แค่ 3 ตาราง (users, parcels, landsmaps_sessions) + user_* เท่านั้น ไม่ได้ครอบ
-- ตารางที่หน้าเว็บ public ใช้อ่านอยู่เดิม (assets, crawler_runs, และ view ต่างๆ
-- ที่เคย grant ให้ anon ไว้ตั้งแต่ 0008/0010/0011)
--
-- ผลคือ: ก่อน login (role=anon) อ่านได้ปกติ, พอ login (role=authenticated)
-- กลับอ่านอะไรไม่ได้เลยนอกจาก 3 ตารางที่เพิ่ง grant ไปใน 0012 — เจอ
-- "permission denied for table assets" ทั้งที่หน้านั้นไม่ต้องการสิทธิ์พิเศษอะไร
-- เลยด้วยซ้ำ (เดิม anon อ่านได้อยู่แล้ว)
--
-- แก้แบบ blanket แทนไล่ grant ทีละตารางแบบ 0008 เพื่อกันปัญหานี้เกิดซ้ำอีก:
-- authenticated ควรอ่านได้ทุกอย่างที่ anon อ่านได้เป็นอย่างน้อย (เข้ม้นน้อยกว่า
-- anon ไม่มีเหตุผล เพราะ authenticated คือ user ที่ login แล้ว ควรเห็นข้อมูล
-- เท่ากับหรือมากกว่า anon เสมอ)
-- =====================================================================

grant select on all tables in schema public to authenticated;

-- กันตารางใหม่ในอนาคตพลาดแบบนี้อีก (ครบทั้ง select ไปด้วยเลย ไม่ใช่แค่ที่ 0012
-- ทำไว้ตอนแรกซึ่งลืมใส่ select แบบ blanket)
alter default privileges in schema public grant select on tables to authenticated;
