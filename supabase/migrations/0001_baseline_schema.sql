-- =====================================================================
-- TPIS Database Schema v5 — Supabase / PostgreSQL
-- เปลี่ยนแปลงจาก v4 (user):
--   [+] date_modified (timestamptz) — timestamp ที่ crawler fetch จาก LED (GMT+7)
--   [+] users table + trigger auto-create เมื่อ signup
--   [+] user_watchlists, user_saved_searches, user_alerts, user_notes, user_recent_views
--   [+] full-text search_vector + GIN index + trigger
--   [+] pg_trgm index สำหรับ ownername, deedno_raw
--   [+] RLS แยก role: anon/user/analyst/admin
--   [+] helper fn: current_user_role()
--   [+] index idx_bid_rounds_pending (bid_date WHERE issale_code='0')
--   [+] views: auction_today, province_summary
--   [~] assets_map: เพิ่ม deedno_raw, deedno_count, date_modified
-- =====================================================================

-- =====================================================================
-- 0) EXTENSIONS
-- =====================================================================
create extension if not exists pg_trgm;
create extension if not exists unaccent;

-- =====================================================================
-- 1) users — role management ผูกกับ Supabase Auth
-- =====================================================================
create table if not exists public.users (
    id          uuid primary key references auth.users(id) on delete cascade,
    email       text,
    full_name   text,
    role        text not null default 'user'
                    check (role in ('user', 'analyst', 'admin')),
    is_active   boolean not null default true,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

comment on table  public.users       is 'User profiles + roles — ผูกกับ Supabase Auth';
comment on column public.users.role  is 'user=ดู+export+watchlist | analyst=+analytics+logs | admin=ทุกอย่าง';

-- auto-insert row เมื่อมี user ใหม่ signup
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer as $$
begin
    insert into public.users (id, email, full_name, role)
    values (
        new.id,
        new.email,
        coalesce(new.raw_user_meta_data->>'full_name', new.email),
        'user'
    )
    on conflict (id) do nothing;
    return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
    after insert on auth.users
    for each row execute function public.handle_new_user();

-- =====================================================================
-- 2) assets — ทรัพย์หลัก (1 row = 1 form จากหน้าค้นหา LED)
-- =====================================================================
create table if not exists public.assets (
    id                  bigint generated always as identity primary key,

    -- ===== Identifiers =====
    str_bid_num         text,   -- ลำดับการขาย-นัดที่ เช่น "3 - 1" (ลอตที่ 3 นัดที่ 1)
    fbidnum             text,   -- เลขลำดับการขายหลัก เช่น "3"
    fbidnuml            text,   -- เลขลำดับการขายส่วนขยาย (มักว่าง ยังไม่ทราบความหมายชัดเจน)
    fsubbidnum          text,   -- เลขลำดับย่อย (นัดที่) เช่น "1"

    -- ===== ขนาดที่ดิน =====
    rai                 numeric,        -- ขนาด (ไร่)
    ngan                numeric,        -- ขนาด (งาน) ตรงกับ field "ngan" ใน LandsMaps response
    wa                  numeric,        -- ขนาด (ตารางวา) อาจเป็นทศนิยม เช่น 28.82
    landtype            text,           -- ประเภทเอกสารสิทธิ์ เช่น "โฉนดเลขที่", "น.ส.3ก"
    landdesc            text,           -- รายละเอียดเอกสารสิทธิ์ เช่น "ตามโฉนด"
    deedno_raw          text,           -- string ดิบจาก LED เช่น "1569-1579,1601-1602,3497"
    deedno              text[],         -- array โฉนดที่ parse แล้ว เช่น ['1569','1570',...,'3497']
    deedno_count        smallint,       -- จำนวนโฉนดทั้งหมด เช่น 14
    addrno              text,           -- เลขที่บ้าน/ที่อยู่ เช่น "179/46"

    -- ===== ที่ตั้งทรัพย์ (จากหน้าค้นหา LED) =====
    tumbol              text,           -- ตำบล/แขวง (ที่ตั้งจริง อาจต่างจากโฉนด)
    ampur               text,           -- อำเภอ/เขต (ที่ตั้งจริง)
    city                text,           -- จังหวัด (ที่ตั้งจริง)

    -- ===== ที่ตั้งตามโฉนด ← ใช้แปลงเป็น provid/amph2 สำหรับ LandsMaps =====
    deedtumbol          text,           -- ตำบล/แขวง ตามโฉนด
    deedampur           text,           -- อำเภอ/เขต ตามโฉนด
    deedcity            text,           -- จังหวัด ตามโฉนด

    -- ===== ประเภททรัพย์ =====
    asset_type_id       text,   -- "001"=ที่ดินว่างเปล่า "002"=ห้องชุด "003"=ที่ดิน+สิ่งปลูกสร้าง
    asset_type_desc     text,   -- ชื่อประเภท เช่น "ที่ดินพร้อมสิ่งปลูกสร้าง"

    -- ===== คดี / ศาล =====
    law_court_id        text,   -- รหัสศาล เช่น "010"=แพ่ง "112"=ล้มละลายกลาง
    law_court_name      text,   -- ชื่อศาล เช่น "แพ่ง"
    law_suit_no         text,   -- เลขคดี เช่น "ผบE.3437"
    law_suit_year       text,   -- ปีคดี (พ.ศ.) เช่น "2567"
    province_id         text,   -- รหัส internal ของ LED ไม่ใช่รหัสจังหวัดทั่วไป เช่น "034"
    province_name       text,   -- ชื่อสำนักงานบังคับคดี เช่น "แพ่งกรุงเทพมหานคร 1"

    -- ===== คู่ความ / เจ้าของ =====
    person1             text,   -- โจทก์/เจ้าหนี้
    person2             text,   -- จำเลย/ลูกหนี้
    owner_suit_name     text,   -- เจ้าของสำนวน (เก็บค่าแรกค่าเดียว)
    ownername           text,   -- ชื่อเจ้าของกรรมสิทธิ์ตามโฉนด
    occupant            text,   -- ผู้ครอบครองทรัพย์ เช่น "ผู้ถือกรรมสิทธิ์" / "ผู้เช่า"

    -- ===== เงินมัดจำ =====
    reserve_fund        numeric,  -- เงินมัดจำสำหรับบุคคลทั่วไป
    reserve_fund1       numeric,  -- เงินมัดจำสำหรับผู้มีสิทธิ์ใช้ส่วนแทน

    -- ===== ราคาประเมิน =====
    assetprice1         numeric,  -- ราคาประเมินโดยผู้เชี่ยวชาญ
    assetprice2         numeric,  -- ⚠️ ยังไม่แน่ใจ
    assetprice3         numeric,  -- ราคาประเมินเจ้าพนักงานบังคับคดี ← ราคาหลัก
    assetprice4         numeric,  -- ราคาประเมินเจ้าพนักงานประเมินราคาทรัพย์กรมบังคับคดี
    assetprice5         numeric,  -- ราคาที่กำหนดโดยคณะกรรมการกำหนดราคาทรัพย์
    assetprice6         numeric,  -- ⚠️ ยังไม่แน่ใจ
    assetprice7         numeric,  -- ⚠️ ยังไม่แน่ใจ
    assetprice8         numeric,  -- ⚠️ ยังไม่แน่ใจ
    assetprice9         numeric,  -- ⚠️ ยังไม่แน่ใจ

    -- ===== หนี้สิน =====
    debtname            text,     -- ชื่อเจ้าหนี้/ผู้รับจำนอง
    debtprice           numeric,  -- ยอดหนี้ (บาท)
    debtdetail          text,     -- รายละเอียดหนี้เพิ่มเติม (มักว่าง)

    -- ===== สถานะการขาย =====
    issale              text,     -- สถานะรวม (มักเป็น "0" เสมอ ⚠️)
    is_extra_pledgb     boolean,  -- ⚠️ ยังไม่ทราบความหมายชัดเจน
    eauc                boolean,  -- เป็น e-Auction หรือไม่
    saletypename        text,     -- วิธีการขาย เช่น "ปลอดการจำนอง" / "การจำนองติดไป"

    -- ===== สรุปสถานะ (คำนวณจาก issale1-8 โดย crawler) =====
    is_closed           boolean,  -- true ถ้าขายแล้ว หรือหมดนัดโดยไม่มีนัด "ยังไม่ถึง"
    is_sold             boolean,  -- true ถ้ามีนัดใดมี issaleN=1 (ขายได้)
    latest_status       text,     -- สถานะนัดล่าสุดที่มีผล เช่น "งดขายไม่มีผู้สู้ราคา"
    latest_round_no     int,      -- เลขนัดล่าสุดที่มีผล (1-8)

    -- ===== วันที่ / หมายเหตุ =====
    ischeck_date        date,     -- วันที่ประกาศขึ้นเว็บ LED
    remark              text,     -- หมายเหตุทรัพย์
    remark1             text,     -- หมายเหตุเพิ่มเติม (มักว่าง)

    -- ===== สถานที่ / เวลาขาย =====
    sale_location1      text,     -- สถานที่จำหน่าย (นัดที่ 1)
    sale_location2      text,     -- สถานที่จำหน่าย (นัดที่ 2 ถ้าต่างออกไป)
    sale_time1          text,     -- เวลาประมูล เช่น "09.00"
    sale_time2          text,     -- เวลาประมูล นัดที่ 2 (มักว่าง)
    tel                 text,     -- เบอร์โทรติดต่อ
    auc_asset_gen       text,     -- รหัสอ้างอิง internal LED ⚠️

    -- ===== URL รูปภาพ =====
    url_picture         text,     -- รูปภาพทรัพย์ (*p.jpg)
    url_map             text,     -- รูปแผนที่ตำแหน่ง (*m.jpg)
    url_mapjot          text,     -- รูปแผนผัง/โฉนด (*j.jpg ⚠️)
    landpicture_path    text,     -- Z:\... path ดิบ (debug)

    -- ===== Metadata จาก crawler =====
    led_province_id     text,     -- รหัสจังหวัด LED dropdown เช่น "10"
    led_province_name   text,     -- ชื่อจังหวัด เช่น "กรุงเทพมหานคร"
    form_action         text,     -- URL ของ asset_open.asp
    raw_payload         jsonb,    -- JSON ดิบทั้งก้อน (สำรอง)

    -- ===== Timestamps =====
    -- date_modified: timestamp ที่ crawler fetch ข้อมูลจาก LED (เวลา Bangkok GMT+7)
    -- ตรงกับ raw["date_modified"] ใน parser.py format: "2026-06-26T09:14:00+07:00"
    date_modified       timestamptz,

    scraped_at          timestamptz not null default now(),
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),

    -- ===== Full-text search =====
    search_vector       tsvector,

    -- กันซ้ำ: province_id + str_bid_num + deedno_raw ไม่ซ้ำกันในระบบ
    constraint uq_assets unique (led_province_id, str_bid_num, deedno_raw)
);

-- ----- Standard indexes -----
create index if not exists idx_assets_city            on public.assets (city);
create index if not exists idx_assets_ampur           on public.assets (ampur);
create index if not exists idx_assets_tumbol          on public.assets (tumbol);
create index if not exists idx_assets_asset_type      on public.assets (asset_type_id);
create index if not exists idx_assets_is_closed       on public.assets (is_closed);
create index if not exists idx_assets_is_sold         on public.assets (is_sold);
create index if not exists idx_assets_deedno          on public.assets using gin (deedno);
create index if not exists idx_assets_deedno_raw      on public.assets (deedno_raw);
create index if not exists idx_assets_deedcity_ampur  on public.assets (deedcity, deedampur);
create index if not exists idx_assets_ngan            on public.assets (ngan);
create index if not exists idx_assets_price3          on public.assets (assetprice3);
create index if not exists idx_assets_saletypename    on public.assets (saletypename);
create index if not exists idx_assets_ischeck_date    on public.assets (ischeck_date desc);
create index if not exists idx_assets_led_province    on public.assets (led_province_id);
create index if not exists idx_assets_date_modified   on public.assets (date_modified desc);

-- ----- Full-text search GIN index -----
create index if not exists idx_assets_search
    on public.assets using gin (search_vector);

-- ----- Trigram index สำหรับ LIKE/ILIKE -----
create index if not exists idx_assets_ownername_trgm
    on public.assets using gin (ownername gin_trgm_ops);
create index if not exists idx_assets_deedno_raw_trgm
    on public.assets using gin (deedno_raw gin_trgm_ops);

-- ----- Trigger: อัพ search_vector อัตโนมัติ -----
create or replace function public.assets_search_vector_update()
returns trigger language plpgsql as $$
begin
    new.search_vector :=
        setweight(to_tsvector('simple', coalesce(new.ownername,       '')), 'A') ||
        setweight(to_tsvector('simple', coalesce(new.deedno_raw,      '')), 'A') ||
        setweight(to_tsvector('simple', coalesce(new.law_suit_no,     '')), 'A') ||
        setweight(to_tsvector('simple', coalesce(new.city,            '')), 'B') ||
        setweight(to_tsvector('simple', coalesce(new.ampur,           '')), 'B') ||
        setweight(to_tsvector('simple', coalesce(new.deedcity,        '')), 'B') ||
        setweight(to_tsvector('simple', coalesce(new.deedampur,       '')), 'B') ||
        setweight(to_tsvector('simple', coalesce(new.asset_type_desc, '')), 'C') ||
        setweight(to_tsvector('simple', coalesce(new.remark,          '')), 'D');
    return new;
end;
$$;

drop trigger if exists trg_assets_search_vector on public.assets;
create trigger trg_assets_search_vector
    before insert or update on public.assets
    for each row execute function public.assets_search_vector_update();

-- =====================================================================
-- 3) asset_bid_rounds — นัดประมูล (normalized จาก biddate1-8 / issale1-8)
--
-- issale codes ยืนยันจากข้อมูลจริง:
--   0  = ยังไม่ถึงนัด / ยังไม่มีผล ("-")
--   1  = ขายได้
--   3  = งดขายไม่มีผู้สู้ราคา
--   13 = งดขาย
--   25 = งดขาย (ปิดเคสถาวร)
-- =====================================================================
create table if not exists public.asset_bid_rounds (
    id              bigint generated always as identity primary key,
    asset_id        bigint not null references public.assets(id) on delete cascade,

    round_no        smallint not null check (round_no between 1 and 8),
    bid_date        date,
    asset_price     numeric,
    issale_code     text,
    status_text     text,

    created_at      timestamptz not null default now(),

    constraint uq_asset_bid_round unique (asset_id, round_no)
);

create index if not exists idx_bid_rounds_asset_id on public.asset_bid_rounds (asset_id);
create index if not exists idx_bid_rounds_bid_date on public.asset_bid_rounds (bid_date);
create index if not exists idx_bid_rounds_status   on public.asset_bid_rounds (issale_code);
-- index เฉพาะรายการที่ยังรอผล — สำหรับ "วันนี้มีประมูลที่ไหน" query
create index if not exists idx_bid_rounds_pending
    on public.asset_bid_rounds (bid_date)
    where issale_code = '0';

-- =====================================================================
-- 4) asset_history — ประวัติการเปลี่ยนแปลง field
-- =====================================================================
create table if not exists public.asset_history (
    id              bigint generated always as identity primary key,
    asset_id        bigint not null references public.assets(id) on delete cascade,

    field_name      text not null,
    old_value       text,
    new_value       text,
    changed_at      timestamptz not null default now(),
    crawler_run_id  bigint
);

create index if not exists idx_history_asset_id   on public.asset_history (asset_id);
create index if not exists idx_history_changed_at on public.asset_history (changed_at desc);
create index if not exists idx_history_field      on public.asset_history (field_name);

-- =====================================================================
-- 5) asset_images — รูปภาพ
-- =====================================================================
create table if not exists public.asset_images (
    id              bigint generated always as identity primary key,
    asset_id        bigint not null references public.assets(id) on delete cascade,

    image_type      text not null,  -- "main" | "map" | "mapjot" | "gallery"
    source_url      text,
    r2_key          text,
    image_hash      text,
    file_size_bytes int,
    sort_order      smallint default 0,

    uploaded_at     timestamptz,
    created_at      timestamptz not null default now(),

    constraint uq_asset_image unique (asset_id, image_type, source_url)
);

create index if not exists idx_images_asset_id   on public.asset_images (asset_id);
create index if not exists idx_images_image_type on public.asset_images (image_type);

-- =====================================================================
-- 6) asset_coordinates — พิกัด จาก LandsMaps API
-- =====================================================================
create table if not exists public.asset_coordinates (
    asset_id        bigint primary key references public.assets(id) on delete cascade,

    api_provid      text,
    api_amph2       text,
    api_parcelno    text,
    api_url         text,

    verify_rai          numeric,
    verify_ngan         numeric,
    verify_wa           numeric,
    verify_parcelno     text,
    verify_status       text not null
        check (verify_status in (
            'matched',
            'partial_match',
            'not_found',
            'mismatch',
            'error'
        )),
    verify_note     text,

    latitude        numeric(12,8),
    longitude       numeric(12,8),
    land_price_per_sqw  numeric,
    utm             text,
    landoffice      text,
    parcel_type     text,
    tambol_id       text,
    parcel_seq      text,

    fetched_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),

    constraint uq_coords_parcel unique (api_provid, api_amph2, api_parcelno)
);

create index if not exists idx_coords_verify_status on public.asset_coordinates (verify_status);
create index if not exists idx_coords_latlon
    on public.asset_coordinates (latitude, longitude)
    where verify_status in ('matched', 'partial_match');

-- =====================================================================
-- 7) asset_land_price
-- =====================================================================
create table if not exists public.asset_land_price (
    asset_id            bigint primary key references public.assets(id) on delete cascade,
    land_price_per_sqw  numeric,
    price_year          text,
    source              text default 'landsmaps',
    fetched_at          timestamptz not null default now()
);

-- =====================================================================
-- 8) user_watchlists — ทรัพย์โปรด (user ขึ้นไป)
-- =====================================================================
create table if not exists public.user_watchlists (
    id          bigint generated always as identity primary key,
    user_id     uuid not null references public.users(id) on delete cascade,
    asset_id    bigint not null references public.assets(id) on delete cascade,
    note        text,
    created_at  timestamptz not null default now(),
    constraint uq_watchlist unique (user_id, asset_id)
);

create index if not exists idx_watchlist_user_id  on public.user_watchlists (user_id);
create index if not exists idx_watchlist_asset_id on public.user_watchlists (asset_id);

-- =====================================================================
-- 9) user_saved_searches — บันทึก filter preset (user ขึ้นไป)
-- =====================================================================
create table if not exists public.user_saved_searches (
    id          bigint generated always as identity primary key,
    user_id     uuid not null references public.users(id) on delete cascade,
    name        text not null,          -- ชื่อ preset เช่น "ที่ดิน ชลบุรี <5M"
    filters     jsonb not null,         -- {"city":"ชลบุรี","asset_type_id":"001","price_max":5000000}
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

create index if not exists idx_saved_searches_user_id on public.user_saved_searches (user_id);

-- =====================================================================
-- 10) user_alerts — แจ้งเตือน bid date / price drop (user ขึ้นไป)
-- =====================================================================
create table if not exists public.user_alerts (
    id              bigint generated always as identity primary key,
    user_id         uuid not null references public.users(id) on delete cascade,
    asset_id        bigint not null references public.assets(id) on delete cascade,
    alert_type      text not null check (alert_type in ('bid_date', 'price_drop', 'status_change')),
    is_active       boolean not null default true,
    last_sent_at    timestamptz,
    created_at      timestamptz not null default now(),
    constraint uq_alert unique (user_id, asset_id, alert_type)
);

create index if not exists idx_alerts_user_id  on public.user_alerts (user_id);
create index if not exists idx_alerts_asset_id on public.user_alerts (asset_id);
create index if not exists idx_alerts_active   on public.user_alerts (is_active) where is_active = true;

-- =====================================================================
-- 11) user_notes — personal note ต่อ asset (user ขึ้นไป)
-- =====================================================================
create table if not exists public.user_notes (
    id          bigint generated always as identity primary key,
    user_id     uuid not null references public.users(id) on delete cascade,
    asset_id    bigint not null references public.assets(id) on delete cascade,
    content     text not null,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now(),
    constraint uq_note unique (user_id, asset_id)
);

create index if not exists idx_notes_user_id  on public.user_notes (user_id);
create index if not exists idx_notes_asset_id on public.user_notes (asset_id);

-- =====================================================================
-- 12) user_recent_views — ประวัติทรัพย์ที่เคยเปิด (user ขึ้นไป)
-- =====================================================================
create table if not exists public.user_recent_views (
    id          bigint generated always as identity primary key,
    user_id     uuid not null references public.users(id) on delete cascade,
    asset_id    bigint not null references public.assets(id) on delete cascade,
    viewed_at   timestamptz not null default now(),
    constraint uq_recent_view unique (user_id, asset_id)
);

create index if not exists idx_recent_views_user_id  on public.user_recent_views (user_id);
create index if not exists idx_recent_views_viewed_at on public.user_recent_views (viewed_at desc);

-- =====================================================================
-- 13) crawler_runs
-- =====================================================================
create table if not exists public.crawler_runs (
    id              bigint generated always as identity primary key,

    started_at      timestamptz not null,
    finished_at     timestamptz,
    status          text check (status in ('running','completed','failed','partial')),

    run_mode        text,
    target_provinces jsonb,

    total_provinces_attempted   int default 0,
    total_provinces_success     int default 0,
    total_provinces_failed      int default 0,
    total_pages_fetched         int default 0,
    total_records_fetched       int default 0,
    total_records_new           int default 0,
    total_records_updated       int default 0,
    total_session_renews        int default 0,
    total_retries               int default 0,

    duration_sec    numeric,
    error_message   text,
    triggered_by    text default 'manual'
);

create index if not exists idx_runs_started_at on public.crawler_runs (started_at desc);
create index if not exists idx_runs_status     on public.crawler_runs (status);

-- =====================================================================
-- 14) crawler_run_details
-- =====================================================================
create table if not exists public.crawler_run_details (
    id              bigint generated always as identity primary key,
    run_id          bigint not null references public.crawler_runs(id) on delete cascade,

    province_id     text not null,
    province_name   text,
    status          text check (status in ('success','failed','skipped')),

    total_pages     int default 0,
    records_fetched int default 0,
    records_new     int default 0,
    records_updated int default 0,
    session_renews  int default 0,
    duration_sec    numeric,

    started_at      timestamptz,
    finished_at     timestamptz,
    error_message   text
);

create index if not exists idx_run_details_run_id      on public.crawler_run_details (run_id);
create index if not exists idx_run_details_province_id on public.crawler_run_details (province_id);
create index if not exists idx_run_details_status      on public.crawler_run_details (status);

-- =====================================================================
-- TRIGGERS: auto-update updated_at
-- =====================================================================
create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists trg_assets_updated_at on public.assets;
create trigger trg_assets_updated_at
    before update on public.assets
    for each row execute function public.set_updated_at();

drop trigger if exists trg_coords_updated_at on public.asset_coordinates;
create trigger trg_coords_updated_at
    before update on public.asset_coordinates
    for each row execute function public.set_updated_at();

drop trigger if exists trg_users_updated_at on public.users;
create trigger trg_users_updated_at
    before update on public.users
    for each row execute function public.set_updated_at();

drop trigger if exists trg_saved_searches_updated_at on public.user_saved_searches;
create trigger trg_saved_searches_updated_at
    before update on public.user_saved_searches
    for each row execute function public.set_updated_at();

drop trigger if exists trg_notes_updated_at on public.user_notes;
create trigger trg_notes_updated_at
    before update on public.user_notes
    for each row execute function public.set_updated_at();

-- =====================================================================
-- HELPER: ดึง role ของ user ปัจจุบัน
-- =====================================================================
create or replace function public.current_user_role()
returns text language sql security definer stable as $$
    select role from public.users where id = auth.uid();
$$;

-- =====================================================================
-- ROW LEVEL SECURITY
-- =====================================================================
alter table public.users                enable row level security;
alter table public.assets               enable row level security;
alter table public.asset_bid_rounds     enable row level security;
alter table public.asset_history        enable row level security;
alter table public.asset_images         enable row level security;
alter table public.asset_coordinates    enable row level security;
alter table public.asset_land_price     enable row level security;
alter table public.user_watchlists      enable row level security;
alter table public.user_saved_searches  enable row level security;
alter table public.user_alerts          enable row level security;
alter table public.user_notes           enable row level security;
alter table public.user_recent_views    enable row level security;
alter table public.crawler_runs         enable row level security;
alter table public.crawler_run_details  enable row level security;

-- ----- anon อ่านข้อมูลทรัพย์ได้ (public read) -----
create policy "public read assets"
    on public.assets for select using (true);
create policy "public read bid_rounds"
    on public.asset_bid_rounds for select using (true);
create policy "public read images"
    on public.asset_images for select using (true);
create policy "public read coordinates"
    on public.asset_coordinates for select using (true);
create policy "public read land_price"
    on public.asset_land_price for select using (true);

-- ----- asset_history: analyst/admin เท่านั้น -----
create policy "analyst read history"
    on public.asset_history for select
    using (public.current_user_role() in ('analyst', 'admin'));

-- ----- crawler_runs/details: analyst/admin เท่านั้น -----
create policy "analyst read crawler_runs"
    on public.crawler_runs for select
    using (public.current_user_role() in ('analyst', 'admin'));
create policy "analyst read crawler_details"
    on public.crawler_run_details for select
    using (public.current_user_role() in ('analyst', 'admin'));

-- ----- users: เห็นของตัวเอง | admin เห็นทั้งหมด -----
create policy "read own profile"
    on public.users for select
    using (id = auth.uid() or public.current_user_role() = 'admin');
create policy "admin update users"
    on public.users for update
    using (public.current_user_role() = 'admin');

-- ----- user_* tables: เห็นและแก้ไขได้เฉพาะของตัวเอง (user ขึ้นไป) -----
create policy "own watchlist"
    on public.user_watchlists for all
    using (user_id = auth.uid() and auth.role() = 'authenticated');

create policy "own saved_searches"
    on public.user_saved_searches for all
    using (user_id = auth.uid() and auth.role() = 'authenticated');

create policy "own alerts"
    on public.user_alerts for all
    using (user_id = auth.uid() and auth.role() = 'authenticated');

create policy "own notes"
    on public.user_notes for all
    using (user_id = auth.uid() and auth.role() = 'authenticated');

create policy "own recent_views"
    on public.user_recent_views for all
    using (user_id = auth.uid() and auth.role() = 'authenticated');

-- INSERT/UPDATE/DELETE ทุก table → ใช้ service_role key (bypass RLS)

-- =====================================================================
-- VIEWS
-- =====================================================================

-- assets_map: สำหรับ GIS map + search API
create or replace view public.assets_map as
select
    a.id,
    a.str_bid_num,
    a.deedno,
    a.deedno_raw,
    a.deedno_count,
    a.asset_type_id,
    a.asset_type_desc,
    a.city,
    a.ampur,
    a.tumbol,
    a.rai,
    a.ngan,
    a.wa,
    a.assetprice3           as appraisal_price,
    a.reserve_fund,
    a.saletypename,
    a.is_closed,
    a.is_sold,
    a.latest_status,
    a.latest_round_no,
    a.url_picture,
    a.ischeck_date,
    a.date_modified,
    a.led_province_id,
    a.led_province_name,
    c.latitude,
    c.longitude,
    c.land_price_per_sqw,
    c.verify_status         as coord_verify_status
from public.assets a
left join public.asset_coordinates c
    on c.asset_id = a.id
    and c.verify_status in ('matched', 'partial_match');

comment on view public.assets_map
    is 'assets + พิกัด LandsMaps (verified) — สำหรับ GIS map และ search API';

-- auction_today: รายการประมูลวันนี้
create or replace view public.auction_today as
select
    r.asset_id,
    r.round_no,
    r.bid_date,
    r.asset_price,
    r.issale_code,
    r.status_text,
    a.str_bid_num,
    a.asset_type_desc,
    a.city,
    a.ampur,
    a.ownername,
    a.law_court_name,
    a.sale_location1,
    a.sale_time1,
    a.url_picture,
    a.led_province_id
from public.asset_bid_rounds r
join public.assets a on a.id = r.asset_id
where r.bid_date = current_date;

comment on view public.auction_today
    is 'รายการนัดประมูลวันนี้ — สำหรับ dashboard widget';

-- province_summary: สรุปรายจังหวัด
create or replace view public.province_summary as
select
    led_province_id,
    led_province_name,
    city,
    count(*)                                    as total_assets,
    count(*) filter (where is_sold = true)      as total_sold,
    count(*) filter (where is_closed = false)   as total_active,
    avg(assetprice3)                            as avg_price,
    max(ischeck_date)                           as latest_update,
    max(date_modified)                          as latest_crawled
from public.assets
group by led_province_id, led_province_name, city;

comment on view public.province_summary
    is 'สรุปข้อมูลรายจังหวัด — สำหรับ province ranking widget';
