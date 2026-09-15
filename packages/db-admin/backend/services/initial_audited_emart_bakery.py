"""Exact product forms audited on Emart's mixed bakery and jam shelf."""

GROUPS = {
    "food.bakery.bread.filled": (
        "대림 제로 붕어빵 슈크림 300g",
        "대림 제로 붕어빵 단팥 300g",
        "치즈롤빵8입",
        "계피 호떡 480g (4개입)",
        "CJ 밸런스밀 치아바타 비프 콰트로치즈 140g*3",
        "문경사과파이만주6입",
        "브리오슈호두단팥빵4입",
        "삼립 한입만쥬 알찬밤만쥬 400g",
    ),
    "food.bakery.bread.sandwich": ("사라다크라상2입",),
    "food.bakery.dessert.donut": ("던킨 미니 글레이즈드 150g (15g*10입)",),
    "food.bakery.dessert.cream_puff": ("빅쿠키슈3입",),
    "food.bakery.spreads.fruit": ("오뚜기 딸기버터잼 280g",),
}

TITLES = {title: leaf for leaf, titles in GROUPS.items() for title in titles}


def reviewed_emart_bakery_leaf(evidence):
    if evidence["mart"] != "emart" or tuple(evidence["source_path_parts"]) != ("베이커리/잼",):
        return None
    return TITLES.get(evidence["source_title"])
