"""Official-URL-corroborated forms in Costco's mixed snack shelf."""
from urllib.parse import urlparse

ENTRIES={
 '신라명과 달콤바삭 크룽지 25g x 15입':('food.snacks.baked.biscuits','Crungji-'),
 'Crispconut 코코넛칩 40g x 10':('food.produce.processed_fruit.dried','Coconut-Chip-'),
 'Snapik 화이트 마시멜로우 1kg x 176':('food.snacks.sweets.candy','White-Marshmallow-'),
 'Green Nut 호두 정과 800g':('food.grains.nuts.walnut','Caramelized-Walnuts-'),
 '후레시컷믹스컵과일 150g x 8팩':('food.produce.processed_fruit.cup','Freshcut-Mix-Cup-Fruits-'),
 '바삭하고 고구마 300G':('food.produce.processed_vegetables.dried','BASACHAGO-SWEET-POTATO'),
 '해태 홈런볼 초코 768g / 128g x 6':('food.snacks.baked.biscuits','Haitai-Homerun-Ball-'),
 '테라칩 클래식 567G':('food.snacks.savory.vegetable','TERRA-CHIPS-CLASSIC-'),
 'CJ 비비고 칩 40g x 10개':('food.snacks.savory.seaweed','CJ-Bibigo-Seaweed-Chip-'),
 '베베쿡 사르르쿵 23g x 10':('food.snacks.savory.grain','Bebecook-Melting-Puffed-Snack-'),
 '베베쿡 처음먹는 빼빼롱뻥 30g x 10':('food.snacks.savory.grain','Bebecook-First-Puffed-Stick-Snack-'),
 '화과방 우유앙빵 35g x 15입 x 5':('food.bakery.bread.filled','Hwakwabang-Milk-Manju-'),
 '상하이 Style 쫀득 황치즈 버터떡빵 40g x 10':('food.bakery.bread.filled','Shanghai-Style-Cheese-Butter-Bread-40g-x-10/'),
 'Tropical Fields 크리스피 코코넛롤400g':('food.snacks.baked.biscuits','Tropical-Fields-Crispy-Coconut-Roll-'),
 '쫀득하갱 팥 & 고구마 데이 1620g / 540g x 3pk':('food.snacks.traditional.yanggaeng','Hwakwabang-Red-BeanSweet-Potato-Paste-Jelly-'),
 '종합 모나카 840g / 280g X 3':('food.snacks.traditional.hangwa','Assorted-Monaka-'),
 '양구 사과세트 5kg':('food.produce.fruit.apple','Yanggu-Apple-Gift-Set-'),
 '아리수 사과 5kg 선물세트':('food.produce.fruit.apple','Arisu-Apple-Gift-Set-'),
}


def reviewed_costco_snack_form_leaf(evidence):
    if evidence['mart']!='costco' or tuple(evidence['source_path_parts'])!=('과자',): return None
    entry=ENTRIES.get(evidence['source_title'])
    if not entry: return None
    leaf,marker=entry
    return leaf if any(urlparse(url).hostname in {'costco.co.kr','www.costco.co.kr'} and marker in url for url in evidence.get('source_urls',())) else None
