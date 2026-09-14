"""Reviewed produce/organic titles; organic is an attribute, not a food type."""

GROUPS = {
    "food.produce.vegetables.eggplant": ("가지 (5입/봉)", "알뜰 가지 (5입) 봉"),
    "food.produce.vegetables.cabbage": ("눈꽃 양배추 White (400g)",),
    "food.produce.vegetables.onion": ("단단한 양파 (4입/팩)", "친환경 양파 1kg/망", "친환경 한끼 양파 2입/망 (400g)"),
    "food.produce.vegetables.chives": ("부추 300g", "부추컷팅 (110g/팩)"),
    "food.produce.vegetables.leaf": ("양상추 300g(1입)", "친환경 청상추 120g/봉", "친환경 추부깻잎 20장*2입/봉 (25g*2)"),
    "food.produce.vegetables.mushroom": ("[신선장인] 한갑규 친환경 느타리버섯 200g/팩", "유기농 표고버섯 200g/팩", "친환경 미니표고 150g/팩", "친환경 표고버섯 150g/팩", "친환경 표고슬라이스 150g/팩", "친환경 흰 목이버섯 150g/팩"),
    "food.produce.vegetables.garlic": ("친환경 깐마늘 150g/봉",),
    "food.produce.vegetables.sweet_potato": ("친환경 꿀고구마(베니하루카) 1.5kg/박스",),
    "food.produce.vegetables.carrot": ("친환경 주스용당근 1kg/봉",),
    "food.produce.vegetables.scallion": ("친환경 줄기대파 200g/봉", "친환경 파채 150g/팩"),
    "food.produce.vegetables.sprouts": ("유기농 콩나물 270g",),
    "food.produce.processed_vegetables.blanched": ("데친 고사리 (400g)",),
    "food.produce.processed_vegetables.frozen": ("[냉동] 유기농 다진 청양고추 180g",),
    "food.bakery.spreads.fruit": ("유기농 딸기잼 340g", "유기농 블루베리잼 340g"),
    "food.seasonings.baking.rice_flour": ("무농약 찹쌀가루 500g",),
    "food.seasonings.baking.oat_flour": ("자연담은 유기농 오트밀 가루 500g",),
    "food.seasonings.oils.olive": ("델파파 유기농 엑스트라 버진 올리브 오일 250ml",),
    "food.produce.processed_fruit.dried": ("썬뷰 유기농 건청포도 198g", "건포도 300g"),
    "food.drinks.juice.vegetable": ("아침에주스 유기농 토마토주스 900ml", "유기농 야채농장 760ml (190mlx4입)"),
    "food.meat.fresh.pork": ("[냉동] 설성목장 무항생제 한돈 대패목살 300g", "[냉동] 설성목장 무항생제 한돈 대패삼겹살300g", "[냉동] 설성목장 무항생제 한돈 옛날 복고삼겹살 300g", "[냉장] 설성목장 무항생제 한돈 앞다리 불고기400g"),
}
TITLES = {title: leaf for leaf, titles in GROUPS.items() for title in titles}

# Reviewed single-fruit listings only. A range may establish fruit identity,
# but must still fail the independent fixed-quantity contract. No approximate
# weight, mixed gift or inferred new alias is accepted by this table.
FRUIT_GROUPS = {
    "emart": {
        "food.produce.fruit.peach": ("부드러운 복숭아 4~6입 팩", "아삭한 복숭아 4~6입 팩"),
    },
    "lottemart": {
        "food.produce.fruit.peach": ("정감 부드러운 복숭아 (4-7입/박스)",),
        "food.produce.fruit.pear": ("천안배 (배 5-6입)", "나주 최종기 농부의 하우스배 (배 7-11입)", "천안 지순태 농부의 GAP 배 (배 8-9입)"),
        "food.produce.fruit.melon": ("AI로 선별한 머스크 메론 (메론4입)",),
        "food.produce.fruit.kiwi": ("제스프리 그린키위 (22~25입)", "제스프리 골드키위 (20~25입)"),
        "food.produce.fruit.mango": ("태국산 망고 (태국망고 9입)",),
        "food.produce.processed_fruit.dried": ("상주곶감(복) (곶감30입)", "상주 곶감 (정) (상주곶감 30입)", "상주 무농약 왕곶감 (곶감 24입)", "청도 실속 반건시 (반건시 20입)", "GAP 청도 반건시 (반건시 30입)", "상주 왕 곶감 (상주곶감 32입)"),
    },
}
FRUIT_TITLES = {mart: {title: leaf for leaf, titles in groups.items() for title in titles}
                for mart, groups in FRUIT_GROUPS.items()}


def reviewed_emart_produce_leaf(evidence):
    if tuple(evidence["source_path_parts"]) == ("과일",):
        fruit = FRUIT_TITLES.get(evidence["mart"], {}).get(evidence["source_title"])
        if fruit:
            return fruit
    if evidence["mart"] != "emart" or tuple(evidence["source_path_parts"]) not in {("채소",), ("친환경/유기농",), ("과일",), ("쌀/잡곡/견과",)}:
        return None
    return TITLES.get(evidence["source_title"])
