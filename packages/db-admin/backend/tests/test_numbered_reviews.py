import pytest
import services.initial_numbered_reviews as numbered
from services.initial_numbered_reviews import rules, reviewed_numbered_leaf
from services.initial_taxonomy import classify_record


def test_path_review_discards_only_vetoed_path_not_other_evidence(monkeypatch):
    import services.initial_taxonomy as taxonomy
    title='슈가버블 구연산 리필 1KG'
    path=['세탁/청소','주방/청소용 세제','변기/싱크/배수구용','욕실세정제']
    key=('homeplus',tuple(path),title)
    rejected='household.cleaning.bath.cleaner'
    target='household.cleaning.general.citric_acid'
    monkeypatch.setattr(numbered,'rules',lambda:{key:target})
    monkeypatch.setattr(numbered,'path_reviews',lambda:{key:rejected})
    raw=dict(source_name='homeplus',source_title=title,source_category_path=path)
    assert classify_record(raw)['unified_category_id']==target
    for changed in (dict(raw,source_name='costco'),dict(raw,source_category_path=path[:-1]),dict(raw,source_title=title+' 혼합세트')):
        result=classify_record(changed)
        assert result['unified_category_id']!=target
    with monkeypatch.context() as scoped:
        scoped.setattr(taxonomy,'_suspicion_reason',lambda category,evidence:None)
        assert classify_record(raw)['classification_reason']=='conflicting_category_evidence'
    for helper,value in (('_name_candidates',{rejected}),('_url_candidates',({rejected},[]))):
        with monkeypatch.context() as scoped:
            scoped.setattr(taxonomy,helper,lambda *args:value)
            assert classify_record(raw)['classification_reason']=='conflicting_category_evidence'


def test_numbered_loader_connects_to_classifier_and_preserves_conflicts(monkeypatch):
    key=('emart',('과자/간식',),'회귀검사용 감자칩 100g')
    monkeypatch.setattr(numbered,'rules',lambda:{key:'food.snacks.savory.potato'})
    raw={'mart':'emart','name':key[2],'attributes':{'mart_native_category_path':'과자/간식'}}
    assert classify_record(raw)['unified_category_id']=='food.snacks.savory.potato'
    assert numbered.reviewed_numbered_leaf({'mart':'emart','source_path_parts':['과자/간식'],'source_title':key[2]+' 혼합세트'}) is None


@pytest.mark.parametrize('key,leaf', list(rules().items()))
def test_numbered_decisions_use_real_classifier_and_reject_changed_context(key,leaf):
    mart,path,title = key
    evidence = {'mart':mart,'source_path_parts':list(path),'source_title':title}
    assert reviewed_numbered_leaf(evidence) == leaf
    for changes in ({'mart':'wrong-mart'},{'source_path_parts':['wrong-path']},{'source_title':title+' 혼합세트'},{'source_title':title+' 변경품'}):
        assert reviewed_numbered_leaf(dict(evidence,**changes)) is None
    if leaf is not None:
        result=classify_record({'mart':mart,'name':title,'attributes':{'mart_native_category_path':' > '.join(path)}})
        assert result['unified_category_id'] == leaf
