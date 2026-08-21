-- =====================================================================
-- Migration 0015 — Wishlist reminder preferences + user self-update
--
-- บริบท: ต้องการให้ user ตั้งค่าเองได้ว่าอยากได้อีเมลแจ้งเตือนนัดประมูล
-- ของทรัพย์ใน wishlist (user_watchlists) ล่วงหน้ากี่วัน (เลือกได้หลายค่า
-- จาก 1/3/7 วัน) หน้า /account (AccountPage.jsx) — เก็บเป็น preference
-- ระดับ user ใน public.users ไม่ใช่ต่อทรัพย์ เพราะเป็นการตั้งค่าภาพรวม
-- ครั้งเดียวใช้กับทุกรายการใน wishlist
--
-- ปัญหาที่เจอระหว่างวางแผน: ตาราง public.users (migration 0001) มี RLS
-- policy update แค่ "admin update users" เท่านั้น — user ทั่วไปยังบันทึก
-- ค่าอะไรของตัวเองไม่ได้เลยแม้แต่ค่านี้ ต้องเปิด self-update policy ก่อน
-- แต่การเปิดกว้างตรงๆ จะทำให้ user แก้ column "role" ของตัวเองเป็น
-- 'admin' ผ่าน REST API ได้เลย (RLS คุมได้แค่ระดับแถว ไม่ใช่ระดับคอลัมน์)
-- จึงต้องมี trigger คอยรีเซ็ต role กลับเป็นค่าเดิมเสมอถ้าคนแก้ไม่ใช่
-- service_role (คือไม่ได้มาจาก backend/Dashboard SQL)
-- =====================================================================

-- ----- 1) Wishlist reminder preferences -----
alter table public.users
    add column if not exists wishlist_notify_enabled boolean not null default false,
    add column if not exists wishlist_reminder_days   smallint[] not null default '{1,3}';

comment on column public.users.wishlist_notify_enabled is
    'user เปิด/ปิดอีเมลแจ้งเตือนนัดประมูลของทรัพย์ใน wishlist เอง จากหน้า /account — '
    'ปิดอยู่ default เพราะเป็น opt-in ไม่ใช่ opt-out';
comment on column public.users.wishlist_reminder_days is
    'จำนวนวันล่วงหน้าที่อยากได้แจ้งเตือนก่อนวันนัด เลือกได้หลายค่าพร้อมกัน '
    '(ตัวเลือกที่ UI ให้เลือกคือ 1/3/7 วัน) มีผลเฉพาะตอน wishlist_notify_enabled=true';

-- ----- 2) เปิดให้ user แก้ไข "แถวตัวเอง" ได้ (เดิมมีแค่ admin update) -----
create policy "user update own profile"
    on public.users for update
    using (id = auth.uid())
    with check (id = auth.uid());

-- ----- 3) กัน user ยกระดับ role ตัวเองผ่านช่องทางที่เพิ่งเปิดในข้อ 2 -----
-- RLS ข้างบนอนุญาตอัปเดตทุกคอลัมน์ของแถวตัวเอง รวมถึง role ด้วย (RLS ไม่มี
-- concept "column-level" ในตัว) เลยต้องมี trigger เสริมชั้นความปลอดภัย:
-- ถ้าใครพยายามเปลี่ยน role และคนทำไม่ใช่ service_role (เช่น admin ผ่าน
-- Supabase Dashboard SQL หรือ backend script ที่ใช้ SERVICE_ROLE_KEY)
-- ให้เงียบๆ คืนค่า role เดิมกลับไป ไม่ raise exception เพื่อไม่ให้ UI
-- ฝั่ง frontend ที่ส่ง payload อื่นมาพร้อมกัน (เช่น update wishlist prefs
-- พร้อม full_name) ต้อง fail ทั้งก้อนเพราะ role ติดมาด้วยโดยไม่ตั้งใจ
create or replace function public.prevent_self_role_escalation()
returns trigger language plpgsql security definer as $$
begin
    if new.role is distinct from old.role and auth.role() <> 'service_role' then
        new.role := old.role;
    end if;
    return new;
end;
$$;

drop trigger if exists trg_users_prevent_role_escalation on public.users;
create trigger trg_users_prevent_role_escalation
    before update on public.users
    for each row execute function public.prevent_self_role_escalation();
