-- =====================================================================
-- Migration 0005 — แยกตาราง parcels ออกจาก asset_coordinates
--
-- ปัญหาที่แก้: asset_coordinates เดิมใช้ asset_id เป็น PRIMARY KEY
-- (1 asset = 1 แถว) แต่มี UNIQUE (api_provid, api_amph2, api_parcelno)
-- กำกับด้วย — ห้องชุด 1 ตึกมีหลายร้อย asset (ห้อง) แต่ใช้โฉนดที่ดิน
-- แปลงเดียวกันหมด พอห้องที่ 2 เป็นต้นไป insert จะชน UNIQUE constraint
-- ทันทีทั้งที่เป็นข้อมูลถูกต้อง
--
-- โครงสร้างใหม่:
--   parcels        — 1 แถวต่อ 1 แปลงที่ดินจริง (unique provid+amph2+parcelno)
--   asset_parcels  — ตารางกลาง เชื่อม asset ↔ parcel แบบ many-to-many
--                    (asset เดียวมีหลายโฉนดได้, parcel เดียวถูกหลาย asset
--                    อ้างอิงได้ — กรณีห้องชุด)
--
-- หมายเหตุ: ไม่มีข้อมูลจริงใน asset_coordinates ที่ต้อง migrate มาก่อน
-- เพราะ landsmaps_collector ยังเขียนแค่ไฟล์ local JSON ไม่เคยต่อ Supabase
-- โดยตรงเลย (นี่คือรอบแรกที่ทำ) จึง DROP ตารางเดิมได้เลยแบบปลอดภัย
-- =====================================================================

drop view if exists public.assets_map;
drop table if exists public.asset_coordinates cascade;

-- =====================================================================
-- parcels — 1 แถวต่อ 1 แปลงที่ดินจริงจาก LandsMaps
-- =====================================================================
create table public.parcels (
    id              bigint generated always as identity primary key,

    provid          text not null,   -- รหัสจังหวัดของ LandsMaps (ต่างจาก LED)
    amph2           text not null,   -- รหัสอำเภอ 2 หลัก
    parcelno        text not null,   -- เลขโฉนด/parcel

    latitude        numeric(12,8),
    longitude       numeric(12,8),
    land_price_per_sqw numeric,
    utm             text,
    landoffice      text,
    parcel_type     text,
    tambol_id       text,
    parcel_seq      text,

    rai             numeric,        -- พื้นที่ทั้งแปลงตาม LandsMaps (ไว้เทียบกับ asset)
    ngan            numeric,
    wa              numeric,

    verify_status   text not null
        check (verify_status in (
            'matched',
            'partial_match',
            'not_found',
            'mismatch',
            'error',
            'not_verified'   -- ห้องชุด — พิกัดใช้ได้ แต่ยังไม่ยืนยัน (รอ admin)
        )),
    verify_note     text,
    verified_by     uuid references public.users(id),
    verified_at     timestamptz,

    -- retry cooldown สำหรับ not_found (กลุ่ม 5.3)
    last_attempted_at timestamptz not null default now(),
    attempt_count     int not null default 1,

    fetched_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),

    constraint uq_parcels unique (provid, amph2, parcelno)
);

comment on table public.parcels is
    'แปลงที่ดินจริงจาก LandsMaps — 1 แถวต่อ 1 แปลง ไม่ผูกกับ asset ตรงๆ '
    'เพราะ 1 แปลงอาจถูกอ้างอิงจากหลาย asset ได้ (เช่น ห้องชุดในตึกเดียวกัน)';

create index idx_parcels_verify_status on public.parcels (verify_status);
create index idx_parcels_latlon on public.parcels (latitude, longitude)
    where verify_status in ('matched', 'partial_match', 'not_verified');
-- ใช้เช็ค cooldown ก่อน retry not_found (กลุ่ม 5.3)
create index idx_parcels_not_found_retry on public.parcels (last_attempted_at)
    where verify_status = 'not_found';

create trigger trg_parcels_updated_at
    before update on public.parcels
    for each row execute function public.set_updated_at();

-- =====================================================================
-- asset_parcels — ตารางกลาง เชื่อม asset ↔ parcel (many-to-many)
-- =====================================================================
create table public.asset_parcels (
    asset_id   bigint not null references public.assets(id) on delete cascade,
    parcel_id  bigint not null references public.parcels(id) on delete cascade,

    -- ผลเทียบพื้นที่ "asset นี้" กับ "parcel นี้" — เป็นคุณสมบัติของคู่ความสัมพันธ์
    -- ไม่ใช่ของ parcel เดี่ยวๆ เพราะ asset เดียวกันอาจเทียบกับหลาย parcel
    -- (multi-deed) และผลอาจต่างกันได้ในแต่ละคู่
    area_match  boolean,   -- true/false = เทียบแล้ว, null = ห้องชุด (เทียบไม่ได้)
    area_note   text,

    created_at  timestamptz not null default now(),

    primary key (asset_id, parcel_id)
);

comment on table public.asset_parcels is
    'ตารางกลาง asset ↔ parcel — รองรับทั้ง asset เดียวมีหลายโฉนด '
    'และ parcel เดียวถูกหลาย asset อ้างอิง (ห้องชุดในตึกเดียวกัน)';

create index idx_asset_parcels_asset_id  on public.asset_parcels (asset_id);
create index idx_asset_parcels_parcel_id on public.asset_parcels (parcel_id);

-- =====================================================================
-- RLS
-- =====================================================================
alter table public.parcels        enable row level security;
alter table public.asset_parcels  enable row level security;
alter table public.parcels        no force row level security;
alter table public.asset_parcels  no force row level security;

create policy "public read parcels"
    on public.parcels for select using (true);
create policy "public read asset_parcels"
    on public.asset_parcels for select using (true);

-- admin verify ผ่านหน้าเว็บได้ (ย้ายมาจาก asset_coordinates เดิมในกลุ่ม 1.5)
create policy "admin verify parcels"
    on public.parcels for update
    using (public.current_user_role() = 'admin')
    with check (public.current_user_role() = 'admin');

-- GRANT ให้ service_role ชัดเจน (เผื่อกรณี ALTER DEFAULT PRIVILEGES จาก
-- migration 0002 ไม่ครอบคลุมเพราะรันคนละ role — กันเหนียวไว้)
grant all on public.parcels        to service_role;
grant all on public.asset_parcels  to service_role;
grant all on sequence parcels_id_seq to service_role;

-- =====================================================================
-- แก้ view assets_map ให้ join ผ่าน asset_parcels/parcels แทน
-- เลือก parcel ตัวแทน 1 ตัวต่อ asset สำหรับปักหมุดแผนที่ (DISTINCT ON)
-- ลำดับความสำคัญ: matched > partial_match > not_verified > อื่นๆ
-- ตามที่ตัดสินใจไว้: not_verified (ห้องชุด) ให้โชว์บนแผนที่ด้วย
-- =====================================================================
create or replace view public.assets_map as
select distinct on (a.id)
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
    p.latitude,
    p.longitude,
    p.land_price_per_sqw,
    p.verify_status         as coord_verify_status
from public.assets a
join public.asset_parcels ap on ap.asset_id = a.id
join public.parcels p on p.id = ap.parcel_id
where p.verify_status in ('matched', 'partial_match', 'not_verified')
order by
    a.id,
    case p.verify_status
        when 'matched'       then 1
        when 'partial_match' then 2
        when 'not_verified'  then 3
        else 4
    end,
    p.id;

comment on view public.assets_map
    is 'assets + พิกัด parcel ตัวแทน 1 จุดต่อ asset (join ผ่าน asset_parcels) '
       '— รวม not_verified ของห้องชุดที่ยังไม่ verify พื้นที่ แต่พิกัดใช้ได้';
