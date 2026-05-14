from __future__ import annotations

from services.seed_taxonomy import get_category_display_label, normalize_category_id


def test_seed_taxonomy_display_labels_are_korean_for_safe_dot_ids() -> None:
    assert get_category_display_label("prepared_food.meal_kit") == "밀키트/델리"
    assert get_category_display_label("seafood.frozen") == "수산/냉동"


def test_seed_taxonomy_preserves_safe_internal_ids_before_family_rules() -> None:
    assert normalize_category_id("vegetable.cabbage") == "vegetable.cabbage"
    assert get_category_display_label("vegetable.cabbage") == "채소/양배추"
    assert normalize_category_id("prepared_food.meal_kit") == "prepared_food.meal_kit"
    assert get_category_display_label("prepared_food.meal_kit") == "밀키트/델리"


def test_seed_taxonomy_normalizes_common_korean_ai_category_strings() -> None:
    assert normalize_category_id("밀키트/델리") == "prepared_food.meal_kit"
    assert normalize_category_id("수산/냉동") == "seafood.frozen"
    assert normalize_category_id("냉동 해산물") == "seafood.frozen"
    assert normalize_category_id("agriculture.tofu") == "processed.tofu.firm"
    assert normalize_category_id("agriculture.fruit.apple") == "produce.fruit"
    assert normalize_category_id("과일") == "produce.fruit"
    assert normalize_category_id("agriculture.bean.tofu") == "processed.tofu.firm"
    assert normalize_category_id("processed.noodle.ramen") == "instant.noodle"
    assert normalize_category_id("household.laundry.detergent") == "daily.detergent"
    assert normalize_category_id("agriculture.fruit.citrus") == "produce.fruit"
    assert normalize_category_id("pantry.grain.oat") == "grain.rice"
    assert normalize_category_id("processed.instant.meal_kit") == "prepared_food.meal_kit"
    assert normalize_category_id("agriculture.fruit.cherry") == "produce.fruit"
    assert normalize_category_id("agriculture.fruit.watermelon") == "produce.fruit"
    assert normalize_category_id("agriculture.leafy.cabbage") == "vegetable.cabbage"
    assert normalize_category_id("agriculture.root.onion") == "produce.vegetable"
    assert normalize_category_id("agriculture.vegetable.asparagus") == "produce.vegetable"
    assert normalize_category_id("seafood.fish.mackerel") == "seafood.fish"
    assert normalize_category_id("meat.beef.processed") == "meat.beef"
    assert normalize_category_id("agriculture.egg") == "livestock.egg"
    assert normalize_category_id("dairy.egg") == "livestock.egg"
    assert normalize_category_id("snack.chips") == "snack.chip"
    assert normalize_category_id("snack.snack") == "snack.general"
    assert normalize_category_id("snack") == "snack.general"
    assert normalize_category_id("beverage") == "beverage.general"
    assert normalize_category_id("beverage.carbonated") == "beverage.soda"
    assert normalize_category_id("bakery.bread") == "bakery.bread"
    assert normalize_category_id("seafood.shellfish") == "seafood.shellfish"
    assert normalize_category_id("household.tissue") == "household.tissue"
    assert normalize_category_id("processed.meat") == "processed.meat"
    assert normalize_category_id("processed.sauce") == "processed.sauce"


def test_seed_taxonomy_uses_family_rules_for_unseen_terms_without_snack_leakage() -> None:
    assert normalize_category_id("agriculture.fruit.자두") == "produce.fruit"
    assert normalize_category_id("agriculture.vegetable.애호박") == "produce.vegetable"
    assert normalize_category_id("seafood.fish.명태") == "seafood.fish"
    assert normalize_category_id("snack.fruit.자두젤리") == "snack.fruit.자두젤리"
