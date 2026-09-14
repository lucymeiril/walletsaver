"""Explicit snack forms read from Emart's mixed snack shelf; no brand guesses."""
GROUPS={
 'food.snacks.baked.cracker': ('4번 구운 야채 크래커300g','통밀 크리스프 크래커 무화과&씨드','빠삭한 크래커 새우맛 200g'),
 'food.snacks.baked.biscuits': ('초코칩쿠키 256G','오트 초코칩쿠키 208g','옹골진 오곡쿠키 288g'),
 'food.snacks.baked.sandwich': ('신상 해태 샌드에이스 크림라떼맛 204g','해태 샌드에이스 우유크림 204g'),
 'food.snacks.baked.pie': ('초코파이 정 새로운시작 12팩 468g (39g*12팩)','크라운 빅파이 제주레몬허니 324g','롯데 명가찰떡파이 350g (패키지 랜덤 발송)'),
 'food.snacks.baked.wafer': ('웨하스스틱 초코(15g*5봉지) 75g',),
 'food.snacks.savory.potato': ('감자칩오리지날 160g',),
 'food.snacks.savory.vegetable': ('자색고구마칩 160 g',),
 'food.snacks.savory.grain': ('한입쌀과자 250g',),
 'food.snacks.savory.wheat': ('라면스낵 250g',),
 'food.snacks.savory.popcorn': ('팝콘 버터솔트맛 80g',),
 'food.snacks.savory.corn': ('도도한나쵸 155g',),
 'food.snacks.bars.protein': ('닥터유 단백질바 퀵차지팩 445g','단백질바미니 224 g'),
 'food.meat.processed.sausage': ('출출할때 먹는 간식소시지 300g',),
 'food.bakery.dessert.cake': ('미니카스텔라인절미 100g',),
 'food.meals.prepared.rice_cake': ('창억 호박인절미 500g',),
 'food.drinks.water_soda.ice': ('퓨어아이스 2.5kg','돌얼음 3kg'),
}
TITLES={title:leaf for leaf,titles in GROUPS.items() for title in titles}


def reviewed_emart_snack_leaf(evidence):
    if evidence['mart']!='emart' or tuple(evidence['source_path_parts'])!=('과자/간식',):
        return None
    return TITLES.get(evidence['source_title'])
