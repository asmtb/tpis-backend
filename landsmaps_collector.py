"""
TPIS - LandsMaps Collector v2
- ใช้ BANGKOK_AMPHUR.json (dol code ที่ถูกต้อง)
- cross-validate rai/ngan/wa ระหว่าง LED และ LandsMaps
- resume ได้ถ้า crash

Input:
    led_all_assets.json   — LED records ทั้งประเทศ
    Copy_as_cURL.txt      — cURL จาก landsmaps.dol.go.th
    BANGKOK_AMPHUR.json   — mapping เขตกรุงเทพ

Output:
    landsmaps_coordinates.json  — unique parcel cache
    progress.json               — resume checkpoint
    landsmaps_collector.log     — log

ติดตั้ง: pip install requests
"""

import json, re, sys, time
from pathlib import Path
from datetime import datetime
import requests

# ========== CONFIG ==========
LED_FILE      = "led_all_assets.json"
CURL_FILE     = "Copy_as_cURL.txt"
BKK_AMPH_FILE = "BANGKOK_AMPHUR.json"
COORD_FILE      = "landsmaps_coordinates.json"
PROGRESS_FILE   = "progress.json"
LOG_FILE        = "landsmaps_collector.log"
NOT_FOUND_FILE  = "landsmaps_not_found.jsonl"  # JSONL: 1 record ต่อบรรทัด

DELAY_SEC     = 0.5
RETRY_MAX     = 3
RETRY_DELAY   = 5
SAVE_EVERY    = 200
# ============================

BASE     = "https://landsmaps.dol.go.th"
API_BASE = f"{BASE}/apiService/LandsMaps"
JWT_EP   = f"{BASE}/apiService/JWT/GetJWTAccessToken"

# --- Tee logger ---
_log_f = open(LOG_FILE, "a", encoding="utf-8")
class Tee:
    def __init__(self, *s): self.streams = s
    def write(self, d):
        for s in self.streams: s.write(d); s.flush()
    def flush(self):
        for s in self.streams: s.flush()
sys.stdout = Tee(sys.__stdout__, _log_f)

def log(msg): print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
def sec(t):   print(f"\n{'='*60}\n  {t}\n{'='*60}")

# --- Not-found logger (append JSONL) ---
_nf_f = open(NOT_FOUND_FILE, "a", encoding="utf-8")

def log_not_found(reason: str, record: dict, cache_key: str = "", extra: dict = None):
    """
    บันทึก record ที่ดึงไม่ได้ลง JSONL file
    reason: "no_deedno" | "no_amphur" | "not_found" | "error"
    """
    entry = {
        "_reason":     reason,
        "_cache_key":  cache_key,
        "_timestamp":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if extra:
        entry.update({f"_{k}": v for k, v in extra.items()})
    entry["led"] = record   # เก็บ LED fields ทุกค่า
    _nf_f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    _nf_f.flush()


# -------------------------------------------------------
# Province code (จาก LandsMaps dropdown)
# -------------------------------------------------------
PROVINCE_CODE = {
    "กระบี่":"81","กรุงเทพมหานคร":"10","กาญจนบุรี":"71","กาฬสินธุ์":"46",
    "กำแพงเพชร":"62","ขอนแก่น":"40","จันทบุรี":"22","ฉะเชิงเทรา":"24",
    "ชลบุรี":"20","ชัยนาท":"18","ชัยภูมิ":"36","ชุมพร":"86",
    "เชียงราย":"57","เชียงใหม่":"50","ตรัง":"92","ตราด":"23",
    "ตาก":"63","นครนายก":"26","นครปฐม":"73","นครพนม":"48",
    "นครราชสีมา":"30","นครศรีธรรมราช":"80","นครสวรรค์":"60","นนทบุรี":"12",
    "นราธิวาส":"96","น่าน":"55","บึงกาฬ":"38","บุรีรัมย์":"31",
    "ปทุมธานี":"13","ประจวบคีรีขันธ์":"77","ปราจีนบุรี":"25","ปัตตานี":"94",
    "พระนครศรีอยุธยา":"14","พะเยา":"56","พังงา":"82","พัทลุง":"93",
    "พิจิตร":"66","พิษณุโลก":"65","เพชรบุรี":"76","เพชรบูรณ์":"67",
    "แพร่":"54","ภูเก็ต":"83","มหาสารคาม":"44","มุกดาหาร":"49",
    "แม่ฮ่องสอน":"58","ยโสธร":"35","ยะลา":"95","ร้อยเอ็ด":"45",
    "ระนอง":"85","ระยอง":"21","ราชบุรี":"70","ลพบุรี":"16",
    "ลำปาง":"52","ลำพูน":"51","เลย":"42","ศรีสะเกษ":"33",
    "สกลนคร":"47","สงขลา":"90","สตูล":"91","สมุทรปราการ":"11",
    "สมุทรสงคราม":"75","สมุทรสาคร":"74","สระแก้ว":"27","สระบุรี":"19",
    "สิงห์บุรี":"17","สุโขทัย":"64","สุพรรณบุรี":"72","สุราษฎร์ธานี":"84",
    "สุรินทร์":"32","หนองคาย":"43","หนองบัวลำภู":"39","อ่างทอง":"15",
    "อำนาจเจริญ":"37","อุดรธานี":"41","อุตรดิตถ์":"53","อุทัยธานี":"61",
    "อุบลราชธานี":"34",
}

# --- โหลด Bangkok amphur mapping จากไฟล์ ---
BKK_AMPH_DOL = {}   # ชื่อเขต → dol code (ใช้กับ LandsMaps)
if Path(BKK_AMPH_FILE).exists():
    with open(BKK_AMPH_FILE, encoding="utf-8") as f:
        bkk_raw = json.load(f)
    for name, codes in bkk_raw.items():
        dol_code = codes.get("dol", "")
        # ใช้เฉพาะที่เป็นตัวเลข 2 หลัก (ข้ามพวก ก1, ช1, ฯลฯ)
        if re.match(r'^\d{2}$', dol_code):
            BKK_AMPH_DOL[name] = dol_code
    log(f"โหลด BANGKOK_AMPHUR.json: {len(BKK_AMPH_DOL)} เขต (dol code)")


def clean_amphur(name: str) -> str:
    """ตัดวงเล็บและข้อความพิเศษออก เช่น 'ดุสิต(บางซื่อ)' → 'ดุสิต'"""
    name = name.strip()
    name = re.sub(r'\s*[\(\（][^\)\）]*[\)\）]', '', name)  # ตัดวงเล็บ
    name = re.sub(r'\s*,.*$', '', name)                      # ตัดหลังจุลภาค
    return name.strip()


# amphur cache สำหรับจังหวัดอื่น
_amphur_cache = {}

def get_amph2(session, provid: str, amphur_name: str) -> str | None:
    """แปลงชื่ออำเภอ → dol code 2 หลัก"""
    cleaned = clean_amphur(amphur_name)

    if provid == "10":
        # ลอง exact match ก่อน
        code = BKK_AMPH_DOL.get(cleaned)
        if code:
            return code
        # ลอง partial match (กรณีชื่อสะกดต่างกันเล็กน้อย)
        for k, v in BKK_AMPH_DOL.items():
            if cleaned in k or k in cleaned:
                return v
        return None

    # จังหวัดอื่น: ดึงจาก API แล้ว cache
    if provid not in _amphur_cache:
        try:
            r = session.get(
                f"{BASE}/apiService/Master/GetAmphoe/{provid}", timeout=10
            )
            r.encoding = "utf-8"
            cache = {}
            if r.status_code == 200 and "_Incapsula" not in r.text:
                data = r.json()
                items = data.get("result", []) if isinstance(data, dict) else data
                for a in (items if isinstance(items, list) else []):
                    n = (a.get("amphur_name_th") or a.get("amphurname") or
                         a.get("name_th") or a.get("name") or "")
                    c = (a.get("amphur_id") or a.get("amphurid") or
                         a.get("id") or a.get("code") or "")
                    if n and c:
                        cache[n] = str(c).zfill(4)[-2:]
            _amphur_cache[provid] = cache
        except Exception:
            _amphur_cache[provid] = {}
        time.sleep(0.3)

    cache = _amphur_cache.get(provid, {})
    code = cache.get(cleaned)
    if not code:
        for k, v in cache.items():
            if cleaned in k or k in cleaned:
                return v
    return code


def refresh_jwt(session) -> bool:
    try:
        r = session.get(JWT_EP, timeout=15)
        r.encoding = "utf-8"
        if "_Incapsula" in r.text:
            return False
        m = re.search(r'"access_token"\s*:\s*"(eyJ[^"]+)"', r.text)
        if m:
            session.headers["Authorization"] = f"Bearer {m.group(1)}"
            return True
    except Exception:
        pass
    return False


def fetch_parcel(session, provid, amph2, deedno):
    url = f"{API_BASE}/GetParcelByParcelNo/{provid}/{amph2}/{deedno}"
    for attempt in range(1, RETRY_MAX + 1):
        try:
            r = session.get(url, timeout=15)
            r.encoding = "utf-8"
            if "_Incapsula" in r.text:
                log("  ⚠️  Imperva — refresh JWT")
                if refresh_jwt(session):
                    time.sleep(2)
                    continue
                return None
            if r.status_code == 200:
                results = r.json().get("result", [])
                return results[0] if results else {}
        except Exception as e:
            if attempt < RETRY_MAX:
                time.sleep(RETRY_DELAY)
            else:
                log(f"  ❌ Error {provid}/{amph2}/{deedno}: {e}")
    return None


def parse_area(val):
    """แปลงค่า rai/ngan/wa เป็น float"""
    try:
        return float(str(val).replace(",", "").strip())
    except:
        return None


MAX_RANGE_SIZE = 200  # ถ้า range ใหญ่กว่านี้ถือว่าข้อมูลผิดปกติ


def _expand_range(start_str: str, end_str: str) -> list:
    """
    Expand range โดยรองรับ short range เช่น 26782-84 → 26782-26784
    Logic: ถ้า end มีหลักน้อยกว่า start → เติม prefix จาก start
    """
    start = int(start_str)
    end_s = end_str.strip()

    if len(end_s) < len(start_str):
        # short range: เอา prefix ของ start มาเติมหน้า end
        prefix = start_str[:len(start_str) - len(end_s)]
        end_full = prefix + end_s
        end = int(end_full)
        # ถ้า end < start หลังเติม prefix แสดงว่า prefix ผิด ลอง prefix สั้นกว่า
        if end < start:
            prefix = start_str[:len(start_str) - len(end_s) - 1]
            end_full = prefix + end_s
            end = int(end_full)
    else:
        end = int(end_s)

    if start > end:
        start, end = end, start

    size = end - start + 1
    if size <= MAX_RANGE_SIZE:
        return [str(n) for n in range(start, end + 1)]
    else:
        log(f"  ⚠️  deedno range ใหญ่เกิน ({size}): {start_str}-{end_str} — เก็บแค่ start/end")
        return [str(start), str(end)]


def parse_deedno(raw: str) -> list:
    """
    แปลง deedno string → list of deedno strings
    รองรับทุก format ที่พบใน LED data:

    ตัดทิ้ง:
      "3497ฯ"                   → ["3497"]
      "44774-44776 ฯลฯ"         → ["44774","44775","44776"]
      "36017 (เดิม 33596)"      → ["36017"]
      "39920 เดิม (119244)"     → ["39920"]
      "2502(บางส่วน)"           → ["2502"]
      "165479 (บ่อหน่วงน้ำร่วม)"→ ["165479"]
      "และ 252208"              → ["252208"]
      "ึ76761"                  → ["76761"]

    พิเศษ — เอาเลขใหม่:
      "57262 (ปัจจุบันคือ 105575)" → ["105575"]

    ตัวคั่นหลายแบบ:
      "21672 , 21673 , 41238"   → ["21672","21673","41238"]
      "16996.16997"             → ["16996","16997"]
      "203094และ203095"         → ["203094","203095"]
      "789 3795 3796 170600"    → ["789","3795","3796","170600"]

    Range ปกติ:
      "1569-1579"               → ["1569",..."1579"]
      "579 - 582"               → ["579","580","581","582"]

    Short range (ย่อหลักท้าย):
      "26782-84"                → ["26782","26783","26784"]
      "162082-3"                → ["162082","162083"]
      "1601-02"                 → ["1601","1602"]
      "106391-415"              → ["106391",..."106415"]
    """
    if not raw:
        return []

    s = raw.strip()

    # --- Step 1: handle "(ปัจจุบันคือ xxx)" → แทนด้วยเลขใหม่ก่อน ---
    s = re.sub(
        r'\d+\s*\(\s*ปัจจุบันคือ\s*(\d+)\s*\)',
        lambda m: m.group(1),
        s
    )

    # --- Step 2: ตัดวงเล็บที่เหลือทั้งหมด (เดิม, บางส่วน, ฯลฯ) ---
    s = re.sub(r'\s*\([^)]*\)', '', s)      # ตัด (...)
    s = re.sub(r'\s*เดิม\s*', ' ', s)       # ตัด "เดิม"

    # --- Step 3: ตัด ฯ, ฯลฯ ---
    s = re.sub(r'ฯลฯ|ฯ', '', s)

    # --- Step 4: ตัด "และ" ที่นำหน้าหรืออยู่ระหว่าง ---
    s = re.sub(r'และ', ',', s)

    # --- Step 5: ตัดตัวอักษรไทยและอักขระแปลกที่ไม่ใช่ตัวเลข/เครื่องหมาย ---
    # ลบ unicode ที่ไม่ใช่ 0-9, -, ,, ., space
    s = re.sub(r'[^\d\-,\.\s]', '', s)

    # --- Step 6: normalize ตัวคั่น → space และ , ---
    s = re.sub(r'[,\.]', ' ', s)   # แทน , และ . ด้วย space
    # normalize "579 - 582" → "579-582" (ตัด space รอบ - ระหว่างตัวเลข)
    s = re.sub(r'(\d)\s+-\s+(\d)', r'\1-\2', s)
    s = re.sub(r'\s+', ' ', s).strip()

    # --- Step 7: split tokens ---
    tokens = s.split(' ')

    results = []
    for token in tokens:
        token = token.strip()
        if not token:
            continue

        # range: ตัวเลข-ตัวเลข (รองรับ short range)
        range_match = re.match(r'^(\d+)\s*-\s*(\d+)$', token)
        if range_match:
            results.extend(_expand_range(range_match.group(1), range_match.group(2)))
        elif re.match(r'^\d+$', token):
            results.append(token)
        # token ที่ไม่ใช่ตัวเลขหรือ range ข้ามไป (ถูกกรองออกแล้วใน step 5)

    # --- Step 8: dedupe รักษา order ---
    seen = set()
    unique = []
    for d in results:
        if d not in seen:
            seen.add(d)
            unique.append(d)

    return unique




def validate_area(led: dict, lm: dict) -> dict:
    """
    เปรียบเทียบพื้นที่จาก LED กับ LandsMaps
    LED fields: rai, ngan, wa
    LandsMaps fields: rai, ngan, wa
    return: {"match": True/False, "diff": {...}}
    """
    led_rai    = parse_area(led.get("rai", 0))
    led_ngan   = parse_area(led.get("ngan", 0))
    led_wa     = parse_area(led.get("wa", 0))
    lm_rai     = parse_area(lm.get("rai", 0))
    lm_ngan    = parse_area(lm.get("ngan", 0))
    lm_wa      = parse_area(lm.get("wa", 0))

    match = (led_rai == lm_rai and led_ngan == lm_ngan and led_wa == lm_wa)
    return {
        "match": match,
        "led":   {"rai": led_rai, "ngan": led_ngan, "wa": led_wa},
        "lm":    {"rai": lm_rai,  "ngan": lm_ngan,  "wa": lm_wa},
    }


# -------------------------------------------------------
# MAIN
# -------------------------------------------------------
sec("TPIS - LandsMaps Collector v2")

# Init session
with open(CURL_FILE, encoding="utf-8") as f:
    curl_content = f.read()

COOKIES = {}
all_sets = re.findall(r"-b '([^']+)'", curl_content)
if all_sets:
    for part in all_sets[-1].split(';'):
        if '=' in part:
            k, v = part.strip().split('=', 1)
            COOKIES[k.strip()] = v.strip()

session = requests.Session()
session.headers.update({
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/149.0.0.0 Safari/537.36",
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "th-TH,th;q=0.9,en;q=0.8",
    "Referer":         f"{BASE}/",
    "Origin":          BASE,
})
for k, v in COOKIES.items():
    session.cookies.set(k, v, domain=".dol.go.th")

if not refresh_jwt(session):
    log("❌ ไม่ได้ JWT")
    sys.exit(1)
log("✅ JWT OK")

# โหลด LED
with open(LED_FILE, encoding="utf-8") as f:
    led_records = json.load(f)
log(f"LED records: {len(led_records):,}")

# โหลด cache
coord_cache = {}
if Path(COORD_FILE).exists():
    with open(COORD_FILE, encoding="utf-8") as f:
        coord_cache = json.load(f)
log(f"Coordinate cache: {len(coord_cache):,} parcels")

# โหลด progress
done_set = set()
if Path(PROGRESS_FILE).exists():
    with open(PROGRESS_FILE, encoding="utf-8") as f:
        prog = json.load(f)
    done_set = set(prog.get("done_indices", []))
log(f"Progress: {len(done_set):,} records ทำแล้ว")

# Stats
stats = {
    "total": len(led_records), "processed": 0,
    "found": 0, "not_found": 0, "cache_hit": 0,
    "no_deedno": 0, "no_amphur": 0, "errors": 0,
    "area_match": 0, "area_mismatch": 0,
}

sec(f"เริ่ม Collect ({len(led_records):,} records)")

for idx, record in enumerate(led_records):

    if idx in done_set:
        continue

    deedno_raw = (record.get("deedno") or "").strip()
    city       = (record.get("deedcity") or record.get("city") or "").strip()
    amphur     = (record.get("deedampur") or record.get("ampur") or "").strip()

    if not deedno_raw:
        stats["no_deedno"] += 1
        done_set.add(idx)
        log_not_found("no_deedno", record)
        continue

    provid = PROVINCE_CODE.get(city) or record.get("_province_id", "").strip()
    if not provid:
        stats["no_amphur"] += 1
        done_set.add(idx)
        log_not_found("no_province", record, extra={"city": city})
        continue

    amph2 = get_amph2(session, provid, amphur)
    if not amph2:
        stats["no_amphur"] += 1
        done_set.add(idx)
        log_not_found("no_amphur", record, extra={"city": city, "amphur": amphur, "provid": provid})
        continue

    # แยก deedno ออกเป็นหลายโฉนด (กรณี multi-deedno เช่น "1569-1579,1601,3497")
    deedno_list = parse_deedno(deedno_raw)

    record_found = False  # ถ้า deedno ใดๆ เจอข้อมูล ถือว่า record นี้ found

    for deedno in deedno_list:
        cache_key = f"{provid}_{amph2}_{deedno}"

        if cache_key in coord_cache:
            stats["cache_hit"] += 1
            record_found = True
            continue

        result = fetch_parcel(session, provid, amph2, deedno)
        stats["processed"] += 1

        if result is None:
            stats["errors"] += 1
            log_not_found("error", record, cache_key=cache_key,
                          extra={"provid": provid, "amph2": amph2, "deedno": deedno})
        elif result == {}:
            stats["not_found"] += 1
            coord_cache[cache_key] = None
            log_not_found("not_found", record, cache_key=cache_key,
                          extra={"provid": provid, "amph2": amph2, "deedno": deedno})
        else:
            record_found = True
            area_check = validate_area(record, result)
            if area_check["match"]:
                stats["area_match"] += 1
            else:
                stats["area_mismatch"] += 1

            coord_cache[cache_key] = {
                "parcellat":     result.get("parcellat"),
                "parcellon":     result.get("parcellon"),
                "utm":           result.get("utm"),
                "n":             result.get("n"),
                "e":             result.get("e"),
                "zone":          result.get("zone"),
                "landprice":     result.get("landprice"),
                "tumbolname":    result.get("tumbolname"),
                "amphurname":    result.get("amphurname"),
                "provname":      result.get("provname"),
                "landoffice":    result.get("landoffice"),
                "landoffice_id": result.get("landoffice_id"),
                "rai":           result.get("rai"),
                "ngan":          result.get("ngan"),
                "wa":            result.get("wa"),
                "parcel_type":   result.get("parcel_type"),
                "parcel_seq":    result.get("parcel_seq"),
                "lands_status":  result.get("lands_status"),
                "provid":        result.get("provid"),
                "amphurid":      result.get("amphurid"),
                "tambol_id":     result.get("tambol_id"),
                "qrcode_link":   result.get("qrcode_link"),
                "_area_match":   area_check["match"],
                "_area_led":     area_check["led"],
                "_area_lm":      area_check["lm"],
            }
            stats["found"] += 1

        time.sleep(DELAY_SEC)

    done_set.add(idx)


    if (stats["processed"] + stats["cache_hit"]) % SAVE_EVERY == 0:
        pct = (idx + 1) / stats["total"] * 100
        log(f"  [{idx+1:,}/{stats['total']:,}] {pct:.1f}% | "
            f"✅{stats['found']:,} ❌{stats['not_found']:,} "
            f"💾{stats['cache_hit']:,} ⚠️{stats['no_amphur']:,} "
            f"📐match={stats['area_match']:,}/mismatch={stats['area_mismatch']:,}")

        with open(COORD_FILE, "w", encoding="utf-8") as f:
            json.dump(coord_cache, f, ensure_ascii=False)
        with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump({"done_indices": list(done_set), "stats": stats}, f)

# Final save
with open(COORD_FILE, "w", encoding="utf-8") as f:
    json.dump(coord_cache, f, ensure_ascii=False, indent=2)
with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
    json.dump({"done_indices": list(done_set), "stats": stats}, f, indent=2)

sec("📊 สรุปผล")
log(f"  Total          : {stats['total']:,}")
log(f"  ✅ Found       : {stats['found']:,}")
log(f"  ❌ Not found   : {stats['not_found']:,}")
log(f"  💾 Cache hit   : {stats['cache_hit']:,}")
log(f"  ⚠️  No amphur  : {stats['no_amphur']:,}")
log(f"  🚫 No deedno   : {stats['no_deedno']:,}")
log(f"  🔴 Errors      : {stats['errors']:,}")
log(f"  Unique parcels : {len(coord_cache):,}")
log(f"  📐 Area match  : {stats['area_match']:,}")
log(f"  📐 Area mismatch: {stats['area_mismatch']:,}")

log(f"  📄 Not-found log: {NOT_FOUND_FILE}")

_nf_f.close()
_log_f.close()
sys.stdout = sys.__stdout__
print(f"\n✅ เสร็จสิ้น")
