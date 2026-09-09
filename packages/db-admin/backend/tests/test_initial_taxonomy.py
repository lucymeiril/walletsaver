"""Initial real-catalog evidence contracts, independent of live sites or DBs."""
from __future__ import annotations

import pytest

from services.initial_taxonomy import (
    LEAVES,
    classify_record,
    contains_term,
    keyword_collisions,
    keyword_definitions,
    native_category_key,
    normalize_source_path,
    source_evidence,
    taxonomy_categories,
    validate_keyword_definitions,
    validate_taxonomy,
)


def _raw(mart, path, name="검수할 상품", **extra):
    return {"mart": mart, "name": name, "attributes": {"mart_native_category_path": path}, **extra}


def test_homeplus_full_path_maps_to_a_four_level_flavoured_milk_leaf():
    result = classify_record(_raw("homeplus", "식품 > 유제품 > 우유 > 초코우유"))
    assert result["unified_category_id"] == "food.dairy.milk.chocolate"
    assert result["category_path"] == ["식품", "유제품", "우유", "초코우유"]
    assert result["classification_confidence"] >= 0.95
    assert result["evidence_type"] == "source_full_path"
    assert result["review_status"] == "classified"  # Never approval/publication.


def test_homeplus_adjacent_duplicates_collapse_without_losing_full_path():
    result = classify_record(_raw("homeplus", "우유/유제품 > 요거트/요구르트 > 떠먹는 요구르트 > 떠먹는 요구르트"))
    assert result["source_path_parts"] == ["우유/유제품", "요거트/요구르트", "떠먹는 요구르트"]
    assert result["unified_category_id"] == "food.dairy.yogurt.spoon"


def test_homeplus_nested_path_beats_top_level_root_only_category():
    result = classify_record(_raw("homeplus", "우유/유제품 > 우유 > 흰우유/저지방우유 > 흰우유", category="우유/유제품", mart_native_category_id="root-only-17"))
    assert result["unified_category_id"] == "food.dairy.milk.plain"
    assert result["source_path_field"] == "attributes.mart_native_category_path"
    assert result["raw_native_category_id"] == "root-only-17"
    assert result["native_category_key"].startswith("homeplus:path:")


def test_lotte_list_path_is_retained_and_consolidated():
    record = {"source": "롯데마트", "name": "검수할 상품", "attributes": {"category_path": ["우유ㆍ유제품", "우유", "바나나ㆍ딸기ㆍ초코ㆍ커피우유", "딸기우유"]}}
    result = classify_record(record)
    assert result["mart"] == "lottemart"
    assert result["unified_category_id"] == "food.dairy.milk.strawberry"
    assert result["source_path_parts"] == record["attributes"]["category_path"]


@pytest.mark.parametrize("wrapper", ["payload", "raw_payload"])
def test_normalized_observation_wrapper_is_equivalent_to_raw_payload(wrapper):
    raw = _raw("homeplus", "우유/유제품 > 치즈/버터 > 슬라이스 치즈 > 슬라이스 치즈")
    direct = classify_record(raw)
    normalized = classify_record({"source_name": "homeplus", "source_record_key": "123", wrapper: raw})
    assert normalized == direct


def test_normalized_observation_top_level_path_fallback():
    result = classify_record({"source_name": "lottemart", "source_title": "상품", "source_category_path": ["과일", "사과ㆍ배", "사과"], "raw_payload": {"name": "상품"}})
    assert result["unified_category_id"] == "food.produce.fruit.apple"


@pytest.mark.parametrize("path", ["우유/유제품", "생수/음료/주류", "정육/계란류"])
def test_emart_slashes_are_not_hierarchy_or_specific_leaf_evidence(path):
    result = classify_record(_raw("emart", path))
    assert result["source_path_parts"] == [path]
    assert result["unified_category_id"] is None
    assert result["classification_reason"] == "broad_source_category"
    assert result["proposed_path"] == [path]


def test_broad_milk_path_needs_specific_flavour_name():
    path = "우유/유제품 > 우유 > 딸기/초코/바나나/기타 우유"
    unresolved = classify_record(_raw("homeplus", path, "브랜드 가공우유 200ml"))
    assert unresolved["unified_category_id"] is None
    assert unresolved["proposed_path"] == path.split(" > ")
    classified = classify_record(_raw("homeplus", path, "브랜드 초코우유 200ml"))
    assert classified["unified_category_id"] == "food.dairy.milk.chocolate"
    assert classified["evidence_type"] == "unambiguous_name_tokens"


@pytest.mark.parametrize("surface", ["Best", "Obanjang", "SpecialPriceOffers", "베스트", "오반장"])
def test_promotion_surface_is_not_a_category(surface):
    result = classify_record(_raw("costco", surface))
    assert result["unified_category_id"] is None
    assert result["review_status"] == "pending"
    assert result["classification_reason"] == "promotion_surface_without_leaf_evidence"


def test_costco_official_razor_taxonomy_resolves_promotion_surface():
    result = classify_record(_raw("costco", "SpecialPriceOffers", "질레트 상품", canonical_url="https://www.costco.co.kr/Health-Beauty/Shaving/Razors/Gillette-Proshield/p/123456"))
    assert result["unified_category_id"] == "beauty.personal.shaving.razor"
    assert result["evidence_type"] == "official_url_taxonomy"
    assert result["source_path"] == "SpecialPriceOffers"
    assert "razors" in result["url_taxonomy_hints"]


def test_costco_broad_shaving_url_needs_product_name_not_a_guessed_leaf():
    url = "https://www.costco.co.kr/Health-Beauty/Shaving/Gillette-Set/p/123456"
    assert classify_record(_raw("costco", "SpecialPriceOffers", canonical_url=url))["unified_category_id"] is None
    result = classify_record(_raw("costco", "SpecialPriceOffers", "질레트 면도기 세트", detail_url=url))
    assert result["unified_category_id"] == "beauty.personal.shaving.razor"


@pytest.mark.parametrize("url", [
    "https://example.test/Health-Beauty/Shaving/Razors/Product/p/123",
    "https://www.costco.co.kr.evil.test/Health-Beauty/Shaving/Razors/Product/p/123",
    "https://www.costco.co.kr/Food/Razors/p/123",  # Product slug, not category.
])
def test_url_must_be_official_and_category_prefix_not_product_slug(url):
    assert classify_record(_raw("costco", "SpecialPriceOffers", canonical_url=url))["unified_category_id"] is None


def test_costco_url_name_conflict_remains_unresolved():
    result = classify_record(_raw("costco", "과자", "브랜드 샴푸 500ml", canonical_url="https://www.costco.co.kr/Health-Beauty/Shaving/Razors/Product/p/123"))
    assert result["unified_category_id"] is None
    assert result["classification_reason"] == "conflicting_category_evidence"
    assert len(result["candidate_category_ids"]) == 2


def test_exact_source_name_conflict_remains_unresolved():
    result = classify_record(_raw("homeplus", "우유/유제품 > 우유 > 흰우유", "브랜드 초코우유 200ml"))
    assert result["unified_category_id"] is None
    assert result["classification_reason"] == "conflicting_category_evidence"


def test_homeplus_root_native_id_does_not_merge_different_paths():
    plain = source_evidence(_raw("homeplus", "우유/유제품 > 우유 > 흰우유", mart_native_category_id="same-root"))
    chocolate = source_evidence(_raw("homeplus", "우유/유제품 > 우유 > 초코우유", mart_native_category_id="same-root"))
    assert plain["raw_native_category_id"] == chocolate["raw_native_category_id"]
    assert plain["native_category_key"] != chocolate["native_category_key"]
    assert plain["native_category_key"] == native_category_key("homeplus", ["우유/유제품", " 우유 ", "흰우유"])


def test_missing_lotte_native_id_still_gets_stable_key():
    a = source_evidence(_raw("lottemart", ["과일", "사과ㆍ배", "사과"]))
    b = source_evidence(_raw("lottemart", ["과일", "사과·배", "사과"]))
    assert a["raw_native_category_id"] is None
    assert a["native_category_key"] == b["native_category_key"]
    assert native_category_key("lottemart", []) is None


@pytest.mark.parametrize(("mart", "path", "category_id"), [
    ("homeplus", "과자/시리얼 > 과자/쿠키/파이 > 비스켓/쿠키/프레첼 > 초코비스켓", "food.snacks.baked.biscuits"),
    ("lottemart", ["라면ㆍ통조림ㆍ즉석밥", "라면", "컵라면", "일반라면"], "food.meals.noodles.cup_ramen"),
    ("lottemart", ["라면ㆍ통조림ㆍ즉석밥", "라면", "봉지라면", "일반라면"], "food.meals.noodles.bag_ramen"),
    ("homeplus", "냉장/냉동/밀키트 > 만두 > 교자만두/군만두 > 고기교자만두", "food.meals.dumplings.gyoza"),
    ("lottemart", ["채소", "고구마ㆍ감자", "감자"], "food.produce.vegetables.potato"),
    ("lottemart", ["정육ㆍ계란", "국내산소고기"], "food.meat.fresh.beef"),
    ("homeplus", "수산물/건어물 > 간편/냉동수산물 > 냉동간편수산물 > 냉동새우", "food.seafood.shellfish.shrimp"),
    ("lottemart", ["양념ㆍ오일ㆍ분말류", "소스류", "파스타소스"], "food.seasonings.sauces.pasta"),
    ("homeplus", "세탁/청소 > 세탁세제/섬유유연제 > 섬유유연제 > 고농축 섬유유연제", "household.cleaning.laundry.softener"),
    ("homeplus", "기저귀 > 하기스/마미포코 > 하기스 > 하기스", "baby.hygiene.diapering.diapers"),
])
def test_semantic_paths_cover_multiple_departments(mart, path, category_id):
    title = "냉동 새우" if category_id == "food.seafood.shellfish.shrimp" else "검수할 상품"
    assert classify_record(_raw(mart, path, title))["unified_category_id"] == category_id


def test_unknown_source_root_is_not_accepted_just_because_leaf_word_matches():
    result = classify_record(_raw("homeplus", "반려동물 > 우유 > 초코우유"))
    assert result["unified_category_id"] is None


def test_internal_node_is_never_filled_with_an_invented_other_leaf():
    result = classify_record(_raw("homeplus", "식품 > 유제품 > 우유"))
    assert result["unified_category_id"] is None
    assert result["proposed_path"] == ["식품", "유제품", "우유"]
    assert not any("기타" in leaf.path[-1] for leaf in LEAVES)


def test_taxonomy_is_deterministic_four_levels_and_assignments_are_leaves():
    categories = taxonomy_categories()
    assert categories == taxonomy_categories(reversed([leaf.id for leaf in LEAVES]))
    validate_taxonomy(categories, [leaf.id for leaf in LEAVES])
    assert max(row["level"] for row in categories) == 3
    assert {row["name_ko"] for row in categories if row["parent_id"] is None} >= {"식품", "생활용품", "유아동"}
    subset = taxonomy_categories(["food.dairy.milk.chocolate"])
    assert len(subset) == 4


def test_taxonomy_validation_rejects_internal_assignment_and_bad_trees():
    categories = taxonomy_categories(["food.dairy.milk.chocolate"])
    with pytest.raises(ValueError, match="leaf"):
        validate_taxonomy(categories, ["food.dairy.milk"])
    with pytest.raises(ValueError, match="four levels"):
        validate_taxonomy([*categories, {"id": "fifth", "parent_id": "food.dairy.milk.chocolate"}])
    with pytest.raises(ValueError, match="Missing"):
        validate_taxonomy([{ "id": "orphan", "parent_id": "absent"}])
    with pytest.raises(ValueError, match="cycle"):
        validate_taxonomy([{"id": "a", "parent_id": "b"}, {"id": "b", "parent_id": "a"}])
    with pytest.raises(ValueError, match="Duplicate"):
        validate_taxonomy([categories[0], categories[0]])


def test_keyword_seed_is_fresh_leaf_only_and_collision_free():
    rows = keyword_definitions()
    assert len(rows) > 100
    validate_keyword_definitions(rows)
    assert keyword_collisions(rows) == {}
    assert all(len(row["word"]) >= 2 for row in rows)
    assert all(row["unified_category_id"] in {leaf.id for leaf in LEAVES} for row in rows)


def test_keywords_use_token_boundaries_and_multiword_synonyms():
    assert contains_term("[브랜드] 초코우유 200ml", "초코우유")
    assert contains_term("BRAND Chocolate Milk 200ml", "chocolate milk")
    assert not contains_term("초코우유맛과자 200g", "초코우유")
    assert not contains_term("초코우유맛 과자 200g", "우유")
    assert classify_record(_raw("emart", "베스트", "초코우유맛과자"))["unified_category_id"] is None


def test_keyword_ambiguous_collision_and_one_character_are_rejected():
    rows = [
        {"word": "초코우유", "synonyms": ["chocolate milk"], "unified_category_id": "food.dairy.milk.chocolate"},
        {"word": "딸기우유", "synonyms": ["Chocolate-Milk"], "unified_category_id": "food.dairy.milk.strawberry"},
    ]
    assert keyword_collisions(rows) == {"chocolate milk": ["food.dairy.milk.chocolate", "food.dairy.milk.strawberry"]}
    with pytest.raises(ValueError, match="collision"):
        validate_keyword_definitions(rows)
    with pytest.raises(ValueError, match="two characters"):
        validate_keyword_definitions([{ "word": "유", "synonyms": [], "unified_category_id": "food.dairy.milk.plain"}])


def test_path_normalization_preserves_nonadjacent_repeats_and_slashes():
    assert normalize_source_path(["A", "A", "B/C", "A"]) == ("A", "B/C", "A")
    assert normalize_source_path('["우유/유제품", "우유", "초코우유"]') == ("우유/유제품", "우유", "초코우유")


def test_milk_fat_and_sterilization_are_attributes_not_flavour_siblings():
    result = classify_record(_raw("homeplus", "우유/유제품 > 우유 > 흰우유", "매일 소화가잘되는우유 멸균 저지방 190ML*6"))
    assert result["unified_category_id"] == "food.dairy.milk.plain"
    assert result["classification_attributes"] == {"fat_content": "low_fat", "sterilized": True}
    chocolate = classify_record(_raw("emart", "우유/유제품", "저지방 초코우유 200ml"))
    assert chocolate["unified_category_id"] == "food.dairy.milk.chocolate"
    assert chocolate["classification_attributes"]["fat_content"] == "low_fat"
    assert "food.dairy.milk.low_fat" not in {leaf.id for leaf in LEAVES}


@pytest.mark.parametrize(("mart", "path", "title"), [
    ("homeplus", "라면/즉석식품/통조림 > 즉석식품/누룽지/죽 > 즉석국 > 즉석국(레토르트)", "오뚜기 3분 카레 매운맛 200G"),
    ("homeplus", "냉장/냉동/밀키트 > 돈까스/떡갈비/너겟 > 돈까스", "목우촌 주부9단치킨까스 360G"),
    ("lottemart", ["델리ㆍ즉석조리", "샌드위치ㆍ햄버거", "샌드위치"], "탱글탱글 소세지가 쏙! 15핫도그 (팩)"),
    ("homeplus", "우유/유제품 > 요거트/요구르트 > 떠먹는 요구르트", "일동후디스 그릭요거트달지않은저지방 80G*4"),
    ("homeplus", "우유/유제품 > 두유 > 일반두유", "매일 아몬드브리즈 무당 950ML"),
    ("costco", "우유", "마이아 프로틴 메이커 두유 제조기 800ml"),
    ("homeplus", "두부/김치/반찬 > 두부/나물 > 낫또", "풀무원 국산콩 진한 콩국물 960G"),
    ("homeplus", "두부/김치/반찬 > 두부/나물 > 순두부/연두부", "씨제이 다담 순두부 찌개 양념 140G"),
    ("homeplus", "냉장/냉동/밀키트 > 떡볶이/면류 > 냉면/소바 > 간편냉면&소바", "씨제이 동치미 냉면육수 300ML"),
    ("homeplus", "수산물/건어물 > 간편/냉동수산물 > 냉동간편수산물 > 냉동새우", "손질 오징어링 500G"),
    ("homeplus", "두부/김치/반찬 > 어묵/맛살/단무지 > 어묵 > 볶음용어묵", "사조대림 실 곤약 400G"),
    ("homeplus", "장류/양념/제빵 > 소금/설탕 > 흰설탕", "CJ 백설 알룰로스 분말 400G"),
    ("emart", "수산물/건해산", "고소한 참기름 돌 김자반 50G"),
    ("emart", "베스트", "화장지/키친타올/생리대 특가(※일부품목제외)"),
    ("homeplus", "세탁/청소 > 세탁세제/섬유유연제 > 섬유유연제", "LG 아우라 피톤치드 편백탈취제 숲속향 500ML"),
    ("emart", "반려동물", "강아지 샴푸 500ml"),
])
def test_observed_source_path_pollution_does_not_get_high_confidence(mart, path, title):
    result = classify_record(_raw(mart, path, title))
    assert result["unified_category_id"] is None
    assert result["review_status"] == "pending"
    assert result["classification_confidence"] < 0.80
    assert result["source_path_parts"]


@pytest.mark.parametrize(("mart", "path", "title", "leaf"), [
    ("costco", "커피", "커클랜드 시그니춰 인스턴트 커피 454g", "food.drinks.coffee.instant"),
    ("costco", "커피", "스타벅스 카페 베로나 홀빈 커피 1.13kg", "food.drinks.coffee.beans"),
    ("costco", "커피", "Hamaya 드립백 커피 8g x 36", "food.drinks.coffee.drip"),
    ("costco", "커피", "벨미오 캡슐커피 클래식 80개입", "food.drinks.coffee.capsule"),
    ("costco", "커피", "네스카페 돌체구스토 아이스 아메리카노 캡슐 36P", "food.drinks.coffee.capsule"),
    ("costco", "커피", "스타벅스 더블샷 200ml x 36캔", "food.drinks.coffee.ready"),
    ("emart", "커피/원두/차", "콜드브루아메리카노(390ml×6)", "food.drinks.coffee.ready"),
    ("homeplus", "커피/차 > 원두커피/캡슐커피 > 분쇄커피 > 분쇄커피", "맥널티 리치 헤이즐넛 분쇄 1KG", "food.drinks.coffee.beans"),
    ("lottemart", ["커피ㆍ원두", "커피믹스ㆍ프림", "커피믹스"], "동서 카누 미니 마일드로스트 아메리카노 100포", "food.drinks.coffee.instant"),
])
def test_audited_coffee_shelves_use_explicit_product_form(mart, path, title, leaf):
    result = classify_record(_raw(mart, path, title))
    assert result["unified_category_id"] == leaf
    assert result["classification_confidence"] >= 0.90


@pytest.mark.parametrize("title", [
    "삼풍 커피필터 600매", "프리파라 네스프레소 전용 캡슐홀더",
    "아소부 뉴 콜드브루 커피메이커", "쏘울핸드 커피 그라인더",
    "카피탈리 시스템 캡슐 커피 머신", "쓰임 스테이블 커피잔 세트",
    "카페, 진정성 밀크티 350ml", "펄세스 스테비아 율무차 18g x 100ct",
    "커피빈 얼그레이 바닐라라떼 25g x 40ct", "루카스나인 우베라떼 18g x 50",
    "맥널티 스테비아 단백질 고구마크림라떼 20T(360G)",
])
def test_polluted_coffee_shelf_accessories_and_other_drinks_stay_pending(title):
    result = classify_record(_raw("costco", "커피", title))
    assert result["unified_category_id"] is None
    assert result["review_status"] == "pending"


def test_mixed_instant_and_drip_coffee_gift_set_stays_pending():
    result = classify_record(_raw("costco", "커피", "스타벅스 아메리카노 & 드립백커피 선물세트"))
    assert result["unified_category_id"] is None


@pytest.mark.parametrize(("title", "leaf"), [
    ("커클랜드 시그니춰 홍자몽주스 2.84L x 2", "food.drinks.juice.fruit"),
    ("델몬트 스테비아 토마토 주스 950ml x 6", "food.drinks.juice.vegetable"),
    ("야채듬뿍 더'진한 레드 주스 125ml x 24", "food.drinks.juice.vegetable"),
    ("풀무원녹즙 프레시업 양배추천해 190ml x 10", "food.drinks.juice.vegetable"),
    ("커클랜드 시그니춰 유기농 코코넛워터 330mlx12", "food.drinks.juice.coconut"),
    ("피지워터 330ml X 24", "food.drinks.water_soda.water"),
    ("동원미네마인스파클링워터 500ml x 48", "food.drinks.water_soda.sparkling"),
    ("코카콜라 250ml x 30", "food.drinks.water_soda.cola"),
    ("칠성사이다 1.8L x 6", "food.drinks.water_soda.cider"),
    ("몬스터에너지울트라 355ml x 24캔", "food.drinks.water_soda.energy"),
    ("토레타과채이온음료 340ml x 24캔", "food.drinks.water_soda.sports"),
    ("분다버그 진저 비어캔 200ml x 24", "food.drinks.water_soda.soda"),
    ("녹차원 보이차 0.9g x 100티백 x 3", "food.drinks.tea.puer"),
    ("동원보성말차500ml x 24병", "food.drinks.tea.green"),
    ("동원보성홍차아이스티 500ml x 24병", "food.drinks.tea.black"),
    ("블랙보리 520ml X 24", "food.drinks.tea.barley"),
    ("쌍계 김동곤명인의 쑥차 파우더 15g x 40", "food.drinks.tea.herbal"),
    ("양반가마솥누룽지500ml x 24", "food.drinks.tea.grain"),
    ("스타벅스더블샷바닐라 275ml x 24", "food.drinks.coffee.ready"),
])
def test_audited_costco_beverage_shelf_uses_explicit_drink_form(title, leaf):
    result = classify_record(_raw("costco", "음료", title))
    assert result["unified_category_id"] == leaf
    assert result["classification_confidence"] >= 0.90


@pytest.mark.parametrize("title", [
    "베트남 영코코넛 9입(7.5kg내외)",
    "폴라레티 후르트 아이스바 40ml x 80",
    "끌레드벨 럭셔리 콜라겐 82 앰플 100ml x 2",
    "벤딕트 차량용 보냉 컵홀더 2개",
    "본비 유차청 2kg",
    "정관장 홍삼원력 50ml x 30포",
    "프리미어 단백질 드링크 325ml x 12팩",
    "칠성사이다 250ml x 30 + 펩시콜라 250ml x 30 콤보팩",
])
def test_audited_costco_beverage_shelf_contaminants_and_unclear_forms_stay_pending(title):
    result = classify_record(_raw("costco", "음료", title))
    assert result["unified_category_id"] is None
    assert result["review_status"] == "pending"


def test_frozen_watermelon_juice_does_not_match_the_korean_word_for_bottled_water():
    result = classify_record(_raw("costco", "음료", "엘제이드얼린생수박주스340ml x 8 x 2"))
    assert result["unified_category_id"] == "food.drinks.juice.fruit"


@pytest.mark.parametrize(("title", "leaf"), [
    ("초정탄산수 1.5L", "food.drinks.water_soda.sparkling"),
    ("백산수 2L", "food.drinks.water_soda.water"),
    ("에비앙 500ml*12입+쇼퍼백 기획", "food.drinks.water_soda.water"),
    ("포카리스웨트900ml", "food.drinks.water_soda.sports"),
    ("칠성사이다 1.8L*2입", "food.drinks.water_soda.cider"),
    ("제로사이다 1L", "food.drinks.water_soda.cider"),
    ("썬키스트 애사비 제로스파클링 500ML", "food.drinks.water_soda.soda"),
    ("[논알콜] 클라우스탈러 330ml(캔)", "food.drinks.non_alcoholic.beer"),
    ("이토엔 오이오차녹차 525ml", "food.drinks.tea.green"),
    ("하늘보리 500ml", "food.drinks.tea.barley"),
    ("옥수수수염차 1.5L", "food.drinks.tea.grain"),
    ("비락식혜 1.5L", "food.drinks.tea.grain"),
    ("스페인 햇살 담은 오렌지 100% 착즙주스 1L", "food.drinks.juice.fruit"),
    ("Fresh토마토음료 1.5L", "food.drinks.juice.vegetable_drink"),
    ("Fresh감귤음료1.5L", "food.drinks.juice.fruit_drink"),
    ("Fresh알로에음료1.5L", "food.drinks.juice.aloe"),
    ("쿨피스플러스 930ml*2입", "food.drinks.juice.fruit_drink"),
])
def test_audited_emart_beverage_shelf_uses_explicit_product_form(title, leaf):
    result = classify_record(_raw("emart", "생수/음료/주류", title))
    assert result["unified_category_id"] == leaf
    assert result["classification_confidence"] >= 0.90


@pytest.mark.parametrize("title", [
    "[매일유업]맘마밀 이유식 퓨레 사과와고구마 100g",
    "처음먹는 평창감자 퓨레 80g",
    "1.8L*2입",
    "처음먹는 배도라지",
    "오트몬드 프로틴 초코 250ml",
    "[논알콜] 클라우드 논알콜릭 500캔",
])
def test_audited_emart_beverage_shelf_unclear_or_non_drinks_stay_pending(title):
    result = classify_record(_raw("emart", "생수/음료/주류", title))
    assert result["unified_category_id"] is None


def test_explicit_bottled_water_name_stays_consistent_on_emart_promotion_shelf():
    result = classify_record(_raw("emart", "베스트", "삼다수 2L (무라벨)"))
    assert result["unified_category_id"] == "food.drinks.water_soda.water"


def test_non_alcoholic_word_without_audited_beer_evidence_does_not_mean_beer():
    result = classify_record(_raw("emart", "생수/음료/주류", "논알콜 샹그리아 750ml"))
    assert result["unified_category_id"] is None


def test_apple_cider_vinegar_drink_does_not_become_korean_cider_soda():
    result = classify_record(_raw("costco", "음료", "쌍계 애플사이다비니거 드링크 사과 5g x 40ct"))
    assert result["unified_category_id"] is None


def test_adjacent_bottle_count_waits_until_package_parser_supports_it():
    result = classify_record(_raw("emart", "생수/음료/주류", "제주 삼다수 그린 500ml 40병"))
    assert result["unified_category_id"] is None
    assert result["classification_reason"] == "source_title_product_type_conflict"


@pytest.mark.parametrize(("title", "leaf"), [
    ("커클랜드 시그니춰 탈각 피스타치오 680g", "food.grains.nuts.pistachio"),
    ("커클랜드 시그니춰 무염 견과 스낵팩 945g", "food.grains.nuts.mixed"),
    ("커클랜드 시그니춰 핑크 솔트감자칩 907g", "food.snacks.savory.potato"),
    ("G.H.CRETORS 시카고 믹스 팝콘 737g", "food.snacks.savory.popcorn"),
    ("El Sabroso 옐로우콘토티야칩851g", "food.snacks.savory.corn"),
    ("Jackson고구마칩454g", "food.snacks.savory.vegetable"),
    ("C-WEED다시마 부각칩 150g", "food.snacks.savory.seaweed"),
    ("갓 튀김 어포 400g", "food.seafood.processed.dried_fish"),
    ("미왕 고소한 쌀과자 250g x 5", "food.snacks.savory.grain"),
    ("Shultz 미니 프레첼 2.72kg", "food.snacks.baked.cracker"),
    ("커피크림 웨이퍼롤 180g x 6", "food.snacks.baked.wafer"),
    ("롯데찰떡파이 35g x 35ea", "food.snacks.baked.pie"),
    ("허쉬 초콜릿칩 쿠키 720g x 2", "food.snacks.baked.biscuits"),
    ("Sennenya 브라운버터 바움쿠헨 50g x 16", "food.snacks.baked.cake"),
    ("화과방 프리미엄 양갱 40g x 40", "food.snacks.traditional.yanggaeng"),
    ("대조 우리쌀 전병 세트 24g x 24", "food.snacks.traditional.hangwa"),
    ("Trolli 젤리 4종 100g x 12", "food.snacks.sweets.jelly"),
    ("Trefin 벨기에 커피 캔디 1.5kg", "food.snacks.sweets.candy"),
    ("Dole 복숭아 과일컵 113g x 16", "food.produce.processed_fruit.cup"),
    ("100% 순수사과 동결건조 과일 30g x 10", "food.produce.processed_fruit.dried"),
    ("카프리썬 오렌지망고 주스 200ml x 20", "food.drinks.juice.fruit"),
])
def test_audited_costco_snack_shelf_uses_explicit_product_form(title, leaf):
    result = classify_record(_raw("costco", "과자", title))
    assert result["unified_category_id"] == leaf


@pytest.mark.parametrize("title", [
    "정직하개 애견용 소고기 육포 1kg", "프리미엄 제철과일 선물세트 총 3.4kg이상",
    "락앤락 휴대용 과일 & 요거트 보틀 600ml x 2P", "카스 초음파 야채 과일 세척기 4L",
    "산리오 캐릭터즈 디저트 휘핑 데코 놀이 세트", "Arla 하바티 & 고다 스낵치즈 510g x 432ea",
    "Snapik 화이트 마시멜로우 1kg x 176",
    "Delici 쿠키버터무스 76g x 6", "해품은김과 김부각 세트",
])
def test_audited_costco_snack_shelf_contaminants_and_bad_packages_stay_pending(title):
    result = classify_record(_raw("costco", "과자", title))
    assert result["unified_category_id"] is None


@pytest.mark.parametrize(("title", "leaf"), [
    ("농심 신라면 120g x 30개", "food.meals.noodles.bag_ramen"),
    ("농심 육개장 사발면 86g x 24개", "food.meals.noodles.cup_ramen"),
    ("데 체코파스타면1kg x 4", "food.meals.noodles.pasta"),
    ("백제 김치 쌀국수100g x 10", "food.meals.noodles.rice_noodle"),
    ("풍국면 우리밀 국수 400g x 10팩", "food.meals.noodles.wheat_noodle"),
    ("풍국면 메밀국수 500g x 6팩", "food.meals.noodles.buckwheat_noodle"),
    ("동원들깨칼국수258g x 4", "food.meals.noodles.kalguksu"),
    ("백제 도토리 비빔막국수 297.5g x 8", "food.meals.noodles.makguksu"),
    ("이가자연면 감자수제비186.5g x 8", "food.meals.noodles.sujebi"),
    ("마이노멀 두부면 130g x 12", "food.meals.noodles.tofu_noodle"),
    ("풀무원 수타식 즉석생우동 195g x 10", "food.meals.noodles.udon"),
    ("풀무원 평양 물냉면 205g x 8", "food.meals.noodles.naengmyeon"),
    ("풀무원 로스팅 파기름 짜장면 105g x 24", "food.meals.noodles.black_bean"),
    ("비비고 고메 중화짬뽕 326g x 6", "food.meals.noodles.jjamppong"),
    ("Blue Dragon 팟타이키트 440g x 2", "food.meals.noodles.pad_thai"),
    ("농심 짜파게티범벅 70g x30개", "food.meals.noodles.cup_ramen"),
    ("오뚜기 진짬뽕 130g x32", "food.meals.noodles.bag_ramen"),
    ("농심 사리면 110g x30", "food.meals.noodles.bag_ramen"),
    ("풀무원 생면식감 순한맛 95.9g x 20", "food.meals.noodles.bag_ramen"),
])
def test_audited_costco_noodle_shelf_uses_explicit_noodle_form(title, leaf):
    result = classify_record(_raw("costco", "라면", title))
    assert result["unified_category_id"] == leaf


@pytest.mark.parametrize("title", [
    "마이어 라면 조리기", "코렐 더블링 라떼 면기 세트 4P", "냉동 손질 오징어 1.5kg X 2pack",
    "절단꽃게 1.2kg X 2pack", "가지 2봉 (7개x 2봉)", "다담 떡볶이 양념 150g x 20",
    "설성목장한우사골 곰탕 스틱 14g x 10 x 4", "Mama's Choice 오징어소면 300g",
    "오뚜기 뿌셔뿌셔 불고기맛 95g x 16",
])
def test_audited_costco_noodle_shelf_contaminants_stay_pending(title):
    result = classify_record(_raw("costco", "라면", title))
    assert result["unified_category_id"] is None


@pytest.mark.parametrize(("title", "leaf"), [
    ("Mama's Choice치즈 오징어 120g x 3", "food.seafood.processed.dried_fish"),
    ("한우물치즈닭갈비구운주먹밥100gx30", "food.meals.rice.rice_ball"),
    ("풀무원치즈볼4개골라담기(360g x 4)", "food.meals.prepared.cheese_ball"),
    ("애슐리 트리플 치즈 피자 395g x 3", "food.meals.prepared.pizza"),
    ("폰타나토마토&로제파스타소스600g x 4", "food.seasonings.sauces.pasta"),
    ("마다마 피티드 올리브 480g x 3", "food.produce.processed_vegetables.olive"),
    ("수지탈 뇨끼 파타타(감자) 1kg x 3", "food.meals.noodles.gnocchi"),
    ("덕화명란튜브110g x 8", "food.seafood.processed.pollock_roe"),
    ("사옹원 소고기육전 765g x 2", "food.meals.prepared.pancake"),
    ("개성제주돼지감자만두 2KG X 2", "food.meals.dumplings.assorted"),
    ("동원 딤섬 새우하가우1.2KG X 2", "food.meals.dumplings.dimsum"),
    ("CJ 비비고 소고기 듬뿍 설렁탕 460g x 6", "food.meals.prepared.soup_stew"),
    ("하림 치킨너겟 1.5kg x 2", "food.meals.prepared.nugget"),
    ("동원 7겹돈까스 1040g x 2", "food.meals.prepared.pork_cutlet"),
    ("BBQ 야자당 닭강정 1.2KG x 2", "food.meals.prepared.chicken"),
    ("테이블마크키츠네 유부우동 283G X 6", "food.meals.noodles.udon"),
    ("마음이가 모둠 꿀떡1.4kg X 2ea", "food.meals.prepared.rice_cake"),
    ("오마뎅 진짜 부산 떡볶이 352g x 5", "food.meals.prepared.tteokbokki"),
    ("천하장사 더블링 콰트로치즈 25g X 40", "food.meat.processed.sausage"),
    ("Scoiattolo 트러플파마지아노라비올리 908g", "food.meals.noodles.ravioli"),
])
def test_audited_costco_cheese_shelf_uses_explicit_product_form(title, leaf):
    result = classify_record(_raw("costco", "치즈", title))
    assert result["unified_category_id"] == leaf


@pytest.mark.parametrize("title", [
    "딩고 애견 치킨껌 2개 x 10봉", "덴마크 구워먹는치즈 500g x 2",
    "구르메 치즈 & 초리조선물세트 875g", "타카쇼 로즈아치",
    "쿠진아트 미니 중식도 & 강판 세트", "치자 2개입",
])
def test_audited_costco_cheese_shelf_ambiguous_and_nonfood_items_stay_pending(title):
    result = classify_record(_raw("costco", "치즈", title))
    assert result["unified_category_id"] is None


@pytest.mark.parametrize(("title", "leaf"), [
    ("후레쉬 라임 8kg", "lime"),
    ("남아공 자몽16kg", "grapefruit"),
    ("용과 4.8kg 선물세트", "dragon_fruit"),
    ("브라질애플망고선물세트3.7kg", "mango"),
])
def test_audited_fruit_title_requires_matching_store_and_shelf(title, leaf):
    result = classify_record(_raw("costco", "과일", title))
    assert result["unified_category_id"] == f"food.produce.fruit.{leaf}"
    assert result["evidence_type"] == "audited_costco_fruit_title"
    assert classify_record(_raw("costco", "과일", title + " 주스"))["unified_category_id"] is None
    assert classify_record(_raw("costco", "커피", title))["unified_category_id"] is None


@pytest.mark.parametrize(("title", "leaf"), [
    ("한우물 소고기잡채350g x 5 x 2pk", "food.meals.prepared.japchae"),
    ("오늘차림 한돈 양념 불고기600g x 3ea", "food.meals.prepared.seasoned_meat"),
    ("부추고기순대 500gx3x2", "food.meat.processed.sundae"),
    ("오리늘보 훈제 슬라이스 500g x 2", "food.meat.processed.smoked_duck"),
    ("마이셰프한우소고기미역국 254g x 2", "food.meals.prepared.soup_stew"),
    ("피터루거 스테이크소스 714ml x 2", "food.seasonings.sauces.meat"),
    ("실키 핑크토마토4kg", "food.produce.fruit.tomato"),
])
def test_audited_meat_shelf_uses_food_form_not_ingredient(title, leaf):
    result = classify_record(_raw("costco", "고기", title))
    assert result["unified_category_id"] == leaf
    assert result["evidence_type"] == "audited_costco_meat_shelf_title"
    assert classify_record(_raw("costco", "고기", title + " 혼합세트"))["unified_category_id"] != leaf
    assert classify_record(_raw("costco", "커피", title))["unified_category_id"] != leaf
    validate_taxonomy(taxonomy_categories({leaf}), {leaf})


@pytest.mark.parametrize("title", [
    "안방그릴 울트라 AB1107CO", "오크우드 장작 15kg",
    "하림 더리얼 밀 냉동 화식 닭고기 60g x 10",
    "하림 더리얼 밀 그레인프리 냉동 화식 닭고기 60g x 10",
    "부추고기순대500Gx3 족발슬라이스 960g",
    "궁 안동식 한우국밥 800g x 2 + 나주식곰탕 510g x 3",
    "설성목장 한우불고기 덮밥소스100g x 8",
])
def test_meat_shelf_contaminants_and_mixed_sets_stay_pending(title):
    assert classify_record(_raw("costco", "고기", title))["unified_category_id"] is None


@pytest.mark.parametrize("title", [
    "수박2호 ( 6KG 미만 )", "허니듀 & 머스크 멜론 세트 4입 (각 2입)",
    "샤인머스캣 애플망고 사과 혼합선물세트4.6kg", "휴롬 원액기 P310 E31ST-BFM02MM",
])
def test_fruit_shelf_does_not_prove_a_single_fixed_product(title):
    assert classify_record(_raw("costco", "과일", title))["unified_category_id"] is None


def test_audited_costco_cheese_shelf_keeps_shredded_pizza_cheese_as_cheese():
    result = classify_record(_raw("costco", "치즈", "소와나무 이태리안 피자치즈 1kg x 3"))
    assert result["unified_category_id"] == "food.dairy.cheese.shredded"


@pytest.mark.parametrize(("title", "leaf"), [
    ("소화잘되는 배안아픈저지방우유 (900ml*2)", "food.dairy.milk.plain"),
    ("서울 A2플러스우유 710ml", "food.dairy.milk.plain"),
    ("유기농우유 900ml", "food.dairy.milk.plain"),
    ("후레쉬 밀크 기획(900ml*2) 1800ml", "food.dairy.milk.plain"),
    ("바나나맛우유 무가당(240ml*4입)", "food.dairy.milk.banana"),
    ("필라델피아 크림치즈190g", "food.dairy.cheese.cream"),
    ("생크림500ml", "food.dairy.cream.fresh"),
    ("버터450g(해동)", "food.dairy.cheese.butter"),
    ("상하 프로틴치즈 라이트 슬라이스15매", "food.dairy.cheese.sliced"),
    ("모짜렐라 슈레드치즈800g", "food.dairy.cheese.shredded"),
    ("상하 프로틴 스트링치즈200g", "food.dairy.cheese.string"),
    ("덴마크 후레쉬 모짜렐라 미니125g", "food.dairy.cheese.fresh_mozzarella"),
    ("보꼬네 올리브오일 모짜렐라 보코치니200g", "food.dairy.cheese.fresh_mozzarella"),
    ("덴마크 후레쉬 리코타150g", "food.dairy.cheese.ricotta"),
    ("덴마크 드링킹요구르트 딸기275ml", "food.dairy.yogurt.drink"),
    ("상하 그릭요거트 무가당80g*4", "food.dairy.yogurt.greek"),
    ("검은콩 블랙9곡두유190ml*16", "food.plant.soy.soymilk"),
])
def test_reviewed_emart_dairy_compound_titles_require_compatible_context(title, leaf):
    result = classify_record(_raw("emart", "우유/유제품", title))
    assert result["unified_category_id"] == leaf
    assert result["classification_confidence"] >= 0.80
    assert len(result["category_path"]) == 4


@pytest.mark.parametrize(("title", "section", "leaf"), [
    ("연세우유소화가잘되는멸균우유190mlx24", "Beverages/Soy-MilkMilk", "food.dairy.milk.plain"),
    ("연세 말차라떼 멸균우유190ml x24", "Beverages/Soy-MilkMilk", "food.dairy.milk.matcha"),
    ("매일유업 Arla 크림치즈 플레인150gx6", "Chilled-Foods/Chilled-Foods", "food.dairy.cheese.cream"),
    ("RoyalOrange 에멘탈 슬라이스150gx3", "Chilled-Foods/CheeseButter", "food.dairy.cheese.sliced"),
    ("커클랜드 쉬레드파마지아노레지아노500gx2", "Chilled-Foods/CheeseButter", "food.dairy.cheese.shredded"),
    ("Zanetti리코타250gx3", "Chilled-Foods/CheeseButter", "food.dairy.cheese.ricotta"),
    ("Zanetti 마스카르포네500gx2", "Chilled-Foods/CheeseButter", "food.dairy.cheese.mascarpone"),
    ("커클랜드 Isigny 브리600gx2", "Chilled-Foods/CheeseButter", "food.dairy.cheese.brie"),
    ("일드프랑스 미니까망베르25gx10x4", "Chilled-Foods/CheeseButter", "food.dairy.cheese.camembert"),
    ("Rabel만체고트러플200gx2", "Chilled-Foods/CheeseButter", "food.dairy.cheese.hard_aged"),
    ("EuroPomella 냉동부라타치즈100gx8", "Frozen-Foods/Instant-FoodDumplingTraditional-PancakesCheese", "food.dairy.cheese.burrata"),
    ("코우카키스딸기그릭요거트150gx6", "Chilled-Foods/Chilled-Foods", "food.dairy.yogurt.greek"),
    ("커클랜드 시그니춰아몬드음료946ml x12", "Beverages/Soy-MilkMilk", "food.plant.drinks.almond"),
    ("Blue Diamond 아몬드 브리즈 오리지널190ml x24", "Beverages/Soy-MilkMilk", "food.plant.drinks.almond"),
    ("아몬드 브리즈 프로틴190ml x24 x2", "Beverages/SoftConcentrated-Drinks", "food.plant.drinks.almond"),
    ("연세우리콩두유 검은콩190mlx24", "Beverages/Soy-MilkMilk", "food.plant.soy.soymilk"),
])
def test_reviewed_costco_dairy_uses_official_context_and_explicit_type(title, section, leaf):
    result = classify_record(_raw("costco", "SpecialPriceOffers", title, canonical_url=f"https://www.costco.co.kr/Foods/{section}/Product/p/12345"))
    assert result["unified_category_id"] == leaf
    assert result["classification_confidence"] >= 0.80


@pytest.mark.parametrize("title", [
    "우유맛과자200g", "초코우유 맛 쿠키200g", "모짜렐라 치즈피자500g",
    "두유 제조기800ml", "가정용 우유 거품기", "그릭요거트 보틀500ml",
    "고마워 치즈야 치즈볼 애견간식", "치즈브림요구르트 애견간식",
    "유기농 우유 반려견 간식", "필라델피아 크림치즈 케이크500g",
    "마스카르포네 파스타소스500g", "스키피땅콩버터크리미462g",
    "ORGANIC VALLEY기버터368G", "인기 치즈/버터 모음전 최대50%행사",
    "서울우유 카페라떼300ml", "연세우유 바닐라딜라이트300ml",
    "할리스 바닐라딜라이트300ml", "커피포리200ml*4입",
    "목장의 신선함이 살아 있는 저지방1L", "1000ml 나100%",
    "윌 오리지날150mlX5개", "비요뜨 초코링", "짜요짜요 딸기맛240g",
    "더 진한 순수 플레인 요거트1.8L", "다논 하루요거트플레인80g*4",
    "소와나무 체다치즈270g", "구워먹는치즈500g", "치즈큐빅파티 플레인87g",
    "오트몬드 오리지널190ml x24", "국산콩 진한 콩국950MLx4",
])
def test_dairy_words_do_not_resolve_non_dairy_or_unspecified_types(title):
    assert classify_record(_raw("emart", "우유/유제품", title))["unified_category_id"] is None


@pytest.mark.parametrize("section", [
    "Fresh-Foods/KimchiSide-Dishes", "Snack/Chocolates-Bars", "Processed-Food/Oils",
    "Processed-Food/SaucesCondiments", "Bread/Bread", "RiceGrains/Rice",
])
def test_dairy_title_does_not_override_a_conflicting_costco_food_url(section):
    result = classify_record(_raw("costco", "우유", "브랜드 그릭요거트 150g", canonical_url=f"https://www.costco.co.kr/Foods/{section}/Product/p/12345"))
    assert result["unified_category_id"] is None
    assert result["classification_reason"] == "dairy_source_context_conflict"


@pytest.mark.parametrize("section", ["Appliances/Blenders", "BabyKidsToysPets/Pet-Supplies/Dog-Foods", "HomeKitchen/Food-Storage"])
def test_costco_nonfood_url_blocks_even_unambiguous_name_token(section):
    result = classify_record(_raw("costco", "치즈", "그릭요거트 150g", canonical_url=f"https://www.costco.co.kr/{section}/Product/p/12345"))
    assert result["unified_category_id"] is None


def test_conflicting_costco_canonical_url_cannot_be_hidden_by_detail_url():
    result = classify_record(_raw("costco", "우유", "그릭요거트 150g", canonical_url="https://www.costco.co.kr/Foods/Fresh-Foods/KimchiSide-Dishes/Product/p/1", detail_url="https://www.costco.co.kr/Foods/Chilled-Foods/Chilled-Foods/Product/p/1"))
    assert result["unified_category_id"] is None


def test_dairy_context_needs_official_url_not_costco_search_label_or_product_slug():
    for url in (None, "https://example.test/Foods/Beverages/Soy-MilkMilk/Product/p/1", "https://www.costco.co.kr/Appliances/Soy-MilkMilk/p/1"):
        assert classify_record(_raw("costco", "우유", "유기농우유900ml", canonical_url=url))["unified_category_id"] is None
    assert classify_record(_raw("costco", "우유", "연세우유 멸균우유200mlx24", canonical_url="https://www.costco.co.kr/Foods/p/1"))["unified_category_id"] == "food.dairy.milk.plain"


def test_dairy_context_does_not_override_specific_source_type_conflict():
    for path, title in (
        ("우유/유제품 > 두유 > 일반두유", "매일 아몬드브리즈 무당950ML"),
        ("우유/유제품 > 치즈/버터 > 슬라이스 치즈", "필라델피아 크림치즈190g"),
        ("우유/유제품 > 요거트/요구르트 > 떠먹는 요구르트", "후디스 그릭요거트80g"),
    ):
        assert classify_record(_raw("homeplus", path, title))["unified_category_id"] is None


def test_explicit_review_only_leaves_do_not_add_loose_name_rules():
    ids = {"food.meals.noodles.glass", "food.bakery.spreads.peanut", "food.seasonings.sauces.black_bean"}
    validate_taxonomy(taxonomy_categories(ids), ids)
    for title in ("오뚜기옛날자른당면1kg", "스키피땅콩버터청크462g", "차오차이짜장소스165g"):
        assert classify_record(_raw("emart", "베스트", title))["unified_category_id"] is None


def test_reviewed_produce_leaves_have_four_levels_and_unique_search_keywords():
    paths = {
        "food.produce.fruit.avocado": ["식품", "농산물", "신선과일", "아보카도"],
        "food.produce.fruit.mango": ["식품", "농산물", "신선과일", "망고"],
        "food.produce.fruit.jujube": ["식품", "농산물", "신선과일", "대추"],
        "food.produce.vegetables.scallion": ["식품", "농산물", "신선채소", "대파"],
        "food.produce.vegetables.napa_cabbage": ["식품", "농산물", "신선채소", "배추"],
        "food.produce.processed_vegetables.dried": ["식품", "농산물", "가공채소", "건채소"],
        "food.produce.processed_vegetables.dried_mushroom": ["식품", "농산물", "가공채소", "건버섯"],
        "food.produce.processed_vegetables.frozen": ["식품", "농산물", "가공채소", "냉동채소"],
    }
    categories = {row["id"]: row for row in taxonomy_categories(paths)}
    validate_taxonomy(categories.values(), paths)
    for leaf_id, expected_path in paths.items():
        actual_path = []
        cursor = leaf_id
        while cursor:
            actual_path.insert(0, categories[cursor]["name_ko"])
            cursor = categories[cursor]["parent_id"]
        assert actual_path == expected_path
    keywords = keyword_definitions(paths)
    assert {row["unified_category_id"]: row["word"] for row in keywords} == {
        leaf_id: path[-1] for leaf_id, path in paths.items()
    }
    assert keyword_collisions(keyword_definitions()) == {}


@pytest.mark.parametrize(("path", "title"), [
    ("과일", "페루산 아보카도 1kg (5~6입)"),
    ("과일", "브라질애플망고3.7kg(7~9입)"),
    ("과일", "사과대추 500g 팩"),
    ("채소", "흙대파 750g"), ("채소", "손질배추 (통)"),
    ("채소", "건고사리 200g"), ("채소", "일품채 목이버섯 200g / 최소구매 2"),
    ("채소", "[냉동] 대파 (500g)"), ("채소", "[냉동] 볶음밥용 채소 (500g)"),
    ("채소", "냉동 다진마늘 400g x 3 x 2"),
    ("과일", "애플 & 태국망고 선물세트 2.8kg"),
    ("과일", "샤인머스캣&애플망고세트3.5kg"),
    ("과일", "아보카도 오일 1L"),
    ("채소", "채소 행사전 (대파/배추 등)"),
    ("채소", "뉴트리플랜 동결건조 야채트릿 200g"),
])
def test_new_produce_leaves_do_not_implicitly_classify_unreviewed_listings(path, title):
    result = classify_record(_raw("emart", path, title))
    assert result["unified_category_id"] is None


def test_fresh_napa_cabbage_leaf_does_not_override_existing_kimchi_contract():
    result = classify_record(_raw("emart", "채소", "배추김치 1kg"))
    assert result["unified_category_id"] == "food.preserved.kimchi.cabbage"


def test_prepared_soup_stew_label_covers_the_existing_stew_contract():
    result = classify_record(_raw("homeplus", "라면/즉석식품/통조림 > 즉석식품/누룽지/죽 > 즉석국", "CJ 비비고 두부 듬뿍 된장찌개 460G"))
    assert result["unified_category_id"] == "food.meals.prepared.soup_stew"
    assert result["category_path"] == ["식품", "간편식·면", "조리식품", "국·탕·찌개"]


@pytest.mark.parametrize(("mart", "path", "title", "leaf"), [
    ("homeplus", "우유/유제품 > 치즈/버터 > 슈레드/피자치즈/파마산 > 피자치즈", "매일 쫄깃하게늘어나는 피자용 슈레드치즈75G*4", "food.dairy.cheese.shredded"),
    ("lottemart", "우유ㆍ유제품 > 치즈 > 슈레드ㆍ피자치즈", "덴마크 피자 모짜렐라 치즈300G", "food.dairy.cheese.shredded"),
    ("homeplus", "우유/유제품 > 치즈/버터 > 스트링/과일/스낵치즈 > 구워먹는치즈등", "오뚜기 스트링치즈 플레인20G*10", "food.dairy.cheese.string"),
    ("homeplus", "우유/유제품 > 요거트/요구르트 > 떠먹는 요구르트", "서울우유 생크림 요거트85G*4", "food.dairy.yogurt.spoon"),
    ("lottemart", "우유ㆍ유제품 > 우유 > 바나나ㆍ딸기ㆍ초코ㆍ커피우유 > 바나나우유", "동원 덴마크 바나바나 우유300ML", "food.dairy.milk.banana"),
    ("lottemart", "우유ㆍ유제품 > 우유 > 바나나ㆍ딸기ㆍ초코ㆍ커피우유 > 초코우유", "푸르밀 가나 쵸코우유225ML*4", "food.dairy.milk.chocolate"),
])
def test_contextual_refinement_preserves_valid_dairy_source_contracts(mart, path, title, leaf):
    assert classify_record(_raw(mart, path, title))["unified_category_id"] == leaf


def test_opaque_flavour_in_mixed_milk_source_is_not_defaulted_to_plain_milk():
    result = classify_record(_raw("homeplus", "우유/유제품 > 우유 > 딸기/초코/바나나/기타 우유", "브랜드 바나바나 우유300ml"))
    assert result["unified_category_id"] is None


def test_reviewed_chinese_meals_and_sauces_have_separate_leaf_paths():
    paths = {
        'food.meals.prepared.mapo_tofu': ['식품', '간편식·면', '조리식품', '즉석마파두부'],
        'food.seasonings.sauces.mapo_tofu': ['식품', '양념·소스', '조미소스', '마파두부소스'],
        'food.seasonings.sauces.pepper_stir_fry': ['식품', '양념·소스', '조미소스', '고추잡채소스'],
        'food.seasonings.sauces.fish_fragrant': ['식품', '양념·소스', '조미소스', '어향소스'],
    }
    nodes = {r['id']: r for r in taxonomy_categories(paths)}
    validate_taxonomy(nodes.values(), paths)
    for leaf, expected in paths.items():
        actual, cursor = [], leaf
        while cursor:
            actual.insert(0, nodes[cursor]['name_ko'])
            cursor = nodes[cursor]['parent_id']
        assert actual == expected
    assert {r['unified_category_id']: r['word'] for r in keyword_definitions(paths)} == {leaf:path[-1] for leaf,path in paths.items()}
    assert keyword_collisions(keyword_definitions()) == {}


@pytest.mark.parametrize('title', ['마파두부 180g', '홍콩식 마파두부소스 150g', '한국풍 마파두부소스 150g', '고추잡채소스 100g', '어향가지소스 100g'])
def test_review_only_chinese_leaves_do_not_create_implicit_title_rules(title):
    assert classify_record(_raw('emart', '밀키트/간편식', title))['unified_category_id'] is None


def test_reviewed_sauce_and_cooking_oil_leaves_have_separate_four_level_paths():
    paths = {
        "food.seasonings.sauces.meat": ["식품", "양념·소스", "조미소스", "고기용소스"],
        "food.seasonings.oils.cooking": ["식품", "양념·소스", "식용유", "요리유"],
    }
    nodes = {row["id"]: row for row in taxonomy_categories(paths)}
    validate_taxonomy(nodes.values(), paths)
    for leaf, expected in paths.items():
        actual = []
        cursor = leaf
        while cursor:
            actual.insert(0, nodes[cursor]["name_ko"])
            cursor = nodes[cursor]["parent_id"]
        assert actual == expected
    assert {row["unified_category_id"]: row["word"] for row in keyword_definitions(paths)} == {
        leaf: path[-1] for leaf, path in paths.items()
    }
    assert keyword_collisions(keyword_definitions()) == {}


@pytest.mark.parametrize("path,title", [
    ("양념/오일", "고기엔 참소스 800g"),
    ("식용유/참기름", "해표 바삭요리유 900ml"),
])
def test_review_only_sauce_and_cooking_oil_leaves_do_not_widen_automatic_rules(path, title):
    assert classify_record(_raw("emart", path, title))["unified_category_id"] is None


def test_reviewed_grain_snack_leaf_has_four_levels_and_a_unique_keyword():
    leaf = "food.snacks.savory.grain"
    nodes = {row["id"]: row for row in taxonomy_categories({leaf})}
    validate_taxonomy(nodes.values(), {leaf})
    actual = []
    cursor = leaf
    while cursor:
        actual.insert(0, nodes[cursor]["name_ko"])
        cursor = nodes[cursor]["parent_id"]
    assert actual == ["식품", "과자·간식", "스낵", "곡물스낵"]
    assert {row["unified_category_id"]: row["word"] for row in keyword_definitions({leaf})} == {
        leaf: "곡물스낵"
    }
    assert keyword_collisions(keyword_definitions()) == {}


def test_review_only_grain_snack_leaf_does_not_widen_automatic_rules():
    assert classify_record(_raw("homeplus", "쌀/곡물 과자", "크라운 죠리퐁 74G"))["unified_category_id"] is None


def test_reviewed_soda_leaf_has_four_levels_and_a_unique_keyword():
    leaf = "food.drinks.water_soda.soda"
    nodes = {row["id"]: row for row in taxonomy_categories({leaf})}
    validate_taxonomy(nodes.values(), {leaf})
    actual = []
    cursor = leaf
    while cursor:
        actual.insert(0, nodes[cursor]["name_ko"])
        cursor = nodes[cursor]["parent_id"]
    assert actual == ["식품", "음료", "생수·탄산", "탄산음료"]
    assert {row["unified_category_id"]: row["word"] for row in keyword_definitions({leaf})} == {
        leaf: "탄산음료"
    }
    assert keyword_collisions(keyword_definitions()) == {}


def test_review_only_soda_leaf_does_not_widen_automatic_rules():
    assert classify_record(_raw("emart", "생수/음료/주류", "맥콜 제로 1.5L"))["unified_category_id"] is None


@pytest.mark.parametrize("leaf,expected", [
    ("food.meals.prepared.pancake", ["식품", "간편식·면", "조리식품", "냉동전"]),
    ("food.seasonings.powders.curry", ["식품", "양념·소스", "분말조미료", "카레가루"]),
])
def test_reviewed_ready_meal_leaves_have_four_levels_and_unique_keywords(leaf, expected):
    nodes = {row["id"]: row for row in taxonomy_categories({leaf})}
    validate_taxonomy(nodes.values(), {leaf})
    actual = []
    cursor = leaf
    while cursor:
        actual.insert(0, nodes[cursor]["name_ko"])
        cursor = nodes[cursor]["parent_id"]
    assert actual == expected
    assert {row["unified_category_id"]: row["word"] for row in keyword_definitions({leaf})} == {
        leaf: expected[-1]
    }
    assert keyword_collisions(keyword_definitions()) == {}


@pytest.mark.parametrize("path,title", [
    ("냉동전", "풀무원 철판 오징어김치전 300g"),
    ("카레가루/카레소스", "오뚜기 백세카레 순한맛 100g"),
])
def test_reviewed_ready_meal_leaves_do_not_widen_automatic_rules(path, title):
    assert classify_record(_raw("lottemart", path, title))["unified_category_id"] is None


@pytest.mark.parametrize("leaf,expected", [
    ("food.produce.vegetables.radish", ["식품", "농산물", "신선채소", "무"]),
    ("food.produce.vegetables.zucchini", ["식품", "농산물", "신선채소", "애호박"]),
    ("food.meals.prepared.fried_shrimp", ["식품", "간편식·면", "조리식품", "새우튀김"]),
    ("food.preserved.sides.stir_fried", ["식품", "반찬·저장식품", "밑반찬", "볶음반찬"]),
])
def test_reviewed_remaining_exact_leaves_have_four_levels(leaf, expected):
    nodes = {row["id"]: row for row in taxonomy_categories({leaf})}
    validate_taxonomy(nodes.values(), {leaf})
    actual, cursor = [], leaf
    while cursor:
        actual.insert(0, nodes[cursor]["name_ko"])
        cursor = nodes[cursor]["parent_id"]
    assert actual == expected
    keywords = {row["unified_category_id"]: row["word"] for row in keyword_definitions({leaf})}
    if leaf.endswith(".radish"):
        assert keywords == {}  # 한 글자 '무'는 무가당/무염 오탐 때문에 자동 키워드로 쓰지 않는다.
    else:
        assert keywords == {leaf: expected[-1]}


@pytest.mark.parametrize("path,title", [
    ("채소", "무 (개)"), ("채소", "애호박 (개)"),
    ("기타튀김", "사세 바삭 튀긴 통새우튀김 300g"),
    ("볶음반찬", "샘표 오징어채볶음 60g"),
])
def test_reviewed_remaining_exact_leaves_do_not_widen_automatic_rules(path, title):
    result = classify_record(_raw("lottemart", path, title))["unified_category_id"]
    assert result not in {
        "food.produce.vegetables.radish", "food.produce.vegetables.zucchini",
        "food.meals.prepared.fried_shrimp", "food.preserved.sides.stir_fried",
    }


def test_reviewed_grain_leaves_have_independent_four_level_paths_and_keywords():
    labels = {"glutinous": "찹쌀", "black": "흑미", "barley": "보리", "millet": "기장", "chickpea": "병아리콩"}
    paths = {f"food.grains.rice.{key}": ["식품", "곡물·견과", "쌀·잡곡", label] for key, label in labels.items()}
    categories = {row["id"]: row for row in taxonomy_categories(paths)}
    validate_taxonomy(categories.values(), paths)
    for leaf, expected in paths.items():
        actual = []
        cursor = leaf
        while cursor:
            actual.insert(0, categories[cursor]["name_ko"])
            cursor = categories[cursor]["parent_id"]
        assert actual == expected
    assert {row["unified_category_id"]: row["word"] for row in keyword_definitions(paths)} == {
        leaf: path[-1] for leaf, path in paths.items()
    }
    assert keyword_collisions(keyword_definitions()) == {}


@pytest.mark.parametrize("title", [
    "국산 찹쌀 5kg", "찰흑미 5kg", "찰보리쌀 4kg", "찰기장쌀 500g", "병아리콩 500g",
    "찹쌀 호떡믹스 400g", "흑미과자 200g", "보리새우 200g", "보리차 500ml", "병아리콩 후무스 200g",
])
def test_review_only_grains_do_not_add_ingredient_based_automatic_assignments(title):
    assert classify_record(_raw("emart", "쌀/잡곡/견과", title))["unified_category_id"] not in {
        f"food.grains.rice.{key}" for key in ("glutinous", "black", "barley", "millet", "chickpea")
    }


@pytest.mark.parametrize("title", [
    "코코넛우유200ml", "아몬드우유200ml", "오트밀크1L", "식물성 우유1L",
    "비건 저지방 우유1L", "식물성 그릭요거트150g", "코코넛그릭요거트150g",
    "비건 슬라이스 치즈200g", "망고우유200ml", "검은콩우유200ml", "밤우유200ml",
])
def test_plant_alternatives_and_unresolved_flavours_are_not_assumed_plain_dairy(title):
    result = classify_record(_raw("emart", "우유/유제품", title))
    assert result["unified_category_id"] is None
