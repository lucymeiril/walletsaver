import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import catalog_review as review


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
