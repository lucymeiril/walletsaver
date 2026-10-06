import pytest
import services.initial_numbered_reviews as numbered
from services.initial_numbered_reviews import rules, reviewed_numbered_leaf
from services.initial_taxonomy import classify_record


def test_capsule_old_conflict_requires_explicit_path_review(monkeypatch):
    raw={'source_name':'homeplus','source_record_key':'070137671',
         'source_title':'LG생활건강 피지디나자임 캡슐세제 26입',
         'source_category_path':['세탁/청소','세탁세제/섬유유연제','액체형 세제','액체 세탁세제']}
    result=classify_record(raw)
    assert result['unified_category_id']=='household.cleaning.laundry.capsule'
    assert result['reviewed_rejected_path_category']=='household.cleaning.laundry.liquid'
    monkeypatch.setattr(numbered,'path_reviews',lambda:{})
    result=classify_record(raw)
    assert result['unified_category_id'] is None
    assert result['classification_reason']=='conflicting_category_evidence'


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


# Preserve historical numbered evidence while checking reviewed storage and
# preparation forms. These are expectations, not production aliases.
REVIEWED_FORM_REVISIONS = {
    ('costco', '촉촉한 반건조 열빙어1.2kg X 2pack'): 'food.seafood.processed.semi_dried_fish',
    ('homeplus', '팔도 뽀로로 딸기맛 235ML'): 'food.drinks.flavoured.strawberry',
    ('homeplus', '그린피스 와사비스낵 380G'): 'food.snacks.savory.beans_peas',
    # Preserve the numbered draft; confirmed literal form refines its old broad leaf.
    ('costco', 'Senoble 크렘브륄레 100g x 8'): 'food.snacks.desserts.creme_brulee',
    **dict.fromkeys([
        ('costco', '호주산 냉동 LA갈비 2.5kg x 2팩'),
        ('costco', '미국산 냉동 LA꽃갈비 2.5kg x 2팩'),
        ('costco', '미국산 냉동 찜본갈비 2.5kg x 2팩'),
        ('costco', '미국산 냉동 차돌박이 1.3kg x 2팩'),
        ('costco', '미국산 냉동 칼집 포갈비 1.2kg x 2팩'),
        ('costco', '호주산 냉동 찜갈비 2.5kg x 2팩'),
        ('costco', '미국산 냉동 척아이롤 1.5kg x 2팩'),
    ], 'food.meat.frozen.beef'),
    ('costco', '이베리코 냉동 목심로스+큐브목심+배받이살 (1.5kg)'): 'food.meat.frozen.pork',
    ('emart', '[냉동] 삼겹살 바로구이 (1,000g)'): 'food.meat.frozen.pork',
    ('homeplus', '티젠 콤부차 요구르트 30T(150G)'): 'food.drinks.powders.kombucha',
}


@pytest.mark.parametrize('key,leaf', list(rules().items()))
def test_numbered_decisions_use_real_classifier_and_reject_changed_context(key,leaf):
    mart,path,title = key
    evidence = {'mart':mart,'source_path_parts':list(path),'source_title':title}
    policy = numbered.source_reviews().get(key, {})
    required = policy.get('source_urls', [])
    if required:
        assert reviewed_numbered_leaf(evidence) is None
        evidence['source_urls'] = required
        evidence['source_review_fields'] = policy['source_fields']
    assert reviewed_numbered_leaf(evidence) == leaf
    for changes in ({'mart':'wrong-mart'},{'source_path_parts':['wrong-path']},{'source_title':title+' 혼합세트'},{'source_title':title+' 변경품'}):
        assert reviewed_numbered_leaf(dict(evidence,**changes)) is None
    if leaf is not None:
        attrs = {'mart_native_category_path':' > '.join(path)}
        attrs.update(dict(zip(('canonical_url','detail_url','source_url'), required)))
        raw_fields = {field: value for field, value in policy.get('source_fields', {}).items() if not field.startswith('attributes.')}
        attrs.update({field.split('.', 1)[1]: value for field, value in policy.get('source_fields', {}).items() if field.startswith('attributes.')})
        result=classify_record({'mart':mart,'name':title,'attributes':attrs, **raw_fields})
        assert result['unified_category_id'] == REVIEWED_FORM_REVISIONS.get((mart, title), leaf)


def test_source_bound_review_requires_complete_evidence_without_changing_ordinary_reviews(monkeypatch):
    key = ('emart', ('과자/간식',), '검토된 상품 100g')
    ordinary = ('emart', ('과자/간식',), '기존 상품 100g')
    url = 'https://retailer.example/product/1'
    leaf = 'food.snacks.savory.potato'
    monkeypatch.setattr(numbered, 'rules', lambda: {key: leaf, ordinary: leaf})
    monkeypatch.setattr(numbered, 'source_reviews', lambda: {key: {'source_urls': [url], 'source_fields': {}}})
    evidence = dict(mart=key[0], source_path_parts=list(key[1]), source_title=key[2])
    for urls in ([], [url + '?changed'], [url, 'https://retailer.example/product/2']):
        assert reviewed_numbered_leaf(dict(evidence, source_urls=urls)) is None
    assert reviewed_numbered_leaf(dict(evidence, source_urls=[url, url])) == leaf
    assert reviewed_numbered_leaf(dict(evidence, source_title=ordinary[2])) == leaf
