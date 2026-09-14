"""Readable processed food forms inside Costco's polluted fruit shelf.

Exact evidence only; mixed fresh gifts, approximation and bulk quantity review
remain separate from classification. Fruit-flavoured tea is not fresh fruit.
"""
GROUPS={
 'food.drinks.tea.kombucha': ('티젠 피치 콤부차 5g x 30ct x 2','티젠 파인애플 콤부차 5g x 30ct x 2','티젠 매실 콤부차 5g x 30ct x 2','티젠 유자 콤부차 5g x 30ct x 2','티젠 샤인머스캣 콤부차 5g x 30ct x 2','티젠 레몬 콤부차 5g x 30ct x 2','티젠 스트로베리 & 키위 콤부차 5g x 30ct x 2','티젠 청귤라임 콤부차 5g x 30ct x 2','티젠 망고구아바 콤부차 5g x 30ct x 2','티젠 베리 콤부차 5g x 30ct x 2'),
 'food.drinks.juice.fruit': ('덴마크스위티 자몽 주스 200ml x 24','니피스 애플주스 1L X 6','마티넬리 사과주스 PET 296ml x 24 x 77'),
 'food.bakery.spreads.fruit': ('Solestado 무화과스프레드700g x 648','Solestado 무화과스프레드700g x 324','퀸즈트리 블루베리 잼 1kg'),
 'food.snacks.sweets.jelly': ('닥터큐 후룻 젤리1,440g / 60g x 24',),
 'food.produce.processed_fruit.dried': ('프리미엄 대봉곶감 선물세트 1.3kg (16입)','프리미엄 유명산지 모듬곶감 선물세트 1.4kg (30입)','상주곶감선물세트30입(1.4kg) X 50CT','반건시곶감세트1.9kg (28입)','명품 왕대봉 곶감세트 2.5kg (24입)'),
 'food.drinks.tea.black': ('4C 아이스티 복숭아맛 2.34kg',),
}
TITLES={title:leaf for leaf,titles in GROUPS.items() for title in titles}


def reviewed_costco_fruit_form_leaf(evidence):
    if evidence['mart']!='costco' or tuple(evidence['source_path_parts'])!=('과일',):
        return None
    return TITLES.get(evidence['source_title'])
