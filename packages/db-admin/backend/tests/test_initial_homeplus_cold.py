import pytest
from services.initial_taxonomy import classify_record, taxonomy_categories, validate_taxonomy


@pytest.mark.parametrize("shelf,title,leaf", [
    ("냉장주스", "매일 썬업100% 과일주스 사과 750ML", "food.drinks.juice.fruit"),
    ("냉장주스", "서울우유 아침에주스 사과 1.8L", "food.drinks.juice.fruit"),
    ("냉장주스", "자임 비타민이 들어있는 사과당근 착즙주스 245ML", "food.drinks.juice.vegetable"),
    ("냉장주스", "서울우유 프루티 홈 자몽 1L", "food.drinks.juice.fruit_drink"),
    ("냉장주스", "서울우유 프루티 홈 토마토 1L", "food.drinks.juice.vegetable_drink"),
    ("신선음료", "비락 유기농 야채사랑365 190ML*4", "food.drinks.juice.vegetable"),
    ("신선음료", "쏘굿 오트 언스윗 1L", "food.plant.drinks.oat"),
    ("신선음료", "서정 느린식혜 1L", "food.drinks.traditional.sikhye"),
    ("신선음료", "simplus 복숭아 아이스티 2.1L", "food.drinks.tea.black"),
    ("푸딩디저트류", "씨제이 쁘띠첼 요거젤리 딸기 210G", "food.snacks.sweets.jelly"),
    ("푸딩디저트류", "씨제이 쁘띠첼 그린애플 210G", "food.snacks.sweets.jelly"),
    ("푸딩디저트류", "MDS 망고 푸딩 1KG", "food.snacks.sweets.pudding"),
])
def test_reviewed_cold_shelf_form(shelf, title, leaf):
    row = {"source_name": "homeplus", "source_category_path": ["우유/유제품", "냉장디저트/음료", shelf], "source_title": title}
    assert classify_record(row)["unified_category_id"] == leaf
    validate_taxonomy(taxonomy_categories({leaf}), {leaf})


@pytest.mark.parametrize("title", ["롯데 콜드오렌지+포도 900ML*2", "우양 자몽맛 가나디 190ML", "이름만 있는 음료 1L"])
def test_mixed_or_opaque_titles_are_not_inferred(title):
    assert classify_record({"source_name": "homeplus", "source_category_path": ["우유/유제품", "냉장디저트/음료", "냉장주스"], "source_title": title})["unified_category_id"] is None


@pytest.mark.parametrize("mart,path", [("emart", ["우유/유제품", "냉장디저트/음료", "푸딩디저트류"]), ("homeplus", ["우유/유제품"])])
def test_exact_mart_and_full_shelf_required(mart, path):
    assert classify_record({"source_name": mart, "source_category_path": path, "source_title": "MDS 망고 푸딩 1KG"})["unified_category_id"] is None
