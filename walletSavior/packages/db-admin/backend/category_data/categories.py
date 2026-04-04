"""
WalletSavior 포괄적 카테고리 트리.

한국 시장에 맞춘 300 개 이상의 계층적 카테고리 데이터.
각 카테고리는 dot-notation ID 를 사용합니다 (예: "agriculture.leafy.spinach").
"""

from __future__ import annotations
from typing import Optional


def _cat(id: str, name: str, *, parent_id: Optional[str] = None,
         depth: int = 0, sort_order: int = 0, icon: Optional[str] = None,
         attributes: Optional[dict] = None) -> dict:
    """카테고리 딕셔너리 생성 헬퍼."""
    return {
        "id": id,
        "name": name,
        "parent_id": parent_id,
        "depth": depth,
        "sort_order": sort_order,
        "icon": icon,
        "attributes": attributes or {},
        "is_active": True,
    }


# ──────────────────────────────────────────────
# 전체 카테고리 목록 (flat list, 300 개 이상)
# ──────────────────────────────────────────────
CATEGORIES: list[dict] = [
    # ═══════════════════════════════════════════
    # 농산물
    # ═══════════════════════════════════════════
    _cat("agriculture", "농산물", icon="🥬", sort_order=1),

    # 엽채류
    _cat("agriculture.leafy", "엽채류", parent_id="agriculture", depth=1, sort_order=1),
    _cat("agriculture.leafy.napa_cabbage", "배추", parent_id="agriculture.leafy", depth=2, sort_order=1),
    _cat("agriculture.leafy.spinach", "시금치", parent_id="agriculture.leafy", depth=2, sort_order=2),
    _cat("agriculture.leafy.lettuce", "상추", parent_id="agriculture.leafy", depth=2, sort_order=3),
    _cat("agriculture.leafy.cabbage", "양배추", parent_id="agriculture.leafy", depth=2, sort_order=4),
    _cat("agriculture.leafy.perilla", "깻잎", parent_id="agriculture.leafy", depth=2, sort_order=5),
    _cat("agriculture.leafy.chive", "부추", parent_id="agriculture.leafy", depth=2, sort_order=6),
    _cat("agriculture.leafy.water_parsley", "미나리", parent_id="agriculture.leafy", depth=2, sort_order=7),
    _cat("agriculture.leafy.bok_choy", "청경채", parent_id="agriculture.leafy", depth=2, sort_order=8),
    _cat("agriculture.leafy.kale", "케일", parent_id="agriculture.leafy", depth=2, sort_order=9),
    _cat("agriculture.leafy.chicory", "치커리", parent_id="agriculture.leafy", depth=2, sort_order=10),
    _cat("agriculture.leafy.bean_sprout", "콩나물", parent_id="agriculture.leafy", depth=2, sort_order=11),
    _cat("agriculture.leafy.mung_sprout", "숙주나물", parent_id="agriculture.leafy", depth=2, sort_order=12),
    _cat("agriculture.leafy.green_onion", "대파", parent_id="agriculture.leafy", depth=2, sort_order=13),
    _cat("agriculture.leafy.chili_pepper_leaf", "고춧잎", parent_id="agriculture.leafy", depth=2, sort_order=14),

    # 과채류
    _cat("agriculture.fruit_veg", "과채류", parent_id="agriculture", depth=1, sort_order=2),
    _cat("agriculture.fruit_veg.tomato", "토마토", parent_id="agriculture.fruit_veg", depth=2, sort_order=1),
    _cat("agriculture.fruit_veg.cucumber", "오이", parent_id="agriculture.fruit_veg", depth=2, sort_order=2),
    _cat("agriculture.fruit_veg.chili", "고추", parent_id="agriculture.fruit_veg", depth=2, sort_order=3),
    _cat("agriculture.fruit_veg.paprika", "파프리카", parent_id="agriculture.fruit_veg", depth=2, sort_order=4),
    _cat("agriculture.fruit_veg.eggplant", "가지", parent_id="agriculture.fruit_veg", depth=2, sort_order=5),
    _cat("agriculture.fruit_veg.pumpkin", "호박", parent_id="agriculture.fruit_veg", depth=2, sort_order=6),
    _cat("agriculture.fruit_veg.zucchini", "애호박", parent_id="agriculture.fruit_veg", depth=2, sort_order=7),
    _cat("agriculture.fruit_veg.green_chili", "풋고추", parent_id="agriculture.fruit_veg", depth=2, sort_order=8),
    _cat("agriculture.fruit_veg.cheongyang", "청양고추", parent_id="agriculture.fruit_veg", depth=2, sort_order=9),
    _cat("agriculture.fruit_veg.sweet_pumpkin", "단호박", parent_id="agriculture.fruit_veg", depth=2, sort_order=10),
    _cat("agriculture.fruit_veg.corn", "옥수수", parent_id="agriculture.fruit_veg", depth=2, sort_order=11),

    # 근채류
    _cat("agriculture.root", "근채류", parent_id="agriculture", depth=1, sort_order=3),
    _cat("agriculture.root.potato", "감자", parent_id="agriculture.root", depth=2, sort_order=1),
    _cat("agriculture.root.sweet_potato", "고구마", parent_id="agriculture.root", depth=2, sort_order=2),
    _cat("agriculture.root.carrot", "당근", parent_id="agriculture.root", depth=2, sort_order=3),
    _cat("agriculture.root.radish", "무", parent_id="agriculture.root", depth=2, sort_order=4),
    _cat("agriculture.root.onion", "양파", parent_id="agriculture.root", depth=2, sort_order=5),
    _cat("agriculture.root.garlic", "마늘", parent_id="agriculture.root", depth=2, sort_order=6),
    _cat("agriculture.root.ginger", "생강", parent_id="agriculture.root", depth=2, sort_order=7),
    _cat("agriculture.root.burdock", "우엉", parent_id="agriculture.root", depth=2, sort_order=8),
    _cat("agriculture.root.lotus_root", "연근", parent_id="agriculture.root", depth=2, sort_order=9),
    _cat("agriculture.root.deodeok", "더덕", parent_id="agriculture.root", depth=2, sort_order=10),
    _cat("agriculture.root.bellflower", "도라지", parent_id="agriculture.root", depth=2, sort_order=11),
    _cat("agriculture.root.taro", "토란", parent_id="agriculture.root", depth=2, sort_order=12),

    # 과일류
    _cat("agriculture.fruit", "과일류", parent_id="agriculture", depth=1, sort_order=4, icon="🍎"),
    _cat("agriculture.fruit.apple", "사과", parent_id="agriculture.fruit", depth=2, sort_order=1),
    _cat("agriculture.fruit.pear", "배", parent_id="agriculture.fruit", depth=2, sort_order=2),
    _cat("agriculture.fruit.tangerine", "감귤", parent_id="agriculture.fruit", depth=2, sort_order=3),
    _cat("agriculture.fruit.strawberry", "딸기", parent_id="agriculture.fruit", depth=2, sort_order=4),
    _cat("agriculture.fruit.grape", "포도", parent_id="agriculture.fruit", depth=2, sort_order=5),
    _cat("agriculture.fruit.watermelon", "수박", parent_id="agriculture.fruit", depth=2, sort_order=6),
    _cat("agriculture.fruit.melon", "참외", parent_id="agriculture.fruit", depth=2, sort_order=7),
    _cat("agriculture.fruit.peach", "복숭아", parent_id="agriculture.fruit", depth=2, sort_order=8),
    _cat("agriculture.fruit.plum", "자두", parent_id="agriculture.fruit", depth=2, sort_order=9),
    _cat("agriculture.fruit.mango", "망고", parent_id="agriculture.fruit", depth=2, sort_order=10),
    _cat("agriculture.fruit.banana", "바나나", parent_id="agriculture.fruit", depth=2, sort_order=11),
    _cat("agriculture.fruit.kiwi", "키위", parent_id="agriculture.fruit", depth=2, sort_order=12),
    _cat("agriculture.fruit.blueberry", "블루베리", parent_id="agriculture.fruit", depth=2, sort_order=13),
    _cat("agriculture.fruit.cherry", "체리", parent_id="agriculture.fruit", depth=2, sort_order=14),
    _cat("agriculture.fruit.cantaloupe", "멜론", parent_id="agriculture.fruit", depth=2, sort_order=15),
    _cat("agriculture.fruit.pineapple", "파인애플", parent_id="agriculture.fruit", depth=2, sort_order=16),
    _cat("agriculture.fruit.hallabong", "한라봉", parent_id="agriculture.fruit", depth=2, sort_order=17),
    _cat("agriculture.fruit.lemon", "레몬", parent_id="agriculture.fruit", depth=2, sort_order=18),
    _cat("agriculture.fruit.persimmon", "감", parent_id="agriculture.fruit", depth=2, sort_order=19),
    _cat("agriculture.fruit.shine_muscat", "샤인머스캣", parent_id="agriculture.fruit", depth=2, sort_order=20),

    # 버섯류
    _cat("agriculture.mushroom", "버섯류", parent_id="agriculture", depth=1, sort_order=5, icon="🍄"),
    _cat("agriculture.mushroom.king_oyster", "새송이버섯", parent_id="agriculture.mushroom", depth=2, sort_order=1),
    _cat("agriculture.mushroom.enoki", "팽이버섯", parent_id="agriculture.mushroom", depth=2, sort_order=2),
    _cat("agriculture.mushroom.shiitake", "표고버섯", parent_id="agriculture.mushroom", depth=2, sort_order=3),
    _cat("agriculture.mushroom.oyster", "느타리버섯", parent_id="agriculture.mushroom", depth=2, sort_order=4),
    _cat("agriculture.mushroom.button", "양송이버섯", parent_id="agriculture.mushroom", depth=2, sort_order=5),
    _cat("agriculture.mushroom.wood_ear", "목이버섯", parent_id="agriculture.mushroom", depth=2, sort_order=6),
    _cat("agriculture.mushroom.matsutake", "송이버섯", parent_id="agriculture.mushroom", depth=2, sort_order=7),

    # 곡류
    _cat("agriculture.grain", "곡류", parent_id="agriculture", depth=1, sort_order=6, icon="🌾"),
    _cat("agriculture.grain.rice", "쌀", parent_id="agriculture.grain", depth=2, sort_order=1),
    _cat("agriculture.grain.glutinous_rice", "찹쌀", parent_id="agriculture.grain", depth=2, sort_order=2),
    _cat("agriculture.grain.barley", "보리", parent_id="agriculture.grain", depth=2, sort_order=3),
    _cat("agriculture.grain.black_rice", "흑미", parent_id="agriculture.grain", depth=2, sort_order=4),
    _cat("agriculture.grain.millet", "좁쌀", parent_id="agriculture.grain", depth=2, sort_order=5),
    _cat("agriculture.grain.oat", "귀리", parent_id="agriculture.grain", depth=2, sort_order=6),

    # ═══════════════════════════════════════════
    # 축산물
    # ═══════════════════════════════════════════
    _cat("livestock", "축산물", icon="🥩", sort_order=2),

    # 소고기
    _cat("livestock.beef", "소고기", parent_id="livestock", depth=1, sort_order=1),
    _cat("livestock.beef.sirloin", "등심", parent_id="livestock.beef", depth=2, sort_order=1),
    _cat("livestock.beef.tenderloin", "안심", parent_id="livestock.beef", depth=2, sort_order=2),
    _cat("livestock.beef.ribs", "갈비", parent_id="livestock.beef", depth=2, sort_order=3),
    _cat("livestock.beef.shank", "사태", parent_id="livestock.beef", depth=2, sort_order=4),
    _cat("livestock.beef.brisket", "양지", parent_id="livestock.beef", depth=2, sort_order=5),
    _cat("livestock.beef.chadol", "차돌박이", parent_id="livestock.beef", depth=2, sort_order=6),
    _cat("livestock.beef.round", "우둔", parent_id="livestock.beef", depth=2, sort_order=7),
    _cat("livestock.beef.chuck", "목심", parent_id="livestock.beef", depth=2, sort_order=8),
    _cat("livestock.beef.hanwoo", "한우", parent_id="livestock.beef", depth=2, sort_order=9,
         attributes={"grade": ["1++", "1+", "1", "2", "3"]}),

    # 돼지고기
    _cat("livestock.pork", "돼지고기", parent_id="livestock", depth=1, sort_order=2),
    _cat("livestock.pork.belly", "삼겹살", parent_id="livestock.pork", depth=2, sort_order=1),
    _cat("livestock.pork.neck", "목살", parent_id="livestock.pork", depth=2, sort_order=2),
    _cat("livestock.pork.front_leg", "앞다리", parent_id="livestock.pork", depth=2, sort_order=3),
    _cat("livestock.pork.hind_leg", "뒷다리", parent_id="livestock.pork", depth=2, sort_order=4),
    _cat("livestock.pork.ribs", "돼지갈비", parent_id="livestock.pork", depth=2, sort_order=5),
    _cat("livestock.pork.loin", "돼지등심", parent_id="livestock.pork", depth=2, sort_order=6),
    _cat("livestock.pork.tenderloin", "돼지안심", parent_id="livestock.pork", depth=2, sort_order=7),

    # 닭고기
    _cat("livestock.chicken", "닭고기", parent_id="livestock", depth=1, sort_order=3),
    _cat("livestock.chicken.whole", "통닭", parent_id="livestock.chicken", depth=2, sort_order=1),
    _cat("livestock.chicken.breast", "닭가슴살", parent_id="livestock.chicken", depth=2, sort_order=2),
    _cat("livestock.chicken.leg", "닭다리", parent_id="livestock.chicken", depth=2, sort_order=3),
    _cat("livestock.chicken.wing", "닭날개", parent_id="livestock.chicken", depth=2, sort_order=4),
    _cat("livestock.chicken.stew_cut", "닭볶음탕용", parent_id="livestock.chicken", depth=2, sort_order=5),

    # 기타 축산
    _cat("livestock.egg", "계란", parent_id="livestock", depth=1, sort_order=4, icon="🥚"),
    _cat("livestock.duck", "오리고기", parent_id="livestock", depth=1, sort_order=5),
    _cat("livestock.lamb", "양고기", parent_id="livestock", depth=1, sort_order=6),
    _cat("livestock.quail_egg", "메추리알", parent_id="livestock", depth=1, sort_order=7),

    # ═══════════════════════════════════════════
    # 수산물
    # ═══════════════════════════════════════════
    _cat("seafood", "수산물", icon="🐟", sort_order=3),

    # 생선
    _cat("seafood.fish", "생선", parent_id="seafood", depth=1, sort_order=1),
    _cat("seafood.fish.mackerel", "고등어", parent_id="seafood.fish", depth=2, sort_order=1),
    _cat("seafood.fish.spanish_mackerel", "삼치", parent_id="seafood.fish", depth=2, sort_order=2),
    _cat("seafood.fish.cutlass", "갈치", parent_id="seafood.fish", depth=2, sort_order=3),
    _cat("seafood.fish.salmon", "연어", parent_id="seafood.fish", depth=2, sort_order=4),
    _cat("seafood.fish.tuna", "참치", parent_id="seafood.fish", depth=2, sort_order=5),
    _cat("seafood.fish.flounder", "광어", parent_id="seafood.fish", depth=2, sort_order=6),
    _cat("seafood.fish.rockfish", "우럭", parent_id="seafood.fish", depth=2, sort_order=7),
    _cat("seafood.fish.sea_bream", "도미", parent_id="seafood.fish", depth=2, sort_order=8),
    _cat("seafood.fish.croaker", "조기", parent_id="seafood.fish", depth=2, sort_order=9),
    _cat("seafood.fish.saury", "꽁치", parent_id="seafood.fish", depth=2, sort_order=10),
    _cat("seafood.fish.cod", "대구", parent_id="seafood.fish", depth=2, sort_order=11),
    _cat("seafood.fish.eel", "장어", parent_id="seafood.fish", depth=2, sort_order=12),

    # 갑각류
    _cat("seafood.crustacean", "갑각류", parent_id="seafood", depth=1, sort_order=2),
    _cat("seafood.crustacean.shrimp", "새우", parent_id="seafood.crustacean", depth=2, sort_order=1),
    _cat("seafood.crustacean.blue_crab", "꽃게", parent_id="seafood.crustacean", depth=2, sort_order=2),
    _cat("seafood.crustacean.snow_crab", "대게", parent_id="seafood.crustacean", depth=2, sort_order=3),
    _cat("seafood.crustacean.lobster", "랍스터", parent_id="seafood.crustacean", depth=2, sort_order=4),
    _cat("seafood.crustacean.king_crab", "킹크랩", parent_id="seafood.crustacean", depth=2, sort_order=5),

    # 조개류/연체류
    _cat("seafood.shellfish", "조개류", parent_id="seafood", depth=1, sort_order=3),
    _cat("seafood.shellfish.clam", "바지락", parent_id="seafood.shellfish", depth=2, sort_order=1),
    _cat("seafood.shellfish.abalone", "전복", parent_id="seafood.shellfish", depth=2, sort_order=2),
    _cat("seafood.shellfish.oyster", "굴", parent_id="seafood.shellfish", depth=2, sort_order=3),
    _cat("seafood.shellfish.mussel", "홍합", parent_id="seafood.shellfish", depth=2, sort_order=4),
    _cat("seafood.shellfish.scallop", "가리비", parent_id="seafood.shellfish", depth=2, sort_order=5),
    _cat("seafood.shellfish.conch", "소라", parent_id="seafood.shellfish", depth=2, sort_order=6),
    _cat("seafood.shellfish.squid", "오징어", parent_id="seafood.shellfish", depth=2, sort_order=7),
    _cat("seafood.shellfish.octopus", "낙지", parent_id="seafood.shellfish", depth=2, sort_order=8),
    _cat("seafood.shellfish.big_octopus", "문어", parent_id="seafood.shellfish", depth=2, sort_order=9),

    # 해조류
    _cat("seafood.seaweed", "해조류", parent_id="seafood", depth=1, sort_order=4),
    _cat("seafood.seaweed.laver", "김", parent_id="seafood.seaweed", depth=2, sort_order=1),
    _cat("seafood.seaweed.wakame", "미역", parent_id="seafood.seaweed", depth=2, sort_order=2),
    _cat("seafood.seaweed.kelp", "다시마", parent_id="seafood.seaweed", depth=2, sort_order=3),

    # 건어물
    _cat("seafood.dried", "건어물", parent_id="seafood", depth=1, sort_order=5),
    _cat("seafood.dried.anchovy", "멸치", parent_id="seafood.dried", depth=2, sort_order=1),
    _cat("seafood.dried.dried_shrimp", "건새우", parent_id="seafood.dried", depth=2, sort_order=2),
    _cat("seafood.dried.dried_squid", "오징어채", parent_id="seafood.dried", depth=2, sort_order=3),
    _cat("seafood.dried.dried_pollack", "북어", parent_id="seafood.dried", depth=2, sort_order=4),

    # 젓갈
    _cat("seafood.fermented", "젓갈", parent_id="seafood", depth=1, sort_order=6),
    _cat("seafood.fermented.shrimp_paste", "새우젓", parent_id="seafood.fermented", depth=2, sort_order=1),
    _cat("seafood.fermented.anchovy_paste", "멸치젓", parent_id="seafood.fermented", depth=2, sort_order=2),
    _cat("seafood.fermented.squid_paste", "오징어젓", parent_id="seafood.fermented", depth=2, sort_order=3),

    # ═══════════════════════════════════════════
    # 가공식품
    # ═══════════════════════════════════════════
    _cat("processed", "가공식품", icon="🥫", sort_order=4),

    # 면류
    _cat("processed.noodle", "면류", parent_id="processed", depth=1, sort_order=1),
    _cat("processed.noodle.ramen", "라면", parent_id="processed.noodle", depth=2, sort_order=1),
    _cat("processed.noodle.noodle", "국수", parent_id="processed.noodle", depth=2, sort_order=2),
    _cat("processed.noodle.pasta", "파스타", parent_id="processed.noodle", depth=2, sort_order=3),
    _cat("processed.noodle.udon", "우동", parent_id="processed.noodle", depth=2, sort_order=4),
    _cat("processed.noodle.glass_noodle", "당면", parent_id="processed.noodle", depth=2, sort_order=5),
    _cat("processed.noodle.cold_noodle", "냉면", parent_id="processed.noodle", depth=2, sort_order=6),
    _cat("processed.noodle.soba", "소바", parent_id="processed.noodle", depth=2, sort_order=7),

    # 통조림
    _cat("processed.canned", "통조림", parent_id="processed", depth=1, sort_order=2),
    _cat("processed.canned.tuna", "참치캔", parent_id="processed.canned", depth=2, sort_order=1),
    _cat("processed.canned.ham", "햄", parent_id="processed.canned", depth=2, sort_order=2),
    _cat("processed.canned.saury", "꽁치캔", parent_id="processed.canned", depth=2, sort_order=3),
    _cat("processed.canned.whelk", "골뱅이캔", parent_id="processed.canned", depth=2, sort_order=4),
    _cat("processed.canned.corn", "옥수수캔", parent_id="processed.canned", depth=2, sort_order=5),
    _cat("processed.canned.spam", "스팸", parent_id="processed.canned", depth=2, sort_order=6),

    # 냉동식품
    _cat("processed.frozen", "냉동식품", parent_id="processed", depth=1, sort_order=3),
    _cat("processed.frozen.dumpling", "만두", parent_id="processed.frozen", depth=2, sort_order=1),
    _cat("processed.frozen.pizza", "냉동피자", parent_id="processed.frozen", depth=2, sort_order=2),
    _cat("processed.frozen.rice", "냉동밥", parent_id="processed.frozen", depth=2, sort_order=3),
    _cat("processed.frozen.chicken", "냉동치킨", parent_id="processed.frozen", depth=2, sort_order=4),
    _cat("processed.frozen.ice_cream", "아이스크림", parent_id="processed.frozen", depth=2, sort_order=5),
    _cat("processed.frozen.frozen_fish", "냉동생선", parent_id="processed.frozen", depth=2, sort_order=6),

    # 소스/양념
    _cat("processed.sauce", "소스/양념", parent_id="processed", depth=1, sort_order=4),
    _cat("processed.sauce.soy_sauce", "간장", parent_id="processed.sauce", depth=2, sort_order=1),
    _cat("processed.sauce.doenjang", "된장", parent_id="processed.sauce", depth=2, sort_order=2),
    _cat("processed.sauce.gochujang", "고추장", parent_id="processed.sauce", depth=2, sort_order=3),
    _cat("processed.sauce.vinegar", "식초", parent_id="processed.sauce", depth=2, sort_order=4),
    _cat("processed.sauce.ketchup", "케첩", parent_id="processed.sauce", depth=2, sort_order=5),
    _cat("processed.sauce.mayo", "마요네즈", parent_id="processed.sauce", depth=2, sort_order=6),
    _cat("processed.sauce.oyster_sauce", "굴소스", parent_id="processed.sauce", depth=2, sort_order=7),
    _cat("processed.sauce.sugar", "설탕", parent_id="processed.sauce", depth=2, sort_order=8),
    _cat("processed.sauce.salt", "소금", parent_id="processed.sauce", depth=2, sort_order=9),
    _cat("processed.sauce.pepper", "후추", parent_id="processed.sauce", depth=2, sort_order=10),

    # 식용유
    _cat("processed.oil", "식용유", parent_id="processed", depth=1, sort_order=5),
    _cat("processed.oil.vegetable", "식용유(일반)", parent_id="processed.oil", depth=2, sort_order=1),
    _cat("processed.oil.olive", "올리브유", parent_id="processed.oil", depth=2, sort_order=2),
    _cat("processed.oil.sesame", "참기름", parent_id="processed.oil", depth=2, sort_order=3),
    _cat("processed.oil.perilla", "들기름", parent_id="processed.oil", depth=2, sort_order=4),
    _cat("processed.oil.canola", "카놀라유", parent_id="processed.oil", depth=2, sort_order=5),

    # 밀가루/분류
    _cat("processed.flour", "밀가루/분류", parent_id="processed", depth=1, sort_order=6),
    _cat("processed.flour.wheat", "밀가루", parent_id="processed.flour", depth=2, sort_order=1),
    _cat("processed.flour.pancake", "부침가루", parent_id="processed.flour", depth=2, sort_order=2),
    _cat("processed.flour.frying", "튀김가루", parent_id="processed.flour", depth=2, sort_order=3),
    _cat("processed.flour.bread", "빵가루", parent_id="processed.flour", depth=2, sort_order=4),

    # 즉석식품
    _cat("processed.instant", "즉석식품", parent_id="processed", depth=1, sort_order=7),
    _cat("processed.instant.rice", "즉석밥", parent_id="processed.instant", depth=2, sort_order=1),
    _cat("processed.instant.soup", "즉석국", parent_id="processed.instant", depth=2, sort_order=2),
    _cat("processed.instant.curry", "즉석카레", parent_id="processed.instant", depth=2, sort_order=3),
    _cat("processed.instant.cup_rice", "컵밥", parent_id="processed.instant", depth=2, sort_order=4),
    _cat("processed.instant.meal_kit", "밀키트", parent_id="processed.instant", depth=2, sort_order=5),

    # 김치/반찬
    _cat("processed.side", "김치/반찬", parent_id="processed", depth=1, sort_order=8),
    _cat("processed.side.kimchi", "김치", parent_id="processed.side", depth=2, sort_order=1),
    _cat("processed.side.kkakdugi", "깍두기", parent_id="processed.side", depth=2, sort_order=2),
    _cat("processed.side.pickled", "장아찌", parent_id="processed.side", depth=2, sort_order=3),

    # 두부/콩
    _cat("processed.tofu", "두부/콩", parent_id="processed", depth=1, sort_order=9),
    _cat("processed.tofu.firm", "두부", parent_id="processed.tofu", depth=2, sort_order=1),
    _cat("processed.tofu.soft", "순두부", parent_id="processed.tofu", depth=2, sort_order=2),
    _cat("processed.tofu.fried", "유부", parent_id="processed.tofu", depth=2, sort_order=3),

    # 빵/베이커리
    _cat("processed.bakery", "빵/베이커리", parent_id="processed", depth=1, sort_order=10),
    _cat("processed.bakery.bread", "식빵", parent_id="processed.bakery", depth=2, sort_order=1),
    _cat("processed.bakery.roll", "모닝빵", parent_id="processed.bakery", depth=2, sort_order=2),
    _cat("processed.bakery.cake", "케이크", parent_id="processed.bakery", depth=2, sort_order=3),
    _cat("processed.bakery.croissant", "크루아상", parent_id="processed.bakery", depth=2, sort_order=4),

    # ═══════════════════════════════════════════
    # 생활용품
    # ═══════════════════════════════════════════
    _cat("household", "생활용품", icon="🧹", sort_order=5),

    _cat("household.detergent", "세제류", parent_id="household", depth=1, sort_order=1),
    _cat("household.detergent.laundry", "세탁세제", parent_id="household.detergent", depth=2, sort_order=1),
    _cat("household.detergent.softener", "섬유유연제", parent_id="household.detergent", depth=2, sort_order=2),
    _cat("household.detergent.dish", "주방세제", parent_id="household.detergent", depth=2, sort_order=3),
    _cat("household.detergent.bathroom", "욕실세제", parent_id="household.detergent", depth=2, sort_order=4),
    _cat("household.detergent.bleach", "표백제", parent_id="household.detergent", depth=2, sort_order=5),

    _cat("household.tissue", "화장지/위생", parent_id="household", depth=1, sort_order=2),
    _cat("household.tissue.toilet", "화장지", parent_id="household.tissue", depth=2, sort_order=1),
    _cat("household.tissue.kitchen", "키친타월", parent_id="household.tissue", depth=2, sort_order=2),
    _cat("household.tissue.wet", "물티슈", parent_id="household.tissue", depth=2, sort_order=3),
    _cat("household.tissue.facial", "미용티슈", parent_id="household.tissue", depth=2, sort_order=4),

    _cat("household.bag", "봉투류", parent_id="household", depth=1, sort_order=3),
    _cat("household.bag.trash", "쓰레기봉투", parent_id="household.bag", depth=2, sort_order=1),
    _cat("household.bag.zipper", "지퍼백", parent_id="household.bag", depth=2, sort_order=2),
    _cat("household.bag.vinyl", "비닐봉투", parent_id="household.bag", depth=2, sort_order=3),

    _cat("household.kitchen", "주방용품", parent_id="household", depth=1, sort_order=4),
    _cat("household.kitchen.wrap", "랩", parent_id="household.kitchen", depth=2, sort_order=1),
    _cat("household.kitchen.foil", "호일", parent_id="household.kitchen", depth=2, sort_order=2),
    _cat("household.kitchen.cup", "일회용컵", parent_id="household.kitchen", depth=2, sort_order=3),
    _cat("household.kitchen.plate", "일회용접시", parent_id="household.kitchen", depth=2, sort_order=4),

    _cat("household.bathroom", "욕실용품", parent_id="household", depth=1, sort_order=5),
    _cat("household.bathroom.toothpaste", "치약", parent_id="household.bathroom", depth=2, sort_order=1),
    _cat("household.bathroom.toothbrush", "칫솔", parent_id="household.bathroom", depth=2, sort_order=2),
    _cat("household.bathroom.body_wash", "바디워시", parent_id="household.bathroom", depth=2, sort_order=3),
    _cat("household.bathroom.shampoo", "샴푸", parent_id="household.bathroom", depth=2, sort_order=4),
    _cat("household.bathroom.conditioner", "린스", parent_id="household.bathroom", depth=2, sort_order=5),

    _cat("household.sanitary", "생리용품", parent_id="household", depth=1, sort_order=6),
    _cat("household.sanitary.pad", "생리대", parent_id="household.sanitary", depth=2, sort_order=1),
    _cat("household.sanitary.liner", "팬티라이너", parent_id="household.sanitary", depth=2, sort_order=2),

    _cat("household.air", "방충/방향", parent_id="household", depth=1, sort_order=7),
    _cat("household.air.freshener", "방향제", parent_id="household.air", depth=2, sort_order=1),
    _cat("household.air.deodorizer", "탈취제", parent_id="household.air", depth=2, sort_order=2),
    _cat("household.air.insecticide", "살충제", parent_id="household.air", depth=2, sort_order=3),

    _cat("household.battery", "건전지/전구", parent_id="household", depth=1, sort_order=8),
    _cat("household.battery.battery", "건전지", parent_id="household.battery", depth=2, sort_order=1),
    _cat("household.battery.bulb", "전구", parent_id="household.battery", depth=2, sort_order=2),
    _cat("household.battery.led", "LED전구", parent_id="household.battery", depth=2, sort_order=3),

    # ═══════════════════════════════════════════
    # 음료
    # ═══════════════════════════════════════════
    _cat("beverage", "음료", icon="🥤", sort_order=6),

    _cat("beverage.water", "생수", parent_id="beverage", depth=1, sort_order=1),
    _cat("beverage.water.still", "생수(일반)", parent_id="beverage.water", depth=2, sort_order=1),
    _cat("beverage.water.sparkling", "탄산수", parent_id="beverage.water", depth=2, sort_order=2),

    _cat("beverage.soda", "탄산음료", parent_id="beverage", depth=1, sort_order=2),
    _cat("beverage.soda.cola", "콜라", parent_id="beverage.soda", depth=2, sort_order=1),
    _cat("beverage.soda.cider", "사이다", parent_id="beverage.soda", depth=2, sort_order=2),
    _cat("beverage.soda.fanta", "환타", parent_id="beverage.soda", depth=2, sort_order=3),
    _cat("beverage.soda.ginger_ale", "진저에일", parent_id="beverage.soda", depth=2, sort_order=4),

    _cat("beverage.juice", "주스", parent_id="beverage", depth=1, sort_order=3),
    _cat("beverage.juice.orange", "오렌지주스", parent_id="beverage.juice", depth=2, sort_order=1),
    _cat("beverage.juice.grape", "포도주스", parent_id="beverage.juice", depth=2, sort_order=2),
    _cat("beverage.juice.tomato", "토마토주스", parent_id="beverage.juice", depth=2, sort_order=3),
    _cat("beverage.juice.apple", "사과주스", parent_id="beverage.juice", depth=2, sort_order=4),

    _cat("beverage.coffee", "커피", parent_id="beverage", depth=1, sort_order=4, icon="☕"),
    _cat("beverage.coffee.bean", "원두커피", parent_id="beverage.coffee", depth=2, sort_order=1),
    _cat("beverage.coffee.instant", "인스턴트커피", parent_id="beverage.coffee", depth=2, sort_order=2),
    _cat("beverage.coffee.can", "캔커피", parent_id="beverage.coffee", depth=2, sort_order=3),
    _cat("beverage.coffee.mix", "커피믹스", parent_id="beverage.coffee", depth=2, sort_order=4),
    _cat("beverage.coffee.capsule", "캡슐커피", parent_id="beverage.coffee", depth=2, sort_order=5),

    _cat("beverage.tea", "차", parent_id="beverage", depth=1, sort_order=5),
    _cat("beverage.tea.green", "녹차", parent_id="beverage.tea", depth=2, sort_order=1),
    _cat("beverage.tea.barley", "보리차", parent_id="beverage.tea", depth=2, sort_order=2),
    _cat("beverage.tea.corn", "옥수수차", parent_id="beverage.tea", depth=2, sort_order=3),
    _cat("beverage.tea.brown_rice", "현미차", parent_id="beverage.tea", depth=2, sort_order=4),

    _cat("beverage.sports", "스포츠음료", parent_id="beverage", depth=1, sort_order=6),
    _cat("beverage.energy", "에너지음료", parent_id="beverage", depth=1, sort_order=7),

    # ═══════════════════════════════════════════
    # 유제품
    # ═══════════════════════════════════════════
    _cat("dairy", "유제품", icon="🥛", sort_order=7),

    _cat("dairy.milk", "우유", parent_id="dairy", depth=1, sort_order=1),
    _cat("dairy.milk.plain", "흰우유", parent_id="dairy.milk", depth=2, sort_order=1),
    _cat("dairy.milk.chocolate", "초코우유", parent_id="dairy.milk", depth=2, sort_order=2),
    _cat("dairy.milk.strawberry", "딸기우유", parent_id="dairy.milk", depth=2, sort_order=3),
    _cat("dairy.milk.banana", "바나나우유", parent_id="dairy.milk", depth=2, sort_order=4),
    _cat("dairy.milk.low_fat", "저지방우유", parent_id="dairy.milk", depth=2, sort_order=5),

    _cat("dairy.yogurt", "요거트", parent_id="dairy", depth=1, sort_order=2),
    _cat("dairy.yogurt.cup", "떠먹는요거트", parent_id="dairy.yogurt", depth=2, sort_order=1),
    _cat("dairy.yogurt.drink", "마시는요거트", parent_id="dairy.yogurt", depth=2, sort_order=2),
    _cat("dairy.yogurt.greek", "그릭요거트", parent_id="dairy.yogurt", depth=2, sort_order=3),

    _cat("dairy.cheese", "치즈", parent_id="dairy", depth=1, sort_order=3),
    _cat("dairy.cheese.slice", "슬라이스치즈", parent_id="dairy.cheese", depth=2, sort_order=1),
    _cat("dairy.cheese.mozzarella", "모짜렐라", parent_id="dairy.cheese", depth=2, sort_order=2),
    _cat("dairy.cheese.cream", "크림치즈", parent_id="dairy.cheese", depth=2, sort_order=3),

    _cat("dairy.butter", "버터/크림", parent_id="dairy", depth=1, sort_order=4),
    _cat("dairy.butter.butter", "버터", parent_id="dairy.butter", depth=2, sort_order=1),
    _cat("dairy.butter.cream", "생크림", parent_id="dairy.butter", depth=2, sort_order=2),
    _cat("dairy.butter.whipping", "휘핑크림", parent_id="dairy.butter", depth=2, sort_order=3),

    # ═══════════════════════════════════════════
    # 주류
    # ═══════════════════════════════════════════
    _cat("alcohol", "주류", icon="🍺", sort_order=8),

    _cat("alcohol.beer", "맥주", parent_id="alcohol", depth=1, sort_order=1),
    _cat("alcohol.beer.domestic", "국산맥주", parent_id="alcohol.beer", depth=2, sort_order=1),
    _cat("alcohol.beer.imported", "수입맥주", parent_id="alcohol.beer", depth=2, sort_order=2),
    _cat("alcohol.beer.craft", "크래프트맥주", parent_id="alcohol.beer", depth=2, sort_order=3),

    _cat("alcohol.soju", "소주", parent_id="alcohol", depth=1, sort_order=2),
    _cat("alcohol.wine", "와인", parent_id="alcohol", depth=1, sort_order=3),
    _cat("alcohol.wine.red", "레드와인", parent_id="alcohol.wine", depth=2, sort_order=1),
    _cat("alcohol.wine.white", "화이트와인", parent_id="alcohol.wine", depth=2, sort_order=2),
    _cat("alcohol.wine.sparkling", "스파클링와인", parent_id="alcohol.wine", depth=2, sort_order=3),
    _cat("alcohol.whisky", "위스키", parent_id="alcohol", depth=1, sort_order=4),
    _cat("alcohol.makgeolli", "막걸리", parent_id="alcohol", depth=1, sort_order=5),

    # ═══════════════════════════════════════════
    # 건강식품
    # ═══════════════════════════════════════════
    _cat("health", "건강식품", icon="💊", sort_order=9),

    _cat("health.vitamin", "비타민", parent_id="health", depth=1, sort_order=1),
    _cat("health.vitamin.c", "비타민C", parent_id="health.vitamin", depth=2, sort_order=1),
    _cat("health.vitamin.d", "비타민D", parent_id="health.vitamin", depth=2, sort_order=2),
    _cat("health.vitamin.multi", "종합비타민", parent_id="health.vitamin", depth=2, sort_order=3),
    _cat("health.vitamin.b", "비타민B", parent_id="health.vitamin", depth=2, sort_order=4),

    _cat("health.probiotic", "유산균", parent_id="health", depth=1, sort_order=2),
    _cat("health.ginseng", "홍삼", parent_id="health", depth=1, sort_order=3),
    _cat("health.omega", "오메가3", parent_id="health", depth=1, sort_order=4),
    _cat("health.protein", "단백질", parent_id="health", depth=1, sort_order=5),
    _cat("health.collagen", "콜라겐", parent_id="health", depth=1, sort_order=6),
    _cat("health.diet", "다이어트", parent_id="health", depth=1, sort_order=7),

    # ═══════════════════════════════════════════
    # 간식
    # ═══════════════════════════════════════════
    _cat("snack", "간식", icon="🍪", sort_order=10),

    _cat("snack.chip", "과자", parent_id="snack", depth=1, sort_order=1),
    _cat("snack.chip.potato", "감자칩", parent_id="snack.chip", depth=2, sort_order=1),
    _cat("snack.chip.shrimp", "새우깡", parent_id="snack.chip", depth=2, sort_order=2),
    _cat("snack.chip.choco_pie", "초코파이", parent_id="snack.chip", depth=2, sort_order=3),
    _cat("snack.chip.pepero", "빼빼로", parent_id="snack.chip", depth=2, sort_order=4),
    _cat("snack.chip.rice_cracker", "쌀과자", parent_id="snack.chip", depth=2, sort_order=5),

    _cat("snack.chocolate", "초콜릿", parent_id="snack", depth=1, sort_order=2),
    _cat("snack.candy", "사탕/젤리", parent_id="snack", depth=1, sort_order=3),
    _cat("snack.candy.candy", "사탕", parent_id="snack.candy", depth=2, sort_order=1),
    _cat("snack.candy.jelly", "젤리", parent_id="snack.candy", depth=2, sort_order=2),
    _cat("snack.candy.gum", "껌", parent_id="snack.candy", depth=2, sort_order=3),

    _cat("snack.nut", "견과류", parent_id="snack", depth=1, sort_order=4),
    _cat("snack.nut.almond", "아몬드", parent_id="snack.nut", depth=2, sort_order=1),
    _cat("snack.nut.walnut", "호두", parent_id="snack.nut", depth=2, sort_order=2),
    _cat("snack.nut.cashew", "캐슈넛", parent_id="snack.nut", depth=2, sort_order=3),
    _cat("snack.nut.peanut", "땅콩", parent_id="snack.nut", depth=2, sort_order=4),
    _cat("snack.nut.mix", "믹스넛", parent_id="snack.nut", depth=2, sort_order=5),

    # ═══════════════════════════════════════════
    # 주유소
    # ═══════════════════════════════════════════
    _cat("gas", "주유소", icon="⛽", sort_order=11),
    _cat("gas.gasoline", "휘발유", parent_id="gas", depth=1, sort_order=1),
    _cat("gas.diesel", "경유", parent_id="gas", depth=1, sort_order=2),
    _cat("gas.lpg", "LPG", parent_id="gas", depth=1, sort_order=3),

    # ═══════════════════════════════════════════
    # 식당
    # ═══════════════════════════════════════════
    _cat("restaurant", "식당", icon="🍽️", sort_order=12),
    _cat("restaurant.korean", "한식", parent_id="restaurant", depth=1, sort_order=1),
    _cat("restaurant.chinese", "중식", parent_id="restaurant", depth=1, sort_order=2),
    _cat("restaurant.japanese", "일식", parent_id="restaurant", depth=1, sort_order=3),
    _cat("restaurant.western", "양식", parent_id="restaurant", depth=1, sort_order=4),
    _cat("restaurant.snack_bar", "분식", parent_id="restaurant", depth=1, sort_order=5),
    _cat("restaurant.fastfood", "패스트푸드", parent_id="restaurant", depth=1, sort_order=6),
    _cat("restaurant.cafe", "카페", parent_id="restaurant", depth=1, sort_order=7, icon="☕"),
    _cat("restaurant.buffet", "뷔페", parent_id="restaurant", depth=1, sort_order=8),
    _cat("restaurant.bbq", "고깃집", parent_id="restaurant", depth=1, sort_order=9),
    _cat("restaurant.sushi", "횟집", parent_id="restaurant", depth=1, sort_order=10),
    _cat("restaurant.pub", "술집/호프", parent_id="restaurant", depth=1, sort_order=11),

    # ═══════════════════════════════════════════
    # 배달
    # ═══════════════════════════════════════════
    _cat("delivery", "배달", icon="🛵", sort_order=13),
    _cat("delivery.chicken", "치킨", parent_id="delivery", depth=1, sort_order=1),
    _cat("delivery.pizza", "피자", parent_id="delivery", depth=1, sort_order=2),
    _cat("delivery.chinese_food", "중국집", parent_id="delivery", depth=1, sort_order=3),
    _cat("delivery.jokbal", "족발/보쌈", parent_id="delivery", depth=1, sort_order=4),
    _cat("delivery.night_snack", "야식", parent_id="delivery", depth=1, sort_order=5),
    _cat("delivery.lunchbox", "도시락", parent_id="delivery", depth=1, sort_order=6),
    _cat("delivery.dessert", "디저트", parent_id="delivery", depth=1, sort_order=7),
    _cat("delivery.korean_food", "한식배달", parent_id="delivery", depth=1, sort_order=8),
    _cat("delivery.burger", "버거", parent_id="delivery", depth=1, sort_order=9),

    # ═══════════════════════════════════════════
    # 의류
    # ═══════════════════════════════════════════
    _cat("clothing", "의류", icon="👕", sort_order=14),

    _cat("clothing.men", "남성의류", parent_id="clothing", depth=1, sort_order=1),
    _cat("clothing.men.shirt", "셔츠", parent_id="clothing.men", depth=2, sort_order=1),
    _cat("clothing.men.pants", "바지", parent_id="clothing.men", depth=2, sort_order=2),
    _cat("clothing.men.jacket", "자켓", parent_id="clothing.men", depth=2, sort_order=3),
    _cat("clothing.men.coat", "코트", parent_id="clothing.men", depth=2, sort_order=4),
    _cat("clothing.men.tshirt", "티셔츠", parent_id="clothing.men", depth=2, sort_order=5),

    _cat("clothing.women", "여성의류", parent_id="clothing", depth=1, sort_order=2),
    _cat("clothing.women.dress", "원피스", parent_id="clothing.women", depth=2, sort_order=1),
    _cat("clothing.women.blouse", "블라우스", parent_id="clothing.women", depth=2, sort_order=2),
    _cat("clothing.women.skirt", "스커트", parent_id="clothing.women", depth=2, sort_order=3),
    _cat("clothing.women.coat", "여성코트", parent_id="clothing.women", depth=2, sort_order=4),

    _cat("clothing.kids", "아동의류", parent_id="clothing", depth=1, sort_order=3),
    _cat("clothing.kids.top", "아동상의", parent_id="clothing.kids", depth=2, sort_order=1),
    _cat("clothing.kids.bottom", "아동하의", parent_id="clothing.kids", depth=2, sort_order=2),
    _cat("clothing.kids.outer", "아동외투", parent_id="clothing.kids", depth=2, sort_order=3),

    _cat("clothing.sports", "스포츠웨어", parent_id="clothing", depth=1, sort_order=4),
    _cat("clothing.sports.athletic", "운동복", parent_id="clothing.sports", depth=2, sort_order=1),
    _cat("clothing.sports.training", "트레이닝복", parent_id="clothing.sports", depth=2, sort_order=2),
    _cat("clothing.sports.yoga", "요가복", parent_id="clothing.sports", depth=2, sort_order=3),

    _cat("clothing.underwear", "속옷", parent_id="clothing", depth=1, sort_order=5),
    _cat("clothing.underwear.men", "남성속옷", parent_id="clothing.underwear", depth=2, sort_order=1),
    _cat("clothing.underwear.women", "여성속옷", parent_id="clothing.underwear", depth=2, sort_order=2),
    _cat("clothing.underwear.socks", "양말", parent_id="clothing.underwear", depth=2, sort_order=3),

    _cat("clothing.shoes", "신발", parent_id="clothing", depth=1, sort_order=6),
    _cat("clothing.shoes.sneakers", "운동화", parent_id="clothing.shoes", depth=2, sort_order=1),
    _cat("clothing.shoes.dress_shoes", "구두", parent_id="clothing.shoes", depth=2, sort_order=2),
    _cat("clothing.shoes.boots", "부츠", parent_id="clothing.shoes", depth=2, sort_order=3),
    _cat("clothing.shoes.slippers", "슬리퍼", parent_id="clothing.shoes", depth=2, sort_order=4),
    _cat("clothing.shoes.sandals", "샌들", parent_id="clothing.shoes", depth=2, sort_order=5),

    _cat("clothing.bag", "가방", parent_id="clothing", depth=1, sort_order=7),
    _cat("clothing.bag.backpack", "백팩", parent_id="clothing.bag", depth=2, sort_order=1),
    _cat("clothing.bag.crossbody", "크로스백", parent_id="clothing.bag", depth=2, sort_order=2),
    _cat("clothing.bag.tote", "토트백", parent_id="clothing.bag", depth=2, sort_order=3),
    _cat("clothing.bag.wallet", "지갑", parent_id="clothing.bag", depth=2, sort_order=4),

    _cat("clothing.accessory", "모자/액세서리", parent_id="clothing", depth=1, sort_order=8),
    _cat("clothing.accessory.hat", "모자", parent_id="clothing.accessory", depth=2, sort_order=1),
    _cat("clothing.accessory.belt", "벨트", parent_id="clothing.accessory", depth=2, sort_order=2),
    _cat("clothing.accessory.scarf", "스카프", parent_id="clothing.accessory", depth=2, sort_order=3),
    _cat("clothing.accessory.gloves", "장갑", parent_id="clothing.accessory", depth=2, sort_order=4),

    # ═══════════════════════════════════════════
    # 가전
    # ═══════════════════════════════════════════
    _cat("appliance", "가전", icon="🏠", sort_order=15),

    _cat("appliance.kitchen", "주방가전", parent_id="appliance", depth=1, sort_order=1),
    _cat("appliance.kitchen.fridge", "냉장고", parent_id="appliance.kitchen", depth=2, sort_order=1),
    _cat("appliance.kitchen.microwave", "전자레인지", parent_id="appliance.kitchen", depth=2, sort_order=2),
    _cat("appliance.kitchen.airfryer", "에어프라이어", parent_id="appliance.kitchen", depth=2, sort_order=3),
    _cat("appliance.kitchen.rice_cooker", "밥솥", parent_id="appliance.kitchen", depth=2, sort_order=4),
    _cat("appliance.kitchen.dishwasher", "식기세척기", parent_id="appliance.kitchen", depth=2, sort_order=5),
    _cat("appliance.kitchen.oven", "오븐", parent_id="appliance.kitchen", depth=2, sort_order=6),

    _cat("appliance.living", "생활가전", parent_id="appliance", depth=1, sort_order=2),
    _cat("appliance.living.washer", "세탁기", parent_id="appliance.living", depth=2, sort_order=1),
    _cat("appliance.living.dryer", "건조기", parent_id="appliance.living", depth=2, sort_order=2),
    _cat("appliance.living.vacuum", "청소기", parent_id="appliance.living", depth=2, sort_order=3),
    _cat("appliance.living.ac", "에어컨", parent_id="appliance.living", depth=2, sort_order=4),
    _cat("appliance.living.fan", "선풍기", parent_id="appliance.living", depth=2, sort_order=5),
    _cat("appliance.living.air_purifier", "공기청정기", parent_id="appliance.living", depth=2, sort_order=6),
    _cat("appliance.living.humidifier", "가습기", parent_id="appliance.living", depth=2, sort_order=7),
    _cat("appliance.living.dehumidifier", "제습기", parent_id="appliance.living", depth=2, sort_order=8),

    _cat("appliance.video", "영상가전", parent_id="appliance", depth=1, sort_order=3),
    _cat("appliance.video.tv", "TV", parent_id="appliance.video", depth=2, sort_order=1),
    _cat("appliance.video.monitor", "모니터", parent_id="appliance.video", depth=2, sort_order=2),
    _cat("appliance.video.projector", "프로젝터", parent_id="appliance.video", depth=2, sort_order=3),

    # ═══════════════════════════════════════════
    # 디지털
    # ═══════════════════════════════════════════
    _cat("digital", "디지털", icon="💻", sort_order=16),

    _cat("digital.mobile", "모바일", parent_id="digital", depth=1, sort_order=1),
    _cat("digital.mobile.smartphone", "스마트폰", parent_id="digital.mobile", depth=2, sort_order=1),
    _cat("digital.mobile.tablet", "태블릿", parent_id="digital.mobile", depth=2, sort_order=2),
    _cat("digital.mobile.smartwatch", "스마트워치", parent_id="digital.mobile", depth=2, sort_order=3),

    _cat("digital.computer", "컴퓨터", parent_id="digital", depth=1, sort_order=2),
    _cat("digital.computer.laptop", "노트북", parent_id="digital.computer", depth=2, sort_order=1),
    _cat("digital.computer.desktop", "데스크탑", parent_id="digital.computer", depth=2, sort_order=2),
    _cat("digital.computer.keyboard", "키보드", parent_id="digital.computer", depth=2, sort_order=3),
    _cat("digital.computer.mouse", "마우스", parent_id="digital.computer", depth=2, sort_order=4),
    _cat("digital.computer.ssd", "SSD", parent_id="digital.computer", depth=2, sort_order=5),
    _cat("digital.computer.ram", "RAM", parent_id="digital.computer", depth=2, sort_order=6),

    _cat("digital.audio", "음향", parent_id="digital", depth=1, sort_order=3),
    _cat("digital.audio.earphone", "이어폰", parent_id="digital.audio", depth=2, sort_order=1),
    _cat("digital.audio.headphone", "헤드폰", parent_id="digital.audio", depth=2, sort_order=2),
    _cat("digital.audio.speaker", "블루투스스피커", parent_id="digital.audio", depth=2, sort_order=3),

    _cat("digital.camera", "카메라", parent_id="digital", depth=1, sort_order=4),
    _cat("digital.camera.dslr", "DSLR", parent_id="digital.camera", depth=2, sort_order=1),
    _cat("digital.camera.mirrorless", "미러리스", parent_id="digital.camera", depth=2, sort_order=2),
    _cat("digital.camera.action", "액션캠", parent_id="digital.camera", depth=2, sort_order=3),

    _cat("digital.gaming", "게이밍", parent_id="digital", depth=1, sort_order=5),
    _cat("digital.gaming.console", "게임기", parent_id="digital.gaming", depth=2, sort_order=1),
    _cat("digital.gaming.game", "게임타이틀", parent_id="digital.gaming", depth=2, sort_order=2),

    # ═══════════════════════════════════════════
    # 가구
    # ═══════════════════════════════════════════
    _cat("furniture", "가구", icon="🛋️", sort_order=17),

    _cat("furniture.living", "거실", parent_id="furniture", depth=1, sort_order=1),
    _cat("furniture.living.sofa", "소파", parent_id="furniture.living", depth=2, sort_order=1),
    _cat("furniture.living.tv_stand", "TV장", parent_id="furniture.living", depth=2, sort_order=2),
    _cat("furniture.living.table", "거실테이블", parent_id="furniture.living", depth=2, sort_order=3),

    _cat("furniture.bedroom", "침실", parent_id="furniture", depth=1, sort_order=2),
    _cat("furniture.bedroom.bed", "침대", parent_id="furniture.bedroom", depth=2, sort_order=1),
    _cat("furniture.bedroom.mattress", "매트리스", parent_id="furniture.bedroom", depth=2, sort_order=2),
    _cat("furniture.bedroom.wardrobe", "옷장", parent_id="furniture.bedroom", depth=2, sort_order=3),
    _cat("furniture.bedroom.drawer", "서랍장", parent_id="furniture.bedroom", depth=2, sort_order=4),

    _cat("furniture.kitchen_furn", "주방가구", parent_id="furniture", depth=1, sort_order=3),
    _cat("furniture.kitchen_furn.dining_table", "식탁", parent_id="furniture.kitchen_furn", depth=2, sort_order=1),
    _cat("furniture.kitchen_furn.dining_chair", "식탁의자", parent_id="furniture.kitchen_furn", depth=2, sort_order=2),
    _cat("furniture.kitchen_furn.cabinet", "수납장", parent_id="furniture.kitchen_furn", depth=2, sort_order=3),

    _cat("furniture.study", "서재", parent_id="furniture", depth=1, sort_order=4),
    _cat("furniture.study.desk", "책상", parent_id="furniture.study", depth=2, sort_order=1),
    _cat("furniture.study.chair", "의자", parent_id="furniture.study", depth=2, sort_order=2),
    _cat("furniture.study.bookshelf", "책장", parent_id="furniture.study", depth=2, sort_order=3),

    # ═══════════════════════════════════════════
    # 화장품
    # ═══════════════════════════════════════════
    _cat("cosmetics", "화장품", icon="💄", sort_order=18),

    _cat("cosmetics.skincare", "스킨케어", parent_id="cosmetics", depth=1, sort_order=1),
    _cat("cosmetics.skincare.toner", "화장수/토너", parent_id="cosmetics.skincare", depth=2, sort_order=1),
    _cat("cosmetics.skincare.lotion", "로션", parent_id="cosmetics.skincare", depth=2, sort_order=2),
    _cat("cosmetics.skincare.essence", "에센스", parent_id="cosmetics.skincare", depth=2, sort_order=3),
    _cat("cosmetics.skincare.cream", "크림", parent_id="cosmetics.skincare", depth=2, sort_order=4),
    _cat("cosmetics.skincare.sunscreen", "선크림", parent_id="cosmetics.skincare", depth=2, sort_order=5),
    _cat("cosmetics.skincare.mask", "마스크팩", parent_id="cosmetics.skincare", depth=2, sort_order=6),

    _cat("cosmetics.makeup", "메이크업", parent_id="cosmetics", depth=1, sort_order=2),
    _cat("cosmetics.makeup.foundation", "파운데이션", parent_id="cosmetics.makeup", depth=2, sort_order=1),
    _cat("cosmetics.makeup.lipstick", "립스틱", parent_id="cosmetics.makeup", depth=2, sort_order=2),
    _cat("cosmetics.makeup.eyeshadow", "아이섀도", parent_id="cosmetics.makeup", depth=2, sort_order=3),
    _cat("cosmetics.makeup.mascara", "마스카라", parent_id="cosmetics.makeup", depth=2, sort_order=4),

    _cat("cosmetics.cleansing", "클렌징", parent_id="cosmetics", depth=1, sort_order=3),
    _cat("cosmetics.cleansing.foam", "클렌징폼", parent_id="cosmetics.cleansing", depth=2, sort_order=1),
    _cat("cosmetics.cleansing.oil", "클렌징오일", parent_id="cosmetics.cleansing", depth=2, sort_order=2),
    _cat("cosmetics.cleansing.water", "클렌징워터", parent_id="cosmetics.cleansing", depth=2, sort_order=3),

    _cat("cosmetics.men_cosmetic", "남성화장품", parent_id="cosmetics", depth=1, sort_order=4),
    _cat("cosmetics.men_cosmetic.razor", "면도기", parent_id="cosmetics.men_cosmetic", depth=2, sort_order=1),
    _cat("cosmetics.men_cosmetic.aftershave", "애프터셰이브", parent_id="cosmetics.men_cosmetic", depth=2, sort_order=2),
    _cat("cosmetics.men_cosmetic.lotion", "남성로션", parent_id="cosmetics.men_cosmetic", depth=2, sort_order=3),

    # ═══════════════════════════════════════════
    # 여행
    # ═══════════════════════════════════════════
    _cat("travel", "여행", icon="✈️", sort_order=19),

    _cat("travel.domestic", "국내여행", parent_id="travel", depth=1, sort_order=1),
    _cat("travel.domestic.hotel", "호텔", parent_id="travel.domestic", depth=2, sort_order=1),
    _cat("travel.domestic.pension", "펜션", parent_id="travel.domestic", depth=2, sort_order=2),
    _cat("travel.domestic.resort", "리조트", parent_id="travel.domestic", depth=2, sort_order=3),
    _cat("travel.domestic.ktx", "KTX", parent_id="travel.domestic", depth=2, sort_order=4),
    _cat("travel.domestic.bus", "고속버스", parent_id="travel.domestic", depth=2, sort_order=5),
    _cat("travel.domestic.rental_car", "렌터카", parent_id="travel.domestic", depth=2, sort_order=6),

    _cat("travel.international", "해외여행", parent_id="travel", depth=1, sort_order=2),
    _cat("travel.international.flight", "항공권", parent_id="travel.international", depth=2, sort_order=1),
    _cat("travel.international.hotel", "해외호텔", parent_id="travel.international", depth=2, sort_order=2),
    _cat("travel.international.insurance", "여행보험", parent_id="travel.international", depth=2, sort_order=3),
    _cat("travel.international.package", "패키지여행", parent_id="travel.international", depth=2, sort_order=4),

    # ═══════════════════════════════════════════
    # 문화
    # ═══════════════════════════════════════════
    _cat("culture", "문화", icon="🎬", sort_order=20),

    _cat("culture.movie", "영화", parent_id="culture", depth=1, sort_order=1),
    _cat("culture.movie.cinema", "영화관", parent_id="culture.movie", depth=2, sort_order=1),
    _cat("culture.movie.ott", "OTT", parent_id="culture.movie", depth=2, sort_order=2),

    _cat("culture.performance", "공연", parent_id="culture", depth=1, sort_order=2),
    _cat("culture.performance.concert", "콘서트", parent_id="culture.performance", depth=2, sort_order=1),
    _cat("culture.performance.musical", "뮤지컬", parent_id="culture.performance", depth=2, sort_order=2),
    _cat("culture.performance.theater", "연극", parent_id="culture.performance", depth=2, sort_order=3),

    _cat("culture.book", "도서", parent_id="culture", depth=1, sort_order=3),
    _cat("culture.book.novel", "소설", parent_id="culture.book", depth=2, sort_order=1),
    _cat("culture.book.comic", "만화", parent_id="culture.book", depth=2, sort_order=2),
    _cat("culture.book.reference", "참고서", parent_id="culture.book", depth=2, sort_order=3),

    # ═══════════════════════════════════════════
    # 교육
    # ═══════════════════════════════════════════
    _cat("education", "교육", icon="📚", sort_order=21),

    _cat("education.online", "온라인교육", parent_id="education", depth=1, sort_order=1),
    _cat("education.online.lecture", "인강", parent_id="education.online", depth=2, sort_order=1),
    _cat("education.online.certification", "자격증", parent_id="education.online", depth=2, sort_order=2),
    _cat("education.online.language", "어학", parent_id="education.online", depth=2, sort_order=3),

    _cat("education.academy", "학원", parent_id="education", depth=1, sort_order=2),
    _cat("education.academy.english", "영어학원", parent_id="education.academy", depth=2, sort_order=1),
    _cat("education.academy.math", "수학학원", parent_id="education.academy", depth=2, sort_order=2),
    _cat("education.academy.coding", "코딩학원", parent_id="education.academy", depth=2, sort_order=3),

    _cat("education.material", "학습교재", parent_id="education", depth=1, sort_order=3),
    _cat("education.material.workbook", "문제집", parent_id="education.material", depth=2, sort_order=1),
    _cat("education.material.reference", "참고서(교육)", parent_id="education.material", depth=2, sort_order=2),

    # ═══════════════════════════════════════════
    # 반려동물
    # ═══════════════════════════════════════════
    _cat("pet", "반려동물", icon="🐾", sort_order=22),

    _cat("pet.dog", "강아지", parent_id="pet", depth=1, sort_order=1),
    _cat("pet.dog.food", "강아지사료", parent_id="pet.dog", depth=2, sort_order=1),
    _cat("pet.dog.snack", "강아지간식", parent_id="pet.dog", depth=2, sort_order=2),
    _cat("pet.dog.supply", "강아지용품", parent_id="pet.dog", depth=2, sort_order=3),
    _cat("pet.dog.toy", "강아지장난감", parent_id="pet.dog", depth=2, sort_order=4),

    _cat("pet.cat", "고양이", parent_id="pet", depth=1, sort_order=2),
    _cat("pet.cat.food", "고양이사료", parent_id="pet.cat", depth=2, sort_order=1),
    _cat("pet.cat.snack", "고양이간식", parent_id="pet.cat", depth=2, sort_order=2),
    _cat("pet.cat.supply", "고양이용품", parent_id="pet.cat", depth=2, sort_order=3),
    _cat("pet.cat.litter", "고양이모래", parent_id="pet.cat", depth=2, sort_order=4),

    # ═══════════════════════════════════════════
    # 기타
    # ═══════════════════════════════════════════
    _cat("etc", "기타", icon="📦", sort_order=23),
    _cat("etc.gift_set", "선물세트", parent_id="etc", depth=1, sort_order=1),
    _cat("etc.gift_card", "기프트카드", parent_id="etc", depth=1, sort_order=2),
    _cat("etc.voucher", "상품권", parent_id="etc", depth=1, sort_order=3),
    _cat("etc.office", "사무용품", parent_id="etc", depth=1, sort_order=4),
    _cat("etc.stationery", "문구류", parent_id="etc", depth=1, sort_order=5),
]


# ──────────────────────────────────────────────
# 유틸리티 — 모듈 레벨 인덱스 (O(1) 조회)
# ──────────────────────────────────────────────

# 한 번만 빌드하여 모든 조회를 O(1)로 만든다
_CATEGORY_INDEX: dict[str, dict] = {c["id"]: c for c in CATEGORIES}

# parent_id → [children] 사전 매핑 (get_children/get_descendants O(1) 조회)
_CHILDREN_INDEX: dict[str | None, list[dict]] = {}
for _c in CATEGORIES:
    _CHILDREN_INDEX.setdefault(_c["parent_id"], []).append(_c)


def find_category(category_id: str) -> Optional[dict]:
    """ID 로 카테고리 검색. 없으면 None."""
    return _CATEGORY_INDEX.get(category_id)


def get_children(category_id: str) -> list[dict]:
    """직접 자식 카테고리 목록. 사전 인덱스로 O(1) 조회."""
    return list(_CHILDREN_INDEX.get(category_id, []))


def get_descendants(category_id: str) -> list[dict]:
    """모든 하위 카테고리 (반복 방식 — 재귀 스택 제거)."""
    result: list[dict] = []
    stack = list(_CHILDREN_INDEX.get(category_id, []))
    while stack:
        child = stack.pop()
        result.append(child)
        stack.extend(_CHILDREN_INDEX.get(child["id"], []))
    return result


def get_ancestors(category_id: str) -> list[dict]:
    """루트까지 상위 카테고리 목록 (가까운 순)."""
    ancestors = []
    current = _CATEGORY_INDEX.get(category_id)
    while current and current["parent_id"]:
        parent = _CATEGORY_INDEX.get(current["parent_id"])
        if parent:
            ancestors.append(parent)
        current = parent
    return ancestors


def get_root_categories() -> list[dict]:
    """최상위 카테고리 목록. 사전 인덱스로 O(1) 조회."""
    return list(_CHILDREN_INDEX.get(None, []))


def get_all_ids() -> list[str]:
    """모든 카테고리 ID 목록."""
    return list(_CATEGORY_INDEX.keys())


def get_category_tree() -> list[dict]:
    """
    전체 카테고리를 트리 구조로 반환.

    각 노드: {id, name, ..., children: [...]}
    """
    idx = {c["id"]: {**c, "children": []} for c in CATEGORIES}

    roots = []
    for cat in CATEGORIES:
        node = idx[cat["id"]]
        if cat["parent_id"] is None:
            roots.append(node)
        else:
            parent = idx.get(cat["parent_id"])
            if parent:
                parent["children"].append(node)

    return roots


def flatten_tree(tree: list[dict]) -> list[dict]:
    """트리 구조를 flat 리스트로 변환."""
    result = []
    for node in tree:
        children = node.pop("children", [])
        result.append(node)
        if children:
            result.extend(flatten_tree(children))
    return result


def validate_tree() -> list[str]:
    """
    카테고리 트리 무결성 검증.

    반환: 오류 메시지 리스트 (빈 리스트 = OK).
    """
    errors = []
    idx = _build_index()
    seen_ids: set[str] = set()

    for cat in CATEGORIES:
        # 중복 ID 체크
        if cat["id"] in seen_ids:
            errors.append(f"중복 ID: {cat['id']}")
        seen_ids.add(cat["id"])

        # parent_id 유효성
        if cat["parent_id"] and cat["parent_id"] not in idx:
            errors.append(f"존재하지 않는 parent_id: {cat['parent_id']} (카테고리: {cat['id']})")

        # depth 일관성
        if cat["parent_id"]:
            parent = idx.get(cat["parent_id"])
            if parent and cat["depth"] != parent["depth"] + 1:
                errors.append(
                    f"depth 불일치: {cat['id']} depth={cat['depth']}, "
                    f"parent depth={parent['depth']}"
                )

    return errors
