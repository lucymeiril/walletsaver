import pytest
from services.initial_taxonomy import classify_record, taxonomy_categories, validate_taxonomy

YOGURT = ["우유/유제품", "요거트/요구르트", "떠먹는 요구르트"]
CHEESE = ["우유/유제품", "치즈/버터", "크림/자연치즈", "크림/과일/스트링/까망베르/모짜렐라치즈"]


@pytest.mark.parametrize("path,title,leaf", [
    (YOGURT, "매일 바이오 그릭요거트 플레인 800G", "food.dairy.yogurt.greek"),
    (YOGURT, "일동후디스 그릭요거트달지않은저지방 80G*4", "food.dairy.yogurt.greek"),
    (YOGURT, "후디스 그릭요거트80g", "food.dairy.yogurt.greek"),
    (YOGURT, "풀무원 다논 그릭플레인 400g", "food.dairy.yogurt.greek"),
    (YOGURT, "서울우유 짜요짜요 요구르트 딸기 240G", "food.dairy.yogurt.squeeze"),
    (YOGURT + ["토핑요거트"], "서울우유 비요뜨 초코링 138G*2", "food.dairy.yogurt.topping"),
    (["우유/유제품", "치즈/버터", "슬라이스 치즈"], "simplus 스트링 치즈 200G (20G*10)", "food.dairy.cheese.string"),
    (["우유/유제품", "치즈/버터", "슬라이스 치즈"], "구르메 파르미지아노 레지아노 치즈 150G", "food.dairy.cheese.hard_aged"),
    (CHEESE, "밀라 마스카포네 250G", "food.dairy.cheese.mascarpone"),
    (CHEESE, "고르곤졸라 피칸테 150G", "food.dairy.cheese.blue"),
    (CHEESE, "램노스 과일치즈 메론망고 125G", "food.dairy.cheese.fruit"),
    (CHEESE, "벨큐브 플레인 큐브치즈 125G", "food.dairy.cheese.portion"),
    (CHEESE, "동원덴마크 구워먹는 치즈 125G", "food.dairy.cheese.grilling"),
])
def test_reviewed_product_form(path, title, leaf):
    assert classify_record({"source_name": "homeplus", "source_category_path": path, "source_title": title})["unified_category_id"] == leaf
    validate_taxonomy(taxonomy_categories({leaf}), {leaf})


@pytest.mark.parametrize("title", ["포션믹스 20G*6", "살라미 슬라이스 100G", "초리조 슬라이스 100G"])
def test_unknown_cheese_or_meat_not_inferred_from_shelf(title):
    assert classify_record({"source_name": "homeplus", "source_category_path": CHEESE, "source_title": title})["unified_category_id"] is None


def test_valid_conflicting_yogurt_form_remains_pending():
    assert classify_record({"source_name": "homeplus", "source_category_path": YOGURT, "source_title": "그릭요거트 마시는 요구르트 200ML"})["unified_category_id"] is None


def test_other_mart_not_granted_retail_override():
    assert classify_record({"source_name": "emart", "source_category_path": YOGURT, "source_title": "매일 바이오 그릭요거트 플레인 800G"})["evidence_type"] != "reviewed_homeplus_shelf_and_form"
