-- =====================================================================
-- Migration 0010 — แก้ province_summary view
--
-- ปัญหา: view เดิม group by 3 column (led_province_id, led_province_name, city)
-- ทำให้ 1 จังหวัดแตกเป็นหลาย row ตามค่า city field ของทรัพย์
-- แก้: group by เฉพาะ led_province_id, led_province_name
--
-- ต้อง drop view ที่ depend ก่อน (assets_map, auction_today)
-- แล้วสร้างคืนทั้งหมด
-- =====================================================================

-- Step 1: drop views ที่ depend กัน
drop view if exists public.assets_map;
drop view if exists public.auction_today;
drop view if exists public.province_summary;

-- =====================================================================
-- Step 2: province_summary (ใหม่ — group by province เท่านั้น)
-- =====================================================================
create view public.province_summary as
select
    led_province_id,
    led_province_name,
    count(*)                                    as total_assets,
    count(*) filter (where is_sold = true)      as total_sold,
    count(*) filter (where is_closed = false)   as total_active,
    avg(assetprice3)                            as avg_price,
    max(ischeck_date)                           as latest_update,
    max(date_modified)                          as latest_crawled
from public.assets
where led_province_id is not null
group by led_province_id, led_province_name;

comment on view public.province_summary
    is 'สรุปข้อมูลรายจังหวัด — group by province เท่านั้น (แก้จาก 0001 ที่ group by city ด้วย)';

-- =====================================================================
-- Step 3: assets_map (คืนจาก migration 0005)
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

-- =====================================================================
-- Step 4: auction_today (คืนจาก migration 0001)
-- =====================================================================
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

-- =====================================================================
-- Step 5: GRANT SELECT ให้ anon (กันหลุดหลัง drop/create)
-- =====================================================================
grant select on public.province_summary to anon;
grant select on public.assets_map       to anon;
grant select on public.auction_today    to anon;
