"""Reviewed Homeplus pantry titles; no identity merging or quantity override."""

GROUPS = {
    "brown_sugar": ("CJ 갈색설탕 3KG", "CJ 갈색설탕 5KG", "CJ 백설 갈색설탕 1KG"),
    "black_sugar": ("CJ 흑설탕 1KG",),
    "allulose": ("CJ 백설 알룰로스 분말 400G",),
    "stevia_blend": ("CJ 백설 달콤함그대로 스테비아 400G",),
    "roasted_salt": ("CJ 명품 천일염 구운소금 180G", "simplus 구운소금 500G"),
    "herb_salt": ("CJ 백설 허브맛 솔트 갈릭(소금) 50G", "CJ 백설 허브맛 솔트 오리지널(소금) 50G"),
    "sea_salt": ("대상 청정원 천일염 가는소금 190G", "대상 청정원 천일염 가는소금 500G", "simplus 천일염 굵은소금 1KG", "simplus 천일염 굵은소금 3KG"),
    "refined_salt": ("simplus 꽃소금 1KG",),
    "malt_flour": ("simplus 국내산 엿기름가루 500G",),
    "rice_flour": ("simplus 국내산 찹쌀가루 400G",),
    "oat_flour": ("simplus 귀리가루 400G",),
    "perilla_flour": ("simplus 들깨가루 300G",),
    "buckwheat_flour": ("simplus 메밀가루 400G",),
    "pancake_mix": ("오뚜기 부침가루 1KG", "해표 부침가루 1KG", "CJ 백설 부침가루 1KG", "simplus 부침가루 1KG"),
    "frying_mix": ("오뚜기 튀김가루 1KG", "해표 튀김가루 1KG", "CJ 백설 튀김가루 1KG"),
    "breadcrumbs": ("동원 빵가루 200G",),
    "baking_soda": ("simplus 베이킹 식소다 150G",),
    "baking_powder": ("simplus 베이킹 파우더 150G",),
    "icing_sugar": ("simplus 슈가 파우더 100G",),
    "almond_flour": ("simplus 아몬드 파우더 100G",),
    "yeast": ("simplus 인스턴트 드라이이스트 100G",),
    "hotcake_mix": ("CJ 백설 우리밀 핫케익믹스 500G",),
    "hotteok_mix": ("CJ 찹쌀 호떡믹스 400G",),
}
TITLES = {title: "food.seasonings.baking." + leaf for leaf, titles in GROUPS.items() for title in titles}


def reviewed_baking_leaf(evidence):
    path = evidence["source_path_parts"]
    if evidence["mart"] != "homeplus" or len(path) < 3 or path[0] != "장류/양념/제빵" or path[1] not in {"밀가루/분말류", "소금/설탕", "시럽/제빵믹스"}:
        return None
    return TITLES.get(evidence["source_title"])
