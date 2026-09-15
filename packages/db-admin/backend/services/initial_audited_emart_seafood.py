"""Exact single seafood forms audited on Emart's mixed seafood shelf."""

GROUPS = {
    "food.seafood.molluscs.squid": (
        "[해동][아르헨티나] 손질 오징어 (대, 마리)",
        "[생물][국산] 손질 오징어 (250g 이상, 2~3미) (내장제거)",
        "[해동][국산] 손질 오징어 (380g, 2-3마리)",
    ),
    "food.seafood.seaweed.miyeok": ("자른미역 (100g)",),
    "food.seafood.shellfish.shrimp": ("[냉동][태국] 자숙 칵테일 새우살 (31-40) (450g)",),
    "food.seafood.fish.croaker": (
        "[전국택배][냉동][국산] 영광법성포 왕부세 보리굴비세트 3호 (10미 1.8kg 내외/미당 26~30cm 내외)",
        "[냉동][국산] 영광 법성포 참굴비 (총 560g) (2미 140g*4팩)",
    ),
    "food.seafood.shellfish.abalone": ("[활][국산] 활 전복 (특)(100g 단위 판매)",),
    "food.seafood.fish.salmon": (
        "[냉장][노르웨이] 연어 배꼽살 (100g)",
        "[냉동][노르웨이] 노브랜드 노르웨이 훈제연어 (180g/팩)",
    ),
    "food.seafood.shellfish.clam": ("[생물][국산] 벌교 맛조개 (300g)",),
    "food.seafood.fish.flounder": ("[냉장][국산] 숙성 광어회 (150g)",),
    "food.seafood.processed.pollock_roe": ("[멤버십][냉장][러시아] 실속명란 (320g/팩)",),
}

TITLES = {title: leaf for leaf, titles in GROUPS.items() for title in titles}


def reviewed_emart_seafood_leaf(evidence):
    if evidence["mart"] != "emart" or tuple(evidence["source_path_parts"]) != ("수산물/건해산",):
        return None
    return TITLES.get(evidence["source_title"])
