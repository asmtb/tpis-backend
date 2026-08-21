"""
email_summary.py — ส่ง email สรุปผลผ่าน Resend API
ใช้ร่วมกันระหว่าง LED (ส่งอัตโนมัติหลัง Cloud Run เสร็จ)
และ LandsMaps (ส่งหลัง run เสร็จไม่ว่าจะ run จากที่ไหน)

Environment variables ที่ต้องตั้งใน Cloud Run Job:
  RESEND_API_KEY  — API key จาก resend.com (ฟรี 3,000 emails/เดือน)
  NOTIFY_EMAIL    — อีเมลที่จะรับการแจ้งเตือน เช่น your@gmail.com

ทดสอบบนเครื่องตัวเองได้โดยตั้งใน .env:
  RESEND_API_KEY=re_xxxxxxxxxxxx
  NOTIFY_EMAIL=your@gmail.com
"""

import os
import json
import requests
from datetime import datetime, timezone, timedelta

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

RESEND_API_KEY = os.environ.get("RESEND_API_KEY") or ""
NOTIFY_EMAIL   = os.environ.get("NOTIFY_EMAIL") or ""
# onboarding@resend.dev = test sender ของ Resend ใช้ได้ทันทีไม่ต้อง verify domain
# เปลี่ยนเป็น domain ของตัวเองได้ทีหลังตอน verify Cloudflare domain เสร็จ
FROM_EMAIL     = "TPIS <onboarding@resend.dev>"
BKK_TZ         = timezone(timedelta(hours=7))


def _send(subject: str, html: str, to: list[str] | None = None) -> bool:
    """
    ส่ง email ผ่าน Resend REST API
    คืน True ถ้าสำเร็จ, False ถ้าไม่มี key หรือ error
    (ไม่ raise exception เพราะไม่อยากให้ email failure ทำให้ crawler พัง)

    to: list ของอีเมลปลายทาง — ถ้าไม่ระบุ (None) ใช้ NOTIFY_EMAIL (แอดมิน)
        เป็น default เดิม (ใช้กับ send_led_summary/send_landsmaps_summary)
        ถ้าระบุ ใช้ส่งหา user ทั่วไปแทน (ใช้กับ send_email() ด้านล่าง)
    """
    recipients = to if to else [NOTIFY_EMAIL]

    if not RESEND_API_KEY or not recipients or not recipients[0]:
        print("⚠️  ไม่พบ RESEND_API_KEY หรือปลายทางอีเมล — ข้ามการส่ง email")
        return False

    try:
        r = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "from":    FROM_EMAIL,
                "to":      recipients,
                "subject": subject,
                "html":    html,
            },
            timeout=15,
        )
        if r.status_code in (200, 201):
            print(f"📧 ส่ง email สำเร็จ → {', '.join(recipients)}")
            return True
        else:
            print(f"⚠️  Resend API error {r.status_code}: {r.text[:200]}")
            return False
    except Exception as e:
        print(f"⚠️  ส่ง email ไม่สำเร็จ: {e}")
        return False


def send_email(to_email: str, subject: str, html: str) -> bool:
    """
    ส่ง email ไปหา user คนใดคนหนึ่งตรงๆ (ต่างจาก _send() ที่เดิม hardcode
    ส่งไป NOTIFY_EMAIL คนเดียวเสมอ) — ใช้กับอีเมลที่ต้องส่งหา user จริง
    เช่น wishlist_email.py (แจ้งเตือนนัดประมูล)
    """
    return _send(subject, html, to=[to_email])


def _now_bkk() -> str:
    return datetime.now(BKK_TZ).strftime("%Y-%m-%d %H:%M")


def _status_icon(success: bool) -> str:
    return "✅" if success else "❌"


# ================================================================
# LED Email
# ================================================================
def send_led_summary(stats: dict, pending_landsmaps: int = 0):
    """
    ส่ง email สรุปหลัง LED crawler รันเสร็จ
    เรียกจาก led_uploader.py ตอนจบ main()

    stats: dict จาก crawler_runs (หรือ stats dict ที่ uploader สะสมไว้)
    pending_landsmaps: จำนวน asset ที่ยังไม่มีพิกัด LandsMaps
                       (query จาก Supabase ตอนเรียกฟังก์ชันนี้)
    """
    success_count  = stats.get("total_provinces_success", 0)
    failed_count   = stats.get("total_provinces_failed",  0)
    total_records  = stats.get("total_records_fetched",   0)
    new_records    = stats.get("total_records_new",       0)
    duration_sec   = stats.get("duration_sec",            0)
    errors         = stats.get("error_message")
    overall_ok     = failed_count == 0 and not errors

    duration_str = (f"{duration_sec/60:.1f} นาที" if duration_sec >= 60
                    else f"{duration_sec:.0f} วินาที")

    # ตาราง province ล้มเหลว (ถ้ามี)
    failed_html = ""
    if errors:
        try:
            err_list = json.loads(errors) if isinstance(errors, str) else errors
            if isinstance(err_list, list) and err_list:
                rows = "".join(
                    f"<tr><td style='padding:4px 8px'>{e.get('province','?')}</td>"
                    f"<td style='padding:4px 8px;color:#dc2626'>{e.get('error','?')[:80]}</td></tr>"
                    for e in err_list[:10]
                )
                failed_html = f"""
                <h3 style="color:#dc2626">⚠️ จังหวัดที่มีปัญหา</h3>
                <table style="border-collapse:collapse;font-size:13px">
                  <tr style="background:#fee2e2">
                    <th style="padding:4px 8px;text-align:left">จังหวัด</th>
                    <th style="padding:4px 8px;text-align:left">Error</th>
                  </tr>{rows}
                </table>"""
        except Exception:
            failed_html = f"<p style='color:#dc2626'>Errors: {str(errors)[:300]}</p>"

    # แถบแจ้งเตือน LandsMaps (ถ้ามี pending)
    landsmaps_html = ""
    if pending_landsmaps > 0:
        landsmaps_html = f"""
        <div style="margin-top:16px;padding:12px 16px;background:#fef9c3;
                    border-left:4px solid #eab308;border-radius:4px">
          <strong>🗺️ LandsMaps</strong><br>
          มี <strong>{pending_landsmaps:,} รายการ</strong> ที่ยังไม่มีพิกัด<br>
          <small style="color:#666">รัน LandsMaps Collector เมื่อว่างเพื่อดึงพิกัดเพิ่ม</small>
        </div>"""

    subject = (f"{'✅' if overall_ok else '⚠️'} TPIS LED — {_now_bkk()} | "
               f"{success_count}/{success_count+failed_count} จังหวัด | "
               f"{total_records:,} records")

    html = f"""
    <div style="font-family:sans-serif;max-width:600px">
      <h2 style="color:{'#16a34a' if overall_ok else '#dc2626'}">
        {_status_icon(overall_ok)} TPIS LED Crawler
      </h2>

      <table style="width:100%;border-collapse:collapse;font-size:14px">
        <tr style="background:#f3f4f6">
          <td style="padding:6px 10px"><strong>เวลา</strong></td>
          <td style="padding:6px 10px">{_now_bkk()} (Bangkok)</td>
        </tr>
        <tr>
          <td style="padding:6px 10px"><strong>จังหวัดสำเร็จ</strong></td>
          <td style="padding:6px 10px">{success_count} / {success_count+failed_count}</td>
        </tr>
        <tr style="background:#f3f4f6">
          <td style="padding:6px 10px"><strong>Records ทั้งหมด</strong></td>
          <td style="padding:6px 10px">{total_records:,}</td>
        </tr>
        <tr>
          <td style="padding:6px 10px"><strong>🆕 รายการใหม่</strong></td>
          <td style="padding:6px 10px">
            <span style="color:{'#16a34a' if new_records > 0 else 'inherit'}">{new_records:,}</span>
          </td>
        </tr>
        <tr>
          <td style="padding:6px 10px"><strong>ระยะเวลา</strong></td>
          <td style="padding:6px 10px">{duration_str}</td>
        </tr>
        <tr style="background:#f3f4f6">
          <td style="padding:6px 10px"><strong>Errors</strong></td>
          <td style="padding:6px 10px">
            {'<span style="color:#16a34a">ไม่มี</span>' if not errors
             else f'<span style="color:#dc2626">{failed_count} จังหวัด</span>'}
          </td>
        </tr>
      </table>

      {failed_html}
      {landsmaps_html}

      <p style="margin-top:24px;font-size:12px;color:#9ca3af">
        TPIS — Thailand Property Intelligence System<br>
        Cloud Run Job: tpis-cron-weekly | Region: asia-southeast3
      </p>
    </div>
    """

    _send(subject, html)


# ================================================================
# LandsMaps Email
# ================================================================
def send_landsmaps_summary(stats: dict):
    """
    ส่ง email สรุปหลัง LandsMaps Collector รันเสร็จ
    เรียกจาก landsmaps_collector.py ตอนจบ main()

    stats: dict ที่ collector สะสมไว้ตลอดการรัน
    """
    found         = stats.get("found",               0)
    not_found     = stats.get("not_found",            0)
    cache_hit     = stats.get("cache_hit",            0)
    area_match    = stats.get("area_match",           0)
    area_mismatch = stats.get("area_mismatch",        0)
    area_na       = stats.get("area_not_applicable",  0)
    errors        = stats.get("errors",               0)
    total         = stats.get("total",                0)
    ip_block      = stats.get("suspected_ip_block",    False)
    stopped_at    = stats.get("stopped_at_index")
    stopped_asset = stats.get("stopped_at_asset_id")
    overall_ok    = errors == 0 and not ip_block

    subject = (
        f"🚫 TPIS LandsMaps — สงสัยโดน IP block ({_now_bkk()})"
        if ip_block else
        f"{'✅' if overall_ok else '⚠️'} TPIS LandsMaps — {_now_bkk()} | "
        f"{found:,} matched | {area_na:,} ห้องชุด"
    )

    block_banner = ""
    if ip_block:
        block_banner = f"""
        <div style="margin-top:16px;padding:12px 16px;background:#fee2e2;
                    border-left:4px solid #dc2626;border-radius:4px;font-size:13px">
          <strong>🚫 หยุดกลางคัน — สงสัยโดน IP block</strong><br>
          not_found ติดกันหลายรายการแล้วเช็คซ้ำกับ parcel ที่เคยดึงสำเร็จมาก่อน
          (canary) ก็ not_found ด้วย — เข้าข่าย Incapsula soft-block (คืนผลว่าง
          เงียบๆ ไม่ขึ้น challenge page)<br>
          ประมวลผลไปแล้ว <strong>{stopped_at:,}/{total:,}</strong> asset ก่อนหยุด
          (asset_id ที่ทำค้างไว้: {stopped_asset}) — asset ที่เหลือจะถูก retry
          อัตโนมัติในรอบถัดไป ไม่ต้องทำอะไรเพิ่ม<br>
          <small style="color:#7f1d1d">แนะนำพัก ~24 ชม. หรือเปลี่ยนเครือข่าย/IP ก่อนรันซ้ำ</small>
        </div>"""

    html = f"""
    <div style="font-family:sans-serif;max-width:600px">
      <h2 style="color:{'#dc2626' if ip_block else ('#16a34a' if overall_ok else '#f59e0b')}">
        {'🚫' if ip_block else _status_icon(overall_ok)} TPIS LandsMaps Collector
      </h2>
      {block_banner}

      <table style="width:100%;border-collapse:collapse;font-size:14px">
        <tr style="background:#f3f4f6">
          <td style="padding:6px 10px"><strong>เวลา</strong></td>
          <td style="padding:6px 10px">{_now_bkk()} (Bangkok)</td>
        </tr>
        <tr>
          <td style="padding:6px 10px"><strong>Asset ที่ประมวลผล</strong></td>
          <td style="padding:6px 10px">{total:,} รายการ</td>
        </tr>
        <tr style="background:#f3f4f6">
          <td style="padding:6px 10px"><strong>✅ Matched</strong></td>
          <td style="padding:6px 10px">{area_match:,} รายการ</td>
        </tr>
        <tr>
          <td style="padding:6px 10px"><strong>⚠️ Mismatch</strong></td>
          <td style="padding:6px 10px">
            <span style="color:{'#dc2626' if area_mismatch > 0 else 'inherit'}">
              {area_mismatch:,} รายการ
            </span>
          </td>
        </tr>
        <tr style="background:#f3f4f6">
          <td style="padding:6px 10px"><strong>🏢 ห้องชุด (not verified)</strong></td>
          <td style="padding:6px 10px">{area_na:,} รายการ</td>
        </tr>
        <tr>
          <td style="padding:6px 10px"><strong>❌ Not found</strong></td>
          <td style="padding:6px 10px">{not_found:,} รายการ</td>
        </tr>
        <tr style="background:#f3f4f6">
          <td style="padding:6px 10px"><strong>💾 Cache hit</strong></td>
          <td style="padding:6px 10px">{cache_hit:,} รายการ (ไม่ต้องยิง API ซ้ำ)</td>
        </tr>
        <tr>
          <td style="padding:6px 10px"><strong>🔴 Errors</strong></td>
          <td style="padding:6px 10px">
            <span style="color:{'#dc2626' if errors > 0 else '#16a34a'}">
              {errors}
            </span>
          </td>
        </tr>
      </table>

      <div style="margin-top:16px;padding:12px 16px;background:#fef3c7;
                  border-left:4px solid #f59e0b;border-radius:4px;font-size:13px">
        <strong>🍪 Cookies</strong><br>
        Cookies ที่ใช้ใน run นี้ถูกใช้แล้ว (อายุ ~1-1.5 ชม.)<br>
        ถ้าจะ run ครั้งหน้า: รัน <code>scripts/test_session.py</code>
        บนเครื่องตัวเองเพื่อ solve hCaptcha และได้ cookies ชุดใหม่
      </div>

      <p style="margin-top:24px;font-size:12px;color:#9ca3af">
        TPIS — Thailand Property Intelligence System
      </p>
    </div>
    """

    _send(subject, html)
