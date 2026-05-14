"""
시드 데이터 — DB 초기 카테고리 + 품목 + 샘플 가격 + 키워드 투입.

왜 존재하는가:
    DB를 초기화한 뒤 빈 테이블만 있으면 API가 빈 배열만 반환한다.
    KAMIS 기반 농산물 카테고리 + 12개 핵심 품목 + 100개 이상 키워드를 넣어서
    DB 연결 직후부터 의미 있는 데이터가 표시되도록 한다.
어디서 쓰이는가:
    py -c "from storage.seed import seed_all; seed_all()"
    또는 main.py의 init-db 명령에서 호출.
"""

import random
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

import logging

logger = logging.getLogger("seed")

from storage.models import (
    Base, Category, Product, BaselinePrice, DiscountHistory,
    HotdealPrice, GasStation, Keyword,
)


# ═══════════════════════════════════════════════
# 카테고리 트리 (KAMIS 기반 + 비식품)
# ═══════════════════════════════════════════════

SEED_CATEGORIES = [
    # 축산물
    {"id": "meat", "name": "축산물", "parent_id": None, "depth": 0, "sort_order": 1, "icon": "🥩"},
    {"id": "meat.pork", "name": "돼지고기", "parent_id": "meat", "depth": 1, "sort_order": 1, "icon": "🐷"},
    {"id": "meat.pork.belly", "name": "삼겹살", "parent_id": "meat.pork", "depth": 2, "sort_order": 1, "icon": "🥓"},
    {"id": "meat.pork.neck", "name": "목살", "parent_id": "meat.pork", "depth": 2, "sort_order": 2, "icon": "🥓"},
    {"id": "meat.pork.tenderloin", "name": "안심", "parent_id": "meat.pork", "depth": 2, "sort_order": 3, "icon": "🥓"},
    {"id": "meat.beef", "name": "소고기", "parent_id": "meat", "depth": 1, "sort_order": 2, "icon": "🐄"},
    {"id": "meat.beef.sirloin", "name": "등심", "parent_id": "meat.beef", "depth": 2, "sort_order": 1, "icon": "🥩"},
    {"id": "meat.beef.brisket", "name": "차돌박이", "parent_id": "meat.beef", "depth": 2, "sort_order": 2, "icon": "🥩"},
    {"id": "meat.chicken", "name": "닭고기", "parent_id": "meat", "depth": 1, "sort_order": 3, "icon": "🍗"},
    {"id": "meat.chicken.breast", "name": "닭가슴살", "parent_id": "meat.chicken", "depth": 2, "sort_order": 1, "icon": "🍗"},
    {"id": "meat.chicken.whole", "name": "통닭", "parent_id": "meat.chicken", "depth": 2, "sort_order": 2, "icon": "🍗"},
    {"id": "meat.egg", "name": "란류", "parent_id": "meat", "depth": 1, "sort_order": 4, "icon": "🥚"},

    # 수산물
    {"id": "seafood", "name": "수산물", "parent_id": None, "depth": 0, "sort_order": 2, "icon": "🐟"},
    {"id": "seafood.fish", "name": "생선", "parent_id": "seafood", "depth": 1, "sort_order": 1, "icon": "🐟"},
    {"id": "seafood.fish.salmon", "name": "연어", "parent_id": "seafood.fish", "depth": 2, "sort_order": 1, "icon": "🍣"},
    {"id": "seafood.fish.mackerel", "name": "고등어", "parent_id": "seafood.fish", "depth": 2, "sort_order": 2, "icon": "🐟"},
    {"id": "seafood.shellfish", "name": "패류", "parent_id": "seafood", "depth": 1, "sort_order": 2, "icon": "🦪"},
    {"id": "seafood.shellfish.shrimp", "name": "새우", "parent_id": "seafood.shellfish", "depth": 2, "sort_order": 1, "icon": "🦐"},
    {"id": "seafood.dried", "name": "건어물", "parent_id": "seafood", "depth": 1, "sort_order": 3, "icon": "🦑"},

    # 채소류
    {"id": "vegetable", "name": "채소류", "parent_id": None, "depth": 0, "sort_order": 3, "icon": "🥬"},
    {"id": "vegetable.root", "name": "근채류", "parent_id": "vegetable", "depth": 1, "sort_order": 1, "icon": "🥕"},
    {"id": "vegetable.root.potato", "name": "감자", "parent_id": "vegetable.root", "depth": 2, "sort_order": 1, "icon": "🥔"},
    {"id": "vegetable.root.onion", "name": "양파", "parent_id": "vegetable.root", "depth": 2, "sort_order": 2, "icon": "🧅"},
    {"id": "vegetable.root.carrot", "name": "당근", "parent_id": "vegetable.root", "depth": 2, "sort_order": 3, "icon": "🥕"},
    {"id": "vegetable.root.radish", "name": "무", "parent_id": "vegetable.root", "depth": 2, "sort_order": 4, "icon": "🥕"},
    {"id": "vegetable.leaf", "name": "엽경채류", "parent_id": "vegetable", "depth": 1, "sort_order": 2, "icon": "🥬"},
    {"id": "vegetable.leaf.cabbage", "name": "배추", "parent_id": "vegetable.leaf", "depth": 2, "sort_order": 1, "icon": "🥬"},
    {"id": "vegetable.leaf.lettuce", "name": "상추", "parent_id": "vegetable.leaf", "depth": 2, "sort_order": 2, "icon": "🥬"},
    {"id": "vegetable.leaf.spinach", "name": "시금치", "parent_id": "vegetable.leaf", "depth": 2, "sort_order": 3, "icon": "🥬"},
    {"id": "vegetable.fruit_veg", "name": "과채류", "parent_id": "vegetable", "depth": 1, "sort_order": 3, "icon": "🌶️"},
    {"id": "vegetable.fruit_veg.tomato", "name": "토마토", "parent_id": "vegetable.fruit_veg", "depth": 2, "sort_order": 1, "icon": "🍅"},
    {"id": "vegetable.fruit_veg.pepper", "name": "고추", "parent_id": "vegetable.fruit_veg", "depth": 2, "sort_order": 2, "icon": "🌶️"},
    {"id": "vegetable.fruit_veg.cucumber", "name": "오이", "parent_id": "vegetable.fruit_veg", "depth": 2, "sort_order": 3, "icon": "🥒"},
    {"id": "vegetable.mushroom", "name": "버섯류", "parent_id": "vegetable", "depth": 1, "sort_order": 4, "icon": "🍄"},

    # 과일류
    {"id": "fruit", "name": "과일류", "parent_id": None, "depth": 0, "sort_order": 4, "icon": "🍎"},
    {"id": "fruit.apple", "name": "사과", "parent_id": "fruit", "depth": 1, "sort_order": 1, "icon": "🍎"},
    {"id": "fruit.pear", "name": "배", "parent_id": "fruit", "depth": 1, "sort_order": 2, "icon": "🍐"},
    {"id": "fruit.grape", "name": "포도", "parent_id": "fruit", "depth": 1, "sort_order": 3, "icon": "🍇"},
    {"id": "fruit.watermelon", "name": "수박", "parent_id": "fruit", "depth": 1, "sort_order": 4, "icon": "🍉"},
    {"id": "fruit.strawberry", "name": "딸기", "parent_id": "fruit", "depth": 1, "sort_order": 5, "icon": "🍓"},
    {"id": "fruit.banana", "name": "바나나", "parent_id": "fruit", "depth": 1, "sort_order": 6, "icon": "🍌"},
    {"id": "fruit.tangerine", "name": "귤", "parent_id": "fruit", "depth": 1, "sort_order": 7, "icon": "🍊"},

    # 곡류
    {"id": "grain", "name": "곡류", "parent_id": None, "depth": 0, "sort_order": 5, "icon": "🌾"},
    {"id": "grain.rice", "name": "쌀", "parent_id": "grain", "depth": 1, "sort_order": 1, "icon": "🍚"},
    {"id": "grain.flour", "name": "밀가루", "parent_id": "grain", "depth": 1, "sort_order": 2, "icon": "🌾"},
    {"id": "grain.noodle", "name": "면류", "parent_id": "grain", "depth": 1, "sort_order": 3, "icon": "🍜"},

    # 유제품
    {"id": "dairy", "name": "유제품", "parent_id": None, "depth": 0, "sort_order": 6, "icon": "🥛"},
    {"id": "dairy.milk", "name": "우유", "parent_id": "dairy", "depth": 1, "sort_order": 1, "icon": "🥛"},
    {"id": "dairy.cheese", "name": "치즈", "parent_id": "dairy", "depth": 1, "sort_order": 2, "icon": "🧀"},
    {"id": "dairy.yogurt", "name": "요구르트", "parent_id": "dairy", "depth": 1, "sort_order": 3, "icon": "🥛"},

    # 가공식품
    {"id": "processed", "name": "가공식품", "parent_id": None, "depth": 0, "sort_order": 7, "icon": "🥫"},
    {"id": "processed.tofu", "name": "두부", "parent_id": "processed", "depth": 1, "sort_order": 1, "icon": "🧊"},
    {"id": "processed.ramen", "name": "라면", "parent_id": "processed", "depth": 1, "sort_order": 2, "icon": "🍜"},
    {"id": "processed.oil", "name": "식용유", "parent_id": "processed", "depth": 1, "sort_order": 3, "icon": "🫒"},
    {"id": "processed.sauce", "name": "소스/양념", "parent_id": "processed", "depth": 1, "sort_order": 4, "icon": "🧂"},
    {"id": "processed.snack", "name": "과자/스낵", "parent_id": "processed", "depth": 1, "sort_order": 5, "icon": "🍪"},

    # 비식품 — 의류
    {"id": "clothing", "name": "의류", "parent_id": None, "depth": 0, "sort_order": 10, "icon": "👕"},
    {"id": "clothing.men", "name": "남성복", "parent_id": "clothing", "depth": 1, "sort_order": 1, "icon": "👔"},
    {"id": "clothing.women", "name": "여성복", "parent_id": "clothing", "depth": 1, "sort_order": 2, "icon": "👗"},
    {"id": "clothing.shoes", "name": "신발", "parent_id": "clothing", "depth": 1, "sort_order": 3, "icon": "👟"},

    # 비식품 — 전자제품
    {"id": "electronics", "name": "전자제품", "parent_id": None, "depth": 0, "sort_order": 11, "icon": "📱"},
    {"id": "electronics.phone", "name": "스마트폰", "parent_id": "electronics", "depth": 1, "sort_order": 1, "icon": "📱"},
    {"id": "electronics.laptop", "name": "노트북", "parent_id": "electronics", "depth": 1, "sort_order": 2, "icon": "💻"},
    {"id": "electronics.audio", "name": "음향기기", "parent_id": "electronics", "depth": 1, "sort_order": 3, "icon": "🎧"},
    {"id": "electronics.monitor", "name": "모니터", "parent_id": "electronics", "depth": 1, "sort_order": 4, "icon": "🖥️"},

    # 비식품 — 주유
    {"id": "gas", "name": "주유", "parent_id": None, "depth": 0, "sort_order": 12, "icon": "⛽"},
    {"id": "gas.gasoline", "name": "휘발유", "parent_id": "gas", "depth": 1, "sort_order": 1, "icon": "⛽"},
    {"id": "gas.diesel", "name": "경유", "parent_id": "gas", "depth": 1, "sort_order": 2, "icon": "⛽"},
    {"id": "gas.lpg", "name": "LPG", "parent_id": "gas", "depth": 1, "sort_order": 3, "icon": "⛽"},

    # 비식품 — 배달
    {"id": "delivery", "name": "배달음식", "parent_id": None, "depth": 0, "sort_order": 13, "icon": "🛵"},
    {"id": "delivery.korean", "name": "한식", "parent_id": "delivery", "depth": 1, "sort_order": 1, "icon": "🍚"},
    {"id": "delivery.chicken", "name": "치킨", "parent_id": "delivery", "depth": 1, "sort_order": 2, "icon": "🍗"},
    {"id": "delivery.pizza", "name": "피자", "parent_id": "delivery", "depth": 1, "sort_order": 3, "icon": "🍕"},
    {"id": "delivery.chinese", "name": "중식", "parent_id": "delivery", "depth": 1, "sort_order": 4, "icon": "🥟"},
]


# ═══════════════════════════════════════════════
# 품목 마스터 데이터
# ═══════════════════════════════════════════════

SEED_PRODUCTS = [
    {"name": "양파",      "category_id": "vegetable.root.onion",  "unit": "1kg",   "avg": 2350,  "stores": {"emart": 2280, "homeplus": 2380, "lottemart": 2490, "costco": 2190}},
    {"name": "삼겹살",    "category_id": "meat.pork.belly",       "unit": "100g",  "avg": 1850,  "stores": {"emart": 1680, "homeplus": 1790, "lottemart": 1650, "costco": 1520}},
    {"name": "계란",      "category_id": "meat.egg",              "unit": "30구",  "avg": 6200,  "stores": {"emart": 5980, "homeplus": 6290, "lottemart": 6100, "costco": 5490}},
    {"name": "사과",      "category_id": "fruit.apple",           "unit": "1kg",   "avg": 4800,  "stores": {"emart": 5100, "homeplus": 5300, "lottemart": 5200, "costco": 4800}},
    {"name": "우유",      "category_id": "dairy.milk",            "unit": "1L",    "avg": 2650,  "stores": {"emart": 2590, "homeplus": 2680, "lottemart": 2620, "costco": 2390}},
    {"name": "쌀",        "category_id": "grain.rice",            "unit": "10kg",  "avg": 28500, "stores": {"emart": 27900, "homeplus": 28200, "lottemart": 28500, "costco": 26500}},
    {"name": "배추",      "category_id": "vegetable.leaf.cabbage","unit": "1포기", "avg": 3200,  "stores": {"emart": 2800, "homeplus": 2950, "lottemart": 2900, "costco": 2600}},
    {"name": "감자",      "category_id": "vegetable.root.potato", "unit": "1kg",   "avg": 2800,  "stores": {"emart": 3100, "homeplus": 2900, "lottemart": 3050, "costco": 2700}},
    {"name": "닭가슴살",  "category_id": "meat.chicken.breast",   "unit": "1kg",   "avg": 8500,  "stores": {"emart": 7900, "homeplus": 8200, "lottemart": 8000, "costco": 7200}},
    {"name": "두부",      "category_id": "processed.tofu",        "unit": "1모",   "avg": 1800,  "stores": {"emart": 1650, "homeplus": 1700, "lottemart": 1650, "costco": 1500}},
    {"name": "식용유",    "category_id": "processed.oil",         "unit": "1.8L",  "avg": 5800,  "stores": {"emart": 5500, "homeplus": 5700, "lottemart": 5600, "costco": 4900}},
    {"name": "라면",      "category_id": "processed.ramen",       "unit": "5입",   "avg": 3900,  "stores": {"emart": 3500, "homeplus": 3600, "lottemart": 3450, "costco": 3200}},
    {"name": "고등어",    "category_id": "seafood.fish.mackerel",  "unit": "1마리", "avg": 3500,  "stores": {"emart": 3200, "homeplus": 3400, "lottemart": 3300, "costco": 2900}},
    {"name": "연어",      "category_id": "seafood.fish.salmon",    "unit": "100g",  "avg": 3200,  "stores": {"emart": 3100, "homeplus": 3300, "lottemart": 3200, "costco": 2800}},
    {"name": "토마토",    "category_id": "vegetable.fruit_veg.tomato", "unit": "1kg", "avg": 4500, "stores": {"emart": 4200, "homeplus": 4500, "lottemart": 4400, "costco": 3900}},
    {"name": "바나나",    "category_id": "fruit.banana",           "unit": "1송이", "avg": 3800,  "stores": {"emart": 3500, "homeplus": 3700, "lottemart": 3600, "costco": 3200}},
]


# ═══════════════════════════════════════════════
# 주유소 데이터
# ═══════════════════════════════════════════════

SEED_GAS_STATIONS = [
    {"name": "현대 셀프 강남점",     "brand": "현대",  "address": "강남구 역삼동 123",    "lat": 37.500, "lng": 127.036, "gasoline": 1598, "diesel": 1438, "lpg": 989,  "is_self": True},
    {"name": "SK 에너지 서초점",     "brand": "SK",    "address": "서초구 서초동 456",    "lat": 37.492, "lng": 127.007, "gasoline": 1612, "diesel": 1452, "lpg": 995,  "is_self": False},
    {"name": "GS 셀프 잠실점",       "brand": "GS",    "address": "송파구 잠실동 789",    "lat": 37.514, "lng": 127.100, "gasoline": 1605, "diesel": 1445, "lpg": 992,  "is_self": True},
    {"name": "S-OIL 방배점",         "brand": "S-OIL", "address": "서초구 방배동 234",    "lat": 37.478, "lng": 126.988, "gasoline": 1625, "diesel": 1468, "lpg": 1002, "is_self": False},
    {"name": "알뜰 셀프 대치점",     "brand": "알뜰",  "address": "강남구 대치동 567",    "lat": 37.495, "lng": 127.062, "gasoline": 1578, "diesel": 1418, "lpg": 975,  "is_self": True},
    {"name": "현대 오일뱅크 삼성점", "brand": "현대",  "address": "강남구 삼성동 890",    "lat": 37.508, "lng": 127.060, "gasoline": 1632, "diesel": 1472, "lpg": None, "is_self": False},
    {"name": "SK 셀프 논현점",       "brand": "SK",    "address": "강남구 논현동 345",    "lat": 37.510, "lng": 127.030, "gasoline": 1589, "diesel": 1429, "lpg": 985,  "is_self": True},
    {"name": "알뜰 주유소 개포점",   "brand": "알뜰",  "address": "강남구 개포동 211",    "lat": 37.480, "lng": 127.050, "gasoline": 1570, "diesel": 1410, "lpg": 970,  "is_self": True},
]


# ═══════════════════════════════════════════════
# 자동완성 키워드 (100개 이상)
# ═══════════════════════════════════════════════

SEED_KEYWORDS = [
    # 축산물
    {"word": "삼겹살",   "synonyms": ["돼지고기", "삼겹", "목살"],          "category_id": "meat.pork.belly"},
    {"word": "돼지고기", "synonyms": ["삼겹살", "돈육", "포크"],            "category_id": "meat.pork"},
    {"word": "목살",     "synonyms": ["돼지목살", "돼지고기"],              "category_id": "meat.pork.neck"},
    {"word": "안심",     "synonyms": ["돼지안심", "안심살"],                "category_id": "meat.pork.tenderloin"},
    {"word": "소고기",   "synonyms": ["쇠고기", "한우", "소"],              "category_id": "meat.beef"},
    {"word": "등심",     "synonyms": ["소등심", "한우등심"],                "category_id": "meat.beef.sirloin"},
    {"word": "차돌박이", "synonyms": ["차돌", "소차돌"],                    "category_id": "meat.beef.brisket"},
    {"word": "닭고기",   "synonyms": ["치킨", "닭"],                       "category_id": "meat.chicken"},
    {"word": "닭가슴살", "synonyms": ["가슴살", "닭가슴"],                  "category_id": "meat.chicken.breast"},
    {"word": "통닭",     "synonyms": ["생닭", "전체닭"],                    "category_id": "meat.chicken.whole"},
    {"word": "계란",     "synonyms": ["달걀", "에그", "egg"],               "category_id": "meat.egg"},
    {"word": "달걀",     "synonyms": ["계란", "에그"],                      "category_id": "meat.egg"},

    # 수산물
    {"word": "연어",     "synonyms": ["새먼", "salmon", "생연어"],          "category_id": "seafood.fish.salmon"},
    {"word": "고등어",   "synonyms": ["고등어구이", "생고등어"],             "category_id": "seafood.fish.mackerel"},
    {"word": "새우",     "synonyms": ["쉬림프", "shrimp"],                  "category_id": "seafood.shellfish.shrimp"},
    {"word": "오징어",   "synonyms": ["squid", "건오징어"],                 "category_id": "seafood.dried"},
    {"word": "멸치",     "synonyms": ["마른멸치", "볶음멸치"],               "category_id": "seafood.dried"},
    {"word": "김",       "synonyms": ["김밥김", "조미김", "구운김"],         "category_id": "seafood.dried"},

    # 채소류
    {"word": "양파",     "synonyms": ["어니언", "onion"],                   "category_id": "vegetable.root.onion"},
    {"word": "감자",     "synonyms": ["potato", "감자채"],                  "category_id": "vegetable.root.potato"},
    {"word": "당근",     "synonyms": ["carrot"],                           "category_id": "vegetable.root.carrot"},
    {"word": "무",       "synonyms": ["무우", "단무지"],                    "category_id": "vegetable.root.radish"},
    {"word": "배추",     "synonyms": ["배추김치", "알배추"],                "category_id": "vegetable.leaf.cabbage"},
    {"word": "상추",     "synonyms": ["쌈채소", "lettuce"],                 "category_id": "vegetable.leaf.lettuce"},
    {"word": "시금치",   "synonyms": ["spinach"],                          "category_id": "vegetable.leaf.spinach"},
    {"word": "토마토",   "synonyms": ["tomato", "방울토마토"],              "category_id": "vegetable.fruit_veg.tomato"},
    {"word": "고추",     "synonyms": ["풋고추", "청양고추", "건고추"],       "category_id": "vegetable.fruit_veg.pepper"},
    {"word": "오이",     "synonyms": ["cucumber", "백오이"],                "category_id": "vegetable.fruit_veg.cucumber"},
    {"word": "파프리카", "synonyms": ["피망", "paprika"],                   "category_id": "vegetable.fruit_veg"},
    {"word": "마늘",     "synonyms": ["깐마늘", "다진마늘", "garlic"],      "category_id": "vegetable.root"},
    {"word": "생강",     "synonyms": ["ginger"],                           "category_id": "vegetable.root"},
    {"word": "대파",     "synonyms": ["파", "쪽파"],                        "category_id": "vegetable.leaf"},
    {"word": "깻잎",     "synonyms": ["들깻잎"],                           "category_id": "vegetable.leaf"},
    {"word": "브로콜리", "synonyms": ["broccoli"],                          "category_id": "vegetable.fruit_veg"},
    {"word": "콩나물",   "synonyms": ["콩나물국"],                          "category_id": "vegetable"},
    {"word": "숙주",     "synonyms": ["숙주나물"],                          "category_id": "vegetable"},
    {"word": "버섯",     "synonyms": ["팽이버섯", "새송이", "표고버섯"],     "category_id": "vegetable.mushroom"},
    {"word": "양배추",   "synonyms": ["cabbage"],                          "category_id": "vegetable.leaf"},
    {"word": "호박",     "synonyms": ["애호박", "단호박"],                   "category_id": "vegetable.fruit_veg"},
    {"word": "고구마",   "synonyms": ["sweet potato"],                     "category_id": "vegetable.root"},

    # 과일류
    {"word": "사과",     "synonyms": ["apple", "부사"],                    "category_id": "fruit.apple"},
    {"word": "배",       "synonyms": ["pear", "신고배"],                    "category_id": "fruit.pear"},
    {"word": "포도",     "synonyms": ["grape", "샤인머스캣"],               "category_id": "fruit.grape"},
    {"word": "수박",     "synonyms": ["watermelon"],                       "category_id": "fruit.watermelon"},
    {"word": "딸기",     "synonyms": ["strawberry"],                       "category_id": "fruit.strawberry"},
    {"word": "바나나",   "synonyms": ["banana"],                           "category_id": "fruit.banana"},
    {"word": "귤",       "synonyms": ["감귤", "한라봉", "tangerine"],       "category_id": "fruit.tangerine"},
    {"word": "복숭아",   "synonyms": ["peach"],                            "category_id": "fruit"},
    {"word": "자두",     "synonyms": ["plum"],                             "category_id": "fruit"},
    {"word": "참외",     "synonyms": ["korean melon"],                     "category_id": "fruit"},
    {"word": "키위",     "synonyms": ["kiwi"],                             "category_id": "fruit"},
    {"word": "망고",     "synonyms": ["mango"],                            "category_id": "fruit"},
    {"word": "블루베리", "synonyms": ["blueberry"],                         "category_id": "fruit"},
    {"word": "체리",     "synonyms": ["cherry"],                           "category_id": "fruit"},
    {"word": "레몬",     "synonyms": ["lemon"],                            "category_id": "fruit"},
    {"word": "오렌지",   "synonyms": ["orange"],                           "category_id": "fruit"},
    {"word": "아보카도", "synonyms": ["avocado"],                           "category_id": "fruit"},

    # 곡류/유제품
    {"word": "쌀",       "synonyms": ["백미", "rice"],                     "category_id": "grain.rice"},
    {"word": "밀가루",   "synonyms": ["flour"],                            "category_id": "grain.flour"},
    {"word": "우유",     "synonyms": ["milk", "흰우유"],                   "category_id": "dairy.milk"},
    {"word": "치즈",     "synonyms": ["cheese", "슬라이스치즈"],            "category_id": "dairy.cheese"},
    {"word": "요구르트", "synonyms": ["yogurt", "요거트"],                  "category_id": "dairy.yogurt"},
    {"word": "버터",     "synonyms": ["butter"],                           "category_id": "dairy"},

    # 가공식품
    {"word": "라면",     "synonyms": ["ramen", "인스턴트면", "컵라면"],      "category_id": "processed.ramen"},
    {"word": "두부",     "synonyms": ["tofu"],                             "category_id": "processed.tofu"},
    {"word": "식용유",   "synonyms": ["cooking oil", "카놀라유"],           "category_id": "processed.oil"},
    {"word": "참기름",   "synonyms": ["sesame oil"],                       "category_id": "processed.oil"},
    {"word": "간장",     "synonyms": ["soy sauce", "진간장"],              "category_id": "processed.sauce"},
    {"word": "된장",     "synonyms": ["soybean paste"],                    "category_id": "processed.sauce"},
    {"word": "고추장",   "synonyms": ["gochujang", "red pepper paste"],    "category_id": "processed.sauce"},
    {"word": "설탕",     "synonyms": ["sugar"],                            "category_id": "processed.sauce"},
    {"word": "소금",     "synonyms": ["salt"],                             "category_id": "processed.sauce"},
    {"word": "식초",     "synonyms": ["vinegar"],                          "category_id": "processed.sauce"},
    {"word": "케첩",     "synonyms": ["ketchup"],                          "category_id": "processed.sauce"},
    {"word": "마요네즈", "synonyms": ["mayonnaise", "마요"],                "category_id": "processed.sauce"},
    {"word": "햄",       "synonyms": ["ham", "런천미트"],                   "category_id": "processed"},
    {"word": "소시지",   "synonyms": ["sausage", "비엔나"],                 "category_id": "processed"},
    {"word": "김치",     "synonyms": ["kimchi", "포기김치"],                "category_id": "processed"},
    {"word": "과자",     "synonyms": ["snack", "스낵"],                     "category_id": "processed.snack"},
    {"word": "음료",     "synonyms": ["drink", "음료수"],                   "category_id": "processed"},
    {"word": "커피",     "synonyms": ["coffee", "믹스커피"],                "category_id": "processed"},
    {"word": "생수",     "synonyms": ["water", "미네랄워터"],               "category_id": "processed"},

    # 비식품
    {"word": "기저귀",   "synonyms": ["diaper"],                           "category_id": None},
    {"word": "물티슈",   "synonyms": ["wet wipe"],                         "category_id": None},
    {"word": "세제",     "synonyms": ["detergent", "세탁세제"],             "category_id": None},
    {"word": "휘발유",   "synonyms": ["gasoline", "가솔린"],               "category_id": "gas.gasoline"},
    {"word": "경유",     "synonyms": ["diesel"],                           "category_id": "gas.diesel"},
    {"word": "LPG",      "synonyms": ["엘피지"],                           "category_id": "gas.lpg"},

    # 전자제품
    {"word": "에어팟",   "synonyms": ["airpods", "이어폰"],                "category_id": "electronics.audio"},
    {"word": "노트북",   "synonyms": ["laptop"],                           "category_id": "electronics.laptop"},
    {"word": "모니터",   "synonyms": ["monitor", "디스플레이"],             "category_id": "electronics.monitor"},
    {"word": "아이폰",   "synonyms": ["iPhone"],                           "category_id": "electronics.phone"},
    {"word": "갤럭시",   "synonyms": ["galaxy", "삼성폰"],                  "category_id": "electronics.phone"},
    {"word": "아이패드", "synonyms": ["iPad", "태블릿"],                    "category_id": "electronics"},

    # 의류
    {"word": "나이키",   "synonyms": ["Nike"],                             "category_id": "clothing.shoes"},
    {"word": "아디다스", "synonyms": ["Adidas"],                            "category_id": "clothing.shoes"},
    {"word": "운동화",   "synonyms": ["sneakers", "러닝화"],                "category_id": "clothing.shoes"},
    {"word": "패딩",     "synonyms": ["padding", "다운자켓"],               "category_id": "clothing"},
    {"word": "청바지",   "synonyms": ["jeans", "데님"],                     "category_id": "clothing"},

    # 배달음식
    {"word": "치킨",     "synonyms": ["fried chicken", "배달치킨"],         "category_id": "delivery.chicken"},
    {"word": "피자",     "synonyms": ["pizza", "배달피자"],                 "category_id": "delivery.pizza"},
    {"word": "짜장면",   "synonyms": ["자장면", "jajangmyeon"],             "category_id": "delivery.chinese"},
    {"word": "족발",     "synonyms": ["보쌈"],                              "category_id": "delivery.korean"},
    {"word": "떡볶이",   "synonyms": ["tteokbokki"],                        "category_id": "delivery.korean"},
]


def seed_all(engine=None, database_url: str | None = None) -> None:
    """전체 시드 데이터 투입 — DB 초기화 후 호출."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    if engine is None:
        import os
        url = database_url or os.getenv("DATABASE_URL", "sqlite:///walletguardian.db")
        connect_args = {}
        if url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        engine = create_engine(url, echo=False, connect_args=connect_args)

    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as session:
        existing = session.query(Product).count()
        if existing > 0:
            logger.info("이미 %d개 품목이 존재합니다. 시드 스킵.", existing)
            return

        logger.info("시드 데이터 투입 시작...")

        cat_count = _seed_categories(session)
        logger.info("  카테고리 %d개 등록", cat_count)

        products = _seed_products(session)
        logger.info("  품목 %d개 등록", len(products))

        price_count = _seed_baseline_prices(session, products)
        logger.info("  기준 가격 %d건 등록", price_count)

        disc_count = _seed_discounts(session, products)
        logger.info("  할인 이력 %d건 등록", disc_count)

        hotdeal_count = _seed_hotdeal_prices(session, products)
        logger.info("  핫딜 가격 %d건 등록", hotdeal_count)

        gas_count = _seed_gas_stations(session)
        logger.info("  주유소 %d개 등록", gas_count)

        kw_count = _seed_keywords(session)
        logger.info("  키워드 %d개 등록", kw_count)

        session.commit()
        logger.info("시드 데이터 투입 완료!")


def _seed_categories(session: Session) -> int:
    """카테고리 트리 등록 — bulk insert로 메모리 효율 개선."""
    # bulk_save_objects 대신 add_all로 배치 삽입 — 건별 add 대비 flush 횟수 감소
    cats = [
        Category(
            id=data["id"],
            name=data["name"],
            parent_id=data["parent_id"],
            depth=data["depth"],
            sort_order=data["sort_order"],
            icon=data.get("icon"),
        )
        for data in SEED_CATEGORIES
    ]
    session.add_all(cats)
    session.flush()
    return len(cats)


def _seed_products(session: Session) -> list[Product]:
    """품목 마스터 등록 — add_all 배치 삽입."""
    products = [
        Product(
            name=data["name"],
            category_id=data["category_id"],
            unit=data["unit"],
        )
        for data in SEED_PRODUCTS
    ]
    session.add_all(products)
    session.flush()  # flush 1회로 모든 product.id 확정
    return products


def _seed_baseline_prices(session: Session, products: list[Product]) -> int:
    """최근 30일간의 매장별 기준 가격 시뮬레이션.

    최적화: 모든 레코드를 리스트에 모은 뒤 add_all로 일괄 삽입 — flush 1회.
    """
    records: list[BaselinePrice] = []
    for idx, p in enumerate(products):
        seed_data = SEED_PRODUCTS[idx]
        for store_name, base_price in seed_data["stores"].items():
            for day_offset in range(30, -1, -1):
                date = datetime.now() - timedelta(days=day_offset)
                variation = random.uniform(-0.05, 0.05)
                price = round(base_price * (1 + variation))
                records.append(BaselinePrice(
                    product_id=p.id,
                    source=store_name,
                    price=price,
                    unit=p.unit,
                    recorded_at=date,
                ))

        # KAMIS 공식 가격
        for day_offset in range(30, -1, -1):
            date = datetime.now() - timedelta(days=day_offset)
            variation = random.uniform(-0.03, 0.03)
            price = round(seed_data["avg"] * (1 + variation))
            records.append(BaselinePrice(
                product_id=p.id,
                source="kamis",
                price=price,
                unit=p.unit,
                recorded_at=date,
            ))

    session.add_all(records)
    return len(records)


def _seed_discounts(session: Session, products: list[Product]) -> int:
    """할인 이력 샘플 — 각 품목당 2~4건. 배치 삽입으로 최적화."""
    stores = ["emart", "homeplus", "lottemart", "costco"]
    records: list[DiscountHistory] = []

    for idx, p in enumerate(products):
        seed_data = SEED_PRODUCTS[idx]
        n_discounts = random.randint(2, 4)
        for _ in range(n_discounts):
            store = random.choice(stores)
            base_price = seed_data["stores"].get(store, seed_data["avg"])
            discount_pct = random.uniform(15, 40)
            sale_price = round(base_price * (1 - discount_pct / 100))
            days_ago = random.randint(1, 60)

            records.append(DiscountHistory(
                product_id=p.id,
                source=store,
                original_price=base_price,
                price=sale_price,
                discount_rate=round(discount_pct, 1),
                valid_from=datetime.now() - timedelta(days=days_ago),
                valid_to=datetime.now() - timedelta(days=max(0, days_ago - 7)),
            ))

    session.add_all(records)
    return len(records)


def _seed_hotdeal_prices(session: Session, products: list[Product]) -> int:
    """핫딜 가격 샘플 — 배치 삽입."""
    communities = ["ppomppu", "fmkorea", "arca", "ruliweb"]
    records: list[HotdealPrice] = []

    for p in products[:8]:
        hours_ago = random.randint(0, 48)
        records.append(HotdealPrice(
            product_id=p.id,
            price=round(random.uniform(0.5, 0.8) * 2000),
            source=random.choice(communities),
            source_url=f"https://example.com/hotdeal/{p.id}",
            title=f"{p.name} 초특가!",
            votes_hot=random.randint(10, 200),
            votes_not=random.randint(0, 30),
            crawled_at=datetime.now() - timedelta(hours=hours_ago),
        ))

    session.add_all(records)
    return len(records)


def _seed_gas_stations(session: Session) -> int:
    """주유소 데이터 등록 — 배치 삽입."""
    stations = [
        GasStation(
            name=data["name"],
            brand=data["brand"],
            address=data["address"],
            lat=data["lat"],
            lng=data["lng"],
            gasoline_price=data["gasoline"],
            diesel_price=data["diesel"],
            lpg_price=data["lpg"],
            is_self=data.get("is_self", False),
        )
        for data in SEED_GAS_STATIONS
    ]
    session.add_all(stations)
    return len(stations)


def _seed_keywords(session: Session) -> int:
    """자동완성 키워드 등록 — 배치 삽입."""
    keywords = [
        Keyword(
            word=data["word"],
            synonyms=data.get("synonyms"),
            category_id=data.get("category_id"),
            search_count=random.randint(10, 500),
        )
        for data in SEED_KEYWORDS
    ]
    session.add_all(keywords)
    return len(keywords)


if __name__ == "__main__":
    seed_all()
