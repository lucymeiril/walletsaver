"""Exact species-declared forms audited on Emart's mixed meat and egg shelf."""

GROUPS = {
    "food.meat.eggs.chicken": (
        "[농할 20% 할인쿠폰 다운로드] 건강하고 행복한 닭이 낳은 동물복지 계란 15구 (대란, 780g)",
        "[농할 20% 할인쿠폰 다운로드] 동물복지 유정란 20구 (대란, 1040g)",
        "[농할 20% 할인쿠폰 다운로드] 무항생제 동물복지 유정란 신선 햇달걀 20구 (760g)",
        "[농할 20% 할인쿠폰 다운로드] 순수백색 1등급 동물복지 유정란 20구 (대란, 1040g)",
        "[농할 20% 할인쿠폰 다운로드] 지리산 영양 신선산골란 20구 (특란, 1,200g)",
        "[농할 20% 할인쿠폰 다운로드] 1등급 우리집 신선계란 20구 (대란, 1040g)",
    ),
    "food.meat.fresh.pork": ("[더느림+] 무항생제 삼겹살 (100g)",),
    "food.meat.fresh.beef": (
        "[농할 20% 할인쿠폰 다운로드][냉장] 한우 등심구이용1+등급300g",
        "와규 윗등심살 ST (100g)",
        "와규 부채 구이용 (100g)",
    ),
    "food.meat.fresh.chicken": ("(닭구이닭)칼집통다리800g",),
}

TITLES = {title: leaf for leaf, titles in GROUPS.items() for title in titles}


def reviewed_emart_meat_egg_leaf(evidence):
    if evidence["mart"] != "emart" or tuple(evidence["source_path_parts"]) != ("정육/계란류",):
        return None
    return TITLES.get(evidence["source_title"])
