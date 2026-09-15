"""Exact declared snack forms audited on Lottemart's general-snack shelf."""

PATH = ("과자ㆍ스낵ㆍ간식", "과자ㆍ쿠키ㆍ파이", "일반과자")
GROUPS = {
    "food.snacks.savory.potato": (
        "오리온 포카칩 오리지널 (50G)", "오리온 스윙칩 볶음고추장 (45G)",
        "오리온 포카칩 어니언 (50G)", "해태 가루비감자칩 (40G)",
        "해태 가루비감자칩 야키니쿠맛 (40G)", "농심 포테토칩 교촌간장치킨맛 (95G)",
        "농심 포테토칩 K 양념치킨맛 (86G)", "농심 포테토칩 엽떡로제맛 (95G)",
    ),
    "food.snacks.savory.corn": ("크라운 카라멜콘 땅콩 (72G)",),
    "food.snacks.savory.fruit": ("산골과일참 통째로과일칩 (10G)",),
    "food.snacks.savory.grain": ("롯데 쌀로칩 들기름 김맛 (38G)",),
    "food.snacks.savory.vegetable": ("오늘좋은 빠삭칩 대파&크림치즈 (80G)", "오늘좋은 빠삭칩 단호박 (85G)"),
}

TITLES = {title: leaf for leaf, titles in GROUPS.items() for title in titles}


def reviewed_lotte_general_snack_leaf(evidence):
    if evidence["mart"] != "lottemart" or tuple(evidence["source_path_parts"]) != PATH:
        return None
    return TITLES.get(evidence["source_title"])
