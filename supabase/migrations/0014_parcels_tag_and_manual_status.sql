-- =====================================================================
-- Migration 0014 — parcels: เพิ่มคอลัมน์ tag + verify_status = 'manual'
--
-- สำหรับหน้า "จัดการโฉนด" (Admin) ที่กำลังจะทำฝั่ง frontend — ให้แอดมินกรอก
-- lat/long เองได้ พร้อม tag (ชื่อคอนโด/สถานที่) ต่อโฉนด
--
-- 1) tag — คอลัมน์ใหม่แยกจาก verify_note โดยตั้งใจ เพราะ verify_note ถูก
--    landsmaps_collector เขียนทับอัตโนมัติทุกครั้งที่รัน (เช่นข้อความ
--    "ห้องชุด — ไม่เทียบพื้นที่...") ถ้าเอา tag ของแอดมินไปแปะช่องเดียวกัน
--    รอบหน้า collector รันซ้ำจะเขียนทับหายหมด
--
-- 2) verify_status = 'manual' — ตอนแอดมิน save lat/long เอง ต้อง set
--    status นี้เพื่อกัน landsmaps_collector รันซ้ำมาทับพิกัดที่กรอกเอง
--    (ดู is_retryable() ใน landsmaps_supabase.py — status อื่นๆ อย่าง
--    not_found/mismatch/error ถูกออกแบบให้ retry ได้เสมอ ถ้าไม่มี status
--    ใหม่นี้ พิกัดที่แอดมินกรอกเองจะโดนทับทิ้งในรอบถัดไป)
-- =====================================================================

-- ----- 1) เพิ่มคอลัมน์ tag -----
alter table public.parcels
    add column if not exists tag text;

comment on column public.parcels.tag is
    'ชื่อคอนโด/สถานที่ที่แอดมินกรอกเอง (ไม่ใช่จาก LandsMaps) — แยกจาก verify_note '
    'เพราะ verify_note ถูก collector เขียนทับอัตโนมัติทุกรอบ';

-- ----- 2) เพิ่มค่า enum ใหม่ 'manual' ใน verify_status -----
-- constraint เดิมตั้งชื่อ auto จาก Postgres: <table>_<column>_check
alter table public.parcels
    drop constraint if exists parcels_verify_status_check;

alter table public.parcels
    add constraint parcels_verify_status_check
    check (verify_status in (
        'matched',
        'partial_match',
        'not_found',
        'mismatch',
        'error',
        'not_verified',  -- ห้องชุด — พิกัดเจอแล้วแต่ยังไม่ verify พื้นที่ (0004)
        'manual'         -- ใหม่: แอดมินกรอก lat/long เอง — ไม่ให้ collector retry ทับ
    ));

comment on column public.parcels.verify_status is
    'matched/partial_match = auto-verify ผ่าน (ที่ดิน/บ้านเดี่ยว) | '
    'not_verified = พิกัดเจอแล้วแต่พื้นที่เทียบอัตโนมัติไม่ได้ (ห้องชุด) รอ admin ยืนยัน | '
    'manual = แอดมินกรอก lat/long เองผ่านหน้า "จัดการโฉนด" — ไม่ retry ซ้ำอีก | '
    'not_found/mismatch/error = ดึงไม่สำเร็จหรือน่าสงสัย';

-- ----- 3) ให้ view assets_map โชว์พิกัด manual บนแผนที่ด้วย -----
-- (เดิม where clause กรองแค่ matched/partial_match/not_verified — ต้องเพิ่ม manual)
drop view if exists public.assets_map;

create view public.assets_map as
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
    a.deedcity,
    a.deedampur,
    a.deedtumbol,
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
    p.verify_status         as coord_verify_status,
    p.tag                   as parcel_tag
from public.assets a
join public.asset_parcels ap on ap.asset_id = a.id
join public.parcels p on p.id = ap.parcel_id
where p.verify_status in ('matched', 'partial_match', 'not_verified', 'manual')
order by
    a.id,
    case p.verify_status
        when 'matched'       then 1
        when 'manual'        then 2
        when 'partial_match' then 3
        when 'not_verified'  then 4
        else 5
    end,
    p.id;

comment on view public.assets_map
    is 'assets + พิกัด parcel ตัวแทน 1 จุดต่อ asset — รวม manual (แอดมินกรอกเอง) '
       'และ not_verified ของห้องชุดที่ยังไม่ verify พื้นที่ แต่พิกัดใช้ได้';

grant select on public.assets_map to anon;
grant select on public.assets_map to authenticated;

-- ----- 4) index ช่วยกรอง "มี tag แล้ว / ยังไม่มี" ในหน้า จัดการโฉนด -----
create index if not exists idx_parcels_tag_not_null
    on public.parcels (tag)
    where tag is not null;
