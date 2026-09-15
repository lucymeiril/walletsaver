"""Exact leaf-level forms from Emart's broad eco/organic shelf."""

GROUPS = {
    "food.meat.eggs.chicken": (
        "산야초 먹인 동물복지 유정란 15개입 (대란, 780g내외)",
        "[1번사육] 지리산 산골 1등급 111 동물복지 자유방목 신선유정란 10개입 (520g)",
        "지리산 산골 어린 닭이 낳은 신선 햇달걀 20구 (760g)",
        "[농할 20% 할인쿠폰 다운로드] 무항생제 동물복지 유정란 신선 햇달걀 20구 (760g)",
        "[농할 20% 할인쿠폰 다운로드] 순수백색 1등급 동물복지 유정란 20구 (대란, 1040g)",
    ),
    "food.meat.eggs.cooked": ("우리 아이가 좋아하는 깐메추리알 270g",),
    "food.dairy.yogurt.spoon": (
        "유기농 베이비 요구르트 플레인 340g (85g*4)",
        "유기농 베이비 요구르트 사과&당근 340g (85g*4)",
        "핑크퐁 유기농 아기요거트 딸기바나나 85gX4",
        "유기농 마이리틀 요거트 플레인 255g (85g*3)",
        "유기농 베이비 요구르트 딸기&바나나 340g (85g*4)",
        "유기농 마이리틀 요거트 딸기&블루베리 255g (85g*3)",
    ),
    "food.dairy.milk.plain": (
        "유기농 우유 750ml", "매일 상하목장 유기농 우유 180ml",
        "유기농 우유 500ml (125ml*4입)", "[서울우유] 유기농 우유 700ml",
    ),
    "food.dairy.cheese.sliced": (
        "앙팡 유기농 아기치즈 스텝2 180g", "유기농 아기치즈 STEP2 360g",
        "앙팡 유기농 어린이치즈 스텝3 180g", "[남양] 자연방목 유기농 아기치즈 2단계 180g",
    ),
    "food.meals.noodles.pasta": ("[펠리체티] 유기농 통밀 푸질리 500g",),
    "food.frozen.dessert.ice_bar": ("얼려먹는 아이스크림 밀크 510ml", "얼려먹는 아이스크림 초코 510ml"),
    "food.produce.vegetables.leaf": (
        "[농할 20% 할인쿠폰 다운로드]친환경 추부깻잎 20장/봉 (25g)",
        "친환경 카이피라 85g/팩", "친환경 청적상추+깻잎혼합 150g/봉",
        "친환경 캠핑용 간편모둠쌈 300g/팩",
    ),
    "food.produce.vegetables.cucumber": ("친환경 오이 2입/봉 (250g내외)",),
    "food.produce.vegetables.zucchini": ("친환경 애호박 2입/봉 (250g이상)",),
    "food.produce.vegetables.radish": ("친환경 무 (1kg이상)",),
    "food.produce.vegetables.mushroom": ("친환경 볶음용 모듬버섯 350g 내외/팩",),
    "food.produce.fruit.tomato": ("친환경 트리플 토마토 900g/팩",),
    "food.grains.rice.soybean": ("유기농 서리태 400g",),
    "food.drinks.traditional.sujeonggwa": ("유기농 수정과 1.8L",),
    "food.drinks.tea.kombucha": ("석류클렌즈콤부차(뷰티) 315ml",),
    "food.drinks.tea.grain": ("국내산 현미로 만든 스틱 미숫가루 600g",),
    "food.seasonings.spices.roasted_sesame": ("유기농 발아 깨소금 180g",),
}

TITLES = {title: leaf for leaf, titles in GROUPS.items() for title in titles}


def reviewed_emart_organic_leaf(evidence):
    if evidence["mart"] != "emart" or tuple(evidence["source_path_parts"]) != ("친환경/유기농",):
        return None
    return TITLES.get(evidence["source_title"])
