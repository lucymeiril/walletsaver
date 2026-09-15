"""Exact drink forms from Emart's broad coffee/beans/tea shelf."""

GROUPS = {
    "food.drinks.coffee.ready": (
        "[매일유업] 마이 카페라떼 220ml*6입 기획",
        "스타벅스 카페 라떼 200ml",
        "강릉커피 라떼 250ml",
        "덴마크 소화가 잘 되는 우유로 만든 카페라떼 250ml",
        "덴마크 소화가 잘되는 우유로만든 바닐라라떼 250ml",
        "레쓰비마일드 175ml*12입",
        "리얼밀크 카페라떼 스위트 950ml",
        "마스터 라떼 500ml",
        "스페셜티 에티오피아 예가체프 460ml",
        "커피타운 딥브라운 모카 250ml",
    ),
    "food.drinks.coffee.mix": ("모카밀크믹스커피250개입",),
    "food.drinks.coffee.instant": ("까페N헤이즐넛향1g*100입",),
    "food.drinks.tea.black": (
        "카페, 진정성 밀크티 350ml",
        "얼그레이 7입",
    ),
    "food.drinks.tea.green": (
        "찬물 하동녹차1.2g*50티백",
        "유기농 말차 45g",
    ),
    "food.drinks.tea.herbal": ("루이보스티 50입",),
    "food.drinks.tea.grain": (
        "[티젠] 카페 오르조 40입",
        "둥글레차 50티백",
        "[대한] 알곡 옥수수차 1kg",
        "누룽지차 100티백",
        "결명자차 18티백 (주전자용)",
    ),
    "food.drinks.tea.barley": ("블랙보리차300g (1.5g*200티백)",),
    "food.drinks.tea.kombucha": ("콤부차 레몬 30입",),
    "food.drinks.tea.fruit_preserve": (
        "[백설]매실청 1.025kg",
        "유기농 광양매실액기스 570g",
        "매실청 570g",
        "생강청 580g",
    ),
}

TITLES = {title: leaf for leaf, titles in GROUPS.items() for title in titles}


def reviewed_emart_coffee_tea_leaf(evidence):
    if evidence["mart"] != "emart":
        return None
    if tuple(evidence["source_path_parts"]) != ("커피/원두/차",):
        return None
    return TITLES.get(evidence["source_title"])
