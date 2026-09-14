"""Explicit product-form candidates; pure functions, no IO or database access.

Only used when the existing classifier has no candidate. Ingredients, pet food,
mixed kits and unrelated retail contexts must not create a positive match.
"""
import re

# id, four-level names, required title expression, corroborating source context,
# excluded title expression. No path-only or fuzzy matching.
FORM_RULES = (
 ('food.drinks.tea.fruit_preserve',('식품','음료','차·코코아','과일청차'),r'(?:생강)?레몬청|자몽청|한라봉청|한라봉차',r'^커피/차 > 전통차/액상차/꿀 > 유자차(?: > 유자차)?$',r'주스|쥬스|탄산|사탕|잼|혼합|세트|유자|녹차|홍차|티백'),
 ('food.seasonings.cooking_herbs.samgyetang',('식품','양념·소스','조리용 건재료','삼계 조리재료'),r'삼계\s*재료',r'건채소|건약재',r'누룽지|찹쌀|닭|삼계탕|완성|밀키트'),
 ('food.drinks.bases.calamansi',('식품','음료','음료용 원액','깔라만시 원액'),r'100%\s*깔라만시|깔라만시\s*100(?:\s|$)',r'액상차/농축액.*농축액',r'에이드|탄산|젤리|세트|혼합'),
 ('household.kitchen.gloves.rubber',('생활용품','주방용품','주방장갑','고무장갑'),r'고무장갑',r'주방|청소|생활용품',r'니트릴'),
 ('household.kitchen.gloves.nitrile',('생활용품','주방용품','주방장갑','니트릴장갑'),r'니트릴\s*장갑',r'주방',r'의료|수술'),
 ('household.kitchen.cleaning.scourer',('생활용품','주방용품','주방청소도구','수세미'),r'수세미',r'주방|세제|청소',r'차|즙|열매|씨앗'),
 ('household.kitchen.cleaning.cloth',('생활용품','주방용품','주방청소도구','행주'),r'행주',r'주방',r'비누|세제'),
 ('household.bath.accessories.shower_ball',('생활용품','욕실용품','목욕소품','샤워볼'),r'샤워볼',r'욕실|바디|청소/생활',r'워시|젤'),
 ('household.bath.accessories.towel',('생활용품','욕실용품','목욕소품','목욕타월'),r'샤워타[월올]|때타[월올]|때밀이',r'욕실|바디|청소/생활',r'워시|젤|비누'),
 ('household.bath.textiles.towel',('생활용품','욕실용품','욕실직물','수건'),r'타월|타올|수건',r'욕실|타월',r'종이|키친|샤워|때밀이|때타|행주|청소'),
 ('household.kitchen.storage.bag',('생활용품','주방용품','식품보관용품','식품보관백'),r'롤백|지퍼백|위생백',r'주방',r'쓰레기|의류'),
 ('household.kitchen.utensils.tongs',('생활용품','주방용품','조리도구','조리집게'),r'집게',r'주방|조리도구',r'빨래|머리|미용'),
 ('food.snacks.sweets.gum',('식품','과자·간식','단과자','껌'),r'껌|롯데\s*자일리톨',r'과자|껌|간식',r'애견|강아지|반려|치약'),
 ('food.meat.processed.jerky',('식품','정육·계란','가공육','육포'),r'육포',r'건어|수산|고기|간식|오반장|과자|육포',r'애견|반려|강아지|고양이|아미오|정직하개'),
 ('food.meals.rice.nurungji',('식품','간편식·면','밥·죽','누룽지'),r'누룽지',r'곡물|견과|쌀|누룽지|라면|즉석',r'차|티백|삼계|재료|부각'),
 ('food.preserved.kimchi.kkakdugi',('식품','반찬·저장식품','김치','깍두기'),r'깍두기',r'김치|반찬',r'볶음밥|양념'),
 ('food.preserved.sides.danmuji',('식품','반찬·저장식품','밑반찬','단무지'),r'단무지',r'반찬|단무지|김밥',r'세트|키트|김밥재료|우엉'),
 ('food.meals.prepared.jokbal',('식품','간편식·면','조리식품','족발'),r'족발',r'냉장|냉동|델리|반찬|밀키트',r'양념|소스'),
 ('food.meals.prepared.cheese_stick',('식품','간편식·면','조리식품','치즈스틱'),r'치즈스틱',r'냉장|냉동|델리|간편',r'과자|스낵'),
 ('food.bakery.bread.tortilla',('식품','베이커리·스프레드','빵','또띠아'),r'또띠아|토르티야',r'또띠아|빵|베이커리|냉장|면류',r'칩|랩샌드|브리또'),
 ('food.meals.prepared.frozen_potato',('식품','간편식·면','조리식품','냉동감자튀김'),r'감자튀김|크링클컷|냉동감자|케이준 양념감자|스파이스웨지',r'냉동|냉장',r'과자|칩'),
)

def product_form_candidates(evidence):
    title=evidence['source_title']
    path=' > '.join(evidence['source_path_parts'])
    if re.search(r'반려|애견|펫푸드|강아지|고양이',path+' '+title):
        return set()
    return {id for id,_,required,context,excluded in FORM_RULES
            if re.search(required,title) and re.search(context,path)
            and not re.search(excluded,title)}
