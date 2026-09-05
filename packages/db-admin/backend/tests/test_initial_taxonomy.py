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
    ("lottemart", ["커피ㆍ원두", "커피믹스ㆍ프림", "커피믹스"], "동서 카누 미니 마일드로스트 아메리카노 100포"),
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


@pytest.mark.parametrize("title", [
    "코코넛우유200ml", "아몬드우유200ml", "오트밀크1L", "식물성 우유1L",
    "비건 저지방 우유1L", "식물성 그릭요거트150g", "코코넛그릭요거트150g",
    "비건 슬라이스 치즈200g", "망고우유200ml", "검은콩우유200ml", "밤우유200ml",
])
def test_plant_alternatives_and_unresolved_flavours_are_not_assumed_plain_dairy(title):
    result = classify_record(_raw("emart", "우유/유제품", title))
    assert result["unified_category_id"] is None
