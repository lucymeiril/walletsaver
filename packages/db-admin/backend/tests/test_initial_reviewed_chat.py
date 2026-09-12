import pytest
from services.initial_reviewed_chat import ROWS, reviewed_chat_leaf
from services.initial_taxonomy import classify_record, source_evidence, taxonomy_categories, validate_taxonomy

PASS43_BLOCKED = {
    # Review evidence is not authority to bypass ingredient/product conflicts.
    '070567864': 'source_title_product_type_conflict',
    '069278314': 'conflicting_category_evidence',
    '069278268': 'conflicting_category_evidence',
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

@pytest.mark.parametrize('accepted',ROWS)
def test_review_is_identity_bound_and_does_not_override_conflicts(accepted):
    row = {'source_name':accepted['mart'],'source_record_key':accepted['source_record_key'],'source_title':accepted['source_title'],'source_category_path':accepted['source_path_parts']}
    result = classify_record(row)
    if accepted['source_record_key'] in PASS44_BLOCKED:
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
