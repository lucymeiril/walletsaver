"""Exact declared grain versus cooked-food forms, not shelf-only inference."""
GROUPS={
 'food.grains.rice.white': ('김화 농협 철원 오대쌀 10kg','예산농협 삼광쌀10kg x 2','팽성농협 장원급제 쌀 4kg x 2','예산농협 황금쌀10kg x 2','여주시 농협 여주쌀 10kg','팽성농협 고시히카리쌀 10kg x 2','푸른들판 유기농쌀 골든퀸 8kg x 2'),
 'food.grains.rice.barley': ('대구농산 흰찹쌀보리쌀 5kg','유기농 쌀보리 1kg x 6'),
 'food.grains.rice.millet': ('미이랑 찰기장쌀2kg',),
 'food.grains.rice.brown': ('팽성농협 아끼바레 현미 5kg x 2','팽성농협 슈퍼오닝 현미 5kg x 2'),
 'food.grains.rice.mixed': ('미이랑 국내산 가바오색현미 5kg','미이랑 파로 혼합 15곡 5kg'),
 'food.grains.rice.quinoa': ('대구농산 퀴노아 1.8kg',),
 'food.grains.rice.farro': ('월드그린 파로2kg /최소구매 2',),
 'food.grains.rice.oat': ('커클랜드 시그니춰 압착귀리 4.54kg',),
 'food.meals.rice.instant': ('햇반 쌀눈가득 쌀밥 210g x 18','오뚜기오뚜기밥 큰밥 300g x 18개','오뚜기밥오곡210g x 18','오뚜기 신동진 큰밥 300g x 18','CJ 햇반 발아현미밥 210g x 18','CJ 햇반 둥근햇반 210g x 36','햇반 이천 쌀밥 210g x 18개','오뚜기 오뚜기밥 작은밥 150g x 30개','오뚜기 오뚜기밥 발아현미 210g x 18개','오뚜기 오뚜기밥 발아흑미210g x 18개','오뚜기 오뚜기밥 고시히카리 210g x 18개'),
 'food.meals.rice.sticky': ('봉하쌀영양찰밥230g x 6 x 2',),
 'food.seasonings.baking.flour': ('농협 우리밀 참밀가루 3kg',),
 'food.seasonings.pastes.gochujang': ('해찬들태양초고추장1.8kg x 2',),
 'food.meals.noodles.rice_noodle': ('애슐리 우삼겹 듬뿍 베트남 쌀국수 600g x 2ea',),
 'food.meals.prepared.tteokbokki': ('CJ 미정당 국물떡볶이401.2g x 8','CJ 미정당 순쌀떡볶이401.2g x 8','양반 로제떡볶이 1,080g'),
 'food.meals.prepared.soup_stew': ('백제 햅쌀 쌀떡국 163g x 16',),
}
TITLES={title:leaf for leaf,titles in GROUPS.items() for title in titles}


def reviewed_costco_rice_form_leaf(evidence):
    if evidence['mart']!='costco' or tuple(evidence['source_path_parts'])!=('쌀',):
        return None
    return TITLES.get(evidence['source_title'])
