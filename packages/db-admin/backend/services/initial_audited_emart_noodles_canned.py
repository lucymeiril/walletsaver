"""Exact food forms audited on Emart's mixed noodles and canned-food shelf."""

GROUPS = {
    "food.meals.noodles.ramen_sari": ("라면사리 110g*4입",),
    "food.meals.prepared.japchae": ("5K PRICE 간편잡채 89.5g",),
    "food.meals.noodles.kalguksu": ("신상 오뚜기 동대문식 닭한마리 칼국수 115g*4개",),
    "food.meals.noodles.bag_ramen": ("불닭볶음면 (70g*6개) 420g", "불닭볶음면 105g"),
    "food.preserved.sides.cucumber_pickle": ("크링클컷 슬라이스 피클 500g", "오이피클 300g"),
    "food.meals.noodles.wheat_noodle": ("샘표 메밀쌀소면 400g",),
    "food.preserved.canned.beans": ("썬큐 베이크드 빈스 420g",),
    "food.meals.noodles.black_bean": ("짜장면사리 400g",),
    "food.meals.noodles.jjamppong": ("완면각짬뽕105g",),
}

TITLES = {title: leaf for leaf, titles in GROUPS.items() for title in titles}


def reviewed_emart_noodles_canned_leaf(evidence):
    if evidence["mart"] != "emart" or tuple(evidence["source_path_parts"]) != ("면류/통조림",):
        return None
    return TITLES.get(evidence["source_title"])
