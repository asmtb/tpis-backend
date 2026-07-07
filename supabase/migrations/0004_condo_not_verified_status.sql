-- =====================================================================
-- Migration 0004 — รองรับ verify_status = 'not_verified' (เคสห้องชุด)
-- อ้างอิงจากที่คุยกันไว้: ห้องชุด (asset_type_id = "002") พื้นที่ที่ LED
-- แสดง (พื้นที่ห้อง) เทียบกับ LandsMaps (พื้นที่ที่ดินทั้งแปลง) กันไม่ได้
-- โดยธรรมชาติ — ดึงพิกัดมาใช้ได้เลย แต่ยังไม่ยืนยันพื้นที่ ต้องรอ admin
-- verify ทีหลัง (แต่ยังโชว์บนแผนที่ได้เลยตามที่ตัดสินใจไว้)
-- =====================================================================

-- ----- 1.3: เพิ่มค่า enum ใหม่ใน verify_status -----
-- constraint เดิมตั้งชื่อ auto จาก Postgres: <table>_<column>_check
alter table public.asset_coordinates
    drop constraint if exists asset_coordinates_verify_status_check;

alter table public.asset_coordinates
    add constraint asset_coordinates_verify_status_check
    check (verify_status in (
        'matched',
        'partial_match',
        'not_found',
        'mismatch',
        'error',
        'not_verified'   -- ใหม่: พิกัดเจอแล้ว แต่ยังไม่ verify พื้นที่ (ห้องชุด)
    ));

comment on column public.asset_coordinates.verify_status is
    'matched/partial_match = auto-verify ผ่าน (ที่ดิน/บ้านเดี่ยว) | '
    'not_verified = พิกัดเจอแล้วแต่พื้นที่เทียบอัตโนมัติไม่ได้ (ห้องชุด) รอ admin ยืนยัน | '
    'not_found/mismatch/error = ดึงไม่สำเร็จหรือน่าสงสัย';

-- ----- 1.4: audit trail — ใครกด verify เมื่อไหร่ -----
alter table public.asset_coordinates
    add column if not exists verified_by uuid references public.users(id);
alter table public.asset_coordinates
    add column if not exists verified_at timestamptz;

comment on column public.asset_coordinates.verified_by is
    'admin ที่กด verify ด้วยตนเอง (ใช้กับ verify_status ที่เดิมเป็น not_verified)';
comment on column public.asset_coordinates.verified_at is
    'เวลาที่ admin กด verify — null ถ้ายังไม่มีใคร verify';

-- ----- 1.5: RLS policy ให้ admin update ผ่านหน้าเว็บได้ -----
-- (ของเดิมมีแค่ "public read" select เท่านั้น เขียนได้แค่ผ่าน service_role)
create policy "admin verify coordinates"
    on public.asset_coordinates for update
    using (public.current_user_role() = 'admin')
    with check (public.current_user_role() = 'admin');

-- ----- 1.6: แก้ view assets_map ให้โชว์ not_verified บนแผนที่ด้วย -----
-- ตามที่ตัดสินใจไว้: ห้องชุดที่ยัง not_verified ให้แสดงบนแผนที่เลย
-- ไม่ต้องรอ admin verify ก่อน (กันไม่ให้ห้องชุดหายจากแผนที่เป็นเวลานาน)
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
    and c.verify_status in ('matched', 'partial_match', 'not_verified');  -- 👈 เพิ่ม not_verified

comment on view public.assets_map
    is 'assets + พิกัด LandsMaps — สำหรับ GIS map และ search API '
       '(รวม not_verified ของห้องชุดที่ยังไม่ verify พื้นที่ แต่พิกัดใช้ได้)';
