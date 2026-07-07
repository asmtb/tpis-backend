"""
config.py — TPIS LED Crawler Configuration
"""

# รายชื่อจังหวัดทั้ง 77 จังหวัด พร้อม province_id ที่ใช้ใน dropdown #provinces
# value มาจาก <option value="XX">จังหวัด</option> ใน form ค้นหา
PROVINCES = [
    {"id": "10",  "name": "กรุงเทพมหานคร",      "name_en": "bangkok"},
    {"id": "11",  "name": "สมุทรปราการ",          "name_en": "samut_prakan"},
    {"id": "12",  "name": "นนทบุรี",              "name_en": "nonthaburi"},
    {"id": "13",  "name": "ปทุมธานี",             "name_en": "pathum_thani"},
    {"id": "14",  "name": "พระนครศรีอยุธยา",      "name_en": "phra_nakhon_si_ayutthaya"},
    {"id": "15",  "name": "อ่างทอง",              "name_en": "ang_thong"},
    {"id": "16",  "name": "ลพบุรี",               "name_en": "lopburi"},
    {"id": "17",  "name": "สิงห์บุรี",            "name_en": "sing_buri"},
    {"id": "18",  "name": "ชัยนาท",               "name_en": "chai_nat"},
    {"id": "19",  "name": "สระบุรี",              "name_en": "saraburi"},
    {"id": "20",  "name": "ชลบุรี",               "name_en": "chonburi"},
    {"id": "21",  "name": "ระยอง",                "name_en": "rayong"},
    {"id": "22",  "name": "จันทบุรี",             "name_en": "chanthaburi"},
    {"id": "23",  "name": "ตราด",                 "name_en": "trat"},
    {"id": "24",  "name": "ฉะเชิงเทรา",           "name_en": "chachoengsao"},
    {"id": "25",  "name": "ปราจีนบุรี",           "name_en": "prachinburi"},
    {"id": "26",  "name": "นครนายก",              "name_en": "nakhon_nayok"},
    {"id": "27",  "name": "สระแก้ว",              "name_en": "sa_kaeo"},
    {"id": "30",  "name": "นครราชสีมา",           "name_en": "nakhon_ratchasima"},
    {"id": "31",  "name": "บุรีรัมย์",            "name_en": "buri_ram"},
    {"id": "32",  "name": "สุรินทร์",             "name_en": "surin"},
    {"id": "33",  "name": "ศรีสะเกษ",             "name_en": "si_sa_ket"},
    {"id": "34",  "name": "อุบลราชธานี",          "name_en": "ubon_ratchathani"},
    {"id": "35",  "name": "ยโสธร",                "name_en": "yasothon"},
    {"id": "36",  "name": "ชัยภูมิ",              "name_en": "chaiyaphum"},
    {"id": "37",  "name": "อำนาจเจริญ",           "name_en": "amnat_charoen"},
    {"id": "97",  "name": "บึงกาฬ",               "name_en": "bueng_kan"},   # dropdown value=97
    {"id": "39",  "name": "หนองบัวลำภู",          "name_en": "nong_bua_lam_phu"},
    {"id": "40",  "name": "ขอนแก่น",              "name_en": "khon_kaen"},
    {"id": "41",  "name": "อุดรธานี",             "name_en": "udon_thani"},
    {"id": "42",  "name": "เลย",                  "name_en": "loei"},
    {"id": "43",  "name": "หนองคาย",              "name_en": "nong_khai"},
    {"id": "44",  "name": "มหาสารคาม",            "name_en": "maha_sarakham"},
    {"id": "45",  "name": "ร้อยเอ็ด",             "name_en": "roi_et"},
    {"id": "46",  "name": "กาฬสินธุ์",            "name_en": "kalasin"},
    {"id": "47",  "name": "สกลนคร",               "name_en": "sakon_nakhon"},
    {"id": "48",  "name": "นครพนม",               "name_en": "nakhon_phanom"},
    {"id": "49",  "name": "มุกดาหาร",             "name_en": "mukdahan"},
    {"id": "50",  "name": "เชียงใหม่",            "name_en": "chiang_mai"},
    {"id": "51",  "name": "ลำพูน",                "name_en": "lamphun"},
    {"id": "52",  "name": "ลำปาง",                "name_en": "lampang"},
    {"id": "53",  "name": "อุตรดิตถ์",            "name_en": "uttaradit"},
    {"id": "54",  "name": "แพร่",                 "name_en": "phrae"},
    {"id": "55",  "name": "น่าน",                 "name_en": "nan"},
    {"id": "56",  "name": "พะเยา",                "name_en": "phayao"},
    {"id": "57",  "name": "เชียงราย",             "name_en": "chiang_rai"},
    {"id": "58",  "name": "แม่ฮ่องสอน",           "name_en": "mae_hong_son"},
    {"id": "60",  "name": "นครสวรรค์",            "name_en": "nakhon_sawan"},
    {"id": "61",  "name": "อุทัยธานี",            "name_en": "uthai_thani"},
    {"id": "62",  "name": "กำแพงเพชร",            "name_en": "kamphaeng_phet"},
    {"id": "63",  "name": "ตาก",                  "name_en": "tak"},
    {"id": "64",  "name": "สุโขทัย",              "name_en": "sukhothai"},
    {"id": "65",  "name": "พิษณุโลก",             "name_en": "phitsanulok"},
    {"id": "66",  "name": "พิจิตร",               "name_en": "phichit"},
    {"id": "67",  "name": "เพชรบูรณ์",            "name_en": "phetchabun"},
    {"id": "70",  "name": "ราชบุรี",              "name_en": "ratchaburi"},
    {"id": "71",  "name": "กาญจนบุรี",            "name_en": "kanchanaburi"},
    {"id": "72",  "name": "สุพรรณบุรี",           "name_en": "suphan_buri"},
    {"id": "73",  "name": "นครปฐม",               "name_en": "nakhon_pathom"},
    {"id": "74",  "name": "สมุทรสาคร",            "name_en": "samut_sakhon"},
    {"id": "75",  "name": "สมุทรสงคราม",          "name_en": "samut_songkhram"},
    {"id": "76",  "name": "เพชรบุรี",             "name_en": "phetchaburi"},
    {"id": "77",  "name": "ประจวบคีรีขันธ์",      "name_en": "prachuap_khiri_khan"},
    {"id": "80",  "name": "นครศรีธรรมราช",        "name_en": "nakhon_si_thammarat"},
    {"id": "81",  "name": "กระบี่",               "name_en": "krabi"},
    {"id": "82",  "name": "พังงา",                "name_en": "phang_nga"},
    {"id": "83",  "name": "ภูเก็ต",               "name_en": "phuket"},
    {"id": "84",  "name": "สุราษฎร์ธานี",         "name_en": "surat_thani"},
    {"id": "85",  "name": "ระนอง",                "name_en": "ranong"},
    {"id": "86",  "name": "ชุมพร",                "name_en": "chumphon"},
    {"id": "90",  "name": "สงขลา",                "name_en": "songkhla"},
    {"id": "91",  "name": "สตูล",                 "name_en": "satun"},
    {"id": "92",  "name": "ตรัง",                 "name_en": "trang"},
    {"id": "93",  "name": "พัทลุง",               "name_en": "phatthalung"},
    {"id": "94",  "name": "ปัตตานี",              "name_en": "pattani"},
    {"id": "95",  "name": "ยะลา",                 "name_en": "yala"},
    {"id": "96",  "name": "นราธิวาส",             "name_en": "narathiwat"},
]

TARGET_URL = "https://asset.led.go.th/newbidreg/"
POST_URL   = "https://asset.led.go.th/newbidreg/default.asp"

# Delay ระหว่าง request (วินาที) — ปรับได้
DELAY_BETWEEN_PAGES     = 0.7
DELAY_BETWEEN_PROVINCES = 3.0

# จำนวนครั้งที่ retry ถ้า request ล้มเหลว
MAX_RETRIES = 3

# Session expire detection: ถ้า response ไม่มี <form name="web หมายความว่า session หมด
SESSION_CHECK_STRING = '<form action="default.asp"'

OUTPUT_DIR = "led_output"  # โฟลเดอร์เก็บ JSON และ log