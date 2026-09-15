"""Exact forms from Homeplus's misleading miscellaneous flavored-powder leaf."""

PATH = ("커피/차", "코코아/핫초코", "가향분말류", "기타가향분말류")

GROUPS = {
    "food.drinks.tea.kombucha": (
        "동서 애사비 콤부차 파인애플망고 150G(30T)", "동서 애사비 콤부차 레몬라임 150G(30T)",
        "티젠 콤부차 레몬 30T (150G)", "티젠 콤부차 매실 30T (150G)",
        "티젠 콤부차 파인애플 30T(150G)", "티젠 콤부차 피치 30T(150G)",
        "티젠 콤부차 망고구아바 30T(150G)", "동서 애사비 콤부차 피치패션프룻 150G(30T)",
        "티젠 콤부차 라즈베리 30T 150G", "티젠 콤부차유자 30T(150G)",
    ),
    "food.drinks.tea.fruit_preserve": ("패션후르츠&한라봉청 1KG", "패션후르츠&레몬청 1KG"),
    "food.drinks.tea.black": ("동서 아이스티 티오 복숭아 40T",),
    "food.drinks.tea.green": ("티젠 브이핏 말차레몬 10T(40G)",),
    "food.supplements.protein.powder": ("맥널티 스테비아 단백질 고구마크림라떼 20T(360G)",),
}

TITLES = {title: leaf for leaf, titles in GROUPS.items() for title in titles}


def reviewed_homeplus_flavored_powder_leaf(evidence):
    if evidence["mart"] != "homeplus" or tuple(evidence["source_path_parts"]) != PATH:
        return None
    return TITLES.get(evidence["source_title"])
