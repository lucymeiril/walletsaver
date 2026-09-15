"""Exact forms from Emart's broad rice/grain/nut shelf."""

GROUPS = {
    "food.grains.rice.white": (
        "[농할 3천원 할인쿠폰 다운로드] 단일품종미 신동진쌀 10kg", "[농할 3천원 할인쿠폰 다운로드] 한눈에 반한 쌀(특) 10kg",
        "[농할 3천원 할인쿠폰 다운로드] 당진 해나루쌀 삼광(특) 10kg", "[농할 5천원 할인쿠폰 다운로드] SSG 이맛쌀 20kg",
        "햇살드리 수향미 골든퀸3호 4kg", "여주대왕님표 여주 진상미 4kg",
    ),
    "food.grains.rice.mixed": (
        "혼합 9곡 4kg", "건강곡물혼합 15곡 2kg", "조류혼합 맛있는 9곡 1kg",
        "96시간숙성한 소화잘되는 잡곡1kg", "영양 혼합12곡 2kg", "저당곡물 돼지감자 현미 2kg",
    ),
    "food.grains.nuts.almond": ("[미국산] 점보사이즈 볶음아몬드 500g", "오도독 볶음 아몬드 300g"),
    "food.grains.nuts.mixed": (
        "리얼 데일리너츠 400g (20g*20개입)", "믹스넛점보 1kg", "30일 매일견과 20gx30입",
        "브라질넛과 사차인치가 들어간 슈퍼믹스 20 x 15입",
    ),
    "food.grains.nuts.walnut": ("구수한 풍미 가득 미국산 호두 400g",),
    "food.grains.nuts.cashew": ("점보사이즈 구운가염캐슈넛 350g",),
    "food.grains.nuts.pecan": ("맘모스사이즈 피칸 300g",),
    "food.grains.nuts.peanut": ("로스티드앤솔티드땅콩 120g", "와사비맛 땅콩 120g"),
    "food.grains.nuts.pumpkin_seed": ("호박씨 400g",),
    "food.grains.rice.chia": ("인도산 치아씨드 400g",),
    "food.snacks.savory.corn": ("부드러운 추억의 강냉이 300g",),
    "food.drinks.tea.grain": ("유기농 발아 미숫가루 700g",),
}

TITLES = {title: leaf for leaf, titles in GROUPS.items() for title in titles}


def reviewed_emart_grain_leaf(evidence):
    if evidence["mart"] != "emart" or tuple(evidence["source_path_parts"]) != ("쌀/잡곡/견과",):
        return None
    return TITLES.get(evidence["source_title"])
