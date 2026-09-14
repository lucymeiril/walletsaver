"""Exact kimchi versus ingredient/prepared forms in the mixed kimchi shelf."""
GROUPS={
 'food.preserved.kimchi.cabbage': ('아워홈포기김치 10kg x 1','종가집 포기배추김치3kgx2','농협 선장맛김치 3KG X 2'),
 'food.preserved.kimchi.bossam': ('종가 김치공방 보쌈김치 1kg x 2',),
 'food.preserved.kimchi.green_onion': ('농협선장파김치 1kg x 3',),
 'food.preserved.kimchi.aged': ('비비고 묵은지 900g X 3ea',),
 'food.meals.prepared.soup_stew': ("Mama's Choice 돼지고기 김치찜 700g x 3",'오뚜기 청주식 돼지김치짜글이 450g x 12'),
 'food.seasonings.spices.chili_powder': ('햇님마을 굵은 고춧가루 100g x 4','남안동농협 고춧가루 1kg'),
 'food.preserved.sides.salted_shrimp': ('새우젓 2kg X 2pack',),
 'food.meals.prepared.seasoned_meat': ('오늘차림 한돈 고추장 제육볶음 600g x 3ea',),
 'food.meals.noodles.udon': ('CJ얼큰우동한그릇용기221g X 10ea',),
 'food.preserved.sides.stir_fried': ('비비고 견과류 멸치볶음 60g x 6',),
}
TITLES={title:leaf for leaf,titles in GROUPS.items() for title in titles}


def reviewed_costco_kimchi_form_leaf(evidence):
    if evidence['mart']!='costco' or tuple(evidence['source_path_parts'])!=('김치',):
        return None
    return TITLES.get(evidence['source_title'])
