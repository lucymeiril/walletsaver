"""
Mock 응답 데이터 — DB 연결 전까지 프론트엔드에 즉시 응답을 제공.

왜 존재하는가:
    프론트엔드 mockData.js와 완전히 동일한 shape을 반환하여,
    mock→real 전환 시 프론트엔드 코드 변경이 0줄이 되도록 보장한다.
어디서 쓰이는가:
    각 API 라우터에서 storage가 None일 때 이 데이터를 반환한다.
"""

# ===== Placeholder 이미지 헬퍼 (프론트엔드와 동일) =====
def _img(w: int, h: int, text: str, bg: str = "1e293b", fg: str = "94a3b8") -> str:
    from urllib.parse import quote
    return f"https://placehold.co/{w}x{h}/{bg}/{fg}?text={quote(text)}"


# ===== 상품 (물가비교) =====
MOCK_PRODUCTS = [
    {"id": 1,  "name": "양파",    "icon": "🧅", "cat": "채소류 > 근채류",   "unit": "1kg",  "avg": 2350,  "cur": 2380,  "low": 1980,  "high": 3200,  "img": _img(200, 200, "양파", "2d4a2d", "9ae89a"), "stores": {"emart": 2280, "homeplus": 2380, "lotte": 2490, "costco": 2190}, "stats": {"dataDays": 180, "records": 1247, "confidence": [1980, 2750], "outliers": 12, "avgDiscount": 22.4, "discFreq": 2.3}},
    {"id": 2,  "name": "삼겹살",  "icon": "🥩", "cat": "축산물 > 돼지고기", "unit": "100g", "avg": 1850,  "cur": 1680,  "low": 1100,  "high": 2400,  "img": _img(200, 200, "삼겹살", "4a2d2d", "e89a9a"), "stores": {"emart": 1680, "homeplus": 1790, "lotte": 1650, "costco": 1520}, "stats": {"dataDays": 180, "records": 1089, "confidence": [1200, 2500], "outliers": 8, "avgDiscount": 18.7, "discFreq": 1.8}},
    {"id": 3,  "name": "계란",    "icon": "🥚", "cat": "축산물 > 란류",     "unit": "30구", "avg": 6200,  "cur": 5980,  "low": 4980,  "high": 8900,  "img": _img(200, 200, "계란", "4a3d2d", "e8c99a"), "stores": {"emart": 5980, "homeplus": 6290, "lotte": 6100, "costco": 5490}, "stats": {"dataDays": 180, "records": 1320, "confidence": [4800, 7600], "outliers": 15, "avgDiscount": 15.3, "discFreq": 1.5}},
    {"id": 4,  "name": "사과",    "icon": "🍎", "cat": "과일류 > 사과",     "unit": "1kg",  "avg": 4800,  "cur": 5200,  "low": 3200,  "high": 7800,  "img": _img(200, 200, "사과", "4a2d32", "e89aaa"), "stores": {"emart": 5100, "homeplus": 5300, "lotte": 5200, "costco": 4800}, "stats": {"dataDays": 365, "records": 2150, "confidence": [3000, 6600], "outliers": 22, "avgDiscount": 20.1, "discFreq": 2.0}},
    {"id": 5,  "name": "우유",    "icon": "🥛", "cat": "유제품 > 우유",     "unit": "1L",   "avg": 2650,  "cur": 2590,  "low": 2200,  "high": 3100,  "img": _img(200, 200, "우유", "2d3a4a", "9ac0e8"), "stores": {"emart": 2590, "homeplus": 2680, "lotte": 2620, "costco": 2390}, "stats": {"dataDays": 180, "records": 980, "confidence": [2200, 3100], "outliers": 5, "avgDiscount": 12.8, "discFreq": 1.2}},
    {"id": 6,  "name": "쌀",      "icon": "🍚", "cat": "곡류 > 쌀",        "unit": "10kg", "avg": 28500, "cur": 27900, "low": 24000, "high": 35000, "img": _img(200, 200, "쌀", "3a3a2d", "c0c09a"), "stores": {"emart": 27900, "homeplus": 28200, "lotte": 28500, "costco": 26500}, "stats": {"dataDays": 365, "records": 890, "confidence": [24000, 33000], "outliers": 3, "avgDiscount": 8.5, "discFreq": 0.8}},
    {"id": 7,  "name": "배추",    "icon": "🥬", "cat": "채소류 > 엽경채류", "unit": "1포기", "avg": 3200, "cur": 2800,  "low": 1800,  "high": 5500,  "img": _img(200, 200, "배추", "2d4a35", "9ae8aa"), "stores": {"emart": 2800, "homeplus": 2950, "lotte": 2900, "costco": 2600}, "stats": {"dataDays": 365, "records": 1680, "confidence": [1500, 4900], "outliers": 18, "avgDiscount": 25.2, "discFreq": 2.5}},
    {"id": 8,  "name": "감자",    "icon": "🥔", "cat": "채소류 > 근채류",   "unit": "1kg",  "avg": 2800,  "cur": 3100,  "low": 2100,  "high": 4200,  "img": _img(200, 200, "감자", "3a3a2d", "c0c09a"), "stores": {"emart": 3100, "homeplus": 2900, "lotte": 3050, "costco": 2700}, "stats": {"dataDays": 180, "records": 1050, "confidence": [2100, 3500], "outliers": 7, "avgDiscount": 16.4, "discFreq": 1.6}},
    {"id": 9,  "name": "닭가슴살", "icon": "🍗", "cat": "축산물 > 닭고기",  "unit": "1kg",  "avg": 8500,  "cur": 7900,  "low": 6500,  "high": 11000, "img": _img(200, 200, "닭가슴살", "4a3d2d", "e8c99a"), "stores": {"emart": 7900, "homeplus": 8200, "lotte": 8000, "costco": 7200}, "stats": {"dataDays": 180, "records": 780, "confidence": [6500, 10500], "outliers": 6, "avgDiscount": 14.2, "discFreq": 1.3}},
    {"id": 10, "name": "두부",    "icon": "🧊", "cat": "가공식품 > 두부",   "unit": "1모",  "avg": 1800,  "cur": 1650,  "low": 1200,  "high": 2400,  "img": _img(200, 200, "두부", "2d3a4a", "9ac0e8"), "stores": {"emart": 1650, "homeplus": 1700, "lotte": 1650, "costco": 1500}, "stats": {"dataDays": 180, "records": 920, "confidence": [1200, 2400], "outliers": 4, "avgDiscount": 17.8, "discFreq": 2.1}},
    {"id": 11, "name": "식용유",  "icon": "🫒", "cat": "조미료 > 유지류",   "unit": "1.8L", "avg": 5800,  "cur": 5500,  "low": 4200,  "high": 7500,  "img": _img(200, 200, "식용유", "3a3a2d", "c0c09a"), "stores": {"emart": 5500, "homeplus": 5700, "lotte": 5600, "costco": 4900}, "stats": {"dataDays": 365, "records": 650, "confidence": [4200, 7400], "outliers": 3, "avgDiscount": 10.5, "discFreq": 0.9}},
    {"id": 12, "name": "라면",    "icon": "🍜", "cat": "가공식품 > 면류",   "unit": "5입",  "avg": 3900,  "cur": 3500,  "low": 2900,  "high": 4500,  "img": _img(200, 200, "라면", "4a2d2d", "e89a9a"), "stores": {"emart": 3500, "homeplus": 3600, "lotte": 3450, "costco": 3200}, "stats": {"dataDays": 180, "records": 1100, "confidence": [2900, 4900], "outliers": 9, "avgDiscount": 19.3, "discFreq": 2.2}},
]

# ===== 핫딜 =====
MOCK_HOTDEALS = [
    {"id": 1,  "title": "이마트 삼겹살 100g 1,100원 시작! 정기 할인 돌아왔어요", "source": "뽐뿌",      "price": 1100,   "origPrice": 1850,   "time": "3분 전",    "cat": "food",        "views": 342,  "comments": 28, "thumb": _img(320, 180, "삼겹살+할인", "4a2d2d", "e89a9a")},
    {"id": 2,  "title": "코스트코 양배추 1kg 5,190원 (정가 6,590원)",           "source": "어미새",     "price": 5190,   "origPrice": 6590,   "time": "12분 전",   "cat": "food",        "views": 156,  "comments": 8,  "thumb": _img(320, 180, "양배추", "2d4a2d", "9ae89a")},
    {"id": 3,  "title": "LG 울트라기어 27인치 QHD 모니터 역대최저 297,000원",   "source": "루리웹",     "price": 297000, "origPrice": 399000, "time": "25분 전",   "cat": "electronics", "views": 892,  "comments": 67, "thumb": _img(320, 180, "모니터", "2d2d4a", "9a9ae8")},
    {"id": 4,  "title": "무신사 봄 세일 최대 70% + 추가 15% 쿠폰",              "source": "에펨코리아", "price": None,   "origPrice": None,   "time": "38분 전",   "cat": "fashion",     "views": 445,  "comments": 23, "thumb": _img(320, 180, "무신사+세일", "4a2d4a", "e89ae8")},
    {"id": 5,  "title": "홈플러스 계란 30구 4,980원 (역대급 가격)",              "source": "뽐뿌",      "price": 4980,   "origPrice": 6200,   "time": "1시간 전",  "cat": "food",        "views": 1203, "comments": 89, "thumb": _img(320, 180, "계란+할인", "4a3d2d", "e8c99a")},
    {"id": 6,  "title": "다이슨 에어랩 리퍼 39만원 (정가 69만원)",               "source": "어미새",     "price": 390000, "origPrice": 690000, "time": "1시간 전",  "cat": "living",      "views": 2341, "comments": 156, "thumb": _img(320, 180, "다이슨", "3a3a3a", "c0c0c0")},
    {"id": 7,  "title": "에어팟 프로 2 USB-C 199,000원 (카드할인 적용)",         "source": "루리웹",     "price": 199000, "origPrice": 329000, "time": "2시간 전",  "cat": "electronics", "views": 1890, "comments": 98, "thumb": _img(320, 180, "에어팟+프로", "2d2d4a", "9a9ae8")},
    {"id": 8,  "title": "이마트 GAP 양파 1.5kg 2,480원 주간특가",               "source": "뽐뿌",      "price": 2480,   "origPrice": 3980,   "time": "2시간 전",  "cat": "food",        "views": 445,  "comments": 12, "thumb": _img(320, 180, "양파+특가", "2d4a2d", "9ae89a")},
    {"id": 9,  "title": "나이키 에어맥스 97 직구 89,000원 (관부가세 포함)",      "source": "에펨코리아", "price": 89000,  "origPrice": 179000, "time": "3시간 전",  "cat": "fashion",     "views": 678,  "comments": 34, "thumb": _img(320, 180, "나이키", "2d2d2d", "e8e8e8")},
    {"id": 10, "title": "GS25 도시락 1+1 행사 (3/14~3/20)",                     "source": "뽐뿌",      "price": None,   "origPrice": None,   "time": "3시간 전",  "cat": "food",        "views": 234,  "comments": 15, "thumb": _img(320, 180, "도시락+1+1", "4a3d2d", "e8c99a")},
    {"id": 11, "title": "쿠팡 롯데 우유 1L 2,190원 로켓배송",                    "source": "어미새",     "price": 2190,   "origPrice": 2650,   "time": "4시간 전",  "cat": "food",        "views": 567,  "comments": 19, "thumb": _img(320, 180, "우유", "2d3a4a", "9ac0e8")},
    {"id": 12, "title": "샤오미 로봇청소기 X10+ 최저가 갱신 449,000원",         "source": "루리웹",     "price": 449000, "origPrice": 699000, "time": "5시간 전",  "cat": "electronics", "views": 1234, "comments": 78, "thumb": _img(320, 180, "로봇청소기", "3a3a3a", "c0c0c0")},
    {"id": 13, "title": "햇반 210g 24입 18,900원 스마일결제",                    "source": "뽐뿌",      "price": 18900,  "origPrice": 28000,  "time": "6시간 전",  "cat": "food",        "views": 892,  "comments": 31, "thumb": _img(320, 180, "햇반", "4a3d2d", "e8c99a")},
    {"id": 14, "title": "탑텐 베이직 티셔츠 1+1 15,000원",                       "source": "에펨코리아", "price": 15000,  "origPrice": 30000,  "time": "7시간 전",  "cat": "fashion",     "views": 310,  "comments": 14, "thumb": _img(320, 180, "탑텐+1+1", "4a2d4a", "e89ae8")},
    {"id": 15, "title": "농협 안심한우 1등급 등심 500g 39,000원",                "source": "어미새",     "price": 39000,  "origPrice": 59000,  "time": "10시간 전", "cat": "food",        "views": 1024, "comments": 47, "thumb": _img(320, 180, "한우+등심", "4a2d2d", "e89a9a")},
    {"id": 16, "title": "에이블리 봄 원피스 모음전 최대 60% 할인",               "source": "무신사매거진", "price": None, "origPrice": None,   "time": "1시간 전",  "cat": "fashion",     "views": 892,  "comments": 42, "thumb": _img(320, 180, "원피스+세일", "4a2d4a", "e89ae8")},
    {"id": 17, "title": "W컨셉 디자이너 재킷 89,000원 (정가 199,000원)",        "source": "에펨코리아", "price": 89000,  "origPrice": 199000, "time": "2시간 전",  "cat": "fashion",     "views": 456,  "comments": 19, "thumb": _img(320, 180, "재킷", "3a2d3a", "c09ac0")},
    {"id": 18, "title": "지그재그 봄 데일리룩 ALL 50% (앱 전용)",                "source": "뽐뿌",      "price": None,   "origPrice": None,   "time": "3시간 전",  "cat": "fashion",     "views": 1230, "comments": 67, "thumb": _img(320, 180, "지그재그", "4a354a", "e8aae8")},
    {"id": 19, "title": "스파오 x 짱구 콜라보 맨투맨 19,900원",                 "source": "루리웹",     "price": 19900,  "origPrice": 39900,  "time": "5시간 전",  "cat": "fashion",     "views": 2100, "comments": 89, "thumb": _img(320, 180, "스파오+짱구", "4a4a2d", "e8e89a")},
    {"id": 20, "title": "아디다스 공식몰 아울렛 추가 30% 쿠폰 (주말 한정)",     "source": "에펨코리아", "price": None,   "origPrice": None,   "time": "8시간 전",  "cat": "fashion",     "views": 780,  "comments": 31, "thumb": _img(320, 180, "아디다스", "2d2d2d", "e8e8e8")},
]

# ===== 마트 전단 =====
MOCK_MART_DATA = {
    "emart": {
        "name": "이마트", "color": "#FFD700", "period": "3/14(목) ~ 3/20(수)",
        "flyerImg": _img(600, 800, "이마트+전단", "FFD700", "333"),
        "items": [
            {"name": "GAP 양파 1.5kg",   "orig": 3980,  "sale": 2480,  "disc": 38, "event": "주간특가", "img": _img(120, 120, "양파", "2d4a2d", "9ae89a")},
            {"name": "한우 등심 100g",     "orig": 8900,  "sale": 5900,  "disc": 34, "event": "축산대전", "img": _img(120, 120, "등심", "4a2d2d", "e89a9a")},
            {"name": "삼겹살 600g",        "orig": 14900, "sale": 9900,  "disc": 34, "event": "1+1",     "img": _img(120, 120, "삼겹살", "4a2d2d", "e89a9a")},
            {"name": "국내산 계란 30구",    "orig": 7980,  "sale": 5980,  "disc": 25, "event": "위크딜",  "img": _img(120, 120, "계란", "4a3d2d", "e8c99a")},
            {"name": "CJ 햇반 210g x12",  "orig": 12900, "sale": 8900,  "disc": 31, "event": "가공식품 SALE", "img": _img(120, 120, "햇반", "3a3a2d", "c0c09a")},
            {"name": "오뚜기 진라면 5P",    "orig": 4200,  "sale": 2900,  "disc": 31, "event": "라면번들", "img": _img(120, 120, "라면", "4a2d2d", "e89a9a")},
            {"name": "매일우유 1L",         "orig": 2990,  "sale": 2390,  "disc": 20, "event": "유제품 할인", "img": _img(120, 120, "우유", "2d3a4a", "9ac0e8")},
            {"name": "신선 딸기 500g",      "orig": 8900,  "sale": 6900,  "disc": 22, "event": "제철 과일", "img": _img(120, 120, "딸기", "4a2d32", "e89aaa")},
        ],
    },
    "homeplus": {
        "name": "홈플러스", "color": "#FF6B35", "period": "3/13(수) ~ 3/19(화)",
        "flyerImg": _img(600, 800, "홈플러스+전단", "FF6B35", "333"),
        "items": [
            {"name": "호주산 채끝 100g",    "orig": 5900, "sale": 3900, "disc": 34, "event": "수입육 할인", "img": _img(120, 120, "채끝", "4a2d2d", "e89a9a")},
            {"name": "풀무원 두부 2입",     "orig": 3800, "sale": 2500, "disc": 34, "event": "1+1",         "img": _img(120, 120, "두부", "2d3a4a", "9ac0e8")},
            {"name": "양배추 1통",          "orig": 4500, "sale": 2900, "disc": 36, "event": "야채도매",    "img": _img(120, 120, "양배추", "2d4a2d", "9ae89a")},
            {"name": "CJ 비비고 만두 1kg",  "orig": 9800, "sale": 6900, "disc": 30, "event": "냉동식품",    "img": _img(120, 120, "만두", "4a3d2d", "e8c99a")},
            {"name": "남양 맛있는우유 1L",   "orig": 2800, "sale": 1990, "disc": 29, "event": "유제품 해피위크", "img": _img(120, 120, "우유", "2d3a4a", "9ac0e8")},
            {"name": "국산 고등어 2마리",    "orig": 7900, "sale": 5900, "disc": 25, "event": "수산大전",    "img": _img(120, 120, "고등어", "2d4a4a", "9ae8e8")},
        ],
    },
    "lotte": {
        "name": "롯데마트", "color": "#E4002B", "period": "3/14(목) ~ 3/20(수)",
        "flyerImg": _img(600, 800, "롯데마트+전단", "E4002B", "fff"),
        "items": [
            {"name": "통삼겹 수육용 1kg",   "orig": 19900, "sale": 12900, "disc": 35, "event": "정육코너", "img": _img(120, 120, "삼겹살", "4a2d2d", "e89a9a")},
            {"name": "국내산 사과 5입",      "orig": 12900, "sale": 8900,  "disc": 31, "event": "과일 대전", "img": _img(120, 120, "사과", "4a2d32", "e89aaa")},
            {"name": "오리온 초코파이 24입", "orig": 8900,  "sale": 5900,  "disc": 34, "event": "과자번들", "img": _img(120, 120, "초코파이", "4a3d2d", "e8c99a")},
            {"name": "서울우유 1L 2입",      "orig": 5200,  "sale": 3900,  "disc": 25, "event": "2입 묶음",  "img": _img(120, 120, "우유", "2d3a4a", "9ac0e8")},
            {"name": "감자 3kg",             "orig": 9900,  "sale": 6900,  "disc": 30, "event": "알뜰장보기", "img": _img(120, 120, "감자", "3a3a2d", "c0c09a")},
        ],
    },
    "costco": {
        "name": "코스트코", "color": "#E31837", "period": "3/16(토) ~ 4/12(토)",
        "flyerImg": _img(600, 800, "코스트코+전단", "E31837", "fff"),
        "items": [
            {"name": "절단 양배추 1kg",       "orig": 6590,  "sale": 5190,  "disc": 21, "event": "코스트코 할인", "img": _img(120, 120, "양배추", "2d4a2d", "9ae89a")},
            {"name": "밤 1망 2kg",            "orig": 14990, "sale": 10490, "disc": 30, "event": "코스트코 할인", "img": _img(120, 120, "밤", "3a3a2d", "c0c09a")},
            {"name": "덴마크 유기농우유 2.3L", "orig": 8990,  "sale": 7290,  "disc": 19, "event": "코스트코 할인", "img": _img(120, 120, "유기농우유", "2d3a4a", "9ac0e8")},
            {"name": "스모크 소시지 793g",     "orig": 17890, "sale": 14390, "disc": 20, "event": "코스트코 할인", "img": _img(120, 120, "소시지", "4a2d2d", "e89a9a")},
            {"name": "킹크랩 다리 1.5kg",     "orig": 89900, "sale": 69900, "disc": 22, "event": "코스트코 할인", "img": _img(120, 120, "킹크랩", "4a2d32", "e89aaa")},
            {"name": "이롬 영양건강식 21포",   "orig": 24990, "sale": 19990, "disc": 20, "event": "코스트코 할인", "img": _img(120, 120, "건강식", "2d4a2d", "9ae89a")},
        ],
    },
}

# ===== 주유소 =====
MOCK_GAS_STATIONS = [
    {"name": "현대 셀프 강남점",    "addr": "강남구 역삼동 123",  "gasoline": 1598, "diesel": 1438, "lpg": 989,  "brand": "현대"},
    {"name": "SK 에너지 서초점",    "addr": "서초구 서초동 456",  "gasoline": 1612, "diesel": 1452, "lpg": 995,  "brand": "SK"},
    {"name": "GS 셀프 잠실점",      "addr": "송파구 잠실동 789",  "gasoline": 1605, "diesel": 1445, "lpg": 992,  "brand": "GS"},
    {"name": "S-OIL 방배점",        "addr": "서초구 방배동 234",  "gasoline": 1625, "diesel": 1468, "lpg": 1002, "brand": "S-OIL"},
    {"name": "알뜰 셀프 대치점",    "addr": "강남구 대치동 567",  "gasoline": 1578, "diesel": 1418, "lpg": 975,  "brand": "알뜰"},
    {"name": "현대 오일뱅크 삼성점", "addr": "강남구 삼성동 890",  "gasoline": 1632, "diesel": 1472, "lpg": None, "brand": "현대"},
    {"name": "SK 셀프 논현점",       "addr": "강남구 논현동 345",  "gasoline": 1589, "diesel": 1429, "lpg": 985,  "brand": "SK"},
    {"name": "알뜰 주유소 개포점",   "addr": "강남구 개포동 211",  "gasoline": 1570, "diesel": 1410, "lpg": 970,  "brand": "알뜰"},
]

# ===== 마트 목록 =====
MOCK_MARTS = [
    {"key": "emart",    "name": "이마트",   "color": "#FFD700"},
    {"key": "homeplus", "name": "홈플러스", "color": "#FF6B35"},
    {"key": "lotte",    "name": "롯데마트", "color": "#E4002B"},
    {"key": "costco",   "name": "코스트코", "color": "#E31837"},
]

# ===== 핫딜 필터 =====
MOCK_HOTDEAL_FILTERS = [
    {"key": "all", "label": "전체"},
    {"key": "food", "label": "식품"},
    {"key": "electronics", "label": "가전"},
    {"key": "living", "label": "생활"},
    {"key": "fashion", "label": "패션 👗"},
]


def mock_price_history(product_id: int, days: int = 30) -> list[dict]:
    """
    가격 히스토리 생성 — 프론트엔드 genPriceHistory()와 동일 로직.

    실제 DB 데이터가 없을 때 차트에 표시할 더미 데이터를 제공.
    """
    import math
    import random
    from datetime import datetime, timedelta

    product = next((p for p in MOCK_PRODUCTS if p["id"] == product_id), None)
    if not product:
        return []

    base = product["avg"]
    low = product["low"]
    high = product["high"]
    data = []

    for i in range(days, -1, -1):
        d = datetime.now() - timedelta(days=i)
        noise = (random.random() - 0.5) * (high - low) * 0.4
        seasonal = math.sin(i / 7 * math.pi) * (high - low) * 0.1
        price = round(base + noise + seasonal)
        price = max(low, min(high, price))
        data.append({"date": d.strftime("%m-%d"), "price": price})

    return data
