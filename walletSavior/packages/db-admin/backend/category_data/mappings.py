"""
WalletSavior 상품-카테고리 매핑.

일반 상품을 카테고리에 매핑하고, 가격 범위/단위 정보를 제공합니다.
"""

from __future__ import annotations
from typing import Optional


def _pm(name: str, *, categories: list[str],
        unit: str = "개", min_price: int = 0, max_price: int = 0,
        aliases: Optional[list[str]] = None,
        brand_examples: Optional[list[str]] = None) -> dict:
    """상품 매핑 딕셔너리 헬퍼."""
    return {
        "name": name,
        "categories": categories,
        "unit": unit,
        "min_price": min_price,
        "max_price": max_price,
        "aliases": aliases or [],
        "brand_examples": brand_examples or [],
    }


# ──────────────────────────────────────────────
# 상품-카테고리 매핑 데이터
# ──────────────────────────────────────────────

PRODUCT_MAPPINGS: list[dict] = [
    # ═══ 농산물 ═══
    _pm("배추", categories=["agriculture.leafy.napa_cabbage"],
        unit="포기", min_price=2000, max_price=8000,
        aliases=["김장배추", "알배추"]),
    _pm("시금치", categories=["agriculture.leafy.spinach"],
        unit="단", min_price=1500, max_price=4000),
    _pm("상추", categories=["agriculture.leafy.lettuce"],
        unit="봉지", min_price=1000, max_price=3000,
        aliases=["청상추", "적상추"]),
    _pm("양배추", categories=["agriculture.leafy.cabbage"],
        unit="통", min_price=2000, max_price=5000),
    _pm("콩나물", categories=["agriculture.leafy.bean_sprout"],
        unit="봉지", min_price=800, max_price=2000),
    _pm("대파", categories=["agriculture.leafy.green_onion"],
        unit="단", min_price=1000, max_price=4000, aliases=["파"]),
    _pm("토마토", categories=["agriculture.fruit_veg.tomato"],
        unit="kg", min_price=3000, max_price=8000,
        aliases=["방울토마토", "대추토마토"]),
    _pm("오이", categories=["agriculture.fruit_veg.cucumber"],
        unit="개", min_price=500, max_price=1500),
    _pm("고추", categories=["agriculture.fruit_veg.chili"],
        unit="봉지", min_price=2000, max_price=6000,
        aliases=["풋고추", "청양고추"]),
    _pm("파프리카", categories=["agriculture.fruit_veg.paprika"],
        unit="개", min_price=1000, max_price=3000),
    _pm("호박", categories=["agriculture.fruit_veg.pumpkin"],
        unit="개", min_price=1000, max_price=4000,
        aliases=["애호박", "단호박"]),
    _pm("감자", categories=["agriculture.root.potato"],
        unit="kg", min_price=2000, max_price=6000),
    _pm("고구마", categories=["agriculture.root.sweet_potato"],
        unit="kg", min_price=3000, max_price=8000,
        aliases=["밤고구마", "꿀고구마"]),
    _pm("당근", categories=["agriculture.root.carrot"],
        unit="개", min_price=500, max_price=2000),
    _pm("양파", categories=["agriculture.root.onion"],
        unit="kg", min_price=1000, max_price=4000),
    _pm("마늘", categories=["agriculture.root.garlic"],
        unit="kg", min_price=5000, max_price=15000,
        aliases=["깐마늘", "통마늘"]),
    _pm("사과", categories=["agriculture.fruit.apple"],
        unit="개", min_price=1000, max_price=5000,
        aliases=["부사사과", "홍로사과"]),
    _pm("배", categories=["agriculture.fruit.pear"],
        unit="개", min_price=2000, max_price=8000),
    _pm("딸기", categories=["agriculture.fruit.strawberry"],
        unit="팩", min_price=5000, max_price=15000,
        aliases=["설향딸기"]),
    _pm("포도", categories=["agriculture.fruit.grape"],
        unit="송이", min_price=3000, max_price=10000),
    _pm("수박", categories=["agriculture.fruit.watermelon"],
        unit="통", min_price=10000, max_price=25000),
    _pm("바나나", categories=["agriculture.fruit.banana"],
        unit="송이", min_price=2000, max_price=5000,
        brand_examples=["돌", "델몬트", "스위티오"]),
    _pm("샤인머스캣", categories=["agriculture.fruit.shine_muscat"],
        unit="송이", min_price=8000, max_price=25000),
    _pm("감귤", categories=["agriculture.fruit.tangerine"],
        unit="kg", min_price=3000, max_price=8000,
        aliases=["귤", "한라봉"]),
    _pm("쌀", categories=["agriculture.grain.rice"],
        unit="kg", min_price=20000, max_price=60000,
        aliases=["백미", "현미"]),

    # ═══ 축산물 ═══
    _pm("삼겹살", categories=["livestock.pork.belly"],
        unit="g", min_price=1500, max_price=3000,
        aliases=["돼지삼겹살", "구이용삼겹살"],
        brand_examples=["한돈", "스페인산"]),
    _pm("목살", categories=["livestock.pork.neck"],
        unit="g", min_price=1200, max_price=2500),
    _pm("돼지갈비", categories=["livestock.pork.ribs"],
        unit="g", min_price=1000, max_price=2500,
        aliases=["양념돼지갈비"]),
    _pm("소등심", categories=["livestock.beef.sirloin"],
        unit="g", min_price=3000, max_price=15000,
        aliases=["등심", "꽃등심"]),
    _pm("소갈비", categories=["livestock.beef.ribs"],
        unit="g", min_price=3000, max_price=12000,
        aliases=["LA갈비", "찜갈비"]),
    _pm("한우", categories=["livestock.beef.hanwoo"],
        unit="g", min_price=5000, max_price=20000,
        aliases=["한우등심", "한우갈비"]),
    _pm("차돌박이", categories=["livestock.beef.chadol"],
        unit="g", min_price=2500, max_price=6000),
    _pm("닭가슴살", categories=["livestock.chicken.breast"],
        unit="g", min_price=800, max_price=2000,
        brand_examples=["하림", "마니커"]),
    _pm("통닭", categories=["livestock.chicken.whole"],
        unit="마리", min_price=5000, max_price=10000),
    _pm("계란", categories=["livestock.egg"],
        unit="구", min_price=4000, max_price=12000,
        aliases=["달걀", "유정란"]),

    # ═══ 수산물 ═══
    _pm("고등어", categories=["seafood.fish.mackerel"],
        unit="마리", min_price=2000, max_price=6000,
        aliases=["자반고등어"]),
    _pm("연어", categories=["seafood.fish.salmon"],
        unit="g", min_price=3000, max_price=10000,
        aliases=["훈제연어", "연어회"]),
    _pm("새우", categories=["seafood.crustacean.shrimp"],
        unit="g", min_price=5000, max_price=20000,
        aliases=["흰다리새우", "대하"]),
    _pm("전복", categories=["seafood.shellfish.abalone"],
        unit="마리", min_price=2000, max_price=8000),
    _pm("김", categories=["seafood.seaweed.laver"],
        unit="봉", min_price=2000, max_price=8000,
        aliases=["구운김", "조미김"]),
    _pm("미역", categories=["seafood.seaweed.wakame"],
        unit="봉지", min_price=2000, max_price=6000),
    _pm("멸치", categories=["seafood.dried.anchovy"],
        unit="봉지", min_price=3000, max_price=10000),

    # ═══ 가공식품 ═══
    _pm("라면", categories=["processed.noodle.ramen"],
        unit="봉지", min_price=600, max_price=1500,
        aliases=["신라면", "진라면"],
        brand_examples=["농심", "오뚜기", "삼양", "팔도"]),
    _pm("라면 멀티팩", categories=["processed.noodle.ramen"],
        unit="팩", min_price=3000, max_price=6000,
        aliases=["라면 5개입"]),
    _pm("참치캔", categories=["processed.canned.tuna"],
        unit="캔", min_price=1500, max_price=4000,
        brand_examples=["동원", "사조"]),
    _pm("스팸", categories=["processed.canned.spam"],
        unit="캔", min_price=3000, max_price=8000),
    _pm("만두", categories=["processed.frozen.dumpling"],
        unit="봉지", min_price=3000, max_price=8000,
        brand_examples=["비비고", "풀무원", "해태"]),
    _pm("즉석밥", categories=["processed.instant.rice"],
        unit="개", min_price=800, max_price=2000,
        aliases=["햇반"], brand_examples=["CJ", "오뚜기"]),
    _pm("간장", categories=["processed.sauce.soy_sauce"],
        unit="mL", min_price=2000, max_price=8000,
        aliases=["진간장", "양조간장"]),
    _pm("고추장", categories=["processed.sauce.gochujang"],
        unit="g", min_price=3000, max_price=10000),
    _pm("된장", categories=["processed.sauce.doenjang"],
        unit="g", min_price=2000, max_price=7000),
    _pm("식용유", categories=["processed.oil.vegetable"],
        unit="mL", min_price=3000, max_price=8000),
    _pm("참기름", categories=["processed.oil.sesame"],
        unit="mL", min_price=5000, max_price=15000),
    _pm("김치", categories=["processed.side.kimchi"],
        unit="kg", min_price=5000, max_price=20000,
        aliases=["포기김치", "맛김치"]),
    _pm("두부", categories=["processed.tofu.firm"],
        unit="모", min_price=1000, max_price=3000,
        brand_examples=["풀무원", "CJ"]),
    _pm("식빵", categories=["processed.bakery.bread"],
        unit="봉", min_price=1500, max_price=4000),
    _pm("밀키트", categories=["processed.instant.meal_kit"],
        unit="세트", min_price=8000, max_price=25000),

    # ═══ 생활용품 ═══
    _pm("세탁세제", categories=["household.detergent.laundry"],
        unit="개", min_price=8000, max_price=25000,
        brand_examples=["퍼실", "피지", "액츠"]),
    _pm("섬유유연제", categories=["household.detergent.softener"],
        unit="개", min_price=5000, max_price=15000,
        brand_examples=["다우니", "피죤"]),
    _pm("화장지", categories=["household.tissue.toilet"],
        unit="롤", min_price=8000, max_price=20000),
    _pm("물티슈", categories=["household.tissue.wet"],
        unit="팩", min_price=1000, max_price=5000),
    _pm("치약", categories=["household.bathroom.toothpaste"],
        unit="개", min_price=2000, max_price=6000),
    _pm("샴푸", categories=["household.bathroom.shampoo"],
        unit="mL", min_price=5000, max_price=15000),

    # ═══ 음료 ═══
    _pm("생수", categories=["beverage.water.still"],
        unit="L", min_price=500, max_price=2000,
        brand_examples=["삼다수", "아이시스", "백산수"]),
    _pm("생수 묶음", categories=["beverage.water.still"],
        unit="팩", min_price=4000, max_price=10000,
        aliases=["생수 2L 6개"]),
    _pm("콜라", categories=["beverage.soda.cola"],
        unit="mL", min_price=1000, max_price=3000,
        brand_examples=["코카콜라", "펩시"]),
    _pm("사이다", categories=["beverage.soda.cider"],
        unit="mL", min_price=1000, max_price=3000,
        brand_examples=["칠성", "스프라이트"]),
    _pm("커피믹스", categories=["beverage.coffee.mix"],
        unit="개", min_price=8000, max_price=20000,
        brand_examples=["맥심", "동서"]),

    # ═══ 유제품 ═══
    _pm("우유", categories=["dairy.milk.plain"],
        unit="mL", min_price=2000, max_price=5000,
        brand_examples=["서울우유", "매일우유", "남양"]),
    _pm("요거트", categories=["dairy.yogurt.cup"],
        unit="개", min_price=800, max_price=3000,
        brand_examples=["요플레", "액티비아"]),
    _pm("치즈", categories=["dairy.cheese.slice"],
        unit="봉", min_price=3000, max_price=8000),
    _pm("버터", categories=["dairy.butter.butter"],
        unit="g", min_price=3000, max_price=10000),

    # ═══ 주류 ═══
    _pm("소주", categories=["alcohol.soju"],
        unit="병", min_price=1500, max_price=3000,
        brand_examples=["참이슬", "처음처럼", "진로"]),
    _pm("맥주", categories=["alcohol.beer.domestic"],
        unit="캔", min_price=1500, max_price=4000,
        brand_examples=["카스", "테라", "하이트"]),

    # ═══ 건강식품 ═══
    _pm("종합비타민", categories=["health.vitamin.multi"],
        unit="병", min_price=10000, max_price=40000,
        brand_examples=["센트룸", "얼라이브"]),
    _pm("홍삼", categories=["health.ginseng"],
        unit="박스", min_price=20000, max_price=100000,
        brand_examples=["정관장"]),
    _pm("유산균", categories=["health.probiotic"],
        unit="박스", min_price=15000, max_price=50000,
        brand_examples=["락토핏", "프로바이오틱스"]),

    # ═══ 간식 ═══
    _pm("감자칩", categories=["snack.chip.potato"],
        unit="봉지", min_price=1500, max_price=4000,
        brand_examples=["프링글스", "레이즈"]),
    _pm("초콜릿", categories=["snack.chocolate"],
        unit="개", min_price=1000, max_price=10000),
    _pm("아몬드", categories=["snack.nut.almond"],
        unit="봉지", min_price=3000, max_price=10000),
    _pm("믹스넛", categories=["snack.nut.mix"],
        unit="봉지", min_price=5000, max_price=15000),

    # ═══ 가전/디지털 ═══
    _pm("냉장고", categories=["appliance.kitchen.fridge"],
        unit="대", min_price=500000, max_price=3000000,
        brand_examples=["삼성", "LG"]),
    _pm("세탁기", categories=["appliance.living.washer"],
        unit="대", min_price=300000, max_price=2000000,
        brand_examples=["삼성", "LG"]),
    _pm("에어컨", categories=["appliance.living.ac"],
        unit="대", min_price=400000, max_price=2500000),
    _pm("청소기", categories=["appliance.living.vacuum"],
        unit="대", min_price=100000, max_price=1000000,
        brand_examples=["다이슨", "LG", "삼성"]),
    _pm("TV", categories=["appliance.video.tv"],
        unit="대", min_price=200000, max_price=5000000),
    _pm("스마트폰", categories=["digital.mobile.smartphone"],
        unit="대", min_price=200000, max_price=2000000,
        brand_examples=["삼성", "애플"]),
    _pm("노트북", categories=["digital.computer.laptop"],
        unit="대", min_price=500000, max_price=3000000,
        brand_examples=["삼성", "LG", "애플", "레노버"]),
    _pm("이어폰", categories=["digital.audio.earphone"],
        unit="개", min_price=10000, max_price=400000,
        brand_examples=["애플", "삼성", "소니"]),

    # ═══ 다중 카테고리 상품 ═══
    _pm("김치찌개", categories=["processed.side.kimchi", "restaurant.korean"],
        unit="인분", min_price=7000, max_price=12000,
        aliases=["김치찌개용 김치"]),
    _pm("불고기", categories=["livestock.beef", "restaurant.korean"],
        unit="g", min_price=2000, max_price=6000,
        aliases=["양념불고기", "소불고기"]),
    _pm("삼계탕", categories=["livestock.chicken", "restaurant.korean"],
        unit="인분", min_price=10000, max_price=18000),
    _pm("비빔밥", categories=["restaurant.korean"],
        unit="인분", min_price=7000, max_price=12000),
    _pm("떡볶이", categories=["processed", "restaurant.snack_bar"],
        unit="인분", min_price=3000, max_price=6000,
        aliases=["밀떡볶이", "쌀떡볶이"]),
    _pm("치킨", categories=["delivery.chicken", "livestock.chicken"],
        unit="마리", min_price=15000, max_price=25000,
        brand_examples=["BBQ", "교촌", "BHC", "굽네"]),
    _pm("피자", categories=["delivery.pizza", "processed.frozen.pizza"],
        unit="판", min_price=15000, max_price=35000,
        brand_examples=["도미노", "피자헛", "파파존스"]),
    _pm("스팸선물세트", categories=["processed.canned.spam", "etc.gift_set"],
        unit="세트", min_price=20000, max_price=50000),
    _pm("한우선물세트", categories=["livestock.beef.hanwoo", "etc.gift_set"],
        unit="세트", min_price=50000, max_price=300000),
    _pm("과일선물세트", categories=["agriculture.fruit", "etc.gift_set"],
        unit="세트", min_price=30000, max_price=100000),
]


# ──────────────────────────────────────────────
# 사전 인덱스 — 모듈 로드 시 한 번만 빌드 (선형 탐색 → O(1) 조회)
# ──────────────────────────────────────────────

# name → mapping dict (정확 일치)
_MAPPING_BY_NAME: dict[str, dict] = {pm["name"]: pm for pm in PRODUCT_MAPPINGS}

# alias → mapping dict (별칭 역매핑)
_MAPPING_BY_ALIAS: dict[str, dict] = {}
for _pm_entry in PRODUCT_MAPPINGS:
    for _alias in _pm_entry.get("aliases", []):
        if _alias not in _MAPPING_BY_ALIAS:
            _MAPPING_BY_ALIAS[_alias] = _pm_entry

# category_id → [mapping dicts] 역인덱스 (get_products_for_category 최적화)
_MAPPINGS_BY_CATEGORY: dict[str, list[dict]] = {}
for _pm_entry in PRODUCT_MAPPINGS:
    for _cat_id in _pm_entry.get("categories", []):
        _MAPPINGS_BY_CATEGORY.setdefault(_cat_id, []).append(_pm_entry)


# ──────────────────────────────────────────────
# 유틸리티 함수
# ──────────────────────────────────────────────

def get_categories_for_product(product_name: str) -> list[str]:
    """상품명으로 매핑된 카테고리 ID 목록 반환."""
    # 1) 정확 이름 매칭 (O(1))
    pm = _MAPPING_BY_NAME.get(product_name)
    if pm:
        return pm["categories"]
    # 2) 별칭 매칭 (O(1))
    pm = _MAPPING_BY_ALIAS.get(product_name)
    if pm:
        return pm["categories"]
    # 3) 부분 매칭 (fallback — 선형 탐색)
    name_lower = product_name.lower()
    for pm in PRODUCT_MAPPINGS:
        if name_lower in pm["name"].lower() or pm["name"].lower() in name_lower:
            return pm["categories"]
    return []


def get_products_for_category(category_id: str) -> list[dict]:
    """특정 카테고리에 매핑된 상품 목록 반환. 사전 인덱스로 O(1) 조회."""
    return list(_MAPPINGS_BY_CATEGORY.get(category_id, []))


def get_price_range(product_name: str) -> Optional[dict]:
    """상품의 예상 가격 범위 반환. O(1) 인덱스 조회 우선."""
    pm = _MAPPING_BY_NAME.get(product_name) or _MAPPING_BY_ALIAS.get(product_name)
    if pm:
        return {
            "min_price": pm["min_price"],
            "max_price": pm["max_price"],
            "unit": pm["unit"],
        }
    return None


def get_unit(product_name: str) -> Optional[str]:
    """상품의 표준 단위 반환. O(1) 인덱스 조회 우선."""
    pm = _MAPPING_BY_NAME.get(product_name) or _MAPPING_BY_ALIAS.get(product_name)
    if pm:
        return pm["unit"]
    return None


# 전체 단위 목록
UNITS = [
    "개", "팩", "봉지", "상자", "박스",
    "kg", "g", "L", "mL",
    "구", "입", "마리", "통", "단", "포기", "송이",
    "캔", "병", "봉", "롤", "모", "세트", "대", "인분", "판",
]
