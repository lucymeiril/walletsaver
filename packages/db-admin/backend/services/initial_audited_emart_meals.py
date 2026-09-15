"""Exact product forms from Emart's broad meal-kit/convenience shelf."""

GROUPS = {
    "food.meals.baby.puree": (
        "[매일유업] 맘마밀 오트밀과 사과푸룬",
        "[매일유업]맘마밀 안심이유식 미역과소고기100g",
        "[매일유업]맘마밀 안심이유식 표고버섯과소고기100g",
    ),
    "food.preserved.sides.danmuji": (
        "김밥용 맛 단무지 550g", "일가집 쫄깃 치자 단무지 200g", "무색소김밥단무지 400g",
    ),
    "food.preserved.sides.ssammu": ("아삭한 쌈무 350g",),
    "food.preserved.sides.acorn_jelly": ("국산도토리묵 350g", "도토리묵 350g"),
    "food.meals.noodles.pasta": ("모짜렐라 비프라자냐 350g",),
    "food.meals.prepared.chicken_skewer": ("소금구이 모듬닭꼬치 600g",),
    "food.meals.prepared.frozen_potato": ("양념감자튀김 400g",),
    "food.meals.prepared.pancake": ("메밀김치전병720g",),
    "food.meals.rice.instant": ("정선 생 곤드레나물밥 5입(1110g)",),
    "food.seasonings.sauces.stew": ("다담 된장찌개 양념500g",),
    "food.meals.prepared.fish_cutlet": ("생선까스 280g",),
}

TITLES = {title: leaf for leaf, titles in GROUPS.items() for title in titles}


def reviewed_emart_meal_leaf(evidence):
    if evidence["mart"] != "emart" or tuple(evidence["source_path_parts"]) != ("밀키트/간편식",):
        return None
    return TITLES.get(evidence["source_title"])
