"""Exact food forms audited on Lottemart's mixed vegetable shelf."""

GROUPS = {
    "food.produce.vegetables.sprouts": (
        "풀무원 특등급 무농약 국산 콩나물 (340G)", "풀무원 국산 숙주나물 (260G)",
        "오늘좋은 더 많은 콩나물 (400G)", "CJ 행복한콩 안심콩나물 (500G/봉)",
        "풀무원 특등급 국산 콩나물 (200G)", "오늘좋은 숙주나물 (380G)",
    ),
    "food.plant.soy.tofu": (
        "오늘좋은 더 큰 두부 (400G)", "오늘좋은 1등급 국산콩 두부 기획 (300G*2입)",
        "강릉초당두부 (550G)", "풀무원 Soga두부 (찌개용) (300G)",
    ),
    "food.produce.vegetables.pumpkin": ("국내산 킹단호박 (개)",),
    "food.produce.vegetables.scallion": ("대파 (700G/봉)",),
    "food.produce.vegetables.carrot": ("당근 (200G)",),
    "food.produce.vegetables.cucumber": ("국내산 다다기오이 (5입/봉)", "국내산 다다기오이 (개)"),
    "food.produce.vegetables.mushroom": ("GAP 친환경 뿌리손질 새송이버섯 (600G/봉)", "GAP 친환경 향기로운 송이버섯 (230G*2/봉)"),
    "food.produce.vegetables.lettuce": ("양상추 (봉)",),
    "food.produce.vegetables.broccoli": ("브로콜리 (1입/봉)",),
    "food.produce.vegetables.pepper": ("국내산 파프리카 (개)",),
    "food.produce.vegetables.onion": ("소용량 양파 (2입/망)",),
    "food.produce.vegetables.garlic": ("소용량 깐마늘 (60G/봉)",),
    "food.produce.vegetables.potato": ("감자 (1.5KG)",),
}

TITLES = {title: leaf for leaf, titles in GROUPS.items() for title in titles}


def reviewed_lotte_vegetable_leaf(evidence):
    if evidence["mart"] != "lottemart" or tuple(evidence["source_path_parts"]) != ("채소",):
        return None
    return TITLES.get(evidence["source_title"])
