"""Exact non-meat products found in Costco's polluted meat shelf."""

from urllib.parse import urlparse


ENTRIES = {
    "맥코믹 몬트리얼 스테이크 시즈닝 822g": (
        "food.seasonings.spices.blend", "/Mccormick-Steak-Seasoning-822g/"
    ),
    "샤브샤브 야채모둠 1.1KG": (
        "food.produce.vegetables.mixed", "/SHABU-SHABU-VEG-MIX-11KG/"
    ),
    "C-WEED 무색소해초샐러드 1kg": (
        "food.meals.prepared.salad", "/C-WEED-Seaweed-Salad-1kg/"
    ),
    "하림 더리얼 밀 냉동 화식 닭고기 60g x 10": (
        "pet.food.feed.dog", "/Harim-The-Real-Meal-Chicken-for-Dogs-60g-x-10/"
    ),
    "하림 더리얼 밀 그레인프리 냉동 화식 닭고기 60g x 10": (
        "pet.food.feed.dog", "/Harim-The-Real-Meal-Grain-Free-Chicken-for-Dogs/"
    ),
}


def reviewed_costco_meat_contaminant_leaf(evidence):
    if evidence["mart"] != "costco" or tuple(evidence["source_path_parts"]) != ("고기",):
        return None
    entry = ENTRIES.get(evidence["source_title"])
    if not entry:
        return None
    leaf, marker = entry
    for url in evidence.get("source_urls", ()):
        parsed = urlparse(url)
        if parsed.hostname in {"costco.co.kr", "www.costco.co.kr"} and marker in parsed.path:
            return leaf
    return None
