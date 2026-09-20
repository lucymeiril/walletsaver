import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path[:0]=[str(Path(__file__).resolve().parents[2]/p) for p in ('packages/shared','packages/db-admin/backend')]
import catalog_review as review


def test_proposal_hash_dry_run_apply_and_duplicate_keys(tmp_path,monkeypatch):
    path=review.named(tmp_path,'sample','.debug-artifacts/review-proposals')
    review.write_new(path,{'packet_sha256':'a'*64,'assignments':{'leaf':[1]},'holds':{'unclear':[2]}})
    calls=[]
    monkeypatch.setattr(review,'decide',lambda *args,**kwargs:calls.append((args,kwargs)))
    with pytest.raises(ValueError,match='hash changed'): review.proposal('sample','bad',root=tmp_path)
    assert not calls
    review.proposal('sample',review.sha(path),root=tmp_path)
    assert calls[-1][0][2:4]==(['leaf=1'],['unclear=2'])
    assert calls[-1][1]['apply'] is False
    review.proposal('sample',review.sha(path),True,tmp_path)
    assert calls[-1][1]['apply'] is True
    path.write_text('{"assignments":{},"assignments":{}}',encoding='utf-8')
    with pytest.raises(ValueError,match='Duplicate JSON key'): review.proposal('sample',review.sha(path),root=tmp_path)


@pytest.mark.parametrize('groups',[{'leaf':[True]},{'leaf':['1']},{'leaf':[]},{'bad=label':[1]},[]])
def test_proposal_rejects_coercible_or_ambiguous_numbers(groups):
    with pytest.raises(ValueError):
        review.proposal_specs({'packet_sha256':'a'*64,'assignments':groups,'holds':{}})


def test_draft_revision_requires_explicit_current_baseline_and_cannot_bypass_certified_hash():
    state={'baseline':'current'}
    review.revision_input_allowed(None,'hash',state,state,True)
    review.revision_input_allowed('hash','hash',{},state,False)
    for args in [(None,'hash',state,state,False),(None,'hash',{'baseline':'old'},state,True),('old','hash',state,state,True)]:
        with pytest.raises(ValueError): review.revision_input_allowed(*args)


def test_path_revision_requires_current_certified_hash(tmp_path,monkeypatch):
    baseline=tmp_path/'baseline';baseline.mkdir()
    monkeypatch.setattr(review,'preflight',lambda root:({},None,baseline,None,None))
    path=review.named(tmp_path,'sample',review.REVIEWS)
    review.write_new(path,{'rows':[]})
    review.write_new(baseline/'checks-passed.json',{'code_sha256':{}})
    with pytest.raises(ValueError,match='Rule file changed'):
        review.revise_path('sample','wrong','leaf','reason',[],tmp_path)
    with pytest.raises(ValueError,match='currently certified'):
        review.revise_path('sample',review.sha(path),'leaf','reason',[],tmp_path)


def test_shelves_count_titles_exclude_reviewed_and_filter():
    def row(rid,title='same',mart='emart',leaf=None):
        return dict(raw_record_id=rid,source_title=title,mart=mart,source_path='생활용품',unified_category_id=leaf)
    rows=[row('a'),row('b'),row('held','hold'),row('done',leaf='leaf'),row('other',mart='costco')]
    assert review.shelf_counts(rows,{'held'},'emart','생활')==[dict(mart='emart',shelf='생활용품',unique=1,observations=2)]
    assert review.shelf_counts(rows,set(),contains='없는경로')==[]


def test_checkpoint_repeat_and_note_update_preserve_backups(tmp_path,monkeypatch):
    docs=tmp_path/'docs'; docs.mkdir()
    state={'baseline':'old'}
    (docs/'catalog-state.json').write_text(json.dumps(state))
    (docs/'RESUME_CHECKPOINT.md').write_text('old')
    monkeypatch.setattr(review,'preflight',lambda root:(review.read(docs/'catalog-state.json'),None,None,None,None))
    state_key=str(Path('docs/catalog-state.json'))
    monkeypatch.setattr(review,'code_hashes',lambda root:{state_key:review.sha(docs/'catalog-state.json')})
    out=tmp_path/'.debug-artifacts/run';out.mkdir(parents=True)
    (out/'catalog-bundle.json').write_text('{}');(out/'staging.sqlite').write_bytes(b'fixture')
    review.write_new(out/'checks-passed.json',dict(status='checks_passed_not_published',baseline='old',code_sha256=review.code_hashes(tmp_path),bundle_sha256=review.sha(out/'catalog-bundle.json'),staging_sha256=review.sha(out/'staging.sqlite'),new_included_ids=['a'],build_report=dict(included_observations=1,unresolved_observations=2,entity_counts=dict(products=1,source_listings=1))))
    review.checkpoint('run','next',tmp_path)
    review.checkpoint('run','next',tmp_path)
    assert len(list((tmp_path/'.debug-artifacts/checkpoint-backups').iterdir()))==1
    review.checkpoint('run','revised',tmp_path)
    assert len(list((tmp_path/'.debug-artifacts/checkpoint-backups').iterdir()))==2
    assert review.read(docs/'catalog-state.json')['next_task']=='revised'
    (out/'staging.sqlite').write_bytes(b'changed')
    with pytest.raises(ValueError,match='Staging changed'): review.checkpoint('run','revised',tmp_path)


def test_observation_report_does_not_join_same_title_or_infer_reason():
    rows=[{'number':1,'raw_record_ids':['a','b'],'hold_reason':''},{'number':2,'raw_record_ids':['missing']}]
    decisions=[{'raw_record_id':'a','source_title':'same','unified_category_id':'leaf'}, {'raw_record_id':'b','source_title':'same','unified_category_id':None}]
    bundle={'observation_accounting':[{'raw_record_id':'a','status':'included','offer_state':'pending_review','reasons':[]},{'raw_record_id':'b','status':'unresolved','reasons':['unit_unresolved']}], 'review_issues':[{'raw_record_ids':['a'],'reasons':['promotion_unresolved']}]}
    result=review.observation_results(rows,decisions,bundle)
    assert result[0]['leaf']=='leaf' and result[0]['reasons']==['promotion_unresolved']
    assert result[1]['leaf'] is None and result[1]['reasons']==['unit_unresolved']
    assert result[2]['status']=='missing' and result[2]['reasons']==[]


def test_contract_references_identify_exact_titles_without_classifying(tmp_path):
    path=tmp_path/'packages/db-admin/backend/tests/test_initial_example.py'
    path.parent.mkdir(parents=True)
    path.write_text('# 동일상품 100g\n# 다른상품\n',encoding='utf-8')
    refs=review.contract_references([{'number':3,'source_title':'동일상품 100g'},{'number':4,'source_title':'동일상품 200g'}],tmp_path)
    assert refs==[{'numbers':[3],'file':path.relative_to(tmp_path).as_posix(),'line':1}]


def test_number_decisions_require_complete_unique_coverage():
    assert review.parse_assignments(['leaf=1,2'],['unclear=3'],3)=={1:('leaf',''),2:('leaf',''),3:(None,'unclear')}
    for sets,holds in [(['leaf=1'],[]),(['leaf=1,1'],[]),(['leaf=0,2'],[]),([],['=1,2'])]:
        with pytest.raises(ValueError): review.parse_assignments(sets,holds,2)


def test_packets_never_overwrite_and_reject_path_escape(tmp_path):
    with pytest.raises(ValueError): review.named(tmp_path,'../escape','.debug-artifacts')
    path=review.named(tmp_path,'sample','.debug-artifacts')
    review.write_new(path,{'a':1})
    with pytest.raises(FileExistsError): review.write_new(path,{'a':2})
    assert json.loads(path.read_text())=={'a':1}


def test_stale_packet_fails_before_any_rule_write(tmp_path,monkeypatch):
    baseline=tmp_path/'baseline';baseline.mkdir()
    monkeypatch.setattr(review,'preflight',lambda root:({'baseline':'current','source_file_sha256':'source'},None,baseline,None,None))
    path=review.named(tmp_path,'sample','.debug-artifacts/review-packets')
    review.write_new(path,{'baseline':'old','source_file_sha256':'source','rows':[]})
    with pytest.raises(ValueError,match='hash'):review.decide('sample','wrong',[],[],tmp_path)
    with pytest.raises(ValueError,match='Stale'):review.decide('sample',review.sha(path),[],[],tmp_path)
    assert not (tmp_path/review.REVIEWS).exists()


def test_prepare_decide_roundtrip_copies_context_and_skips_holds(tmp_path,monkeypatch):
    baseline=tmp_path/'baseline';baseline.mkdir()
    row={'raw_record_id':'r1','mart':'emart','source_path':'과자/간식','source_path_parts':['과자/간식'],'source_title':'회귀검사용 감자칩 100g','unified_category_id':None}
    (baseline/'classification-decisions.json').write_text(json.dumps([row]),encoding='utf-8')
    state={'baseline':'baseline','source_file_sha256':'source'}
    monkeypatch.setattr(review,'preflight',lambda root:(state,None,baseline,None,None))
    review.prepare('sample','emart','과자/간식',tmp_path)
    packet=review.named(tmp_path,'sample','.debug-artifacts/review-packets')
    review.decide('sample',review.sha(packet),[],['inspect=1'],tmp_path,apply=False)
    assert not (tmp_path/review.REVIEWS/'sample.json').exists()
    review.decide('sample',review.sha(packet),[],['inspect=1'],tmp_path)
    saved=review.read(tmp_path/review.REVIEWS/'sample.json')['rows'][0]
    assert saved['source_title']==row['source_title'] and saved['raw_record_ids']==['r1']
    assert saved['source_row_sha256']=={'r1':review.digest(row)}
    assert saved['leaf'] is None and saved['hold_reason']=='inspect'
    with pytest.raises(ValueError,match='No unreviewed'): review.prepare('second','emart','과자/간식',tmp_path)


def test_checkpoint_rejects_changed_code_before_document_update(tmp_path,monkeypatch):
    state={'baseline':'old'}
    monkeypatch.setattr(review,'preflight',lambda root:(state,None,None,None,None))
    monkeypatch.setattr(review,'code_hashes',lambda root:{'code':'new'})
    out=tmp_path/'.debug-artifacts/run';out.mkdir(parents=True)
    review.write_new(out/'checks-passed.json',{'status':'checks_passed_not_published','baseline':'old','code_sha256':{'code':'old'}})
    with pytest.raises(ValueError,match='Code changed'): review.checkpoint('run','next',tmp_path)
    assert not (tmp_path/'docs').exists()


def test_hold_draft_preserves_backup_and_rejects_certified_file(tmp_path,monkeypatch):
    baseline=tmp_path/'baseline';baseline.mkdir()
    monkeypatch.setattr(review,'preflight',lambda root:({'baseline':'baseline'},None,baseline,None,None))
    certificate=baseline/'checks-passed.json'
    review.write_new(certificate,{'code_sha256':{}})
    path=review.named(tmp_path,'sample',review.REVIEWS)
    original={'baseline':'baseline','rows':[{'number':1,'leaf':'leaf','hold_reason':''}]}
    review.write_new(path,original)
    old_hash=review.sha(path)
    with pytest.raises(ValueError,match='Unknown'):review.hold_draft('sample',old_hash,'2','reason',tmp_path)
    review.hold_draft('sample',old_hash,'1','conflict',tmp_path)
    assert review.read(path)['rows'][0]['leaf'] is None
    backups=list((tmp_path/'.debug-artifacts/review-revisions').glob('*.json'))
    assert len(backups)==1 and review.read(backups[0])==original
    certificate.write_text(json.dumps({'code_sha256':{path.relative_to(tmp_path).as_posix():'hash'}}))
    with pytest.raises(ValueError,match='Certified'):review.hold_draft('sample',review.sha(path),'1','reason',tmp_path)
