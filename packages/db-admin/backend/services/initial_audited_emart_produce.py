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


def reviewed_emart_produce_leaf(evidence):
    if evidence["mart"] != "emart" or tuple(evidence["source_path_parts"]) not in {("채소",), ("친환경/유기농",), ("과일",), ("쌀/잡곡/견과",)}:
        return None
    return TITLES.get(evidence["source_title"])
