-- =====================================================================
-- Migration 0016 — wishlist_reminder_log: กันส่งอีเมลแจ้งเตือนซ้ำ
--
-- บริบท: wishlist_notify.py (Cloud Run Job ใหม่ รันทุกวัน) ส่งอีเมลแจ้ง
-- เตือนนัดประมูลของทรัพย์ใน user_watchlists ตาม wishlist_reminder_days
-- ที่ user เลือกไว้เอง (migration 0015) — ต้องมีที่เก็บว่า "ส่งไปแล้วรึยัง"
-- กันไม่ให้ user ได้รับอีเมลซ้ำทุกวันจนกว่าจะถึงวันนัดจริง
-- =====================================================================

create table public.wishlist_reminder_log (
    id          bigint generated always as identity primary key,
    user_id     uuid   not null references public.users(id)  on delete cascade,
    asset_id    bigint not null references public.assets(id) on delete cascade,

    round_no    smallint not null,   -- นัดที่เท่าไหร่ (1-8) ณ ตอนที่ส่ง
    bid_date    date     not null,   -- วันนัด ณ ตอนที่ส่ง — รวมอยู่ใน unique key
                                      -- ด้วยเพราะถ้านัดถูกเลื่อนวัน (crawler รอบ
                                      -- ถัดไปอัปเดต bid_date ใหม่) ต้องนับเป็นนัด
                                      -- ใหม่ที่ยังไม่เคยแจ้ง ไม่ใช่นัดเดิมที่ส่งแล้ว
    day_offset  smallint not null,   -- แจ้งล่วงหน้ากี่วัน (1/3/7 ตามที่ user เลือก)

    sent_at     timestamptz not null default now(),

    constraint uq_wishlist_reminder unique (user_id, asset_id, round_no, bid_date, day_offset)
);

comment on table public.wishlist_reminder_log is
    'log การส่งอีเมลแจ้งเตือนนัดประมูล wishlist แต่ละครั้ง — กันส่งซ้ำ '
    '(unique ครอบ bid_date ด้วย เพื่อให้แจ้งใหม่ได้ถ้านัดถูกเลื่อนวัน)';

create index idx_wishlist_reminder_user  on public.wishlist_reminder_log (user_id);
create index idx_wishlist_reminder_asset on public.wishlist_reminder_log (asset_id);

-- ตารางนี้เขียน/อ่านผ่าน service_role (backend script ใช้ SERVICE_ROLE_KEY)
-- เท่านั้น ยังไม่มี UI ไหนในเว็บต้องอ่านตรงๆ (ไม่มีหน้า "ประวัติการแจ้งเตือน"
-- ตอนนี้) — เปิด RLS ไว้ตาม pattern ทุกตารางในระบบ แต่ไม่ต้องมี public policy
alter table public.wishlist_reminder_log enable row level security;
alter table public.wishlist_reminder_log no force row level security;

grant all on public.wishlist_reminder_log to service_role;
grant all on sequence wishlist_reminder_log_id_seq to service_role;
