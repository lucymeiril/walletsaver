"""Exact reviewed pantry titles. Ingredient and quantity review stay separate."""

GROUPS = {
    "spices.mustard_paste": ("대상 청정원 연 겨자 95G",),
    "spices.wasabi_paste": ("움트리 생와사비 120G", "움트리 육류앤 생와사비 120G"),
    "spices.chili_powder": ("괴산 순정 고춧가루 100G",),
    "spices.cumin": ("브레드가든 쿠민 53G",),
    "spices.parsley": ("신영 파슬리 11G",),
    "spices.star_anise": ("전원식품 팔각(스타아니스) 80G",),
    "spices.roasted_sesame": ("오뚜기 옛날 볶음 참깨 100G", "오뚜기 옛날 볶음 참깨 200G", "해표_볶음참깨_180G"),
    "spices.whole_chili": ("신영 페페로치노홀 20G",),
    "stock.beef": ("CJ 쇠고기다시다 명품골드 100G", "simplus 쇠고기다시 1KG", "simplus 한우다시 300G", "CJ 쇠고기다시다 300G", "CJ 쇠고기다시다 500G", "CJ 쇠고기다시다 명품골드 96G"),
    "stock.seasoned_salt": ("대상 미원 맛소금 250G", "대상 미원 맛소금 500G", "대상 미원맛소금 95G"),
    "stock.umami": ("대상 발효 미원 100G",),
    "stock.chicken": ("대상 청정원 쉐프의 치킨스톡 340G",),
    "stock.vegetable_tablet": ("청정원 맛선생야채국물내기한알 100G",),
    "sauces.broth": ("simplus 샤브샤브 가쓰오육수 500G", "simplus 샤브샤브 야채육수 500G"),
    "syrups.oligosaccharide": ("대상 청정원 요리 올리고당 1.2KG", "CJ 백설 올리고당 1.2KG", "CJ 백설 올리고당 700G", "CJ 백설 요리 올리고당 700G"),
    "syrups.starch": ("오뚜기 옛날 물엿 1.2KG", "simplus 물엿 1.2KG"),
    "syrups.plum": ("청정원 매실청 650G",),
    "syrups.allulose": ("CJ 백설 알룰로스 700G",),
    "syrups.rice": ("simplus 조청쌀엿 1.2KG",),
    "stock.cooking_wine": ("대상 청정원 맛술 830ML", "롯데칠성 미림 900ML", "CJ 백설맛술 생강 800ML"),
}
TITLES = {title: "food.seasonings." + leaf for leaf, titles in GROUPS.items() for title in titles}


def reviewed_seasoning_leaf(evidence):
    path = evidence["source_path_parts"]
    if evidence["mart"] != "homeplus" or len(path) < 3 or path[0] != "장류/양념/제빵" or path[1] not in {"고추가루/깨/향신료", "다시다/미원/맛소금", "식초/물엿/맛술/액젓"}:
        return None
    return TITLES.get(evidence["source_title"])
