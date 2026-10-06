import pytest
from services.initial_reviewed_chat import ROWS, reviewed_chat_leaf
from services.initial_taxonomy import classify_record, source_evidence, taxonomy_categories, validate_taxonomy

PASS43_BLOCKED = {
    # Review evidence is not authority to bypass ingredient/product conflicts.
    '070567864': 'source_title_product_type_conflict',
    # 069278314/069278268 were ingredient-name conflicts, not real oil
    # products. Pass58 exact seafood/title evidence removes only candidates
    # vetoed as oil ingredients; the ordinary accepted-leaf assertion below
    # now covers them. Valid contradictory candidates remain blocked.
}
PASS44_BLOCKED = {
    # Accepted category evidence must not suppress source/ingredient conflicts.
    **dict.fromkeys(['071390258','127465120','126296972','103790615',
                    '069739616','129622202','143580391','127144229'],
                   'conflicting_category_evidence'),
    **dict.fromkeys(['120108964','068981243','057467472','000045411'],
                   'conflicting_category_evidence'),
}
PASS45_BLOCKED = {
    # 070137671: exact numbered review now discards only the liquid-shelf
    # candidate already vetoed by the explicit capsule title. A replacement
    # test verifies the original conflict returns without that path review.
    **dict.fromkeys(['112841891','141923001','112088334',
                    '140583801','140583784','058706690','148605655','071275902'],
                   'conflicting_category_evidence'),
    '129081772':'dairy_ingredient_accessory_or_mixed_product',
}
REVIEWED_REJECTED_PATH = {
    '070031202': 'food.snacks.savory.corn',
    '070031162': 'food.snacks.savory.corn',
    '128904268': 'food.meals.prepared.soup_stew',
    '128852547': 'food.meals.prepared.soup_stew',
}

# pass171 parent-reviewed exact forms replace only these historical conflict
# expectations. The old accepted proposals and their identity tests stay intact.
REVIEWED_SEMANTIC_REVISIONS = {
    '124679799':'food.plant.drinks.almond',
    '070567864':'food.meals.noodles.naengmyeon',
    '071390258':'food.preserved.canned.tuna',
    '129622202':'food.meals.prepared.meal_kit',
    '143580391':'food.preserved.kimchi.white',
    '127144229':'food.preserved.kimchi.white',
    **dict.fromkeys(['120108964','068981243','057467472','000045411'], 'food.meals.noodles.bag_ramen'),
    '112841891':'food.plant.soy.tofu',
    '129081772':'food.dairy.yogurt.topping',
    '141923001':'food.seasonings.spices.whole_chili',
    '112088334':'food.plant.soy.silken',
    **dict.fromkeys(['140583801','140583784','058706690','148605655'], 'food.meals.rice.rice_ball'),
    '071275902':'food.meals.prepared.kimbap',
}

# Independent literal blackbean + exact soymilk-shelf corroboration replaces
# only the old blanket plant-name hold; external proposal identity stays pinned.
SOURCE_CORROBORATION_REVISIONS = dict.fromkeys(['124942580','124942505'],'food.plant.soy.soymilk')
SOURCE_CORROBORATION_REVISIONS.update({
    '069487441': 'food.snacks.savory.noodle',
    # Literal oranda refines the old generic han-gwa proposal; its identity stays pinned.
    '069487429': 'food.snacks.traditional.oranda',
    '069473198': 'food.meat.frozen.chicken',
    '071124684': 'food.meat.frozen.pork',
    '071095700': 'food.meat.frozen.pork',
    '070333761': 'food.meat.frozen.pork',
    # Literal native powder/mix shelves refine these historical tea proposals;
    # original proposal bytes and listing identity assertions stay unchanged.
    '071393848': 'food.drinks.powders.tea_mix',
    '004739183': 'food.drinks.powders.cocoa',
})

@pytest.mark.parametrize('accepted',ROWS)
def test_review_is_identity_bound_and_does_not_override_conflicts(accepted):
    row = {'source_name':accepted['mart'],'source_record_key':accepted['source_record_key'],'source_title':accepted['source_title'],'source_category_path':accepted['source_path_parts']}
    result = classify_record(row)
    if accepted['source_record_key'] in REVIEWED_SEMANTIC_REVISIONS:
        assert result['unified_category_id'] == REVIEWED_SEMANTIC_REVISIONS[accepted['source_record_key']]
        if accepted['source_record_key'] not in {'070567864','129081772'}:
            assert result['reviewed_rejected_category_ids']
    elif accepted['source_record_key'] in SOURCE_CORROBORATION_REVISIONS:
        assert result['unified_category_id'] == SOURCE_CORROBORATION_REVISIONS[accepted['source_record_key']]
        assert not result['reviewed_rejected_category_ids']
    elif accepted['source_record_key'] in PASS45_BLOCKED:
        assert result['unified_category_id'] is None
        assert result['classification_reason'] == PASS45_BLOCKED[accepted['source_record_key']]
    elif accepted['source_record_key'] in PASS44_BLOCKED:
        assert result['unified_category_id'] is None
        assert result['classification_reason'] == PASS44_BLOCKED[accepted['source_record_key']]
        if accepted['source_record_key'] in {'120108964','068981243','057467472','000045411'}:
            # The new exact-title review establishes bag ramen, while the old
            # identity-bound proposal still asserts black-bean noodles. Both
            # candidates must remain visible and conflict when that key is supplied.
            assert set(result['candidate_category_ids']) == {
                'food.meals.noodles.bag_ramen', 'food.meals.noodles.black_bean'}
    elif accepted['source_record_key'] in PASS43_BLOCKED:
        assert result['unified_category_id'] is None
        assert result['classification_reason'] == PASS43_BLOCKED[accepted['source_record_key']]
    elif accepted['leaf'].startswith('food.plant.'):
        # Existing dairy-source corroboration/conflict gates still hold these.
        assert result['unified_category_id'] is None
        assert result['classification_reason'] in ('conflicting_category_evidence','source_title_product_type_conflict','source_leaf_needs_name_corroboration')
    else:
        assert result['unified_category_id'] == accepted['leaf']
        if accepted['source_record_key'] in REVIEWED_REJECTED_PATH:
            assert result['reviewed_rejected_path_category'] == REVIEWED_REJECTED_PATH[accepted['source_record_key']]
    validate_taxonomy(taxonomy_categories({accepted['leaf']}),{accepted['leaf']})
    for changed in ({**row,'source_record_key':'not-reviewed'}, {**row,'source_title':row['source_title']+' 변경'}, {**row,'source_name':'costco'}, {**row,'source_category_path':['다른 진열']}):
        assert reviewed_chat_leaf(changed,source_evidence(changed)) is None
