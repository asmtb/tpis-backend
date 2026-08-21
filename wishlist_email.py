"""
wishlist_email.py — เทมเพลตอีเมลแจ้งเตือนนัดประมูลของทรัพย์ใน wishlist
ใช้ send_email() กลางจาก email_summary.py (Resend) ส่งหา user แต่ละคนตรงๆ
ต่างจาก send_led_summary()/send_landsmaps_summary() ที่ hardcode ส่งไป
NOTIFY_EMAIL (แอดมิน) คนเดียวเสมอ

สไตล์อีเมล (สี #0057B8, header/footer) ให้ตรงกับ template "Confirm signup"
ที่ตั้งไว้ใน Supabase Dashboard แล้ว เพื่อให้อีเมลทุกฉบับของ TPIS หน้าตา
สอดคล้องกัน
"""

from email_summary import send_email


def _fmt_location(asset: dict) -> str:
    parts = [p for p in (asset.get("tumbol"), asset.get("ampur"), asset.get("city")) if p]
    return " ".join(parts) or "-"


def send_wishlist_reminder(to_email: str, items: list[dict]) -> bool:
    """
    ส่งอีเมลแจ้งเตือนนัดประมูล — รวมทุกทรัพย์ที่ต้องแจ้งของ user คนนี้เป็น
    อีเมลเดียว (ไม่แยกส่งทีละทรัพย์ ตามที่ตัดสินใจไว้)

    items: list ของ
      {"asset": {...แถวจาก assets...}, "round_no": int,
       "bid_date": "YYYY-MM-DD", "days_left": int}
    """
    if not items:
        return True

    items = sorted(items, key=lambda x: x["days_left"])   # ใกล้สุดขึ้นก่อน

    rows_html = ""
    for it in items:
        asset = it["asset"]
        rows_html += f"""
        <tr>
          <td style="padding:10px 8px;border-bottom:1px solid #E2E8F0">
            <div style="font-weight:700;font-size:14px;color:#0F172A">
              {asset.get('str_bid_num') or '-'}
            </div>
            <div style="font-size:12px;color:#64748B;margin-top:2px">
              {asset.get('asset_type_desc') or ''} · {_fmt_location(asset)}
            </div>
          </td>
          <td style="padding:10px 8px;border-bottom:1px solid #E2E8F0;text-align:right;white-space:nowrap">
            <div style="font-weight:700;font-size:14px;color:#0057B8">
              อีก {it['days_left']} วัน
            </div>
            <div style="font-size:12px;color:#64748B;margin-top:2px">
              นัดที่ {it['round_no']} · {it['bid_date']}
            </div>
          </td>
        </tr>"""

    subject = f"⏰ แจ้งเตือนนัดประมูล {len(items)} รายการใน Wishlist — TPIS"

    html = f"""
    <div style="font-family: -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; max-width: 480px; margin: 0 auto; background: #ffffff;">

      <div style="padding: 32px 32px 24px; text-align: center; border-bottom: 3px solid #0057B8;">
        <div style="font-size: 22px; font-weight: 800; color: #0057B8;">TPIS</div>
        <div style="font-size: 12px; color: #64748B; margin-top: 2px;">Thailand Property Intelligence System</div>
      </div>

      <div style="padding: 28px 32px;">
        <h1 style="font-size: 18px; font-weight: 700; color: #0F172A; margin: 0 0 8px;">
          ⏰ ใกล้ถึงวันนัดประมูลแล้ว
        </h1>
        <p style="font-size: 13px; line-height: 1.7; color: #334155; margin: 0 0 20px;">
          ทรัพย์ในรายการที่คุณบันทึกไว้ ({len(items)} รายการ) กำลังจะถึงวันนัดประมูลเร็วๆ นี้
        </p>

        <table style="width:100%;border-collapse:collapse;font-size:13px">
          {rows_html}
        </table>

        <p style="font-size: 12px; color: #94A3B8; margin: 20px 0 0;">
          จัดการรายการที่บันทึกไว้และปรับความถี่การแจ้งเตือนได้ที่หน้า
          "จัดการบัญชี" บนเว็บ TPIS
        </p>
      </div>

      <div style="padding: 20px 32px; background: #F8FAFC; border-top: 1px solid #E2E8F0;">
        <p style="font-size: 11px; color: #94A3B8; margin: 0; text-align: center;">
          © TPIS — Thailand Property Intelligence System
        </p>
      </div>

    </div>
    """

    return send_email(to_email, subject, html)
