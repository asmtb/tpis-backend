-- =====================================================================
-- Migration 0003 — เพิ่ม code_version สำหรับ traceability
-- เหตุผล: เวลาข้อมูลมีปัญหาย้อนหลัง จะได้รู้ทันทีว่า record นั้นมาจาก
--         code version ไหน ไม่ต้องเดาจาก timestamp คร่าวๆ
-- =====================================================================

alter table public.crawler_runs
    add column if not exists code_version text;

comment on column public.crawler_runs.code_version
    is 'เวอร์ชันโค้ดตอนรัน เช่น 2026.07.07-1 — อ่านจากไฟล์ VERSION ใน image ตอน build';
