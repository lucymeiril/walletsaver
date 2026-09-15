"""Explicit drink and frozen-drink forms from Costco's mixed beverage shelf."""
GROUPS={
 'food.drinks.juice.aloe': ('알로에 베라 500ml x 24',),
 'food.drinks.juice.smoothie': ('옐로우스무디350ml x 24',),
 'food.drinks.juice.lemonade': ('델몬트 스퀴즈 사과/오렌지 에이드 240ml x 30 x 2팩','커클랜드 시그니춰 유기농 레몬에이드 2.84L x 2','나탈리스레몬에이드 1L x 4','링티 쿨가드 레몬에이드 11.6g x 28'),
 'food.drinks.juice.fruit': ('롯데쌕쌕오렌지 240ml x 30 x 96','롯데쌕쌕오렌지 240ml x 30','나탈리스오렌지비트1Lx4','나탈리스오렌지망고 1Lx4','나탈리스오렌지파인애플1Lx4'),
 'food.drinks.juice.fruit_drink': ('피크닉천도복숭아 240ML X 24',),
 'food.drinks.tea.grain': ('설빙 옛날 미숫가루 24g x 50','국산서리태귀리쉐이크 1.5kg'),
 'food.drinks.tea.ready': ('양반오미자차 500ml x 24병',),
 'food.drinks.tea.fruit_preserve': ('본비 꿀매실청 2kg','본비 생강청 2kg'),
}
TITLES={title:leaf for leaf,titles in GROUPS.items() for title in titles}


def reviewed_costco_beverage_leaf(evidence):
    if evidence['mart']!='costco' or tuple(evidence['source_path_parts'])!=('음료',):
        return None
    title=evidence['source_title']
    if title=='폴라레티 후르트 아이스바 40ml x 80' and any('/Frozen-Foods/' in url and 'Ice-Bar-' in url for url in evidence.get('source_urls',())):
        return 'food.frozen.dessert.ice_bar'
    return TITLES.get(title)
