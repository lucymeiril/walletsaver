"""Conservative, reviewable taxonomy for the first real four-mart catalog.

This module has no database or network side effects and deliberately does not
import the legacy category/keyword seed.  It is an initial classification aid,
not an automatic publication approval.  ``classify_record`` accepts a crawler
payload, or a normalized observation with that payload in ``payload`` or
``raw_payload``.  It always returns the original source-path evidence as well as
the decision, including for unresolved rows.

The curated leaves consolidate mart merchandising trees into product types.
Source labels are compared as complete labels: slashes and middle dots are
never interpreted as hierarchy separators.  In particular, an Emart label such
as ``우유/유제품`` is one broad node, not two nested categories.
"""
from __future__ import annotations

from services.initial_audited_food import AUDITED_EMART_FOOD_TITLES
from services.initial_audited_household import AUDITED_EMART_HOUSEHOLD_TITLES

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import hashlib
import json
import re
import unicodedata
from urllib.parse import unquote, urlsplit
from typing import Any


MAX_CATEGORY_LEVEL = 3  # A domain root is level zero: at most four nodes.


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _label_key(value: Any) -> str:
    # Normalize punctuation *within* a label; do not split it into a path.
    text = _text(value).replace("ㆍ", "/").replace("·", "/").replace("ᆞ", "/")
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).casefold()


def _tokens(value: Any) -> tuple[str, ...]:
    return tuple(re.findall(r"[a-z0-9가-힣]+", unicodedata.normalize("NFKC", _text(value)).casefold()))


def _alternatives(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split("|") if part.strip())


@dataclass(frozen=True)
class Leaf:
    id: str
    path: tuple[str, str, str, str]
    source_labels: tuple[str, ...]
    context_labels: tuple[str, ...]
    name_terms: tuple[str, ...] = ()


def _group(prefix: str, path: tuple[str, str, str], contexts: str, rows: Iterable[tuple[str, ...]]) -> tuple[Leaf, ...]:
    return tuple(
        Leaf(f"{prefix}.{row[0]}", (*path, row[1]), _alternatives(row[2]), _alternatives(contexts), _alternatives(row[3]) if len(row) > 3 else ())
        for row in rows
    )


# These are semantic product types, not an import of either mart's tree.  A
# compound native leaf may consolidate to a product type (e.g. butter/chocolate
# biscuits -> biscuits), but a mixed-type leaf has no catch-all mapping.
LEAVES: tuple[Leaf, ...] = (
    *_group("food.dairy.milk", ("식품", "유제품", "우유"), "우유/유제품|유제품|dairy|우유|milk", (
        # Fat percentage/sterilization are attributes, not siblings of flavour.
        ("plain", "흰우유", "흰우유|멸균흰우유|일반우유|저지방우유|plain milk", "흰우유|일반우유|저지방우유|저지방 우유|무지방 우유|plain milk"),
        ("chocolate", "초코우유", "초코우유|초콜릿우유|chocolate milk", "초코우유|초콜릿우유|초코 우유|초콜릿 우유|chocolate milk"),
        ("strawberry", "딸기우유", "딸기우유|strawberry milk", "딸기우유|딸기 우유|strawberry milk"),
        ("banana", "바나나우유", "바나나우유|banana milk", "바나나우유|바나나 우유|banana milk"),
        ("coffee", "커피우유", "커피우유|coffee milk", "커피우유|커피 우유"),
        ("matcha", "말차우유", "말차우유"),
    )),
    *_group("food.dairy.yogurt", ("식품", "유제품", "발효유"), "우유/유제품|유제품|dairy|요거트/요구르트", (
        ("spoon", "떠먹는요거트", "떠먹는 요구르트|떠먹는요구르트|떠먹는요거트", "떠먹는요거트|떠먹는 요거트|떠먹는 요구르트"),
        ("drink", "마시는요구르트", "마시는요구르트|마시는 요구르트|일반요구르트|농후발효유", "마시는요구르트|마시는 요구르트"),
        ("greek", "그릭요거트", "그릭요거트", "그릭요거트|그릭 요거트|greek yogurt"),
    )),
    *_group("food.dairy.cheese", ("식품", "유제품", "치즈·버터"), "우유/유제품|유제품|dairy|치즈|치즈/버터", (
        ("sliced", "슬라이스치즈", "슬라이스 치즈|슬라이스치즈", "슬라이스치즈|슬라이스 치즈"),
        ("shredded", "슈레드치즈", "슈레드/피자치즈|슈레드치즈|피자치즈", "슈레드치즈|슈레드 치즈|피자치즈"),
        ("string", "스트링치즈", "스트링치즈", "스트링치즈|스트링 치즈"),
        ("butter", "버터", "버터"),
        # New types are grounded in reviewed source listings, not catch-alls.
        # No global name terms: glued titles need the contextual rule below.
        ("cream", "크림치즈", "크림치즈"),
        ("fresh_mozzarella", "생모짜렐라", "생모짜렐라"),
        ("ricotta", "리코타치즈", "리코타치즈"),
        ("burrata", "부라타치즈", "부라타치즈"),
        ("mascarpone", "마스카르포네", "마스카르포네"),
        ("brie", "브리치즈", "브리치즈"),
        ("camembert", "까망베르치즈", "까망베르치즈"),
        ("hard_aged", "경성숙성치즈", "경성숙성치즈"),
    )),
    *_group("food.dairy.cream", ("식품", "유제품", "유크림"), "우유/유제품|유제품|dairy", (
        ("fresh", "생크림", "생크림"),
    )),
    *_group("food.plant.drinks", ("식품", "식물성식품", "식물성음료"), "우유/유제품|식물성음료", (
        ("almond", "아몬드음료", "아몬드음료"),
    )),
    *_group("food.plant.soy", ("식품", "식물성식품", "콩가공품"), "우유/유제품|두부/김치/반찬|채소|두부/나물|두부/나또/콩나물/숙주나물", (
        ("soymilk", "두유", "일반두유|가공두유|두유", "두유|soy milk"),
        ("tofu", "두부", "부침용두부|찌개용두부|부침/찌개용두부|두부", "부침두부|찌개두부|부침용두부|찌개용두부"),
        ("silken", "순두부·연두부", "순두부/연두부", "순두부|연두부"),
        ("natto", "낫토", "낫또|나또|낫토", "낫또|낫토|나또"),
        ("fried_tofu", "유부", "유부"),
    )),
    *_group("food.produce.fruit", ("식품", "농산물", "신선과일"), "과일", (
        ("apple", "사과", "사과"), ("pear", "배", "배"), ("grape", "포도", "포도|샤인머스캣"),
        ("peach", "복숭아", "복숭아"), ("plum", "자두", "자두"), ("citrus", "감귤류", "귤|감귤|한라봉|천혜향|레드향"),
        ("banana", "바나나", "바나나"), ("kiwi", "키위", "키위|참다래"), ("berry", "딸기·베리", "딸기|블루베리"),
        ("melon", "멜론·참외", "멜론|참외"), ("watermelon", "수박", "수박"),
        ("tomato", "토마토", "토마토|방울토마토"),
        # Exact reviewed listings only: fruit-name mentions do not prove form.
        ("avocado", "아보카도", ""), ("mango", "망고", ""), ("jujube", "대추", ""),
        ("lime", "라임", ""), ("grapefruit", "자몽", ""), ("dragon_fruit", "용과", ""),
    )),
    *_group("food.produce.processed_fruit", ("식품", "농산물", "가공과일"), "과일|쌀/잡곡/견과류", (
        ("frozen", "냉동과일", "냉동과일", "냉동과일|냉동 과일"),
        ("dried", "건과일", "건과일|건조과일"),
        ("cut", "손질과일", "간편/컷팅과일|컷팅과일"),
        ("cup", "과일컵", ""),
    )),
    *_group("food.produce.vegetables", ("식품", "농산물", "신선채소"), "채소", (
        ("potato", "감자", "감자"), ("sweet_potato", "고구마", "고구마"), ("onion", "양파", "양파"),
        ("garlic", "마늘", "마늘"), ("carrot", "당근", "당근"), ("cucumber", "오이", "오이"),
        ("cabbage", "양배추", "양배추"), ("pepper", "고추·파프리카", "고추|파프리카|피망"),
        ("pumpkin", "호박", "호박|애호박|단호박"), ("eggplant", "가지", "가지"),
        ("leaf", "쌈채소", "쌈채소|상추|깻잎"), ("sprouts", "콩나물·숙주", "콩나물|숙주|숙주나물"),
        ("mushroom", "버섯", "버섯|팽이버섯|새송이버섯|느타리버섯|표고버섯"),
        ("salad", "샐러드채소", "믹스샐러드|샐러드채소"),
        ("scallion", "대파", ""), ("napa_cabbage", "배추", ""),
        ("radish", "무", ""), ("zucchini", "애호박", ""),
    )),
    # Dry/frozen processing wins over an unreliable Fresh-Foods source path.
    # These leaves and search terms add no automatic source/name mappings.
    *_group("food.produce.processed_vegetables", ("식품", "농산물", "가공채소"), "채소", (
        ("dried", "건채소", ""), ("dried_mushroom", "건버섯", ""),
        ("frozen", "냉동채소", ""),
        ("olive", "절임올리브", ""),
    )),
    *_group("food.grains.rice", ("식품", "곡물·견과", "쌀·잡곡"), "쌀/잡곡/견과류|쌀/잡곡|쌀|잡곡", (
        ("white", "백미", "백미|쌀/백미"), ("mixed", "혼합곡", "혼합곡|혼합잡곡"),
        ("brown", "현미", "현미"), ("oat", "귀리", "귀리"),
        # Reviewed raw grains; no implicit source/name rules for processed
        # foods that merely mention these ingredients.
        ("glutinous", "찹쌀", ""), ("black", "흑미", ""),
        ("barley", "보리", ""), ("millet", "기장", ""),
        ("chickpea", "병아리콩", ""),
    )),
    *_group("food.grains.nuts", ("식품", "곡물·견과", "견과류"), "견과|견과류|쌀/잡곡/견과류", (
        ("almond", "아몬드", "아몬드"), ("walnut", "호두", "호두"), ("peanut", "땅콩", "땅콩"),
        ("macadamia", "마카다미아", "마카다미아"), ("cashew", "캐슈넛", "캐슈넛"),
        ("pistachio", "피스타치오", ""), ("mixed", "혼합견과", ""),
    )),
    *_group("food.meat.fresh", ("식품", "정육·계란", "신선육"), "정육/계란|정육/계란류|정육|축산", (
        ("beef", "소고기", "국내산소고기|수입산소고기|한우|한우간편팩상품|프리미엄 한우구이|소고기"),
        ("pork", "돼지고기", "국내산돼지고기|수입산돼지고기|돈육간편팩상품|돼지고기"),
        ("chicken", "닭고기", "닭고기|닭다리/날개/윙봉|생닭"),
    )),
    *_group("food.meat.eggs", ("식품", "정육·계란", "알류"), "정육/계란|정육/계란류|계란/알류|계란/메추리알", (
        ("chicken", "계란", "계란|일반란|계란15구|계란10구|계란25구 이상|동물복지란/유정란등"),
        ("quail", "메추리알", "메추리알", "메추리알"),
    )),
    *_group("food.meat.processed", ("식품", "정육·계란", "가공육"), "두부/김치/반찬|햄/어묵/맛살/닭가슴살|간편식/밀키트", (
        ("sausage", "소시지", "소시지|비엔나소시지|간식용소시지", "비엔나소시지|비엔나 소시지"),
        ("ham", "햄", "햄/샌드위치햄/슬라이스햄|햄/분절햄/슬라이스햄/김밥햄"),
        ("bacon", "베이컨", "베이컨"), ("breast", "가공닭가슴살", "닭가슴살"),
        ("smoked_duck", "훈제오리", ""), ("sundae", "순대", ""),
    )),
    *_group("food.seafood.fish", ("식품", "수산물", "생선"), "수산물/건어물|수산물/건해산물|수산물", (
        ("mackerel", "고등어", "고등어"), ("salmon", "연어", "연어"), ("pollock", "명태", "명태|동태|생태"),
    )),
    *_group("food.seafood.shellfish", ("식품", "수산물", "갑각·패류"), "수산물/건어물|수산물/건해산물|수산물", (
        ("shrimp", "새우", "냉동새우|새우"), ("crab", "게", "게/꽃게/대게"), ("abalone", "전복", "전복"),
    )),
    *_group("food.seafood.seaweed", ("식품", "수산물", "해조류"), "수산물/건어물|수산물/건해산물|수산물", (
        ("laver", "김", "김|도시락김|전장김|김자반/김가루"), ("miyeok", "미역", "미역"), ("kelp", "다시마", "다시마"),
    )),
    *_group("food.seafood.processed", ("식품", "수산물", "수산가공품"), "수산물/건어물|수산물/건해산물|두부/김치/반찬|햄/어묵/맛살/닭가슴살", (
        ("fishcake", "어묵", "볶음용어묵|국탕용어묵|간식용어묵|요리용어묵"),
        ("surimi", "맛살", "맛살|간식용맛살"), ("dried_fish", "건어물스낵", "어포|쥐치"), ("anchovy", "건멸치", "멸치"),
        ("pollock_roe", "명란", ""), ("seafood_ball", "해물경단", ""),
    )),
    *_group("food.meals.noodles", ("식품", "간편식·면", "면요리"), "라면/즉석식품/통조림|라면/통조림/즉석밥|간편식/밀키트|냉장/냉동/밀키트|건면/생면/면요리", (
        ("cup_ramen", "컵라면", "컵라면", "컵라면"),
        ("bag_ramen", "봉지라면", "일반라면/비빔라면|봉지라면", "봉지라면"),
        ("pasta", "파스타면", "파스타/스파게티면", "파스타면|스파게티면"),
        ("naengmyeon", "냉면·메밀면", "간편냉면&소바|냉면/메밀면|냉면"),
        ("udon", "우동", "우동|우동사리"), ("jjolmyeon", "쫄면", "쫄면"),
        ("black_bean", "짜장면", "짜장면"),
        ("glass", "당면", ""),  # Reviewed assignments only, not broad name matching.
        ("rice_noodle", "쌀국수", ""), ("wheat_noodle", "소면·국수", ""),
        ("buckwheat_noodle", "메밀국수", ""),
        ("kalguksu", "칼국수", ""), ("makguksu", "막국수", ""),
        ("sujebi", "수제비", ""), ("tofu_noodle", "두부면", ""),
        ("jjamppong", "짬뽕면", ""),
        ("pad_thai", "팟타이", ""),
        ("gnocchi", "뇨끼", ""), ("ravioli", "라비올리", ""),
    )),
    *_group("food.meals.rice", ("식품", "간편식·면", "밥·죽"), "라면/즉석식품/통조림|라면/통조림/즉석밥|간편식/밀키트|냉장/냉동/밀키트", (
        ("instant", "즉석밥", "즉석밥", "즉석밥"), ("cup", "컵밥", "컵밥", "컵밥"),
        ("fried", "볶음밥", "볶음밥|냉동밥/덥밥류"), ("porridge", "죽", "죽|즉석죽"),
        ("soup", "스프", "스프|즉석스프"),
        ("rice_ball", "주먹밥", ""), ("sticky", "찰밥", ""),
    )),
    *_group("food.meals.dumplings", ("식품", "간편식·면", "만두"), "간편식/밀키트|냉장/냉동/밀키트", (
        ("gyoza", "교자만두", "고기교자만두|교자만두", "교자만두"),
        ("steamed", "찐만두", "고기찐만두|찐만두", "찐만두"),
        ("boiled", "물만두", "물만두", "물만두"), ("dimsum", "딤섬", "딤섬"),
        ("assorted", "일반만두", ""),
    )),
    *_group("food.meals.prepared", ("식품", "간편식·면", "조리식품"), "간편식/밀키트|냉장/냉동/밀키트|라면/즉석식품/통조림|델리/즉석조리", (
        ("soup_stew", "국·탕·찌개", "국/탕|탕|즉석국|즉석국(레토르트)"),
        ("curry", "즉석카레", "즉석카레", "즉석카레"), ("black_bean", "즉석짜장", "즉석짜장", "즉석짜장"),
        ("mapo_tofu", "즉석마파두부", ""),  # Reviewed meal, not cooking sauce.
        ("pancake", "냉동전", ""),  # Reviewed frozen pancakes only; no broad name rule.
        ("fried_shrimp", "새우튀김", ""),  # Reviewed prepared shrimp, not raw seafood.
        ("tteokbokki", "떡볶이", "간편떡볶이|떡볶이"), ("pork_cutlet", "돈까스", "돈까스"),
        ("chicken", "조리치킨", "치킨|치킨/닭강정|치킨기타"), ("nugget", "치킨너겟·텐더", "너겟|치킨너겟/치킨텐더"),
        ("pizza", "피자", "피자"), ("hotdog", "핫도그", "핫도그"), ("tteokgalbi", "떡갈비", "떡갈비"),
        ("sandwich", "샌드위치", "샌드위치"), ("meal_kit", "밀키트", "한식밀키트|일식|아시안식"),
        ("cheese_ball", "치즈볼", ""), ("vegetable_fritter", "채소튀김", ""),
        ("meat_patty", "동그랑땡", ""), ("rice_cake", "떡", ""),
        ("japchae", "조리잡채", ""), ("seasoned_meat", "양념육", ""),
    )),
    *_group("food.preserved.kimchi", ("식품", "반찬·저장식품", "김치"), "두부/김치/반찬|김치/반찬/젓갈", (
        ("cabbage", "배추김치", "배추김치|포기김치|맛김치", "배추김치|포기김치|맛김치"),
        ("radish", "총각김치", "총각김치", "총각김치"), ("yeolmu", "열무김치", "열무김치", "열무김치"),
        ("water", "물김치", "물김치", "물김치"), ("white", "백김치", "백김치", "백김치"),
    )),
    *_group("food.preserved.sides", ("식품", "반찬·저장식품", "밑반찬"), "두부/김치/반찬|김치/반찬/젓갈", (
        ("stir_fried", "볶음반찬", ""),
    )),
    *_group("food.preserved.canned", ("식품", "반찬·저장식품", "통조림"), "라면/즉석식품/통조림|라면/통조림/즉석밥|통조림", (
        ("tuna", "참치통조림", "참치|참치통조림", "참치통조림|참치 통조림"),
        ("ham", "햄통조림", "햄통조림", "햄통조림|햄 통조림"),
        ("corn", "옥수수통조림", "옥수수통조림", "옥수수통조림"),
        ("fruit", "과일통조림", "과일통조림", "과일통조림"),
        ("whelk", "골뱅이통조림", "골뱅이통조림", "골뱅이통조림"),
        ("saury", "꽁치통조림", "꽁치통조림", "꽁치통조림"),
    )),
    *_group("food.snacks.baked", ("식품", "과자·간식", "구운과자"), "과자/시리얼|과자/스낵/간식", (
        ("biscuits", "쿠키·비스킷", "버터비스켓|초코비스켓|쿠키/비스킷|비스킷|쿠키"),
        ("cracker", "크래커", "크래커"), ("sandwich", "샌드과자", "크림비스켓|샌드"),
        ("wafer", "웨하스", "웨하스/웨이퍼"), ("pie", "파이과자", "파이케이크류|파이"),
        ("cake", "케이크과자", ""),
    )),
    *_group("food.snacks.savory", ("식품", "과자·간식", "스낵"), "과자/시리얼|과자/스낵/간식", (
        ("corn", "옥수수스낵", "옥수수스낵|나쵸"), ("potato", "감자스낵", "감자스낵", "감자칩"),
        ("wheat", "밀가루스낵", "밀가루스낵"), ("popcorn", "팝콘", "팝콘"),
        ("grain", "곡물스낵", ""),
        ("vegetable", "채소스낵", ""), ("seaweed", "해조스낵", ""),
    )),
    *_group("food.snacks.sweets", ("식품", "과자·간식", "단과자"), "과자/시리얼|과자/스낵/간식", (
        ("chocolate", "초콜릿", "바초콜릿|볼초콜릿|초콜릿"), ("jelly", "젤리", "젤리"),
        ("candy", "캔디", "하드캔디|소프트캔디|캔디"),
    )),
    *_group("food.snacks.cereal", ("식품", "과자·간식", "시리얼"), "과자/시리얼|과자/스낵/간식", (
        ("flakes", "플레이크시리얼", "후레이크|플레이크"), ("granola", "그래놀라", "그래놀라", "그래놀라"),
    )),
    *_group("food.snacks.traditional", ("식품", "과자·간식", "전통간식"), "", (
        ("hangwa", "한과·전병", ""), ("yanggaeng", "양갱", ""),
    )),
    *_group("food.drinks.coffee", ("식품", "음료", "커피"), "커피/차|커피/원두|우유/유제품|생수/음료|생수/음료/주류", (
        ("ready", "커피음료", "냉장커피|캔/PET커피|일반커피"),
        ("mix", "커피믹스", "커피믹스", "커피믹스|커피 믹스"),
        ("instant", "인스턴트커피", "프리미엄커피"),
        ("beans", "원두커피", "원두커피|원두|홀빈커피|분쇄커피", "원두커피"),
        ("drip", "드립커피", "드립커피"),
        ("capsule", "캡슐커피", "캡슐커피"),
    )),
    *_group("food.drinks.water_soda", ("식품", "음료", "생수·탄산"), "생수/음료|생수/음료/주류", (
        ("water", "생수", "생수|먹는샘물", "먹는샘물|미네랄워터|백산수|아이시스|트루워터|삼다수|에비앙|피지워터"), ("sparkling", "탄산수", "탄산수", "탄산수"),
        ("cola", "콜라", "콜라"), ("cider", "사이다", "사이다"), ("soda", "탄산음료", ""),
        ("sports", "스포츠음료", "스포츠/이온음료", "이온음료|스포츠음료"),
        ("energy", "에너지음료", "", ""),
    )),
    *_group("food.drinks.juice", ("식품", "음료", "과채음료"), "생수/음료|생수/음료/주류", (
        ("fruit", "과일주스", "", ""),
        ("vegetable", "채소주스", "", ""),
        ("coconut", "코코넛워터", "", ""),
        ("fruit_drink", "과일음료", "", ""),
        ("vegetable_drink", "채소음료", "", ""),
        ("aloe", "알로에음료", "", ""),
    )),
    *_group("food.drinks.non_alcoholic", ("식품", "음료", "무알코올음료"), "생수/음료|생수/음료/주류", (
        ("beer", "무알코올맥주", "", ""),
    )),
    *_group("food.drinks.tea", ("식품", "음료", "차·코코아"), "커피/차|차/액상차/핫초코", (
        ("barley", "보리차", "보리차", "보리차"), ("herbal", "허브차", "허브차"),
        ("citron", "유자차", "유자차", "유자차"), ("cocoa", "코코아·핫초코", "코코아/핫초코", "핫초코|코코아분말"),
        ("green", "녹차·말차", "", ""), ("black", "홍차·아이스티", "", ""),
        ("puer", "보이차", "", ""), ("grain", "곡물차", "", ""),
    )),
    *_group("food.seasonings.pastes", ("식품", "양념·소스", "장류"), "장류/양념/제빵|양념/오일/분말류", (
        ("soy", "간장", "간장"), ("gochujang", "고추장", "고추장"), ("doenjang", "된장", "된장"), ("ssamjang", "쌈장", "쌈장"),
    )),
    *_group("food.seasonings.sauces", ("식품", "양념·소스", "조미소스"), "장류/양념/제빵|양념/오일/분말류", (
        ("pasta", "파스타소스", "스파게티소스|파스타소스", "파스타소스|스파게티소스"),
        ("ketchup", "케첩", "케찹|케첩"), ("mayo", "마요네즈", "마요네즈"), ("mustard", "머스타드", "머스타드"),
        ("mala", "마라소스", "마라소스", "마라소스"), ("fish", "액젓·어류조미액", "액젓"),
        ("black_bean", "짜장소스", ""),  # Reviewed assignments only.
        ("mapo_tofu", "마파두부소스", ""),
        ("pepper_stir_fry", "고추잡채소스", ""),
        ("fish_fragrant", "어향소스", ""),
        ("meat", "고기용소스", ""),
    )),
    *_group("food.bakery.spreads", ("식품", "베이커리·스프레드", "스프레드"), "", (
        ("peanut", "땅콩버터", ""),  # Never confused with dairy butter by its name.
        ("fruit", "과일잼·마멀레이드", ""),
    )),
    *_group("food.bakery.bread", ("식품", "베이커리·스프레드", "빵"), "", (
        ("sliced", "식빵", ""), ("roll", "모닝롤", ""), ("bagel", "베이글", ""),
        ("hard", "하드롤·바게트", ""), ("pastry", "페이스트리", ""), ("dough", "제빵생지", ""),
    )),
    *_group("food.bakery.dessert", ("식품", "베이커리·스프레드", "디저트"), "", (
        ("cake", "케이크", ""), ("muffin", "머핀", ""), ("scone", "스콘", ""), ("financier", "휘낭시에", ""),
    )),
    *_group("food.seasonings.oils", ("식품", "양념·소스", "식용유"), "장류/양념/제빵|양념/오일/분말류", (
        ("canola", "카놀라유", "카놀라유", "카놀라유"), ("grape", "포도씨유", "포도씨유", "포도씨유"),
        ("olive", "올리브유", "올리브유", "올리브유"), ("sesame", "참기름", "참기름", "참기름"),
        ("cooking", "요리유", ""),
    )),
    *_group("food.seasonings.baking", ("식품", "양념·소스", "기초조미·제빵"), "장류/양념/제빵|양념/오일/분말류", (
        ("flour", "밀가루", "밀가루"), ("sugar", "설탕", "흰설탕|설탕"), ("vinegar", "식초", "식초"),
        ("pepper", "후추", "후추"), ("stock", "육수", "코인육수", "코인육수"),
    )),
    *_group("food.seasonings.powders", ("식품", "양념·소스", "분말조미료"), "장류/양념/제빵|양념/오일/분말류", (
        ("curry", "카레가루", ""),  # Reviewed powder products only; instant curry stays separate.
    )),
    *_group("household.cleaning.laundry", ("생활용품", "청소·세탁", "세탁용품"), "세탁/청소|청소/생활용품", (
        ("liquid", "액체세탁세제", "액체 세탁세제|액체세탁세제", "액체세탁세제|액체 세탁세제"),
        ("softener", "섬유유연제", "고농축 섬유유연제|섬유유연제", "섬유유연제"),
        ("capsule", "캡슐세탁세제", ""), ("dryer_sheet", "건조기시트", ""),
        ("oxygen_bleach", "산소계표백제", ""), ("machine_cleaner", "세탁조세정제", ""),
    )),
    *_group("household.cleaning.kitchen", ("생활용품", "청소·세탁", "주방청소"), "세탁/청소|청소/생활용품", (
        ("detergent", "주방세제", "일반 주방세제/퐁퐁|주방세제", "주방세제|주방 세제"),
        ("dishwasher", "식기세척기세제", "식기세척기 세제|식기세척기세제", "식기세척기세제|식기세척기 세제"),
        ("degreaser", "주방기름때세정제", ""),
    )),
    *_group("household.cleaning.bath", ("생활용품", "청소·세탁", "욕실청소"), "세탁/청소|청소/생활용품", (
        ("cleaner", "욕실세정제", "욕실세정제", "욕실세정제|욕실 세정제"),
        ("drain", "배수관세정제", ""), ("toilet", "변기세정제", ""), ("mold", "곰팡이제거제", ""),
    )),
    *_group("household.cleaning.general", ("생활용품", "청소·세탁", "일반청소"), "", (
        ("chlorine", "염소계표백제", ""), ("glass", "유리세정제", ""), ("wipes", "청소용티슈", ""),
        ("dehumidifier", "제습제", ""), ("deodorizer", "탈취제", ""),
    )),
    *_group("household.hygiene.feminine", ("생활용품", "위생용품", "생리용품"), "", (
        ("liner", "팬티라이너", ""), ("overnight", "오버나이트패드", ""),
        ("pants", "입는오버나이트", ""), ("tampon", "탐폰", ""),
    )),
    *_group("household.hygiene.paper", ("생활용품", "위생용품", "제지"), "화장지/물티슈|제지/위생/건강|욕실/생활용품", (
        ("toilet", "두루마리휴지", "두루마리|두루마리화장지|두루마리휴지", "두루마리휴지|두루마리 화장지"),
        ("kitchen", "키친타월", "키친타올|키친타월", "키친타월|키친타올"),
        ("facial", "미용티슈", "미용티슈", "미용티슈|각티슈"),
        ("wipes", "물티슈", "물티슈", "물티슈"),
    )),
    *_group("beauty.personal.shaving", ("뷰티·개인관리", "개인위생", "면도용품"), "뷰티|미용|면도/제모|shaving|shaving-hair-removal|personal-care", (
        ("razor", "면도기", "면도기|razors|mens-razors", "면도기|razor"),
        ("blades", "면도날", "면도날|razor-blades", "면도날|면도날 리필|razor blades"),
        ("foam", "면도거품", "면도거품|쉐이빙폼|shaving-cream", "쉐이빙폼|쉐이빙 폼|면도거품|shaving cream"),
    )),
    *_group("beauty.personal.hair", ("뷰티·개인관리", "개인위생", "헤어케어"), "헤어/바디/뷰티|헤어/바디|헤어케어|hair-care", (
        ("shampoo", "샴푸", "샴푸|shampoo", "샴푸|shampoo"),
        ("conditioner", "린스·컨디셔너", "린스|컨디셔너|conditioner", "린스|헤어컨디셔너"),
        ("treatment", "헤어트리트먼트", ""), ("dye", "염색제", ""),
    )),
    *_group("beauty.personal.oral", ("뷰티·개인관리", "개인위생", "구강관리"), "", (
        ("toothpaste", "치약", ""), ("toothbrush", "칫솔", ""), ("floss", "치실", ""),
    )),
    *_group("beauty.personal.body", ("뷰티·개인관리", "개인위생", "바디케어"), "", (
        ("lotion", "바디로션", ""), ("wash", "바디워시", ""),
        ("handwash", "핸드워시", ""), ("soap", "세안·목욕비누", ""),
    )),
    *_group("baby.hygiene.diapering", ("유아동", "유아위생", "배변용품"), "기저귀|유아동/완구|유아용품", (
        ("diapers", "유아기저귀", "하기스|마미포코|팸퍼스|보솜이|유아기저귀", "유아기저귀|아기기저귀"),
        ("wipes", "유아물티슈", "유아물티슈|아기물티슈", "유아물티슈|아기물티슈"),
    )),
)

_BY_ID = {leaf.id: leaf for leaf in LEAVES}
_PROMO = {_label_key(v) for v in ("Best", "베스트", "Obanjang", "오반장", "SpecialPriceOffers", "OnlineDeals", "온라인할인", "행사상품")}
_MART_ALIASES = {"이마트": "emart", "홈플러스": "homeplus", "롯데마트": "lottemart", "코스트코": "costco"}

# Build indexes once. Re-normalizing every rule for every observation made a
# real 9,196-row review unnecessarily slow, and provides no extra evidence.
_PATH_INDEX: dict[str, list[tuple[str, frozenset[str], frozenset[str]]]] = defaultdict(list)
_NAME_INDEX: dict[str, list[tuple[tuple[str, ...], str]]] = defaultdict(list)
for _leaf in LEAVES:
    _contexts = frozenset(_label_key(label) for label in _leaf.context_labels)
    _roots = _contexts | {_label_key(_leaf.path[0]), _leaf.id.split(".")[0]}
    for _label in _leaf.source_labels:
        _PATH_INDEX[_label_key(_label)].append((_leaf.id, _contexts, frozenset(_roots)))
    for _term in _leaf.name_terms:
        _term_tokens = _tokens(_term)
        if _term_tokens:
            _NAME_INDEX[_term_tokens[0]].append((_term_tokens, _leaf.id))


# Real full-path audit found these source branches contain adjacent product
# types. These checks can only WITHHOLD a classification; they never assign a
# new leaf by a loose substring. Retain the candidate/path for operator review.
_TITLE_REQUIRED = {
    "food.drinks.tea.citron": r"유자",
    "food.drinks.water_soda.cola": r"콜라|코카|펩시",
    "food.meals.noodles.black_bean": r"짜장",
    "food.meals.noodles.udon": r"우동",
    "food.meals.prepared.meal_kit": r"밀키트",
    "food.meals.prepared.pork_cutlet": r"돈까스|돈카츠|돈가스",
    "food.meals.prepared.sandwich": r"샌드위치",
    "food.meals.prepared.tteokgalbi": r"떡갈비|너비아니",
    "food.meals.rice.fried": r"볶음밥",
    "food.plant.soy.natto": r"낫또|나또|낫토",
    "food.plant.soy.soymilk": r"두유",
    "food.plant.soy.silken": r"순두부|연두부",
    "food.preserved.kimchi.radish": r"총각",
    "food.preserved.kimchi.yeolmu": r"열무",
    "food.produce.fruit.banana": r"바나나",
    "food.seafood.shellfish.shrimp": r"새우|쉬림프",
    "food.seasonings.baking.pepper": r"후추|페퍼",
}
_TITLE_FORBIDDEN = {
    "food.dairy.cheese.sliced": r"까요까요|파르미지아노|레지아노|아페리프레|크림치즈|스트링",
    "food.dairy.yogurt.spoon": r"그릭|짜먹|짜요짜요",
    "food.drinks.coffee.mix": r"아메리카노|카누.*(?:마일드로스트|디카페인)",
    "food.drinks.water_soda.water": r"\d+(?:\.\d+)?\s*ml\s+\d+\s*병",
    "food.meals.noodles.bag_ramen": r"잡채|닭한마리",
    "food.meals.noodles.naengmyeon": r"쫄면|육수|소스",
    "food.meals.prepared.nugget": r"가라아게",
    "food.meals.prepared.pizza": r"피아디나",
    "food.meals.prepared.soup_stew": r"육수|카레|커리|짜장|(?:짬뽕|된장)밥",
    "food.meat.eggs.quail": r"장조림",
    "food.meat.processed.ham": r"함박|미트볼",
    "food.meat.processed.sausage": r"미트볼|스팸|살코기햄|델리햄|김밥햄",
    "food.preserved.kimchi.yeolmu": r"물김치",
    "food.produce.processed_fruit.dried": r"고구마",
    "food.produce.processed_fruit.frozen": r"아사이볼|망고볼",
    "food.seafood.processed.fishcake": r"곤약",
    "food.seafood.shellfish.shrimp": r"오징어|씨푸드믹스",
    "food.seasonings.baking.sugar": r"알룰로스|스테비아|뉴슈가",
    "food.snacks.baked.biscuits": r"크래커|파이|웨하스|샌드",
    "food.snacks.baked.sandwich": r"웨하스|하임|쿠크다스",
    "food.snacks.savory.corn": r"팝콘",
    "household.cleaning.bath.cleaner": r"과탄산|베이킹소다|구연산|세탁조|배수관",
    "household.cleaning.laundry.liquid": r"캡슐|시트|분말",
    "household.cleaning.laundry.softener": r"탈취제",
}
_TITLE_REQUIRED = {key: re.compile(value, re.I) for key, value in _TITLE_REQUIRED.items()}
_TITLE_FORBIDDEN = {key: re.compile(value, re.I) for key, value in _TITLE_FORBIDDEN.items()}


_DAIRY_TITLE_VETO = re.compile(
    r"제조기|메이커|거품기|보틀|장난감|인형|사료|반려|강아지|고양이|애견|애묘|"
    r"과자|쿠키|비스킷|비스켓|크래커|웨하스|케이크|앙빵|식빵|와플|빵|"
    r"피자(?!치즈|용슈레드치즈|모짜렐라치즈)|핫도그|소시지|소세지|초리조|하몽|만두|주먹밥|볶음밥|"
    r"오징어|어포|육포|떡볶이|떡갈비|돈까스|소스|드레싱|양념|"
    r"모음전|(?:땅콩|아몬드|캐슈|기)버터",
    re.I,
)
_DAIRY_CONTEXT_LABELS = frozenset(_label_key(label) for label in (
    "우유/유제품", "유제품", "dairy", "치즈/버터", "식물성음료",
))
_COSTCO_DAIRY_CONTEXT = frozenset((
    "food", "foods", "fresh-foods", "chilled-foods", "frozen-foods",
    "beverages", "soy-milkmilk", "cheesebutter", "softconcentrated-drinks",
    # This category also contains dumplings/ready meals. It is only a food
    # context; explicit product-type words and title vetoes remain necessary.
    "instant-fooddumplingtraditional-pancakescheese",
))
_COSTCO_KNOWN_CONTEXT = _COSTCO_DAIRY_CONTEXT | frozenset((
    "kimchiside-dishes", "oils", "snack", "snacks", "bread", "saucescondiments",
    "ricegrains", "pastanoodles", "healthsupplement", "pet-supplies", "dog-foods",
))
_PLANT_DAIRY_HINT = re.compile(r"식물성|비건|(?:코코넛|아몬드|오트|귀리|두유)(?:그릭)?(?:우유|밀크|요거트|치즈)")

_COFFEE_CONTEXT_LABELS = frozenset(_label_key(label) for label in (
    "커피", "커피/차", "커피/원두", "커피/원두/차",
))
_COFFEE_NON_PRODUCT = re.compile(
    r"필터|커피컵|커피잔|보온|보냉|주전자|케틀|홀더|메이커|그라인더|드리퍼|"
    r"핸들서버|바리스타서버|머그|포트|머신|테이블|식탁|블렌더|상품권|클리닝캡슐",
    re.I,
)
_COFFEE_OTHER_DRINK = re.compile(
    r"밀크티|티박스|티 에디션|티포트|녹차|홍차|보이차|우엉차|메밀차|옥수수차|"
    r"생강차|쌍화차|유자차|한라봉차|아이스티|콤부차|코코아|제티|율무차|"
    r"레몬즙|레몬청|자몽청|한라봉청|깔라만시|애사비|벌꿀|꿀 ",
    re.I,
)


def _contextual_coffee_candidates(evidence: Mapping[str, Any]) -> set[str]:
    """Classify explicit coffee forms inside audited, polluted coffee shelves."""
    if not any(_label_key(part) in _COFFEE_CONTEXT_LABELS for part in evidence["source_path_parts"]):
        return set()
    title = evidence["source_title"]
    if _COFFEE_NON_PRODUCT.search(title) or _COFFEE_OTHER_DRINK.search(title):
        return set()
    if re.search(r"아메리카노\s*&\s*드립백", title, re.I):
        return set()
    if re.search(r"캡슐", title, re.I):
        return {"food.drinks.coffee.capsule"}
    if re.search(r"드립백\s*커피|드립백커피|드립커피|핸드드립", title, re.I):
        return {"food.drinks.coffee.drip"}
    if re.search(r"(?:아메리카노|콜드브루|바리스타룰스).{0,20}\d+(?:\.\d+)?\s*(?:ml|l)\b", title, re.I):
        return {"food.drinks.coffee.ready"}
    if re.search(r"홀빈|원두", title, re.I):
        return {"food.drinks.coffee.beans"}
    if re.search(r"커피믹스|모카골드|스페셜\s*골드\s*블렌드|카누.{0,20}라떼", title, re.I):
        return {"food.drinks.coffee.mix"}
    if re.search(r"인스턴트\s*커피|카누|아메리카노|커피스틱", title, re.I):
        return {"food.drinks.coffee.instant"}
    if re.search(r"스타벅스\s*(?:더블샷|파이크\s*플레이스\s*로스트)\b", title, re.I):
        return {"food.drinks.coffee.ready"}
    return set()


def _contextual_audited_beverage_candidates(evidence: Mapping[str, Any]) -> set[str]:
    """Classify explicit forms in fully audited Costco and Emart drink shelves."""
    shelf = (evidence["mart"], tuple(map(_label_key, evidence["source_path_parts"])))
    audited_shelves = {
        ("costco", (_label_key("음료"),)),
        ("emart", (_label_key("생수/음료/주류"),)),
    }
    if shelf not in audited_shelves:
        return set()
    title = evidence["source_title"]
    # These audited shelf contaminants are not packaged beverages.
    if re.search(r"컵홀더|앰플|아이스바|영코코넛|콤보팩|이유식\s*퓨레|고구마\s*퓨레|단호박\s*퓨레|감자\s*퓨레", title, re.I):
        return set()
    if (re.search(r"논알콜|논알코올|무알콜|무알코올", title, re.I)
            and re.search(r"클라우스탈러|버드와이저|클라우드|맥주|비어", title, re.I)
            and re.search(r"\d+(?:\.\d+)?\s*ml", title, re.I)):
        return {"food.drinks.non_alcoholic.beer"}
    if re.search(r"레쓰비|스타벅스\s*더블샷", title, re.I):
        return {"food.drinks.coffee.ready"}
    if re.search(r"코코넛\s*(?:퓨어)?워터", title, re.I):
        return {"food.drinks.juice.coconut"}
    if re.search(r"피지워터|미네랄워터|백산수|아이시스|트루워터|삼다수|에비앙|(?<![가-힣])생수(?![가-힣])", title, re.I):
        return {"food.drinks.water_soda.water"}
    if re.search(r"탄산수|스파클링워터|트레비", title, re.I):
        return {"food.drinks.water_soda.sparkling"}
    if re.search(r"콜라|코카콜라|펩시", title, re.I):
        return {"food.drinks.water_soda.cola"}
    if "애플사이다비니거" not in title.replace(" ", "") and re.search(r"사이다", title, re.I):
        return {"food.drinks.water_soda.cider"}
    if re.search(r"에너지\s*드링크|레드불|몬스터에너지|핫식스", title, re.I):
        return {"food.drinks.water_soda.energy"}
    if re.search(r"이온음료|게토레이|토레타|전해질드링크|포카리스웨트|파워오투|맑은이온", title, re.I):
        return {"food.drinks.water_soda.sports"}
    if re.search(r"탄산음료|진저\s*비어|밀키스|오랑지나|레몬소다|비타500\s*스파클링|웰치소다|제로스파클링", title, re.I):
        return {"food.drinks.water_soda.soda"}
    if re.search(r"보이차", title, re.I):
        return {"food.drinks.tea.puer"}
    if re.search(r"말차", title, re.I):
        return {"food.drinks.tea.green"}
    if re.search(r"홍차|아이스티", title, re.I):
        return {"food.drinks.tea.black"}
    if re.search(r"블랙보리", title, re.I):
        return {"food.drinks.tea.barley"}
    if re.search(r"쑥차", title, re.I):
        return {"food.drinks.tea.herbal"}
    if re.search(r"누룽지", title, re.I):
        return {"food.drinks.tea.grain"}
    if re.search(r"식혜|옥수수수염차", title, re.I):
        return {"food.drinks.tea.grain"}
    if re.search(r"하늘보리|안심아이차\s*보리", title, re.I):
        return {"food.drinks.tea.barley"}
    if re.search(r"녹차", title, re.I):
        return {"food.drinks.tea.green"}
    if re.search(r"녹즙|(?:토마토|야채|채소|ABC|그린).{0,20}(?:착즙\s*)?주스", title, re.I):
        return {"food.drinks.juice.vegetable"}
    if re.search(r"(?:주스|쥬스)", title, re.I):
        return {"food.drinks.juice.fruit"}
    if re.search(r"토마토음료", title, re.I):
        return {"food.drinks.juice.vegetable_drink"}
    if re.search(r"알로에음료", title, re.I):
        return {"food.drinks.juice.aloe"}
    if re.search(r"갈아만든배|과즙|감귤음료|복숭아음료|쿨피스|쿨피치|피크닉\s*사과|델몬트\s*사과\s*드링크|(?:포도|사과)100(?:%|\b)", title, re.I):
        return {"food.drinks.juice.fruit_drink"}
    return set()


def _contextual_costco_snack_candidates(evidence: Mapping[str, Any]) -> set[str]:
    """Classify explicit product forms in the fully audited Costco snack shelf."""
    if evidence["mart"] != "costco" or tuple(map(_label_key, evidence["source_path_parts"])) != (_label_key("과자"),):
        return set()
    title = evidence["source_title"]
    if re.search(r"애견|보틀|세척기|놀이\s*세트|제철과일|사과\s*선물세트|블루베리$|바로먹는감자|스낵치즈|쿠키버터무스|김과\s*김부각", title, re.I):
        return set()
    if re.search(r"1\s*kg\s*[x×*]\s*176", title, re.I):
        return set()
    if re.search(r"주스|쥬스", title, re.I):
        return {"food.drinks.juice.fruit"}
    if re.search(r"과일컵", title, re.I):
        return {"food.produce.processed_fruit.cup"}
    if re.search(r"동결건조\s*과일|건조과일", title, re.I):
        return {"food.produce.processed_fruit.dried"}
    if re.search(r"피스타치오", title, re.I):
        return {"food.grains.nuts.pistachio"}
    if re.search(r"캐슈넛", title, re.I):
        return {"food.grains.nuts.cashew"}
    if re.search(r"호두", title, re.I) and not re.search(r"정과", title, re.I):
        return {"food.grains.nuts.walnut"}
    if re.search(r"(?:피넛|땅콩)", title, re.I) and not re.search(r"프레첼|쿠키|초콜릿", title, re.I):
        return {"food.grains.nuts.peanut"}
    if re.search(r"견과|넛츠", title, re.I) and not re.search(r"초콜릿|쿠키", title, re.I):
        return {"food.grains.nuts.mixed"}
    if re.search(r"팝콘", title, re.I):
        return {"food.snacks.savory.popcorn"}
    if re.search(r"감자칩|프링글스|크리스피\s*프라이즈", title, re.I):
        return {"food.snacks.savory.potato"}
    if re.search(r"나초|토티야\s*칩|뻥이요", title, re.I):
        return {"food.snacks.savory.corn"}
    if re.search(r"고구마칩|야채부각", title, re.I):
        return {"food.snacks.savory.vegetable"}
    if re.search(r"다시마\s*부각칩|김부각", title, re.I):
        return {"food.snacks.savory.seaweed"}
    if re.search(r"어포", title, re.I):
        return {"food.seafood.processed.dried_fish"}
    if re.search(r"쌀\s*크래커|쌀과자|누룽지|두부\s*현미\s*스낵|서리태\s*스낵", title, re.I):
        return {"food.snacks.savory.grain"}
    if re.search(r"누가\s*샌드위치\s*크래커", title, re.I):
        return {"food.snacks.baked.sandwich"}
    if re.search(r"웨이퍼|웨하스", title, re.I):
        return {"food.snacks.baked.wafer"}
    if re.search(r"파이", title, re.I) and not re.search(r"파인애플", title, re.I):
        return {"food.snacks.baked.pie"}
    if re.search(r"프레첼|크래커", title, re.I):
        return {"food.snacks.baked.cracker"}
    if re.search(r"쿠키|비스킷|비스켓|랑그드샤|도너츠", title, re.I):
        return {"food.snacks.baked.biscuits"}
    if re.search(r"카스테라|도라야끼|바움쿠헨", title, re.I):
        return {"food.snacks.baked.cake"}
    if re.search(r"양갱", title, re.I):
        return {"food.snacks.traditional.yanggaeng"}
    if re.search(r"한과|오란다|전병", title, re.I):
        return {"food.snacks.traditional.hangwa"}
    if re.search(r"젤리", title, re.I):
        return {"food.snacks.sweets.jelly"}
    if re.search(r"캔디|마시멜로우", title, re.I):
        return {"food.snacks.sweets.candy"}
    return set()


def _contextual_costco_noodle_candidates(evidence: Mapping[str, Any]) -> set[str]:
    """Classify explicit noodle forms in the fully audited Costco ramen shelf."""
    if evidence["mart"] != "costco" or tuple(map(_label_key, evidence["source_path_parts"])) != (_label_key("라면"),):
        return set()
    title = evidence["source_title"]
    if re.search(r"조리기|면기\s*세트|냉동\s*손질\s*오징어|절단꽃게|가지\s*2봉|떡볶이\s*양념|곰탕\s*스틱|오징어소면|누룽지|뿌셔뿌셔", title, re.I):
        return set()
    if re.search(r"팟타이\s*키트", title, re.I):
        return {"food.meals.noodles.pad_thai"}
    if re.search(r"두부면|두유면", title, re.I):
        return {"food.meals.noodles.tofu_noodle"}
    if re.search(r"쌀국수", title, re.I):
        return {"food.meals.noodles.rice_noodle"}
    if re.search(r"메밀국수", title, re.I):
        return {"food.meals.noodles.buckwheat_noodle"}
    if re.search(r"수제비|누룽제비", title, re.I):
        return {"food.meals.noodles.sujebi"}
    if re.search(r"칼국수", title, re.I):
        return {"food.meals.noodles.kalguksu"}
    if re.search(r"막국수", title, re.I):
        return {"food.meals.noodles.makguksu"}
    if re.search(r"냉면|냉모밀", title, re.I):
        return {"food.meals.noodles.naengmyeon"}
    if re.search(r"우동", title, re.I) and not re.search(r"(?:컵|사발|용기)", title, re.I):
        return {"food.meals.noodles.udon"}
    if re.search(r"파스타|스파게티|라자냐|푸실리|파팔레|페투치네", title, re.I) and not re.search(r"(?:컵|사발|용기)", title, re.I):
        return {"food.meals.noodles.pasta"}
    if re.search(r"짜장면", title, re.I):
        return {"food.meals.noodles.black_bean"}
    if re.search(r"짬뽕", title, re.I) and not re.search(r"(?:컵|사발|용기|진짬뽕\s*\d)", title, re.I):
        return {"food.meals.noodles.jjamppong"}
    if re.search(r"(?:컵|사발|큰사발|왕뚜껑|용기|짜파게티범벅)", title, re.I):
        return {"food.meals.noodles.cup_ramen"}
    if re.search(r"우리밀\s*국수|다복면", title, re.I):
        return {"food.meals.noodles.wheat_noodle"}
    if re.search(r"라면|짜파게티|비빔면|안성탕면|너구리|짜슐랭|오동통면|스낵면|진짬뽕|사리면|생면식감", title, re.I):
        return {"food.meals.noodles.bag_ramen"}
    return set()


def _contextual_costco_fruit_candidates(evidence: Mapping[str, Any]) -> set[str]:
    """Exact audited titles: mixed gifts and approximate weights need review."""
    if evidence["mart"] != "costco" or tuple(evidence["source_path_parts"]) != ("과일",):
        return set()
    titles = {
        "후레쉬 라임 8kg": "lime",
        "멕시코후레쉬라임2kg": "lime",
        "남아공 자몽16kg": "grapefruit",
        "남아공 자몽 6.4kg": "grapefruit",
        "용과 4.8kg 선물세트": "dragon_fruit",
        "복숭아 5kg 선물세트": "peach",
        "황금배 7.5kg 선물세트": "pear",
        "제스프리 골드키위 선물세트2.7kg": "kiwi",
        "제스프리유기농골드키위 5.7kg(31~37입)": "kiwi",
        "제스프리 그린키위(점보)4.9kg (36~39입)": "kiwi",
        "뉴질랜드 제스프리 골드키위 5.7kg(26~31입)": "kiwi",
        "뉴질랜드제스프리점보그린키위선물세트5.4kg": "kiwi",
        "뉴질랜드 제스프리 점보 골드키위 선물세트 5.4kg": "kiwi",
        "프리미엄샤인머스캣 선물세트 4kg": "grape",
        "브라질애플망고선물세트3.7kg": "mango",
        "프리미엄 배 선물세트 7.5kg(11~12입)": "pear",
        "배 선물세트 5kg (9입이내)": "pear",
        "사과 선물세트 4kg (15입이내)": "apple",
        "프리미엄아보카도 선물세트 4kg (15입)": "avocado",
        "제주 불로초 고당도 하우스 감귤 3kg": "citrus",
        "청송사과세트5kg(15입이내)": "apple",
        "의성眞사과세트4kg": "apple",
        "하우스 밀감 3kg": "citrus",
        "하우스 감귤 5kg 세트": "citrus",
    }
    leaf = titles.get(evidence["source_title"])
    return {f"food.produce.fruit.{leaf}"} if leaf else set()


def _contextual_costco_meat_shelf_candidates(evidence: Mapping[str, Any]) -> set[str]:
    """Audited exact listings: the search shelf also contains grills and pet food.

    Do not infer raw meat from an ingredient, or extend these decisions to
    changed titles/mixed sets. Quantity and promotion validation remain separate.
    """
    if evidence["mart"] != "costco" or tuple(evidence["source_path_parts"]) != ("고기",):
        return set()
    audited = {
        "한우물 소고기잡채350g x 5 x 2pk": "food.meals.prepared.japchae",
        "사리원궁중소고기버섯잡채458g x 2": "food.meals.prepared.japchae",
        "마이셰프 알찬 고기마파두부 719g x 2": "food.meals.prepared.mapo_tofu",
        "오늘차림 한돈 양념 불고기600g x 3ea": "food.meals.prepared.seasoned_meat",
        "오늘차림서울식육수소불고기1,060g x 2ea": "food.meals.prepared.seasoned_meat",
        "부추고기순대 500gx3x2": "food.meat.processed.sundae",
        "해드림 부추고기순댓국 2,500g": "food.meals.prepared.soup_stew",
        "해찬들 사계절쌈장 500g x 8": "food.seasonings.pastes.ssamjang",
        "상하키친 비프카레 170g x 8": "food.meals.prepared.curry",
        "피터루거 스테이크소스 714ml x 2": "food.seasonings.sauces.meat",
        "온작 차돌 된장찌개 800G X 4": "food.meals.prepared.soup_stew",
        "오리늘보 훈제 슬라이스 500g x 2": "food.meat.processed.smoked_duck",
        "실키 핑크토마토4kg": "food.produce.fruit.tomato",
        "수지스닭다리살 스테이크 1,050g": "food.meals.prepared.chicken",
        "동원그릴리직화트러플도이치햄 500g x 6": "food.meat.processed.ham",
        "궁 안동식 한우국밥800g x 2": "food.meals.prepared.soup_stew",
        "오늘차림 한돈 고추장 불고기전골 1,150g x 3ea": "food.meals.prepared.soup_stew",
        "동원양반진국소고기무국 460g x 5": "food.meals.prepared.soup_stew",
        "한우물숯불닭고기볶음밥300g x 7 x 2봉(4200g)": "food.meals.rice.fried",
        "마이셰프한우소고기미역국 254g x 2": "food.meals.prepared.soup_stew",
        "해초미인 기장미역 280g": "food.seafood.seaweed.miyeok",
        "화과방 프리미엄 양갱세트 1000g x 5세트": "food.snacks.traditional.yanggaeng",
    }
    leaf = audited.get(evidence["source_title"])
    return {leaf} if leaf else set()


def _contextual_costco_cheese_shelf_candidates(evidence: Mapping[str, Any]) -> set[str]:
    """Classify explicit food forms in Costco's heavily polluted cheese shelf."""
    if evidence["mart"] != "costco" or tuple(map(_label_key, evidence["source_path_parts"])) != (_label_key("치즈"),):
        return set()
    title = evidence["source_title"]
    if re.search(r"애견|선물세트|로즈아치|중식도|필러\s*&\s*가위|치자\s*2개입", title, re.I):
        return set()
    if re.search(r"치즈\s*오징어", title, re.I):
        return {"food.seafood.processed.dried_fish"}
    if re.search(r"주먹밥", title, re.I):
        return {"food.meals.rice.rice_ball"}
    if re.search(r"치즈볼", title, re.I):
        return {"food.meals.prepared.cheese_ball"}
    if re.search(r"핫도그", title, re.I):
        return {"food.meals.prepared.hotdog"}
    if re.search(r"피자", title, re.I) and not re.search(r"피자치즈", title, re.I):
        return {"food.meals.prepared.pizza"}
    if re.search(r"파스타\s*소스|페스토", title, re.I):
        return {"food.seasonings.sauces.pasta"}
    if re.search(r"올리브", title, re.I):
        return {"food.produce.processed_vegetables.olive"}
    if re.search(r"뇨끼", title, re.I):
        return {"food.meals.noodles.gnocchi"}
    if re.search(r"라비올리", title, re.I):
        return {"food.meals.noodles.ravioli"}
    if re.search(r"곶감", title, re.I):
        return {"food.produce.processed_fruit.dried"}
    if re.search(r"명란", title, re.I):
        return {"food.seafood.processed.pollock_roe"}
    if re.search(r"(?:육전|빈대떡|감자채전|해물파전)", title, re.I):
        return {"food.meals.prepared.pancake"}
    if re.search(r"(?:오이고추|통표고)튀김", title, re.I):
        return {"food.meals.prepared.vegetable_fritter"}
    if re.search(r"왕교자", title, re.I):
        return {"food.meals.dumplings.gyoza"}
    if re.search(r"(?:수제만두|감자만두)", title, re.I):
        return {"food.meals.dumplings.assorted"}
    if re.search(r"(?:하가우|완탕)", title, re.I):
        return {"food.meals.dumplings.dimsum"}
    if re.search(r"(?:김치찌개|설렁탕|곰탕|육개장|추어탕|곱창전골)", title, re.I):
        return {"food.meals.prepared.soup_stew"}
    if re.search(r"(?:치킨텐더|치킨너겟|용가리\s*치킨)", title, re.I):
        return {"food.meals.prepared.nugget"}
    if re.search(r"돈까스", title, re.I):
        return {"food.meals.prepared.pork_cutlet"}
    if re.search(r"(?:통살치킨|닭강정|버팔로\s*핫봉|자메이카스타일\s*치킨|황금홀릭\s*순살)", title, re.I):
        return {"food.meals.prepared.chicken"}
    if re.search(r"해물경단", title, re.I):
        return {"food.seafood.processed.seafood_ball"}
    if re.search(r"우동", title, re.I):
        return {"food.meals.noodles.udon"}
    if re.search(r"찰밥", title, re.I):
        return {"food.meals.rice.sticky"}
    if re.search(r"꿀떡", title, re.I):
        return {"food.meals.prepared.rice_cake"}
    if re.search(r"떡볶이", title, re.I):
        return {"food.meals.prepared.tteokbokki"}
    if re.search(r"천하장사", title, re.I):
        return {"food.meat.processed.sausage"}
    if re.search(r"동그랑땡", title, re.I):
        return {"food.meals.prepared.meat_patty"}
    return set()


def _dairy_context(evidence: Mapping[str, Any]) -> tuple[bool, bool]:
    """Return (supported context, conflicting context), never a leaf alone.

    Search labels do not establish Costco dairy context. Every available
    official product URL must be compatible, including a conflicting canonical
    URL hidden by an otherwise plausible detail URL. Generic /Foods/p/ID can
    establish food only; the caller must still prove the type from the title.
    """
    if evidence["mart"] != "costco":
        path_keys = [_label_key(part) for part in evidence["source_path_parts"]]
        labels = set(path_keys)
        supported = bool(labels & _DAIRY_CONTEXT_LABELS)
        # A dairy subcategory named 스트링/과일/스낵치즈 is not a snack root.
        conflicting = any(re.search(r"반려|애견|애묘|완구|가전", part) for part in labels) or bool(path_keys and re.search(r"과자|스낵", path_keys[0]))
        return supported and not conflicting, conflicting
    supported, conflicting = False, False
    for url in evidence["source_urls"]:
        try:
            parsed = urlsplit(url)
        except ValueError:
            continue
        if (parsed.hostname or "").casefold() not in {"costco.co.kr", "www.costco.co.kr"}:
            continue
        parts = [unquote(part).casefold() for part in parsed.path.split("/") if part]
        if "p" not in parts or parts.index("p") == len(parts) - 1:
            continue
        prefix = parts[:parts.index("p")]
        # Product names are not categories. Preserve known terminal category
        # segments for official URLs which omit the product-name slug.
        if prefix and prefix[-1] not in _COSTCO_KNOWN_CONTEXT:
            prefix = prefix[:-1]
        if not prefix:
            continue
        compatible = prefix[0] in {"food", "foods"} and set(prefix) <= _COSTCO_DAIRY_CONTEXT
        supported |= compatible
        conflicting |= not compatible
    return supported and not conflicting, conflicting


def _contextual_dairy_candidates(evidence: Mapping[str, Any]) -> set[str]:
    """Recognize reviewed Korean type compounds only inside a food context.

    This is deliberately separate from token-aware search keyword synonyms.
    Neither a broad mart node nor a product brand is sufficient on its own.
    Unspecified cheese, yogurt texture and opaque brand-only names stay pending.
    """
    supported, conflicting = _dairy_context(evidence)
    title = re.sub(r"\s+", "", unicodedata.normalize("NFKC", evidence["source_title"])).casefold()
    if not supported or conflicting or _DAIRY_TITLE_VETO.search(title):
        return set()
    candidates: set[str] = set()
    if re.search(r"두유(?=$|[0-9a-z(]|검은콩|순수|고단백|오리지널|플레인|아몬드|무가당|저당|파우치|발아현미)", title):
        candidates.add("food.plant.soy.soymilk")
    if re.search(r"아몬드(?:음료|브리즈)", title):
        candidates.add("food.plant.drinks.almond")
    if re.search(r"그릭요(?:거|구)트|greekyogurt", title):
        candidates.add("food.dairy.yogurt.greek")
    elif re.search(r"(?:드링킹|마시는)요(?:구르트|거트)", title):
        candidates.add("food.dairy.yogurt.drink")
    elif re.search(r"떠먹는요(?:구르트|거트)", title):
        candidates.add("food.dairy.yogurt.spoon")
    cheese_name = re.search(r"치즈|체다|고다|에담|에멘탈|마스담|모짜렐라|파마지아노|파르미지아노|레지아노", title)
    # Shapes take precedence over milk/cheese variety (e.g. shredded Parmesan).
    # A shape plus a different explicit form such as cream/string is a conflict.
    shaped = set()
    if cheese_name and "슬라이스" in title:
        shaped.add("food.dairy.cheese.sliced")
    if cheese_name and re.search(r"슈레드|쉬레드|shredded", title):
        shaped.add("food.dairy.cheese.shredded")
    if "스트링치즈" in title:
        shaped.add("food.dairy.cheese.string")
    candidates |= shaped
    if "크림치즈" in title:
        candidates.add("food.dairy.cheese.cream")
    if not shaped:
        for pattern, leaf in (
            (r"(?:후레쉬|프레쉬|프레시|생)모짜렐라|보코치니", "fresh_mozzarella"),
            (r"리코타", "ricotta"), (r"부라타치즈", "burrata"),
            (r"마스카르포네", "mascarpone"), (r"브리(?=$|[0-9a-z]|치즈)", "brie"),
            (r"까망베르|카망베르", "camembert"), (r"그라나파다노|만체고", "hard_aged"),
        ):
            if re.search(pattern, title):
                candidates.add(f"food.dairy.cheese.{leaf}")
    if "버터" in title:
        candidates.add("food.dairy.cheese.butter")
    if re.search(r"생크림(?=$|[0-9a-z(])", title) and not re.search(r"식물성|휘핑|요거트|요구르트|치즈", title):
        candidates.add("food.dairy.cream.fresh")

    # Remove milk-manufacturer names before looking for an actual milk noun.
    # A coffee/yogurt sold by 서울우유 or 연세우유 is not itself plain milk.
    milk_title = re.sub(r"서울우유|연세우유|매일우유", "", title)
    milk_type = re.search(r"우유(?=$|[0-9a-z(]|저지방|고칼슘|비타민|오리지널|무가당|기획)|밀크(?=$|[0-9a-z(]|기획)", milk_title)
    if milk_type and not candidates and not re.search(r"요거트|요구르트|치즈|크림|분유|두유|단백질음료|카페라[떼테]|카푸치노|콜드브루|바닐라딜라이트|아메리카노", milk_title):
        flavours = {
            leaf for pattern, leaf in (
                (r"(?:초코|쵸코)(?:릿)?", "chocolate"), (r"딸기", "strawberry"),
                (r"바나나", "banana"), (r"커피", "coffee"), (r"말차", "matcha"),
            ) if re.search(pattern, milk_title)
        }
        if flavours:
            candidates.update(f"food.dairy.milk.{leaf}" for leaf in flavours)
        elif not re.search(r"가공우유|맛|라[떼테]|코코아|흑당|바닐라|혼합|망고|복숭아|멜론|메론|검은콩|바나바나|밤우유", milk_title) and not any(re.search(r"바나나|딸기|초코|초콜릿|커피|가공우유", part) for part in evidence["source_path_parts"]):
            candidates.add("food.dairy.milk.plain")
    return candidates


def _suspicion_reason(category_id: str, evidence: Mapping[str, Any]) -> str | None:
    title = evidence["source_title"]
    if category_id.startswith("food.dairy.") and _PLANT_DAIRY_HINT.search(re.sub(r"\s+", "", title)):
        return "plant_alternative_not_confirmed_dairy"
    if category_id.startswith("food.dairy.") or category_id in {"food.plant.soy.soymilk", "food.plant.drinks.almond"}:
        if _DAIRY_TITLE_VETO.search(re.sub(r"\s+", "", title)):
            return "dairy_ingredient_accessory_or_mixed_product"
        if _dairy_context(evidence)[1]:
            return "dairy_source_context_conflict"
    if category_id.startswith("food.") and re.search(r"제조기|메이커|장난감|인형|사료|반려견|반려묘|강아지|고양이", title):
        return "non_food_product_or_pet_context"
    if category_id.startswith("beauty.") and (re.search(r"강아지|고양이|반려견|반려묘|애견|애묘", title) or evidence["source_path_parts"][:1] == ["반려동물"]):
        return "pet_product_context"
    if category_id.startswith(("food.plant.", "food.meals.noodles.", "food.dairy.milk.")) and re.search(r"양념|드레싱|제조기", title):
        return "ingredient_or_accessory_instead_of_product"
    if category_id.startswith("food.seasonings.oils.") and re.search(r"김자반|돌자반|재래김|스낵|김밥|참치", title):
        return "ingredient_mentioned_in_different_product"
    if category_id.startswith("household.hygiene.paper.") and ("특가" in title or "일부품목제외" in title) and "/" in title:
        return "multi_product_promotion_not_listing"
    required = _TITLE_REQUIRED.get(category_id)
    if required is not None and not required.search(title):
        return "source_leaf_needs_name_corroboration"
    forbidden = _TITLE_FORBIDDEN.get(category_id)
    if forbidden is not None and forbidden.search(title):
        return "source_title_product_type_conflict"
    return None


def taxonomy_categories(category_ids: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """Return deterministic bundle rows; optionally include only used branches."""
    selected = set(category_ids) if category_ids is not None else set(_BY_ID)
    unknown = selected - set(_BY_ID)
    if unknown:
        raise ValueError(f"Unknown leaf category IDs: {sorted(unknown)}")
    nodes: dict[str, dict[str, Any]] = {}
    for leaf_id in sorted(selected):
        leaf = _BY_ID[leaf_id]
        parts = leaf.id.split(".")
        for level, name in enumerate(leaf.path):
            node_id = ".".join(parts[:level + 1])
            row = {"id": node_id, "parent_id": ".".join(parts[:level]) or None, "slug": parts[level], "name_ko": name, "level": level, "source_origin": "initial-real-catalog-v1"}
            if node_id in nodes and nodes[node_id] != row:
                raise ValueError(f"Conflicting taxonomy node: {node_id}")
            nodes[node_id] = row
    rows = sorted(nodes.values(), key=lambda row: (row["level"], row["id"]))
    for order, row in enumerate(rows):
        row["sort_order"] = order
    validate_taxonomy(rows, selected)
    return rows


def validate_taxonomy(categories: Iterable[Mapping[str, Any]], assigned_ids: Iterable[str] = ()) -> None:
    """Reject missing parents, cycles, fifth levels and internal assignments."""
    rows = list(categories)
    by_id = {str(row["id"]): row for row in rows}
    if len(by_id) != len(rows):
        raise ValueError("Duplicate category ID")
    parents = {str(row["parent_id"]) for row in rows if row.get("parent_id")}
    for node_id in by_id:
        chain: set[str] = set()
        cursor: str | None = node_id
        while cursor:
            if cursor in chain:
                raise ValueError(f"Category cycle at {cursor}")
            if cursor not in by_id:
                raise ValueError(f"Missing category parent {cursor}")
            chain.add(cursor)
            cursor = by_id[cursor].get("parent_id")
        if len(chain) > MAX_CATEGORY_LEVEL + 1:
            raise ValueError(f"Category exceeds four levels: {node_id}")
        if "level" in by_id[node_id] and int(by_id[node_id]["level"]) != len(chain) - 1:
            raise ValueError(f"Incorrect category level: {node_id}")
    for node_id in assigned_ids:
        if node_id not in by_id or node_id in parents:
            raise ValueError(f"Assignment is not a known leaf: {node_id}")


def keyword_definitions(category_ids: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """Fresh, collision-checked search terms; not loose substring match rules."""
    selected = set(category_ids) if category_ids is not None else set(_BY_ID)
    rows = []
    for leaf_id in sorted(selected):
        leaf = _BY_ID[leaf_id]
        terms = [leaf.path[-1], *leaf.name_terms]
        unique: dict[tuple[str, ...], str] = {}
        for term in terms:
            if len("".join(_tokens(term))) >= 2:
                unique.setdefault(_tokens(term), term)
        if not unique:
            continue
        values = list(unique.values())
        rows.append({"word": values[0], "synonyms": values[1:], "unified_category_id": leaf_id})
    validate_keyword_definitions(rows)
    return rows


def keyword_collisions(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[str]]:
    """Find the same token-normalized term pointing at different leaves."""
    owners: dict[tuple[str, ...], set[str]] = defaultdict(set)
    for row in rows:
        for term in (row.get("word"), *(row.get("synonyms") or [])):
            key = _tokens(term)
            if key:
                owners[key].add(str(row.get("unified_category_id") or ""))
    return {" ".join(term): sorted(ids) for term, ids in sorted(owners.items()) if len(ids) > 1}


def validate_keyword_definitions(rows: Iterable[Mapping[str, Any]]) -> None:
    rows = list(rows)
    for row in rows:
        if row.get("unified_category_id") not in _BY_ID:
            raise ValueError("Keyword must refer to a curated leaf")
        if not isinstance(row.get("synonyms", []), (list, tuple)):
            raise ValueError("Keyword synonyms must be a list")
        for term in (row.get("word"), *(row.get("synonyms") or [])):
            if not isinstance(term, str) or len("".join(_tokens(term))) < 2:
                raise ValueError("Keywords and synonyms require at least two characters")
    collisions = keyword_collisions(rows)
    if collisions:
        raise ValueError(f"Ambiguous keyword collisions: {collisions}")


def contains_term(text: str, term: str) -> bool:
    """Match complete token sequences, never arbitrary Korean substrings."""
    haystack, needle = _tokens(text), _tokens(term)
    return bool(needle) and any(haystack[i:i + len(needle)] == needle for i in range(len(haystack) - len(needle) + 1))


def normalize_source_path(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        raw_parts = value
    elif isinstance(value, str):
        # JSON arrays occur in normalized exports; malformed/python repr arrays
        # are not silently interpreted as trusted category paths.
        if value.lstrip().startswith("["):
            try:
                decoded = json.loads(value)
            except (ValueError, TypeError):
                decoded = None
            raw_parts = decoded if isinstance(decoded, list) else [value]
        else:
            raw_parts = re.split(r"\s*(?:>|→)\s*", value)
    else:
        raw_parts = []
    parts: list[str] = []
    for raw in raw_parts:
        if isinstance(raw, Mapping):
            raw = raw.get("name") or raw.get("label") or raw.get("title")
        part = _text(raw)
        if part and (not parts or _label_key(part) != _label_key(parts[-1])):
            parts.append(part)
    return tuple(parts)


def native_category_key(mart: str, source_path: Iterable[str]) -> str | None:
    """Path identity, not Homeplus's reused root ID or a missing Lotte ID."""
    parts = tuple(_label_key(part) for part in source_path if _text(part))
    if not parts:
        return None
    body = json.dumps([mart, *parts], ensure_ascii=False, separators=(",", ":"))
    return f"{mart}:path:{hashlib.sha256(body.encode('utf-8')).hexdigest()[:24]}"


def source_evidence(record: Mapping[str, Any]) -> dict[str, Any]:
    payload = record.get("payload") or record.get("raw_payload") or record
    if not isinstance(payload, Mapping):
        payload = record
    attrs = payload.get("attributes") or payload.get("attrs") or {}
    if not isinstance(attrs, Mapping):
        attrs = {}
    mart = _text(record.get("mart") or record.get("source_name") or payload.get("mart") or payload.get("source_name") or attrs.get("source_name") or payload.get("source")).casefold()
    mart = _MART_ALIASES.get(mart, mart)
    # HP's full path lives under attributes despite a root-only top-level ID.
    # Older Lotte payloads use category_path; newer ones also carry native path.
    path_candidates = (
        (attrs.get("mart_native_category_path"), "attributes.mart_native_category_path"),
        (attrs.get("category_path"), "attributes.category_path"),
        (attrs.get("source_category_path"), "attributes.source_category_path"),
        (payload.get("mart_native_category_path"), "mart_native_category_path"),
        (payload.get("source_category_path"), "source_category_path"),
        (payload.get("category_path"), "category_path"),
        (record.get("source_category_path"), "observation.source_category_path"),
        (payload.get("category"), "category"),
        (attrs.get("category_hint"), "attributes.category_hint"),
    )
    path, field = (), None
    for value, candidate_field in path_candidates:
        candidate = normalize_source_path(value)
        if candidate:
            path, field = candidate, candidate_field
            break
    urls = []
    for container in (payload, attrs, record):
        for key in ("canonical_url", "detail_url", "source_url"):
            value = _text(container.get(key))
            if value and value not in urls:
                urls.append(value)
    return {
        "mart": mart,
        "source_path": " > ".join(path),
        "source_path_parts": list(path),
        "source_path_field": field,
        "native_category_key": native_category_key(mart, path),
        "raw_native_category_id": payload.get("mart_native_category_id") or attrs.get("mart_native_category_id"),
        "source_title": _text(payload.get("raw_name") or payload.get("source_title") or payload.get("name") or record.get("source_title") or record.get("name")),
        "source_urls": urls,
        "promotion_surface": any(_label_key(part) in _PROMO for part in path),
    }


def _path_candidates(evidence: Mapping[str, Any]) -> set[str]:
    parts = evidence["source_path_parts"]
    if evidence["mart"] not in {"homeplus", "lottemart"} or len(parts) < 2 or evidence["promotion_surface"]:
        return set()
    keys = [_label_key(part) for part in parts]
    last, ancestors = keys[-1], set(keys[:-1])
    candidates = set()
    for leaf_id, contexts, roots in _PATH_INDEX.get(last, ()):
        if ancestors.intersection(contexts) and keys[0] in roots:
            candidates.add(leaf_id)
    # Lotte distinguishes bag/cup at the penultimate node, while its last node
    # describes flavour.  Flavour does not become an extra fifth taxonomy level.
    ramen_flavours = {_label_key(label) for label in ("일반라면", "볶음면/기타라면", "짜장라면", "비빔면", "컵라면", "봉지라면")}
    if evidence["mart"] == "lottemart" and keys[0] == _label_key("라면ㆍ통조림ㆍ즉석밥") and len(keys) >= 3 and last in ramen_flavours:
        if _label_key("컵라면") in ancestors:
            candidates.add("food.meals.noodles.cup_ramen")
        elif _label_key("봉지라면") in ancestors:
            candidates.add("food.meals.noodles.bag_ramen")
    return candidates


def _name_candidates(title: str) -> set[str]:
    tokens = _tokens(title)
    return {
        leaf_id for index, token in enumerate(tokens)
        for term, leaf_id in _NAME_INDEX.get(token, ())
        if tokens[index:index + len(term)] == term
    }


# A product slug is NOT taxonomy evidence.  Only known complete URL category
# segments before the last product-name segment, on the official hostname, are
# considered.  Broad Shaving/Mens-Shaving itself cannot distinguish blade/razor.
_COSTCO_URL_LEAVES = {
    "razors": "beauty.personal.shaving.razor",
    "razor-blades": "beauty.personal.shaving.blades",
    "shaving-cream": "beauty.personal.shaving.foam",
    "shampoo": "beauty.personal.hair.shampoo",
    "shampoos": "beauty.personal.hair.shampoo",
    "fabric-softeners": "household.cleaning.laundry.softener",
    "dishwashing-liquid": "household.cleaning.kitchen.detergent",
    "toilet-paper": "household.hygiene.paper.toilet",
    "paper-towels": "household.hygiene.paper.kitchen",
}


def _url_candidates(evidence: Mapping[str, Any]) -> tuple[set[str], list[str]]:
    candidates: set[str] = set()
    hints: list[str] = []
    if evidence["mart"] != "costco":
        return candidates, hints
    for url in evidence["source_urls"]:
        try:
            parsed = urlsplit(url)
        except ValueError:
            continue
        if (parsed.hostname or "").casefold() not in {"costco.co.kr", "www.costco.co.kr"}:
            continue
        segments = [unquote(part).casefold() for part in parsed.path.split("/") if part]
        if "p" not in segments:
            continue
        product_marker = segments.index("p")
        # Official product URL: /Department/Subcategory/Product-Name/p/ID.
        taxonomy_segments = segments[:max(0, product_marker - 1)]
        hints.extend(part for part in taxonomy_segments if part not in hints)
        candidates.update(_COSTCO_URL_LEAVES[part] for part in taxonomy_segments if part in _COSTCO_URL_LEAVES)
    return candidates, hints


def classify_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Classify only supported leaf evidence; return a reviewable plain dict.

    ``review_status='classified'`` means sufficient evidence for a *proposal*,
    never DB/publication approval.  A caller must retain unresolved observations
    and must not convert ``proposed_path`` to an assigned category.
    """
    evidence = source_evidence(record)
    path_ids = _path_candidates(evidence)
    name_ids = _name_candidates(evidence["source_title"])
    url_ids, url_hints = _url_candidates(evidence)
    contextual_ids = _contextual_dairy_candidates(evidence)
    coffee_ids = _contextual_coffee_candidates(evidence)
    beverage_ids = _contextual_audited_beverage_candidates(evidence)
    snack_ids = _contextual_costco_snack_candidates(evidence)
    noodle_ids = _contextual_costco_noodle_candidates(evidence)
    cheese_shelf_ids = _contextual_costco_cheese_shelf_candidates(evidence)
    fruit_ids = _contextual_costco_fruit_candidates(evidence)
    meat_shelf_ids = _contextual_costco_meat_shelf_candidates(evidence)
    audited_emart_leaf = (
        AUDITED_EMART_FOOD_TITLES.get(evidence["source_title"])
        if evidence["mart"] == "emart" and tuple(evidence["source_path_parts"]) in {
            ("밀키트/간편식",), ("면류/통조림",), ("베이커리/잼",),
        } else None
    )
    audited_emart_ids = {audited_emart_leaf} if audited_emart_leaf else set()
    household_leaf = (
        AUDITED_EMART_HOUSEHOLD_TITLES.get(evidence["source_title"])
        if evidence["mart"] == "emart" and tuple(evidence["source_path_parts"]) in {
            ("청소/생활용품",), ("제지/위생/건강",), ("헤어/바디/뷰티",),
        } else None
    )
    household_ids = {household_leaf} if household_leaf else set()
    if coffee_ids:
        # Audited product-form words are more specific than a mart's broad
        # "커피믹스" shelf (which also contains plain Kanu Americano).
        path_ids = {candidate for candidate in path_ids if not candidate.startswith("food.drinks.coffee.")}
        name_ids = {candidate for candidate in name_ids if not candidate.startswith("food.drinks.coffee.")}
    all_ids = path_ids | name_ids | url_ids | contextual_ids | coffee_ids | beverage_ids | snack_ids | noodle_ids | cheese_shelf_ids | fruit_ids | meat_shelf_ids | audited_emart_ids | household_ids
    result = {
        **evidence,
        "unified_category_id": None,
        "classification_confidence": 0.0,
        "review_status": "pending",
        "classification_reason": "insufficient_leaf_evidence",
        "evidence_type": None,
        "category_path": [],
        "proposed_path": None,
        "candidate_category_ids": sorted(all_ids),
        "url_taxonomy_hints": url_hints,
    }
    if len(all_ids) > 1:
        result["classification_reason"] = "conflicting_category_evidence"
        result["proposed_path"] = [list(_BY_ID[candidate].path) for candidate in sorted(all_ids)]
        return result
    if all_ids:
        category_id = next(iter(all_ids))
        suspicion = _suspicion_reason(category_id, evidence)
        if suspicion:
            result["classification_reason"] = suspicion
            result["proposed_path"] = list(_BY_ID[category_id].path)
            return result
        confidence, kind = (
            (0.97, "source_full_path") if path_ids else
            ((0.93, "official_url_taxonomy") if url_ids else
             ((0.90, "contextual_coffee_title") if coffee_ids else
              ((0.90, "contextual_costco_beverage_title") if beverage_ids else
               ((0.90, "contextual_costco_snack_title") if snack_ids else
                ((0.90, "contextual_costco_noodle_title") if noodle_ids else
                 ((0.90, "contextual_costco_cheese_shelf_title") if cheese_shelf_ids else
                  ((0.86, "unambiguous_name_tokens") if name_ids else (0.90, "contextual_dairy_title"))))))))
        )
        if fruit_ids:
            confidence, kind = 0.95, "audited_costco_fruit_title"
        if meat_shelf_ids:
            confidence, kind = 0.95, "audited_costco_meat_shelf_title"
        if audited_emart_ids:
            confidence, kind = 0.95, "audited_emart_food_title"
        if household_ids:
            confidence, kind = 0.95, "audited_emart_household_title"
        result.update(unified_category_id=category_id, classification_confidence=confidence, review_status="classified", classification_reason=f"supported_by_{kind}", evidence_type=kind, category_path=list(_BY_ID[category_id].path))
        if category_id.startswith("food.dairy.milk."):
            result["classification_attributes"] = {
                "fat_content": "fat_free" if "무지방" in evidence["source_title"] else ("low_fat" if "저지방" in evidence["source_title"] else None),
                "sterilized": True if "멸균" in evidence["source_title"] else None,
            }
        return result
    if evidence["promotion_surface"]:
        result["classification_reason"] = "promotion_surface_without_leaf_evidence"
    elif len(evidence["source_path_parts"]) <= 1:
        result["classification_reason"] = "broad_source_category"
    # Preserve human-readable evidence, without inventing a 기타 leaf or assigning
    # an existing internal node merely to increase coverage.
    result["proposed_path"] = evidence["source_path_parts"] or url_hints or None
    return result


__all__ = [
    "LEAVES", "MAX_CATEGORY_LEVEL", "classify_record", "contains_term",
    "keyword_collisions", "keyword_definitions", "native_category_key",
    "normalize_source_path", "source_evidence", "taxonomy_categories",
    "validate_keyword_definitions", "validate_taxonomy",
]
