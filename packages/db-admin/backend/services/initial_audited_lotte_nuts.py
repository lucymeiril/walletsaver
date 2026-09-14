"""Exact readable product forms in the mixed Lotte grain/nut shelf."""
PATH=('쌀ㆍ잡곡ㆍ견과류',)
GROUPS={
 'food.grains.nuts.pecan': ('바삭한 피칸 (120G)',),
 'food.grains.nuts.peanut': ('볶음 땅콩 (450G)',),
 'food.grains.nuts.cashew': ('구운 껍질캐슈넛 (180G)',),
 'food.grains.nuts.pistachio': ('피스타치오 (170G)',),
 'food.grains.nuts.pumpkin_seed': ('구운 호박씨 (300G)',),
 'food.grains.nuts.macadamia': ('오늘좋은 통마카다미아 (250G)','오늘좋은 바닐라향 마카다미아 (40G)'),
 'food.grains.nuts.almond': ('HBAF 와사비맛 아몬드 (120G)','오늘좋은 허니버터 아몬드 (50G)','HBAF 군옥수수맛 아몬드 (120G)','오늘좋은 와사비향 아몬드 (50G)','HBAF 쿠키앤크림 아몬드 (120G)','오늘좋은 군옥수수맛 아몬드 (50G)','HBAF 마늘빵 아몬드 (120G)'),
 'food.grains.nuts.mixed': ('HBAF 스낵믹스넛 짭짤고소 (200G)','매일 견과 (20G*10입)','매일견과 하루한줌 80봉 (1280G)','베스트견과 3MIX (190G)','펍 앤 믹스너츠 (450G)','넛츠박스 매일견과 20봉 (360G)'),
 'food.produce.processed_fruit.dried': ('테일러 말린 무화과 (170G)','오늘좋은 건포도 (400G)'),
 'food.snacks.savory.vegetable': ('바삭한 골든고구마칩 (200G)','달콤한 자색고구마칩 (240G)','그린너트 단호박칩 (200G)'),
 'food.snacks.savory.fruit': ('사바 바나나칩 (250G)','바나나칩 (400G)'),
}
TITLES={title:leaf for leaf,titles in GROUPS.items() for title in titles}


def reviewed_lotte_nut_leaf(evidence):
    if evidence['mart']!='lottemart' or tuple(evidence['source_path_parts'])!=PATH:
        return None
    return TITLES.get(evidence['source_title'])
