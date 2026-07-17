-- =====================================================================
-- Migration 0011 — เพิ่ม deed location fields ใน assets_map view
--
-- เหตุผล: assets.city / ampur / tumbol หลายรายการว่างเปล่า
-- ต้องใช้ deedcity / deedampur / deedtumbol (ที่ตั้งตามโฉนด) แทน
-- Web app ใช้ fmtLocation() ที่ deed first → fallback city/ampur/tumbol
--
-- ไม่ drop auction_today และ province_summary
-- เพราะทั้งสอง view query จาก assets table โดยตรง ไม่ depend assets_map
-- =====================================================================

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
    -- ที่อยู่จริงของทรัพย์
    a.city,
    a.ampur,
    a.tumbol,
    -- ที่ตั้งตามโฉนด (เพิ่มใหม่ — มักมีข้อมูลครบกว่า)
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
    is 'assets + พิกัด parcel ตัวแทน 1 จุดต่อ asset '
       '— มี deedcity/deedampur/deedtumbol สำหรับแสดงที่อยู่ที่ถูกต้องกว่า';

grant select on public.assets_map to anon;
