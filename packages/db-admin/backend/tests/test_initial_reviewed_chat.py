import pytest
from services.initial_reviewed_chat import ROWS, reviewed_chat_leaf
from services.initial_taxonomy import classify_record, source_evidence, taxonomy_categories, validate_taxonomy


@pytest.mark.parametrize('accepted',ROWS)
def test_review_is_identity_bound_and_does_not_override_conflicts(accepted):
    row = {'source_name':accepted['mart'],'source_record_key':accepted['source_record_key'],'source_title':accepted['source_title'],'source_category_path':accepted['source_path_parts']}
    result = classify_record(row)
    if accepted['leaf'].startswith('food.plant.'):
        # Existing dairy-source corroboration/conflict gates still hold these.
        assert result['unified_category_id'] is None
        assert result['classification_reason'] in ('conflicting_category_evidence','source_title_product_type_conflict','source_leaf_needs_name_corroboration')
    else:
        assert result['unified_category_id'] == accepted['leaf']
    validate_taxonomy(taxonomy_categories({accepted['leaf']}),{accepted['leaf']})
    for changed in ({**row,'source_record_key':'not-reviewed'}, {**row,'source_title':row['source_title']+' 변경'}, {**row,'source_name':'costco'}, {**row,'source_category_path':['다른 진열']}):
        assert reviewed_chat_leaf(changed,source_evidence(changed)) is None
