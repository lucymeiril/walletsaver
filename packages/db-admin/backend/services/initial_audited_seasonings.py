"""Exact reviewed pantry titles. Ingredient and quantity review stay separate."""

GROUPS = {
    "spices.mustard_paste": ("대상 청정원 연 겨자 95G",),
    "spices.wasabi_paste": ("움트리 생와사비 120G", "움트리 육류앤 생와사비 120G"),
    "spices.chili_powder": ("괴산 순정 고춧가루 100G",),
    "spices.cumin": ("브레드가든 쿠민 53G",),
    "spices.parsley": ("신영 파슬리 11G",),
    "spices.star_anise": ("전원식품 팔각(스타아니스) 80G",),
    "spices.roasted_sesame": ("오뚜기 옛날 볶음 참깨 100G", "오뚜기 옛날 볶음 참깨 200G", "해표_볶음참깨_180G"),
    "spices.whole_chili": ("신영 페페로치노홀 20G",),
    "stock.beef": ("CJ 쇠고기다시다 명품골드 100G", "simplus 쇠고기다시 1KG", "simplus 한우다시 300G", "CJ 쇠고기다시다 300G", "CJ 쇠고기다시다 500G", "CJ 쇠고기다시다 명품골드 96G"),
    "stock.seasoned_salt": ("대상 미원 맛소금 250G", "대상 미원 맛소금 500G", "대상 미원맛소금 95G"),
    "stock.umami": ("대상 발효 미원 100G",),
    "stock.chicken": ("대상 청정원 쉐프의 치킨스톡 340G",),
    "stock.vegetable_tablet": ("청정원 맛선생야채국물내기한알 100G",),
    "sauces.broth": ("simplus 샤브샤브 가쓰오육수 500G", "simplus 샤브샤브 야채육수 500G"),
    "syrups.oligosaccharide": ("대상 청정원 요리 올리고당 1.2KG", "CJ 백설 올리고당 1.2KG", "CJ 백설 올리고당 700G", "CJ 백설 요리 올리고당 700G"),
    "syrups.starch": ("오뚜기 옛날 물엿 1.2KG", "simplus 물엿 1.2KG"),
    "syrups.plum": ("청정원 매실청 650G",),
    "syrups.allulose": ("CJ 백설 알룰로스 700G",),
    "syrups.rice": ("simplus 조청쌀엿 1.2KG",),
    "stock.cooking_wine": ("대상 청정원 맛술 830ML", "롯데칠성 미림 900ML", "CJ 백설맛술 생강 800ML"),
}
TITLES = {title: "food.seasonings." + leaf for leaf, titles in GROUPS.items() for title in titles}

# A polluted, broad Emart shelf is not evidence by itself. Only these exact
# independently readable product forms are added; opaque tablet stock and
# unstated sweetener formulation remain unresolved.
EMART_GROUPS = {
    'sauces.pasta': ('홈스타일 토마토 스파게티 소스 400g','백설 토마토 파스타 소스 600g','바질페스토185g','백설 꽃게로제 파스타 소스 430g'),
    'pastes.soy': ('[SSG ONLY] 햇살담은 두번달인진간장840ml*2입기획','CJ 해찬들 맛간장 450ml','CJ 해찬들 진간장 780ml','진간장금F3 1.7L'),
    'sauces.stew': ('다담 고깃집 된장찌개양념 130g','백설 강된장 찌개양념 130g'),
    'stock.seasoned_salt': ('미원 맛소금 250g',),
    'stock.cooking_wine': ('미림 900ml','미림 500ml','생강&매실 맛술 410ml'),
    'sauces.cho_gochujang': ('해찬들 초고추장 1.05kg',),
    'sauces.mayo': ('하인즈 라이트 마요네즈 285ml','고소한 마요네즈 300g'),
    'spices.roasted_sesame': ('볶음참깨 200g',),
    'pastes.ssamjang': ('정성깃든쌈장 500g','순창 쌈장 500g'),
    'baking.brown_sugar': ('[백설] 갈색설탕(중백당) 1kg','백설 자일로스설탕(갈색) 1kg'),
    'spices.wasabi_paste': ('생와사비 43g','생와사비 35g'),
    'sauces.tonkatsu': ('클래식 돈카츠소스 400g','돈까스소스 470g'),
    'stock.chicken': ('백설 치킨스톡 350g','쉐프의 치킨스톡 340g'),
    'oils.olive': ('구즈만 올리브오일 1L','유기농 엑스트라버진 올리브 오일 750ml','올리브오일 500ml(피쿠알)','델파파 유기농 엑스트라 버진 올리브 오일 250ml'),
    'sauces.mustard': ('홀그레인머스타드 200g','홀그레인 머스타드 200g','데일리 머스타드소스335g'),
    'pastes.doenjang': ('해찬들 재래식된장 500g','순창 재래식생된장 500g'),
    'pastes.gochujang': ('해찬들 태양초고추장 500g',),
    'stock.umami': ('발효미원 100g',),
    'syrups.oligosaccharide': ('백설 올리고당 700g',),
    'spices.chili_powder': ('국산 고운 고춧가루 110g',),
    'baking.sea_salt': ('순수천혜염 천일염 가는소금 500g',),
    'sauces.dressing': ('비비드키친 저당 참깨드레싱 235g',),
    'baking.flour': ('중력 밀가루 1kg',),
    'baking.pancake_mix': ('백설 5가지재료 부침가루1kg',),
    'oils.sunflower': ('해바라기유 1L',),
    'spices.whole_chili': ('페페론치노홀 22g(스테인리스&유리병 용기)',),
    'oils.perilla': ('들기름 320ml',),
    'baking.frying_mix': ('백설 5가지재료 튀김가루 1kg',),
    'baking.hotcake_mix': ('[백설] 핫케익 믹스 500g',),
    'baking.pepper': ('통흑후추 그라인더 65g',),
    'sauces.tteokbokki': ('반듯한식 국물떡볶이양념소스_150g',),
}
EMART_TITLES = {title:'food.seasonings.'+leaf for leaf,titles in EMART_GROUPS.items() for title in titles}


def reviewed_seasoning_leaf(evidence):
    path = evidence["source_path_parts"]
    if evidence['mart']=='emart' and path==['양념/오일']:
        return EMART_TITLES.get(evidence['source_title'])
    if evidence["mart"] != "homeplus" or len(path) < 3 or path[0] != "장류/양념/제빵" or path[1] not in {"고추가루/깨/향신료", "다시다/미원/맛소금", "식초/물엿/맛술/액젓"}:
        return None
    return TITLES.get(evidence["source_title"])
