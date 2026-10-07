"""Explicit product-form candidates; pure functions, no IO or database access.

Fallback candidates and literal refinements of broad baked-product leaves.
Ingredients, pet food, mixed kits and unrelated retail contexts are excluded.
"""
import re
from urllib.parse import urlparse

# Named public labels confirm these shapes under the original native SKU and
# original package-image asset. Brand/flavour alone supplies no shape evidence.
REVIEWED_CEREAL_FORMS = (
    ('포스트 오레오 오즈 (500G)', 'https://lottemartzetta.com/products/OS8801037065626/details',
     'food.snacks.cereal.rings', '7149bf1d8a67705acece1e00255b4565d910f8a157040cbb4f3703d388fd73db'),
    ('포스트 오곡코코볼 컵 시리얼 (30G)', 'https://lottemartzetta.com/products/OS8801037096569/details',
     'food.snacks.cereal.balls', '3a0aebded5dac4e41a69923503545d4bed8c2f601e6d95da4289da9749d4f595'),
)

# Public printed form linked to the same native SKU and original package asset.
# This establishes only snack form, never the current recipe or historical amounts.
REVIEWED_NATIVE_SNACK_FORMS = (
    ('costco', ('라면',), '오뚜기 뿌셔뿌셔 불고기맛 1.52kg / 95g x 16',
     'https://www.costco.co.kr/Foods/Snack/CookieCracker/Ottogi-Pusho-Pusho-Bulgogi-flavor-152kg-95g-x16/p/610710',
     'food.snacks.savory.noodle', 'food.snacks.savory.wheat',
     '21a885cca16b8171bfc9b7043a65bedee9a317aa44fa07b0313868b418c39f2a'),
)


def reviewed_native_snack_form_refinement(evidence):
    """Exact native/title/context physical form; no flavour or price transfer."""
    matched = [(leaf, broad) for mart, path, title, url, leaf, broad, _ in REVIEWED_NATIVE_SNACK_FORMS
               if evidence['mart'] == mart and tuple(evidence['source_path_parts']) == path
               and evidence['source_title'] == title and evidence['source_urls'] == [url]]
    return ({matched[0][0]}, {matched[0][1]}) if len(matched) == 1 else (set(), set())


REVIEWED_NATIVE_DRINK_FORMS = (
    ('emart', ('생수/음료/주류',), '에비앙 500ml*12입+쇼퍼백 기획', 'https://emart.ssg.com/item/itemView.ssg?itemId=1000855569590&siteNo=6001&salestrNo=2037', 'food.drinks.water_sets.water_bag', 'food.drinks.water_soda.water', '8d47eafe906426a7ab6d555bac2bfe9f246f0f1c9365085eecc8c3bd793b7c06'),
    ('costco', ('커피',), '루카스나인 우베라떼 18g x 50',
     'https://www.costco.co.kr/Foods/CoffeeTeaDrink/Instant-Coffee/Lookas9-Ube-Latte-18g-x-50/p/695490',
     'food.drinks.powders.ube_latte', 'food.drinks.coffee.mix',
     'cba7b9c15b2ee4d556d99beaeef79f3c05d0aa971a092b405443bc7ab8cf0ad3'),
)


def reviewed_native_drink_form_refinement(evidence):
    """Named native beverage presentation; no recipe, caffeine or legal mineral claim."""
    matched = [(leaf, broad) for mart, path, title, url, leaf, broad, _ in REVIEWED_NATIVE_DRINK_FORMS
               if evidence['mart'] == mart and tuple(evidence['source_path_parts']) == path
               and evidence['source_title'] == title and evidence['source_urls'] == [url]]
    return ({matched[0][0]}, {matched[0][1]}) if len(matched) == 1 else (set(), set())


REVIEWED_NATIVE_PROCESSED_FORMS = (
    ('emart', ('건강식품',), '6년근홍삼정업 2개입세트 (240g*2병) (쇼핑백동봉)', 'https://emart.ssg.com/item/itemView.ssg?itemId=1000633878709&siteNo=7009&salestrNo=2551', 'food.supplements.sets.red_ginseng_bag', 'food.supplements.functional.red_ginseng', '0e13cab8ec0e748a90bef595816a2cb200006c2e6083fdfb519d0368bd4dac52'),
    ('homeplus', ('두부/김치/반찬', '어묵/맛살/단무지', '어묵', '국탕용어묵'),
     '환공어묵 부산명품 물떡 어묵꼬치 10입 460G',
     'https://mfront.homeplus.co.kr/item?itemNo=069798234&storeType=HYPER',
     'food.meals.sets.ricecake_fishcake', 'food.seafood.processed.fishcake',
     '07095902089199df89315d4b51c214a6a3c68ef5862df82eff40ea5156b14717'),
    ('costco', ('치즈',), '천하장사 더블링 콰트로치즈 25g X 40',
     'https://www.costco.co.kr/Foods/Processed-Food/Instant-Food/Double-Ring-Quattro-Cheese-25g-X-40/p/691985',
     'food.seafood.processed.fish_sausage', 'food.meat.processed.sausage',
     'ab288c46a94139a3d5105f841b694468dbefa380ae752b56c6896a5de574d918'),
)


def reviewed_native_processed_form_refinement(evidence):
    """Original native/package-bound processed form, independently of offer eligibility."""
    matched = [(leaf, broad) for mart, path, title, url, leaf, broad, _ in REVIEWED_NATIVE_PROCESSED_FORMS
               if evidence['mart'] == mart and tuple(evidence['source_path_parts']) == path
               and evidence['source_title'] == title and evidence['source_urls'] == [url]]
    return ({matched[0][0]}, {matched[0][1]}) if len(matched) == 1 else (set(), set())

# id, four-level names, required title expression, corroborating source context,
# excluded title expression. No path-only or fuzzy matching.
FORM_RULES = (
 ('food.produce.processed_fruit.fruit_bowl',('식품','농산물','가공과일','냉동과일볼'),r'^(?:아사이|망고)\s*볼(?:\s*\(\s*\d+(?:\.\d+)?\s*[Gg]\s*/\s*팩\s*\))?$',r'^과일\s*>\s*간편[ㆍ·ᆞ]냉동과일\s*>\s*냉동과일$',r'혼합|세트|요거트|요구르트|아이스크림|만들기|재료|[+]' ),
 ('electronics.video.screens.portable',('디지털','영상가전','스크린','포터블스크린'),r'포터블\s*스크린',r'^(?:오반장$|디지털(?: >|$)|영상가전(?: >|$)|영상기기(?: >|$))',r'케이스|커버|파우치|거치대|받침대|스탠드|교체|부품|액세서리|보호\s*필름|세정|청소|혼합|세트|\+|텔레비전|프로젝터|(?:^|\s)TV(?:\s|$)'),
 ('food.drinks.water_sets.water_bag',('식품','음료','생수세트','생수·가방세트'),r'(?:생수|미네랄워터|에비앙).*(?:\+\s*(?:쇼퍼백|쇼핑백)|(?:쇼퍼백|쇼핑백)\s*(?:동봉|포함|증정))',r'생수|음료',r'맛|향|농축|분말|반려|(?:쇼퍼백|쇼핑백)\s*(?:미포함|별도|없음|미동봉)'),
 ('food.supplements.sets.red_ginseng_bag',('식품','건강식품','홍삼제품세트','홍삼제품·가방세트'),r'홍삼(?:정|농축).*(?:\+\s*(?:쇼퍼백|쇼핑백)|(?:쇼퍼백|쇼핑백)\s*(?:동봉|포함|증정))',r'^건강식품(?: >|$)',r'맛|향|화장품|장난감|반려|(?:쇼퍼백|쇼핑백)\s*(?:미포함|별도|없음|미동봉)'),
 ('food.meals.sets.ricecake_fishcake',('식품','간편식·면','복합식품세트','떡·어묵조리세트'),r'(?:떡.*어묵|어묵.*떡).*조리\s*세트',r'밀키트|간편|어묵|반찬',r'반려|만들기\s*도구|장난감|떡국떡'),
 ('food.seafood.processed.fish_sausage',('식품','수산물','수산가공품','어육소시지'),r'어육\s*소시지',r'수산물|간식|햄|어묵|치즈',r'반려|애견|강아지|고양이|만들기|재료|세트|혼합'),
 ('food.drinks.powders.ube_latte',('식품','음료','분말음료','우베라떼분말'),r'우베.*라떼.*(?:분말|파우더)|우베.*(?:분말|파우더).*라떼',r'음료|커피|분말차',r'커피|캡슐|원액|시럽|케이크|과자|반려|혼합'),
 ('food.snacks.savory.snack_sausage',('식품','과자·간식','스낵','간식소시지'),r'간식\s*(?:용\s*)?소시지',r'간식|과자|소시지',r'반려|애견|강아지|고양이|만들기|재료|세트|혼합'),
 ('food.seafood.processed.fish_snack',('식품','수산물','수산가공품','어포스낵'),r'튀김.*어포|어포.*튀[김각]|쥐포.*튀김',r'과자|수산물|건어물|어포',r'반려|애견|강아지|고양이|만들기|재료|세트|혼합'),
 ('food.seafood.processed.semi_dried_fish',('식품','수산물','수산가공품','반건조생선'),r'반건조.*(?:생선|열빙어|민어|고등어|가자미|조기|우럭|갈치)',r'수산물|생선|건어물',r'반려|애견|강아지|고양이|밀키트|조림|탕|세트|혼합'),
 ('food.seafood.processed.dried_pollock',('식품','수산물','수산가공품','건황태'),r'건조\s*황태(?:채)?|건황태',r'수산물|건해산|건어물',r'황태(?:채)?\s*국|국물|탕|육수|소스|무침|찜|스낵|과자|혼합|세트|반려|애견|강아지|고양이'),
 ('household.electrical.power.power_strip',('생활용품','전기용품','전원연결용품','멀티탭'),r'멀티탭',r'전기용품|전원연결|멀티탭',r'거치|보관|정리|커버|케이스|홀더|마운트|교체|수리|부품|혼합'),
 ('food.meat.frozen.pork',('식품','정육·계란','냉동육','냉동돼지고기'),r'냉동.*(?:돼지|삼겹살|목심)|(?:돼지|삼겹살|목심).*냉동',r'정육|육류|축산|돼지고기',r'양념|훈제|소시지|햄|불고기|볶음|덮밥|돈까스|만두|패티|스테이크|찌개|가공|조리|소고기|쇠고기|닭|오리|양고기|혼합|세트|장난감|반려'),
 ('pet.food.feed.cat',('반려동물','먹거리','사료','고양이사료'),r'반려묘\s*사료|고양이\s*사료',r'^반려동물$',r'반려견|강아지|혼합|세트|간식'),
 ('pet.food.feed.dog',('반려동물','먹거리','사료','강아지사료'),r'반려견\s*사료|강아지\s*사료',r'^반려동물$',r'반려묘|고양이|혼합|세트|간식'),
 ('pet.food.treats.chew',('반려동물','먹거리','간식','씹는간식'),r'육포|덴탈(?:껌|스틱|크런치|라이프)|우유껌|내츄럴껌|츄잉스틱|터키츄|칠면조힘줄',r'^반려동물$',r'사료|샴푸|세트|혼합|장난감'),
 ('pet.food.treats.creamy',('반려동물','먹거리','간식','짜먹는간식'),r'츄르|짜먹는',r'^반려동물$',r'사료|샴푸|세트|혼합|장난감'),
 ('pet.food.treats.meat',('반려동물','먹거리','간식','순살간식'),r'간식.*순살|순살.*간식',r'^반려동물$',r'육포|덴탈|껌|츄잉|츄르|짜먹는|사료|샴푸|세트|혼합|장난감'),
 ('pet.food.treats.tofu',('반려동물','먹거리','간식','두부간식'),r'간식.*두부|두부.*간식',r'^반려동물$',r'육포|덴탈|껌|츄잉|츄르|짜먹는|사료|샴푸|세트|혼합|장난감'),
 ('pet.cat.hygiene.litter',('반려동물','고양이용품','배변용품','고양이모래'),r'고양이\s*모래',r'^반려동물$',r'사료|간식|세트|혼합'),
 ('pet.hygiene.waste.pads',('반려동물','위생용품','배변용품','배변패드'),r'배변패드|쉬야응가.*패드',r'^반려동물$',r'세트|혼합'),
 ('household.kitchen.consumables.paper_cup',('생활용품','주방용품','주방소모품','종이컵'),r'종이컵',r'주방',r'뚜껑|세트|혼합|특가|라면|커피믹스'),
 ('household.kitchen.consumables.coffee_filter',('생활용품','주방용품','주방소모품','커피필터'),r'커피\s*필터',r'주방|커피용품|^커피$',r'머신|세트|정수|공기'),
 ('household.kitchen.coffee.dripper',('생활용품','주방용품','커피도구','드리퍼'),r'드리퍼|드립퍼',r'^커피$',r'세트|메이커|머신|필터|커피밀|그라인더|혼합'),
 ('household.kitchen.coffee.manual_grinder',('생활용품','주방용품','커피도구','수동커피밀'),r'커피밀',r'^커피$',r'전동|전자|자동|세트|혼합'),
 ('household.kitchen.coffee.scale',('생활용품','주방용품','커피도구','커피저울'),r'커피\s*전자\s*저울',r'^커피$',r'세트|혼합'),
 ('household.kitchen.consumables.drain_net',('생활용품','주방용품','주방소모품','싱크대거름망'),r'싱크대\s*거름망',r'주방',r'세트|세제'),
 ('household.kitchen.consumables.chopsticks',('생활용품','주방용품','주방소모품','일회용젓가락'),r'나무젓가락|일회용\s*젓가락',r'주방',r'세트|도시락|라면'),
 ('household.kitchen.utensils.scissors',('생활용품','주방용품','조리도구','주방가위'),r'주방가위|불고기\s*가위',r'주방',r'세트|특가|외 BEST|채칼|도마'),
 ('household.kitchen.utensils.turner',('생활용품','주방용품','조리도구','뒤집개'),r'뒤집개',r'주방',r'세트|특가'),
 ('household.kitchen.utensils.slicer',('생활용품','주방용품','조리도구','채칼'),r'채칼',r'주방',r'세트|특가|가위|도마|믹싱볼'),
 ('household.kitchen.cookware.wok',('생활용품','주방용품','조리용기','궁중팬'),r'궁중팬',r'주방',r'세트|특가|뚜껑'),
 ('household.kitchen.consumables.baking_paper',('생활용품','주방용품','주방소모품','종이호일'),r'종이호일',r'주방',r'세트|특가'),
 ('food.drinks.bases.lemon',('식품','음료','음료용 원액','레몬즙'),r'레몬즙',r'^커피/차 > 전통차/액상차/꿀 > 액상차/농축액 > 농축액$',r'에이드|탄산|젤리|세트|혼합|레몬청|\d+\s*[Tt]\b'),
 ('food.drinks.bases.tea_ade',('식품','음료','음료용 원액','차·에이드 베이스'),r'티앤에이드',r'^커피/차 > 전통차/액상차/꿀 > 액상차/농축액 > 농축액$',r'탄산|젤리|세트|혼합|사탕'),
 # The stable leaf also contains declared ginger preserves and plum extracts.
 # Its preparation form does not establish a fruit-only ingredient claim.
 ('food.drinks.tea.fruit_preserve',('식품','음료','차·코코아','청·농축차'),r'(?:생강)?레몬청|자몽청|한라봉청|한라봉차',r'^커피/차 > 전통차/액상차/꿀 > 유자차(?: > 유자차)?$',r'주스|쥬스|탄산|사탕|잼|혼합|세트|유자|녹차|홍차|티백'),
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
 ('food.snacks.assortments.mixed_chips',('식품','과자·간식','혼합간식','혼합칩'),r'칩\s*(?:믹스|모음)',r'^과자$|과자[ㆍ/]',r'만들기|재료|소스'),
 ('food.snacks.assortments.snacks',('식품','과자·간식','혼합간식','스낵모음'),r'스낵\s*모음',r'^과자$|과자[ㆍ/]',r'만들기|재료|소스'),
 ('food.snacks.baked.toast',('식품','과자·간식','구운과자','토스트과자'),r'토스트\s*레귤러',r'^과자$|과자[ㆍ/]',r'샌드위치|만들기|키트'),
 ('food.drinks.juice.ginger_shot',('식품','음료','과채음료','진저샷'),r'진저\s*샷',r'^음료$|생수/음료',r'분말|파우더|캡슐|정제|만들기'),
 ('food.drinks.assortments.combo',('식품','음료','혼합음료','음료콤보'),r'(?:피지오.*[+].*피치딸기|(?:사이다|콜라).*?[+].*?(?:콜라|밀키스).*콤보팩)',r'^음료$|생수/음료',r'분말|파우더|시럽|원액|만들기'),
 ('food.meals.prepared.bbq_ribs',('식품','간편식·면','조리식품','바비큐폭립'),r'바비큐\s*폭립',r'^치즈$|냉장|냉동|간편|델리|조리',r'소스|양념|생고기|원육|폭립맛'),
 ('food.supplements.functional.albumin',('식품','건강식품','건강보조식품','알부민보충식품'),r'알부민',r'^건강식품(?: >|$)',r'화장품|앰플|크림|주사|검사'),
 ('food.bakery.kits.cookie',('식품','베이커리·스프레드','제과키트','쿠키만들기키트'),r'쿠키\s*만들기',r'^냉장/냉동/밀키트 > 아이스크림/디저트/얼음 > 디저트 > 냉동케익/푸딩/마카롱$|제과|제빵',r'장난감|도구만|틀만'),
 ('food.drinks.flavoured.yogurt',('식품','음료','향미음료','요거트맛음료'),r'요거트맛',r'^생수/음료/주류 > 과일/야채음료',r'젤리|사탕|쿠키|분말|파우더|만들기'),
 ('food.snacks.savory.twisted',('식품','과자·간식','스낵','짭짤꽈배기스낵'),r'솔티\s*꽈배기',r'과자|스낵|간식',r'만들기|믹스|재료|빵집'),
 ('food.dairy.yogurt.drinking_greek',('식품','유제품','발효유','마시는그릭요거트'),r'(?:마시는|드링킹)\s*그릭\s*요(?:거|구)트',r'요거트[ㆍ/]요구르트.*마시는요구르트',r'식물성|비건|분말|파우더|쿠키|맛음료'),
 ('food.bakery.assortments.mixed',('식품','베이커리·스프레드','베이커리모둠','혼합베이커리'),r'츄러스\s*[&+]\s*소보로\s*미니크라상',r'베이커리|빵|제과',r'만들기|재료|소스|밀키트'),
 ('food.snacks.baked.crepe',('식품','과자·간식','구운과자','크레페과자'),r'크레페',r'비스켓|비스킷|과자',r'만들기|믹스|재료|반죽|밀키트|혼합|세트|반려'),
 ('food.snacks.baked.waffle',('식품','과자·간식','구운과자','와플과자'),r'와플',r'비스켓|비스킷|과자',r'만들기|믹스|재료|반죽|메이커|기계|혼합|세트|반려'),
 ('food.snacks.baked.crispy_roll',('식품','과자·간식','구운과자','크리스피롤과자'),r'크리스피\s*(?:코코넛\s*)?롤',r'과자|비스켓|비스킷',r'만들기|믹스|재료|반죽|혼합|세트|반려|웨이퍼|웨하스'),
 ('food.snacks.baked.pretzel',('식품','과자·간식','구운과자','프레첼과자'),r'프레첼|프레츠[엘]?',r'과자|비스켓|비스킷',r'만들기|믹스|재료|반죽|혼합|세트|반려'),
 ('food.bakery.dessert.pancake',('식품','베이커리·스프레드','디저트','팬케이크·도라야키'),r'도라야[끼키]|팬케[이익크]+',r'과자|베이커리|빵',r'만들기|믹스|재료|반죽|혼합|세트|반려'),
 ('food.snacks.chewy.rice_cake_pie',('식품','과자·간식','쫀득과자','찰떡파이'),r'찰떡\s*파이',r'과자|파이',r'만들기|믹스|재료|혼합|세트|반려'),
 ('food.snacks.sweets.marshmallow',('식품','과자·간식','단과자','마시멜로'),r'마[시쉬]멜로(?:우)?|(?i:\bmarshmallows?\b)',r'과자|캔디|간식',r'맛|향|초콜릿|젤리|쿠키|비스켓|소스|만들기|믹스|혼합|반려'),
 ('food.snacks.desserts.creme_brulee',('식품','과자·간식','디저트','크렘브륄레'),r'크렘\s*브[뤼륄]레|(?i:creme\s*brulee)',r'과자|디저트|냉장|냉동',r'맛|향|초콜릿|쿠키|아이스크림|만들기|믹스|혼합|반려'),
 ('food.snacks.traditional.monaka',('식품','과자·간식','전통간식','모나카'),r'모나카|(?i:\bmonaka\b)',r'과자|전통|간식',r'아이스크림|맛|향|만들기|믹스|반려'),
 ('food.snacks.traditional.oranda',('식품','과자·간식','전통간식','오란다'),r'오란다',r'과자|전통|간식',r'맛|향|만들기|믹스|반려'),
 ('food.snacks.sets.chocolate_glass',('식품','과자·간식','간식·식기세트','초콜릿·유리컵세트'),r'유리컵\s*기획팩',r'초콜릿',r'컵만|식기만|빈\s*(?:유리)?컵|만들기|장난감|반려'),
 ('food.snacks.savory.tortilla_nacho',('식품','과자·간식','스낵','나초·토르티야칩'),r'나[쵸초]|(?:토티야|토르티야|또띠아)\s*칩',r'과자|스낵|간식',r'나[쵸초](?:치즈)?(?:맛|향)|소스|딥|치즈맛\s*(?:감자|팝콘)|빵|밀키트|반려|만들기'),
 ('food.snacks.assortments.corn_peanut',('식품','과자·간식','혼합간식','옥수수스낵·땅콩혼합'),r'(?:카라멜)?콘\s*(?:과|&|\+)\s*땅콩',r'과자|스낵|간식',r'맛|향|버터|분말|반려|만들기'),
 ('food.snacks.savory.noodle',('식품','과자·간식','스낵','면스낵'),r'(?:라면|마카로니)\s*스낵',r'과자|스낵|간식',r'끓여|조리용|밀키트|반려|만들기'),
 ('food.snacks.savory.puffed',('식품','과자·간식','스낵','팽화스낵'),r'팽화\s*(?:과자|스낵)|퍼프드?\s*스낵',r'과자|스낵|간식',r'맛|향|반려|만들기'),
 ('food.snacks.savory.beans_peas',('식품','과자·간식','스낵','콩·완두스낵'),r'(?:서리태|완두콩|그린피스)\b.*스낵|(?:서리태|완두콩|그린피스)\s*스낵',r'과자|스낵|간식',r'맛|향|단백질|분말|두유|국물|반려|만들기'),
 ('food.snacks.savory.rice_cracker',('식품','과자·간식','스낵','쌀크래커'),r'쌀\s*크래커',r'과자|스낵|간식',r'맛|향|반려|만들기'),
 ('food.drinks.juice.fruit_ade',('식품','음료','과채음료','과일에이드'),r'(?:사과|오렌지|자몽|복숭아|망고|청포도|포도)(?:\s*[/+·]\s*(?:사과|오렌지|자몽|복숭아|망고|청포도|포도))*\s*에이드',r'^(?!.*(?:농축액|분말|원액|시럽))(?:음료$|생수/음료(?:/주류)?(?: > .*)?$|우유/유제품 > 냉장디저트/음료 > 냉장주스(?: > 냉장주스)?$)',r'레몬|맛|향|분말|파우더|원액|농축|베이스|시럽|만들기|사탕|젤리|반려'),
 ('food.drinks.flavoured.strawberry',('식품','음료','향미음료','딸기맛음료'),r'딸기맛',r'^생수/음료/주류 > 과일/야채음료 > 어린이음료(?: > 어린이음료)?$',r'우유|밀크|요거트|요구르트|주스|쥬스|과즙|분말|파우더|젤리|사탕|캔디|아이스크림|아이스바|반려'),
 ('food.drinks.powders.electrolyte',('식품','음료','분말음료','전해질함유분말음료'),r'전해질.*(?:(?:드링크|음료).*(?:파우더|분말)|(?:파우더|분말).*(?:드링크|음료))',r'^음료$|생수/음료|건강식품',r'정제|캡슐|의약|주사|분석|시약|반려|완성음료'),
)

_BAKED_REFINEMENTS = {
    'food.snacks.baked.crepe': {'food.snacks.baked.biscuits'},
    'food.snacks.baked.waffle': {'food.snacks.baked.biscuits'},
    'food.snacks.baked.crispy_roll': {'food.snacks.baked.biscuits'},
    'food.snacks.baked.pretzel': {'food.snacks.baked.cracker', 'food.snacks.baked.biscuits'},
    'food.bakery.dessert.pancake': {'food.snacks.baked.pie', 'food.snacks.baked.cake'},
    'food.snacks.chewy.rice_cake_pie': {'food.snacks.baked.pie'},
    'food.snacks.baked.toast': {'food.snacks.baked.biscuits'},
    'food.snacks.baked.stick': {'food.snacks.baked.biscuits'},
    'food.bakery.dessert.donut': {'food.snacks.baked.biscuits'},
    'food.snacks.baked.cake': {'food.snacks.baked.pie'},
    'food.bakery.dessert.cake': {'food.snacks.baked.cake'},
}


def baked_form_refinement(evidence):
    """Return an explicit physical form and only its subsumed broad leaves.

    A joint shelf is corroboration, never sufficient on its own. Named mixed
    recipes may share a form; this function grants no composition or price facts.
    """
    title = evidence['source_title']
    path = ' > '.join(evidence['source_path_parts'])
    if re.search(r'반려|애견|강아지|고양이|만들기|믹스|재료|반죽|밀키트|혼합세트', title + ' ' + path):
        return set(), set()
    ids = product_form_candidates(evidence) & _BAKED_REFINEMENTS.keys()
    if re.search(r'과자|비스켓|비스킷|파이', path):
        if re.search(r'토스트\s*비스[킷켓]', title):
            ids.add('food.snacks.baked.toast')
        if re.search(r'통밀\s*참깨\s*스틱', title):
            ids.add('food.snacks.baked.stick')
        if re.search(r'도너츠|도넛츠|도넛', title):
            ids.add('food.bakery.dessert.donut')
        # Cake can name a cracker flavour. An explicit cracker shelf does not
        # establish a cake's physical form merely from that flavour string.
        if (re.search(r'케이크', title) and not re.search(r'찰떡|팬케|도라야', title)
                and not re.search(r'크래커', path)):
            ids.add('food.snacks.baked.cake')
    if (re.search(r'바움쿠헨|카스테라', title)
            and (re.search(r'베이커리|빵', path)
                 or any('/Bread/' in str(url) for url in evidence.get('source_urls', ())))):
        ids.add('food.bakery.dessert.cake')
    if len(ids) != 1:
        return set(), set()
    leaf = next(iter(ids))
    return ids, _BAKED_REFINEMENTS[leaf]

def product_form_candidates(evidence):
    title=evidence['source_title']
    path=' > '.join(evidence['source_path_parts'])
    pet_context = bool(re.search(r'반려|애견|펫푸드|강아지|고양이',path+' '+title))
    return {id for id,_,required,context,excluded in FORM_RULES
            if (not pet_context or id.startswith('pet.'))
            and re.search(required,title) and re.search(context,path)
            and not re.search(excluded,title)}


def confection_form_refinement(evidence):
    """Refine related broad confection leaves from literal form plus context.

    Shelf-only flavour/shape assumptions do not replace a prior leaf. Quantity
    and gift-component counts are separate contracts, never inferred here.
    """
    broader = {
        'food.snacks.sweets.marshmallow': {'food.snacks.sweets.candy'},
        'food.snacks.desserts.creme_brulee': {'food.snacks.sweets.pudding'},
        'food.snacks.traditional.monaka': {'food.snacks.traditional.hangwa'},
        'food.snacks.traditional.oranda': {'food.snacks.traditional.hangwa'},
        'food.snacks.sets.chocolate_glass': {'food.snacks.sweets.chocolate'},
    }
    forms = product_form_candidates(evidence) & broader.keys()
    if len(forms) != 1:
        return set(), set()
    return forms, broader[next(iter(forms))]


def reviewed_cereal_form_refinement(evidence):
    """Native-bound physical shapes; no package/count/recipe transfer."""
    if (evidence['mart'] != 'lottemart' or evidence['source_path_parts'] !=
            ['과자ㆍ스낵ㆍ간식', '시리얼', '후레이크']):
        return set(), set()
    forms = {leaf for title, url, leaf, _ in REVIEWED_CEREAL_FORMS
             if title == evidence['source_title'] and evidence['source_urls'] == [url]}
    return (forms, {'food.snacks.cereal.flakes'}) if len(forms) == 1 else (set(), set())


def savory_form_refinement(evidence):
    """A concrete snack preparation refines only related broad material leaves.

    A nacho shelf is polluted by cone and chicken-flavoured snacks. Its name
    alone proves neither tortilla form nor corn material. Flavour supplies no base.
    """
    broader = {
        'food.snacks.savory.tortilla_nacho': {'food.snacks.savory.corn'},
        'food.snacks.assortments.corn_peanut': {'food.snacks.savory.corn'},
        'food.snacks.savory.noodle': {'food.snacks.savory.wheat'},
        'food.snacks.savory.puffed': {'food.snacks.savory.grain'},
        'food.snacks.savory.beans_peas': {'food.snacks.savory.grain', 'food.snacks.savory.vegetable'},
        'food.snacks.savory.rice_cracker': {'food.snacks.savory.grain', 'food.snacks.baked.cracker'},
        'food.meals.rice.nurungji': {'food.snacks.savory.grain'},
    }
    forms = product_form_candidates(evidence) & broader.keys()
    path = ' > '.join(evidence['source_path_parts'])
    rice_ingredient = r'맛|향|차|티백|삼계|부각|사탕|캔디|초콜릿|쿠키|닭|백숙|죽|국물|탕|누룽지\s*(?:팝|과자|스낵)'
    if re.search(rice_ingredient, evidence['source_title']):
        forms.discard('food.meals.rice.nurungji')
    if re.search(r'과자|스낵|간식', path) and not re.search(r'반려|만들기|재료|밀키트', path+' '+evidence['source_title']):
        if re.search(r'누룽지', evidence['source_title']) and not re.search(rice_ingredient, evidence['source_title']):
            forms.add('food.meals.rice.nurungji')
        if evidence['mart'] == 'costco' and evidence['source_path_parts'] == ['과자']:
            for source_url in evidence.get('source_urls', ()):
                url = urlparse(source_url)
                if (url.scheme == 'https' and url.hostname in {'costco.co.kr', 'www.costco.co.kr'}
                        and re.fullmatch(r'/Foods/Snack/CookieCracker/[^/]*Puffed[^/]*Snack[^/]*/p/\d+', url.path, re.I)):
                    forms.add('food.snacks.savory.puffed')
    return (forms, broader[next(iter(forms))]) if len(forms) == 1 else (set(), set())


def beverage_form_refinement(evidence):
    """Literal prepared form refines only related broad beverage leaves.

    Juice content/flavour and a cold mixed shelf are different evidence. No legal
    nutrition class, recipe percentages, carbonation or amounts are inferred.
    """
    broader = {
        'food.drinks.powders.ube_latte': {'food.drinks.coffee.mix'},
        'food.drinks.water_sets.water_bag': {'food.drinks.water_soda.water'},
        'food.drinks.juice.fruit_ade': {'food.drinks.juice.fruit_drink', 'food.drinks.juice.lemonade'},
        'food.drinks.flavoured.strawberry': {'food.drinks.juice.fruit_drink'},
        'food.drinks.powders.electrolyte': {'food.drinks.water_soda.sports'},
        'food.drinks.juice.fruit_vegetable': {'food.drinks.juice.vegetable', 'food.drinks.juice.fruit'},
        'food.drinks.juice.fruit': {'food.drinks.juice.fruit_drink'},
    }
    forms = product_form_candidates(evidence) & broader.keys()
    title = evidence['source_title']; path = ' > '.join(evidence['source_path_parts'])
    ready = (re.search(r'음료|냉장주스', path) and not re.search(r'농축액|분말|원액|시럽', path)
             and not re.search(r'맛|향|파우더|분말|농축|원액|시럽|베이스|재료|캔디|젤리|쿠키|반려', title))
    if ready:
        if re.search(r'(?:사과\s*당근|당근\s*사과)\s*(?:착즙\s*)?주스', title):
            forms.add('food.drinks.juice.fruit_vegetable')
        if re.search(r'100\s*%\s*과즙\s*(?:사과|오렌지|포도|파인애플|자몽|복숭아|망고)', title):
            forms.add('food.drinks.juice.fruit')
    return (forms, broader[next(iter(forms))]) if len(forms) == 1 else (set(), set())


def processed_food_form_refinement(evidence):
    """Declared presentation refines related broad forms, never ingredients."""
    broader = {
        'food.supplements.sets.red_ginseng_bag': {'food.supplements.functional.red_ginseng'},
        'food.produce.processed_fruit.fruit_bowl': {'food.produce.processed_fruit.frozen', 'food.snacks.desserts.smoothie_bowl'},
        'food.seafood.processed.fish_sausage': {'food.meat.processed.sausage'},
        'food.snacks.savory.snack_sausage': {'food.meat.processed.sausage'},
        'food.seafood.processed.fish_snack': {'food.seafood.processed.dried_fish'},
        'food.seafood.processed.semi_dried_fish': {'food.seafood.processed.dried_fish'},
        'food.meat.processed.sausage': {'food.meat.processed.breast'},
        'food.meat.processed.ham': {'food.meat.processed.breast'},
    }
    forms = product_form_candidates(evidence) & broader.keys()
    title = evidence['source_title']; path = ' > '.join(evidence['source_path_parts'])
    excluded = re.search(r'반려|애견|강아지|고양이|만들기|재료|세트|혼합|소스|양념장', title + ' ' + path)
    if not excluded:
        if evidence['source_path_parts'] and evidence['source_path_parts'][-1] == '간식용소시지':
            if re.search(r'소시지|천하장사', title):
                forms.add('food.snacks.savory.snack_sausage')
        if re.search(r'닭가슴살', path) and re.search(r'닭가슴살\s*소시지', title):
            forms.add('food.meat.processed.sausage')
        if re.search(r'닭가슴살', path) and re.search(r'닭가슴살\s*샌드위치햄', title):
            forms.add('food.meat.processed.ham')
        if re.search(r'어포', title) and re.search(r'과자', path):
            for source_url in evidence.get('source_urls', ()):
                url = urlparse(source_url)
                if (url.scheme == 'https' and url.hostname in {'costco.co.kr', 'www.costco.co.kr'}
                        and re.fullmatch(r'/Foods/Snack/[^/]+/[^/]*Fish-Snack[^/]*/p/\d+', url.path, re.I)):
                    forms.add('food.seafood.processed.fish_snack')
    return (forms, broader[next(iter(forms))]) if len(forms) == 1 else (set(), set())
