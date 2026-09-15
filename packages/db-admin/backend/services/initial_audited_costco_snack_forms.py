"""Official-URL-corroborated forms in Costco's mixed snack shelf."""
from urllib.parse import urlparse

ENTRIES={
 '신라명과 달콤바삭 크룽지 25g x 15입':('food.snacks.baked.biscuits','Crungji-'),
 'Crispconut 코코넛칩 40g x 10':('food.produce.processed_fruit.dried','Coconut-Chip-'),
 'Snapik 화이트 마시멜로우 1kg x 176':('food.snacks.sweets.candy','White-Marshmallow-'),
 'Green Nut 호두 정과 800g':('food.grains.nuts.walnut','Caramelized-Walnuts-'),
 '후레시컷믹스컵과일 150g x 8팩':('food.produce.processed_fruit.cup','Freshcut-Mix-Cup-Fruits-'),
}


def reviewed_costco_snack_form_leaf(evidence):
    if evidence['mart']!='costco' or tuple(evidence['source_path_parts'])!=('과자',): return None
    entry=ENTRIES.get(evidence['source_title'])
    if not entry: return None
    leaf,marker=entry
    return leaf if any(urlparse(url).hostname in {'costco.co.kr','www.costco.co.kr'} and marker in url for url in evidence.get('source_urls',())) else None
