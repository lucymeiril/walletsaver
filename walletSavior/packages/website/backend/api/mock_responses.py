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
    {"id": 1,  "name": "양파",      "icon": "🧅", "cat": "채소류 > 근채류",     "unit": "1kg",   "avg": 2350,  "cur": 2380,  "low": 1980,  "high": 3200,  "price_tier": "wait",  "img": _img(200, 200, "양파", "2d4a2d", "9ae89a"), "stores": {"이마트": 2280, "홈플러스": 2380, "롯데마트": 2490, "코스트코": 2190}, "stats": {"dataDays": 180, "records": 1247, "confidence": [1980, 2750], "outliers": 12, "avgDiscount": 22.4, "discFreq": 2.3}},
    {"id": 2,  "name": "삼겹살",    "icon": "🥩", "cat": "축산물 > 돼지고기",   "unit": "100g",  "avg": 1850,  "cur": 1680,  "low": 1100,  "high": 2400,  "price_tier": "good",  "img": _img(200, 200, "삼겹살", "4a2d2d", "e89a9a"), "stores": {"이마트": 1680, "홈플러스": 1790, "롯데마트": 1650, "코스트코": 1520}, "stats": {"dataDays": 180, "records": 1089, "confidence": [1200, 2500], "outliers": 8, "avgDiscount": 18.7, "discFreq": 1.8}},
    {"id": 3,  "name": "계란",      "icon": "🥚", "cat": "축산물 > 란류",       "unit": "30구",  "avg": 6200,  "cur": 5980,  "low": 4980,  "high": 8900,  "price_tier": "good",  "img": _img(200, 200, "계란", "4a3d2d", "e8c99a"), "stores": {"이마트": 5980, "홈플러스": 6290, "롯데마트": 6100, "코스트코": 5490}, "stats": {"dataDays": 180, "records": 1320, "confidence": [4800, 7600], "outliers": 15, "avgDiscount": 15.3, "discFreq": 1.5}},
    {"id": 4,  "name": "사과",      "icon": "🍎", "cat": "과일류 > 사과",       "unit": "1kg",   "avg": 4800,  "cur": 5200,  "low": 3200,  "high": 7800,  "price_tier": "wait",  "img": _img(200, 200, "사과", "4a2d32", "e89aaa"), "stores": {"이마트": 5100, "홈플러스": 5300, "롯데마트": 5200, "코스트코": 4800}, "stats": {"dataDays": 365, "records": 2150, "confidence": [3000, 6600], "outliers": 22, "avgDiscount": 20.1, "discFreq": 2.0}},
    {"id": 5,  "name": "우유",      "icon": "🥛", "cat": "유제품 > 우유",       "unit": "1L",    "avg": 2650,  "cur": 2590,  "low": 2200,  "high": 3100,  "price_tier": "good",  "img": _img(200, 200, "우유", "2d3a4a", "9ac0e8"), "stores": {"이마트": 2590, "홈플러스": 2680, "롯데마트": 2620, "코스트코": 2390}, "stats": {"dataDays": 180, "records": 980, "confidence": [2200, 3100], "outliers": 5, "avgDiscount": 12.8, "discFreq": 1.2}},
    {"id": 6,  "name": "쌀",        "icon": "🍚", "cat": "곡류 > 쌀",           "unit": "10kg",  "avg": 28500, "cur": 27900, "low": 24000, "high": 35000, "price_tier": "good",  "img": _img(200, 200, "쌀", "3a3a2d", "c0c09a"), "stores": {"이마트": 27900, "홈플러스": 28200, "롯데마트": 28500, "코스트코": 26500}, "stats": {"dataDays": 365, "records": 890, "confidence": [24000, 33000], "outliers": 3, "avgDiscount": 8.5, "discFreq": 0.8}},
    {"id": 7,  "name": "배추",      "icon": "🥬", "cat": "채소류 > 엽경채류",   "unit": "1포기", "avg": 3200,  "cur": 2800,  "low": 1800,  "high": 5500,  "price_tier": "great", "img": _img(200, 200, "배추", "2d4a35", "9ae8aa"), "stores": {"이마트": 2800, "홈플러스": 2950, "롯데마트": 2900, "코스트코": 2600}, "stats": {"dataDays": 365, "records": 1680, "confidence": [1500, 4900], "outliers": 18, "avgDiscount": 25.2, "discFreq": 2.5}},
    {"id": 8,  "name": "감자",      "icon": "🥔", "cat": "채소류 > 근채류",     "unit": "1kg",   "avg": 2800,  "cur": 3100,  "low": 2100,  "high": 4200,  "price_tier": "wait",  "img": _img(200, 200, "감자", "3a3a2d", "c0c09a"), "stores": {"이마트": 3100, "홈플러스": 2900, "롯데마트": 3050, "코스트코": 2700}, "stats": {"dataDays": 180, "records": 1050, "confidence": [2100, 3500], "outliers": 7, "avgDiscount": 16.4, "discFreq": 1.6}},
    {"id": 9,  "name": "닭가슴살",  "icon": "🍗", "cat": "축산물 > 닭고기",     "unit": "1kg",   "avg": 8500,  "cur": 7900,  "low": 6500,  "high": 11000, "price_tier": "good",  "img": _img(200, 200, "닭가슴살", "4a3d2d", "e8c99a"), "stores": {"이마트": 7900, "홈플러스": 8200, "롯데마트": 8000, "코스트코": 7200}, "stats": {"dataDays": 180, "records": 780, "confidence": [6500, 10500], "outliers": 6, "avgDiscount": 14.2, "discFreq": 1.3}},
    {"id": 10, "name": "두부",      "icon": "🧊", "cat": "가공식품 > 두부",     "unit": "1모",   "avg": 1800,  "cur": 1650,  "low": 1200,  "high": 2400,  "price_tier": "great", "img": _img(200, 200, "두부", "2d3a4a", "9ac0e8"), "stores": {"이마트": 1650, "홈플러스": 1700, "롯데마트": 1650, "코스트코": 1500}, "stats": {"dataDays": 180, "records": 920, "confidence": [1200, 2400], "outliers": 4, "avgDiscount": 17.8, "discFreq": 2.1}},
    {"id": 11, "name": "식용유",    "icon": "🫒", "cat": "조미료 > 유지류",     "unit": "1.8L",  "avg": 5800,  "cur": 5500,  "low": 4200,  "high": 7500,  "price_tier": "good",  "img": _img(200, 200, "식용유", "3a3a2d", "c0c09a"), "stores": {"이마트": 5500, "홈플러스": 5700, "롯데마트": 5600, "코스트코": 4900}, "stats": {"dataDays": 365, "records": 650, "confidence": [4200, 7400], "outliers": 3, "avgDiscount": 10.5, "discFreq": 0.9}},
    {"id": 12, "name": "라면",      "icon": "🍜", "cat": "가공식품 > 면류",     "unit": "5입",   "avg": 3900,  "cur": 3500,  "low": 2900,  "high": 4500,  "price_tier": "great", "img": _img(200, 200, "라면", "4a2d2d", "e89a9a"), "stores": {"이마트": 3500, "홈플러스": 3600, "롯데마트": 3450, "코스트코": 3200}, "stats": {"dataDays": 180, "records": 1100, "confidence": [2900, 4900], "outliers": 9, "avgDiscount": 19.3, "discFreq": 2.2}},
    {"id": 13, "name": "고구마",    "icon": "🍠", "cat": "채소류 > 근채류",     "unit": "1kg",   "avg": 3500,  "cur": 3200,  "low": 2500,  "high": 5000,  "price_tier": "good",  "img": _img(200, 200, "고구마", "4a3d2d", "e8c99a"), "stores": {"이마트": 3200, "홈플러스": 3400, "롯데마트": 3300, "코스트코": 2900}, "stats": {"dataDays": 180, "records": 850, "confidence": [2500, 4500], "outliers": 5, "avgDiscount": 15.0, "discFreq": 1.5}},
    {"id": 14, "name": "돼지목살",  "icon": "🥩", "cat": "축산물 > 돼지고기",   "unit": "100g",  "avg": 1650,  "cur": 1550,  "low": 1000,  "high": 2200,  "price_tier": "good",  "img": _img(200, 200, "돼지목살", "4a2d2d", "e89a9a"), "stores": {"이마트": 1550, "홈플러스": 1600, "롯데마트": 1580, "코스트코": 1400}, "stats": {"dataDays": 180, "records": 920, "confidence": [1000, 2100], "outliers": 6, "avgDiscount": 16.2, "discFreq": 1.7}},
    {"id": 15, "name": "참치캔",    "icon": "🐟", "cat": "가공식품 > 통조림",   "unit": "150g",  "avg": 2200,  "cur": 1980,  "low": 1500,  "high": 2800,  "price_tier": "great", "img": _img(200, 200, "참치캔", "2d4a4a", "9ae8e8"), "stores": {"이마트": 1980, "홈플러스": 2100, "롯데마트": 2050, "코스트코": 1800}, "stats": {"dataDays": 180, "records": 700, "confidence": [1500, 2600], "outliers": 4, "avgDiscount": 12.5, "discFreq": 1.3}},
    {"id": 16, "name": "바나나",    "icon": "🍌", "cat": "과일류 > 열대과일",   "unit": "1송이", "avg": 3200,  "cur": 2900,  "low": 2200,  "high": 4500,  "price_tier": "good",  "img": _img(200, 200, "바나나", "4a4a2d", "e8e89a"), "stores": {"이마트": 2900, "홈플러스": 3100, "롯데마트": 3000, "코스트코": 2700}, "stats": {"dataDays": 365, "records": 1100, "confidence": [2200, 4200], "outliers": 8, "avgDiscount": 13.5, "discFreq": 1.8}},
    {"id": 17, "name": "김치",      "icon": "🥬", "cat": "가공식품 > 김치",     "unit": "1kg",   "avg": 8500,  "cur": 7800,  "low": 5500,  "high": 12000, "price_tier": "good",  "img": _img(200, 200, "김치", "4a2d2d", "e89a9a"), "stores": {"이마트": 7800, "홈플러스": 8200, "롯데마트": 8000, "코스트코": 7200}, "stats": {"dataDays": 365, "records": 950, "confidence": [5500, 11000], "outliers": 7, "avgDiscount": 14.8, "discFreq": 1.2}},
    {"id": 18, "name": "콩나물",    "icon": "🌱", "cat": "채소류 > 콩나물",     "unit": "1봉",   "avg": 1200,  "cur": 1100,  "low": 800,   "high": 1800,  "price_tier": "good",  "img": _img(200, 200, "콩나물", "2d4a2d", "9ae89a"), "stores": {"이마트": 1100, "홈플러스": 1150, "롯데마트": 1100, "코스트코": 980},  "stats": {"dataDays": 180, "records": 600, "confidence": [800, 1600], "outliers": 3, "avgDiscount": 10.0, "discFreq": 1.0}},
    {"id": 19, "name": "소고기등심","icon": "🥩", "cat": "축산물 > 소고기",     "unit": "100g",  "avg": 8900,  "cur": 9200,  "low": 6500,  "high": 13000, "price_tier": "wait",  "img": _img(200, 200, "소고기등심", "4a2d2d", "e89a9a"), "stores": {"이마트": 9200, "홈플러스": 9500, "롯데마트": 9300, "코스트코": 8500}, "stats": {"dataDays": 365, "records": 1450, "confidence": [6500, 12000], "outliers": 10, "avgDiscount": 20.5, "discFreq": 1.5}},
    {"id": 20, "name": "딸기",      "icon": "🍓", "cat": "과일류 > 딸기",       "unit": "500g",  "avg": 7500,  "cur": 6900,  "low": 4500,  "high": 12000, "price_tier": "good",  "img": _img(200, 200, "딸기", "4a2d32", "e89aaa"), "stores": {"이마트": 6900, "홈플러스": 7200, "롯데마트": 7000, "코스트코": 6500}, "stats": {"dataDays": 180, "records": 680, "confidence": [4500, 10500], "outliers": 9, "avgDiscount": 18.0, "discFreq": 2.0}},
    {"id": 21, "name": "당근",      "icon": "🥕", "cat": "채소류 > 근채류",     "unit": "1kg",   "avg": 2900,  "cur": 2700,  "low": 2000,  "high": 4000,  "price_tier": "good",  "img": _img(200, 200, "당근", "4a3d2d", "e8c99a"), "stores": {"이마트": 2700, "홈플러스": 2850, "롯데마트": 2800, "코스트코": 2500}, "stats": {"dataDays": 180, "records": 750, "confidence": [2000, 3800], "outliers": 4, "avgDiscount": 14.0, "discFreq": 1.4}},
    {"id": 22, "name": "대파",      "icon": "🌿", "cat": "채소류 > 파류",       "unit": "1단",   "avg": 1800,  "cur": 1600,  "low": 1000,  "high": 3000,  "price_tier": "great", "img": _img(200, 200, "대파", "2d4a2d", "9ae89a"), "stores": {"이마트": 1600, "홈플러스": 1700, "롯데마트": 1650, "코스트코": 1400}, "stats": {"dataDays": 365, "records": 1200, "confidence": [1000, 2800], "outliers": 11, "avgDiscount": 20.0, "discFreq": 2.2}},
    {"id": 23, "name": "마늘",      "icon": "🧄", "cat": "채소류 > 양념채소",   "unit": "1kg",   "avg": 7800,  "cur": 7200,  "low": 5000,  "high": 11000, "price_tier": "good",  "img": _img(200, 200, "마늘", "3a3a2d", "c0c09a"), "stores": {"이마트": 7200, "홈플러스": 7500, "롯데마트": 7400, "코스트코": 6800}, "stats": {"dataDays": 365, "records": 880, "confidence": [5000, 10500], "outliers": 6, "avgDiscount": 12.0, "discFreq": 1.1}},
    {"id": 24, "name": "요거트",    "icon": "🥛", "cat": "유제품 > 발효유",     "unit": "450ml", "avg": 3200,  "cur": 2900,  "low": 2200,  "high": 4000,  "price_tier": "great", "img": _img(200, 200, "요거트", "2d3a4a", "9ac0e8"), "stores": {"이마트": 2900, "홈플러스": 3000, "롯데마트": 2950, "코스트코": 2600}, "stats": {"dataDays": 180, "records": 550, "confidence": [2200, 3800], "outliers": 3, "avgDiscount": 11.5, "discFreq": 1.3}},
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
    {"id": 1, "name": "현대 셀프 강남점",    "addr": "강남구 역삼동 123",  "lat": 37.5012, "lng": 127.0396, "gasoline": 1598, "diesel": 1438, "lpg": 989,  "brand": "현대",   "updated_at": "2025-03-30T10:00:00"},
    {"id": 2, "name": "SK 에너지 서초점",    "addr": "서초구 서초동 456",  "lat": 37.4837, "lng": 127.0070, "gasoline": 1612, "diesel": 1452, "lpg": 995,  "brand": "SK",     "updated_at": "2025-03-30T10:00:00"},
    {"id": 3, "name": "GS 셀프 잠실점",      "addr": "송파구 잠실동 789",  "lat": 37.5133, "lng": 127.1000, "gasoline": 1605, "diesel": 1445, "lpg": 992,  "brand": "GS",     "updated_at": "2025-03-30T10:00:00"},
    {"id": 4, "name": "S-OIL 방배점",        "addr": "서초구 방배동 234",  "lat": 37.4790, "lng": 126.9875, "gasoline": 1625, "diesel": 1468, "lpg": 1002, "brand": "S-OIL",  "updated_at": "2025-03-30T10:00:00"},
    {"id": 5, "name": "알뜰 셀프 대치점",    "addr": "강남구 대치동 567",  "lat": 37.4946, "lng": 127.0562, "gasoline": 1578, "diesel": 1418, "lpg": 975,  "brand": "알뜰",   "updated_at": "2025-03-30T10:00:00"},
    {"id": 6, "name": "현대 오일뱅크 삼성점", "addr": "강남구 삼성동 890",  "lat": 37.5087, "lng": 127.0632, "gasoline": 1632, "diesel": 1472, "lpg": None, "brand": "현대",   "updated_at": "2025-03-30T10:00:00"},
    {"id": 7, "name": "SK 셀프 논현점",       "addr": "강남구 논현동 345",  "lat": 37.5100, "lng": 127.0300, "gasoline": 1589, "diesel": 1429, "lpg": 985,  "brand": "SK",     "updated_at": "2025-03-30T10:00:00"},
    {"id": 8, "name": "알뜰 주유소 개포점",   "addr": "강남구 개포동 211",  "lat": 37.4800, "lng": 127.0500, "gasoline": 1570, "diesel": 1410, "lpg": 970,  "brand": "알뜰",   "updated_at": "2025-03-30T10:00:00"},
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

# ===== 커뮤니티 게시글 =====
MOCK_POSTS = [
    {"id": 1, "title": "이마트 삼겹살 100g 1,100원! 역대급이네요", "content": "오늘 이마트에서 삼겹살이 100g에 1,100원이에요! 역대급 할인이라 공유합니다.", "post_type": "hotdeal", "category": "food", "author_id": 1, "author_nickname": "절약왕", "views": 342, "comments_count": 5, "hot_votes": 45, "not_votes": 3, "price": 1100, "original_price": 1850, "url": "https://emart.com/deal/1", "created_at": "2025-03-30T09:00:00", "updated_at": "2025-03-30T09:00:00"},
    {"id": 2, "title": "코스트코 양배추 꿀팁", "content": "코스트코 양배추가 요즘 진짜 저렴해요. 절단 양배추 1kg에 5,190원!", "post_type": "tip", "category": "food", "author_id": 2, "author_nickname": "장보기달인", "views": 156, "comments_count": 3, "hot_votes": 12, "not_votes": 1, "price": None, "original_price": None, "url": None, "created_at": "2025-03-30T08:30:00", "updated_at": "2025-03-30T08:30:00"},
    {"id": 3, "title": "LG 모니터 최저가 어디서 사야하나요?", "content": "LG 울트라기어 27인치 QHD 모니터 사려는데 어디가 가장 싼가요?", "post_type": "qna", "category": "electronics", "author_id": 3, "author_nickname": "IT덕후", "views": 89, "comments_count": 7, "hot_votes": 0, "not_votes": 0, "price": None, "original_price": None, "url": None, "created_at": "2025-03-29T22:00:00", "updated_at": "2025-03-29T22:00:00"},
    {"id": 4, "title": "다이슨 에어랩 리퍼 39만원 HOT", "content": "다이슨 에어랩 리퍼비쉬가 39만원! 정가 69만원인데 거의 반값이에요.", "post_type": "hotdeal", "category": "living", "author_id": 4, "author_nickname": "핫딜헌터", "views": 2341, "comments_count": 15, "hot_votes": 89, "not_votes": 5, "price": 390000, "original_price": 690000, "url": "https://shop.com/dyson", "created_at": "2025-03-29T18:00:00", "updated_at": "2025-03-29T18:00:00"},
    {"id": 5, "title": "장보기 절약 꿀팁 모음", "content": "1. 전단지 확인하기\n2. 마트 앱 쿠폰 활용\n3. 대용량 구매\n4. 제철 식재료 위주로", "post_type": "tip", "category": "food", "author_id": 1, "author_nickname": "절약왕", "views": 567, "comments_count": 12, "hot_votes": 34, "not_votes": 0, "price": None, "original_price": None, "url": None, "created_at": "2025-03-29T15:00:00", "updated_at": "2025-03-29T15:00:00"},
    {"id": 6, "title": "에어팟 프로 2 어디서 사면 좋을까요?", "content": "USB-C 에어팟 프로 2 사려고 하는데 쿠팡이 좋을까요 애플스토어가 좋을까요?", "post_type": "qna", "category": "electronics", "author_id": 5, "author_nickname": "애플러", "views": 234, "comments_count": 8, "hot_votes": 0, "not_votes": 0, "price": None, "original_price": None, "url": None, "created_at": "2025-03-29T12:00:00", "updated_at": "2025-03-29T12:00:00"},
    {"id": 7, "title": "홈플러스 유제품 할인 정보 공유", "content": "이번 주 홈플러스에서 유제품 해피위크 진행중! 우유 1L가 1,990원이에요.", "post_type": "free", "category": "food", "author_id": 2, "author_nickname": "장보기달인", "views": 178, "comments_count": 4, "hot_votes": 8, "not_votes": 0, "price": 1990, "original_price": 2800, "url": None, "created_at": "2025-03-28T20:00:00", "updated_at": "2025-03-28T20:00:00"},
    {"id": 8, "title": "나이키 에어맥스 97 직구 후기", "content": "89,000원에 직구했는데 관부가세 포함 가격이고 배송 1주일 걸렸어요. 품질 좋습니다!", "post_type": "free", "category": "fashion", "author_id": 6, "author_nickname": "패션피플", "views": 445, "comments_count": 6, "hot_votes": 15, "not_votes": 2, "price": 89000, "original_price": 179000, "url": None, "created_at": "2025-03-28T14:00:00", "updated_at": "2025-03-28T14:00:00"},
]

# ===== 커뮤니티 댓글 =====
MOCK_COMMENTS = {
    1: [
        {"id": 1, "content": "역시 이마트! 바로 가야겠어요", "author_id": 2, "author_nickname": "장보기달인", "parent_id": None, "created_at": "2025-03-30T09:10:00"},
        {"id": 2, "content": "어느 지점이에요?", "author_id": 3, "author_nickname": "IT덕후", "parent_id": None, "created_at": "2025-03-30T09:15:00"},
        {"id": 3, "content": "전 지점 공통이에요!", "author_id": 1, "author_nickname": "절약왕", "parent_id": 2, "created_at": "2025-03-30T09:20:00"},
        {"id": 4, "content": "정보 감사합니다~", "author_id": 4, "author_nickname": "핫딜헌터", "parent_id": None, "created_at": "2025-03-30T09:25:00"},
        {"id": 5, "content": "저도 다녀왔는데 진짜 싸더라고요", "author_id": 5, "author_nickname": "애플러", "parent_id": None, "created_at": "2025-03-30T09:30:00"},
    ],
    2: [
        {"id": 6, "content": "코스트코 회원이 부럽네요 ㅠ", "author_id": 3, "author_nickname": "IT덕후", "parent_id": None, "created_at": "2025-03-30T08:45:00"},
        {"id": 7, "content": "비회원도 상품권으로 구매 가능해요!", "author_id": 2, "author_nickname": "장보기달인", "parent_id": 6, "created_at": "2025-03-30T08:50:00"},
        {"id": 8, "content": "오 그런 방법이!", "author_id": 3, "author_nickname": "IT덕후", "parent_id": 7, "created_at": "2025-03-30T08:55:00"},
    ],
    4: [
        {"id": 9, "content": "리퍼라도 이 가격이면 미쳤다", "author_id": 1, "author_nickname": "절약왕", "parent_id": None, "created_at": "2025-03-29T18:10:00"},
        {"id": 10, "content": "AS 가능한가요?", "author_id": 6, "author_nickname": "패션피플", "parent_id": None, "created_at": "2025-03-29T18:20:00"},
    ],
}

# ===== 식당 =====
MOCK_RESTAURANTS = [
    {"id": 1, "name": "김밥천국 강남점",   "category": "분식",   "address": "강남구 역삼동 123-4", "lat": 37.5010, "lng": 127.0395, "avg_price": 6000,  "rating": 4.1, "review_count": 234},
    {"id": 2, "name": "맘스터치 서초점",   "category": "패스트푸드", "address": "서초구 서초동 456-7", "lat": 37.4840, "lng": 127.0075, "avg_price": 7500,  "rating": 4.0, "review_count": 178},
    {"id": 3, "name": "한솥 잠실점",       "category": "도시락", "address": "송파구 잠실동 789-1", "lat": 37.5135, "lng": 127.1005, "avg_price": 5500,  "rating": 3.8, "review_count": 156},
    {"id": 4, "name": "백종원의 원조쌈밥", "category": "한식",   "address": "서초구 방배동 234-5", "lat": 37.4795, "lng": 126.9880, "avg_price": 8500,  "rating": 4.3, "review_count": 312},
    {"id": 5, "name": "이디야커피 대치점", "category": "카페",   "address": "강남구 대치동 567-8", "lat": 37.4950, "lng": 127.0565, "avg_price": 4500,  "rating": 3.9, "review_count": 89},
    {"id": 6, "name": "역전우동 강남점",   "category": "일식",   "address": "강남구 삼성동 890-1", "lat": 37.5090, "lng": 127.0635, "avg_price": 7000,  "rating": 4.2, "review_count": 267},
    {"id": 7, "name": "맥도날드 논현점",   "category": "패스트푸드", "address": "강남구 논현동 345-6", "lat": 37.5105, "lng": 127.0305, "avg_price": 8000,  "rating": 3.7, "review_count": 445},
    {"id": 8, "name": "본죽 개포점",       "category": "한식",   "address": "강남구 개포동 211-2", "lat": 37.4805, "lng": 127.0505, "avg_price": 9000,  "rating": 4.4, "review_count": 198},
]

# ===== 레시피 가격 비교 =====
MOCK_RECIPE_COMPARE = [
    {
        "recipe_name": "김치찌개 (2인분)",
        "servings": 2,
        "cook_cost": 5200,
        "delivery_cost": 14000,
        "dine_out_cost": 16000,
        "savings_vs_delivery": 8800,
        "savings_vs_dine_out": 10800,
        "ingredients": [
            {"name": "돼지목살 200g", "price": 3300},
            {"name": "김치 300g", "price": 1200},
            {"name": "두부 1/2모", "price": 700},
        ],
    },
    {
        "recipe_name": "된장찌개 (2인분)",
        "servings": 2,
        "cook_cost": 3800,
        "delivery_cost": 13000,
        "dine_out_cost": 14000,
        "savings_vs_delivery": 9200,
        "savings_vs_dine_out": 10200,
        "ingredients": [
            {"name": "된장 2큰술", "price": 500},
            {"name": "두부 1/2모", "price": 700},
            {"name": "감자 1개", "price": 600},
            {"name": "양파 1/2개", "price": 400},
            {"name": "대파 1대", "price": 300},
            {"name": "애호박 1/4개", "price": 500},
            {"name": "고추 1개", "price": 300},
            {"name": "멸치육수", "price": 500},
        ],
    },
    {
        "recipe_name": "제육볶음 (2인분)",
        "servings": 2,
        "cook_cost": 7500,
        "delivery_cost": 18000,
        "dine_out_cost": 20000,
        "savings_vs_delivery": 10500,
        "savings_vs_dine_out": 12500,
        "ingredients": [
            {"name": "돼지목살 300g", "price": 4950},
            {"name": "양파 1개", "price": 800},
            {"name": "고추장 2큰술", "price": 600},
            {"name": "대파 1대", "price": 300},
            {"name": "고춧가루/간장/설탕", "price": 850},
        ],
    },
]

# ===== 사용자 즐겨찾기 (mock) =====
MOCK_FAVORITES = [
    {"id": 1, "product_id": 1, "product_name": "양파", "added_at": "2025-03-28T10:00:00"},
    {"id": 2, "product_id": 2, "product_name": "삼겹살", "added_at": "2025-03-28T11:00:00"},
    {"id": 3, "product_id": 5, "product_name": "우유", "added_at": "2025-03-29T09:00:00"},
]

# ===== 사용자 가격 알림 (mock) =====
MOCK_ALERTS = [
    {"id": 1, "product_id": 2, "product_name": "삼겹살", "target_price": 1500, "current_price": 1680, "status": "active", "created_at": "2025-03-28T10:00:00"},
    {"id": 2, "product_id": 4, "product_name": "사과", "target_price": 4000, "current_price": 5200, "status": "active", "created_at": "2025-03-29T09:00:00"},
]


def mock_price_history(product_id: int, days: int = 30) -> list[dict]:
    """가격 히스토리 생성 — 차트에 표시할 더미 데이터."""
    import math
    import random
    from datetime import datetime, timedelta

    product = next((p for p in MOCK_PRODUCTS if p["id"] == product_id), None)
    if not product:
        return []

    base = product["avg"]
    low = product["low"]
    high = product["high"]
    sources = ["이마트", "홈플러스", "롯데마트", "코스트코"]
    data = []

    for i in range(days, -1, -1):
        d = datetime.now() - timedelta(days=i)
        noise = (random.random() - 0.5) * (high - low) * 0.4
        seasonal = math.sin(i / 7 * math.pi) * (high - low) * 0.1
        price = round(base + noise + seasonal)
        price = max(low, min(high, price))
        data.append({
            "date": d.strftime("%Y-%m-%d"),
            "price": price,
            "source": sources[i % len(sources)],
        })

    return data
