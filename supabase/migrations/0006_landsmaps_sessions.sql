-- =====================================================================
-- Migration 0006 — landsmaps_sessions: เก็บ cookies สำหรับ LandsMaps
-- เหตุผล: Collector รันบน Cloud Run (ไม่มี local file) ต้องอ่าน cookies
--         จาก Supabase แทน — คุณ solve hCaptcha บนเครื่องตัวเอง ได้
--         test_cookies.json แล้ว upload ผ่าน Admin UI เข้าตารางนี้
-- =====================================================================

create table public.landsmaps_sessions (
    id           bigint generated always as identity primary key,
    cookies_json jsonb  not null,
    uploaded_at  timestamptz not null default now(),
    note         text,        -- เช่น "2026-07-09 solve manually"
    is_active    boolean not null default true
);

comment on table public.landsmaps_sessions is
    'cookies จาก hCaptcha challenge ของ landsmaps.dol.go.th — '
    'upload ผ่าน Admin UI หลัง solve captcha ด้วยมือบนเครื่องตัวเอง '
    'อายุ cookies ~1-1.5 ชม. (จากการทดสอบจริง)';

-- enforce ว่ามีแค่ 1 แถวที่ is_active=true ในแต่ละเวลา
create unique index uq_landsmaps_sessions_active
    on public.landsmaps_sessions (is_active)
    where is_active = true;

-- RLS
alter table public.landsmaps_sessions enable row level security;
alter table public.landsmaps_sessions no force row level security;

-- service_role อ่าน/เขียนได้ (crawler ใช้ตอน run)
grant all on public.landsmaps_sessions to service_role;
grant all on sequence landsmaps_sessions_id_seq to service_role;

-- admin อ่านได้จาก UI (authenticated user)
create policy "admin read sessions"
    on public.landsmaps_sessions for select
    using (public.current_user_role() = 'admin');
create policy "admin insert sessions"
    on public.landsmaps_sessions for insert
    with check (public.current_user_role() = 'admin');
create policy "admin update sessions"
    on public.landsmaps_sessions for update
    using (public.current_user_role() = 'admin');
