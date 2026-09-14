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
                    '070031202','070031162','069739616','129622202',
                    '128904268','128852547','143580391','127144229'],
                   'conflicting_category_evidence'),
    **dict.fromkeys(['120108964','068981243','057467472','000045411'],
                   'source_leaf_needs_name_corroboration'),
}
PASS45_BLOCKED = {
    **dict.fromkeys(['112841891','070137671','141923001','112088334',
                    '140583801','140583784','058706690','148605655','071275902'],
                   'conflicting_category_evidence'),
    '129081772':'dairy_ingredient_accessory_or_mixed_product',
}

@pytest.mark.parametrize('accepted',ROWS)
def test_review_is_identity_bound_and_does_not_override_conflicts(accepted):
    row = {'source_name':accepted['mart'],'source_record_key':accepted['source_record_key'],'source_title':accepted['source_title'],'source_category_path':accepted['source_path_parts']}
    result = classify_record(row)
    if accepted['source_record_key'] in PASS45_BLOCKED:
        assert result['unified_category_id'] is None
        assert result['classification_reason'] == PASS45_BLOCKED[accepted['source_record_key']]
    elif accepted['source_record_key'] in PASS44_BLOCKED:
        assert result['unified_category_id'] is None
        assert result['classification_reason'] == PASS44_BLOCKED[accepted['source_record_key']]
    elif accepted['source_record_key'] in PASS43_BLOCKED:
        assert result['unified_category_id'] is None
        assert result['classification_reason'] == PASS43_BLOCKED[accepted['source_record_key']]
    elif accepted['leaf'].startswith('food.plant.'):
        # Existing dairy-source corroboration/conflict gates still hold these.
        assert result['unified_category_id'] is None
        assert result['classification_reason'] in ('conflicting_category_evidence','source_title_product_type_conflict','source_leaf_needs_name_corroboration')
    else:
        assert result['unified_category_id'] == accepted['leaf']
    validate_taxonomy(taxonomy_categories({accepted['leaf']}),{accepted['leaf']})
    for changed in ({**row,'source_record_key':'not-reviewed'}, {**row,'source_title':row['source_title']+' 변경'}, {**row,'source_name':'costco'}, {**row,'source_category_path':['다른 진열']}):
        assert reviewed_chat_leaf(changed,source_evidence(changed)) is None
