import json
from pathlib import Path
import subprocess
import sys
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import catalog_harness as h

def test_test_profile_counts_cases_failures_and_skips(tmp_path):
 path=tmp_path/'tests.xml'
 path.write_text('<testsuites><testsuite><testcase classname="module" name="a[1]" time="0.2"/><testcase classname="module" name="a[2]" time="0.3"><failure/></testcase><testcase classname="other" time="0"><skipped/></testcase></testsuite></testsuites>')
 assert h.test_profile(path)=={'module':{'cases':2,'seconds':0.5,'failures':1,'skipped':0},'other':{'cases':1,'seconds':0.0,'failures':0,'skipped':1}}

def put(path,value):
 path.parent.mkdir(parents=True,exist_ok=True)
 path.write_text(json.dumps(value),encoding='utf-8')

@pytest.fixture
def workspace(tmp_path):
 source=tmp_path/'.debug-artifacts/source/source-pending.sqlite'
 protected=tmp_path/'.walletsavior/admin.sqlite'
 for p in (source,protected):
  p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'test-only-not-a-real-database')
 baseline=tmp_path/'.debug-artifacts/baseline'
 decisions={'decisions':[{'id':i} for i in range(431)]}
 put(tmp_path/'handoff/decisions.json',decisions)
 put(baseline/'reviewed-decisions.json',decisions)
 put(baseline/'summary.json',{'build_report':{'included_observations':1,'unresolved_observations':1}})
 put(baseline/'catalog-bundle.json',bundle())
 state={'source':str(source.relative_to(tmp_path)),'protected_db':str(protected.relative_to(tmp_path)),
        'source_file_sha256':h.sha(source),'protected_db_sha256':h.sha(protected),
        'baseline':str(baseline.relative_to(tmp_path)),'decisions':'handoff/decisions.json','included':1,'unresolved':1}
 put(tmp_path/'docs/catalog-state.json',state)
 return tmp_path

def bundle(included=('a',)):
 return {'source_manifest':{'source_sha256':'same'},'observation_accounting':[
  {'raw_record_id':i,'status':'included' if i in included else 'unresolved'} for i in ('a','b')]}

@pytest.mark.parametrize('name',['../escape','initial-catalog-../../x','C:/data','initial-catalog-X','x','initial-catalog-'])
def test_invalid_output_rejected(tmp_path,name):
 with pytest.raises(ValueError):h.output_path(tmp_path,name)

def test_existing_output_rejected(tmp_path):
 out=tmp_path/'.debug-artifacts/initial-catalog-test';out.mkdir(parents=True)
 with pytest.raises(ValueError):h.output_path(tmp_path,'initial-catalog-test')

def test_operating_db_cannot_be_source(workspace):
 state=h.read(workspace/'docs/catalog-state.json');state['source']=state['protected_db']
 put(workspace/'docs/catalog-state.json',state)
 with pytest.raises(ValueError,match='allowed directory'):h.preflight(workspace)

def test_original_changes_rejected(workspace):
 (workspace/'.walletsavior/admin.sqlite').write_bytes(b'changed')
 with pytest.raises(ValueError,match='Operating DB hash'):h.preflight(workspace)

def test_missing_review_or_draft_rejected(workspace):
 (workspace/'.debug-artifacts/baseline/DO_NOT_USE.md').write_text('draft')
 with pytest.raises(ValueError,match='draft'):h.preflight(workspace)

def test_preflight_is_read_only(workspace):
 before={p:h.sha(p) for p in workspace.rglob('*') if p.is_file()}
 h.preflight(workspace)
 assert before=={p:h.sha(p) for p in workspace.rglob('*') if p.is_file()}

def test_logged_success_retains_output_without_console_dump(tmp_path,capsys):
 log=tmp_path/'success.log'
 metrics=h.execute_logged([sys.executable,'-c','print("x" * 10000)'],tmp_path,log)
 assert metrics['output_bytes']>=10000
 assert metrics['seconds']>=0
 assert capsys.readouterr().out==''

def test_logged_failure_preserves_full_log_and_bounds_tail(tmp_path,capsys):
 log=tmp_path/'failure.log'
 with pytest.raises(subprocess.CalledProcessError) as caught:
  h.execute_logged([sys.executable,'-c','print("x" * 10000); print("failure detail"); raise SystemExit(7)'],tmp_path,log)
 output=capsys.readouterr().out
 assert caught.value.returncode==7
 assert 'failure detail' in output and len(output)<=4001
 assert log.stat().st_size>10000

def test_disappearing_or_duplicate_records_rejected():
 with pytest.raises(ValueError,match='disappeared'):h.compare_bundles(bundle(),bundle(('b',)))
 bad=bundle();bad['observation_accounting'].append(bad['observation_accounting'][0])
 with pytest.raises(ValueError,match='Duplicate'):h.compare_bundles(bundle(),bad)
 assert h.compare_bundles(bundle(),bundle(('a','b')))==['b']

def test_failed_command_never_certifies(workspace,monkeypatch):
 monkeypatch.setattr(h,'code_hashes',lambda root:{'code':'same'})
 def fail(*args,**kwargs):raise subprocess.CalledProcessError(1,['test'])
 monkeypatch.setattr(h,'execute_logged',fail)
 with pytest.raises(subprocess.CalledProcessError):h.run('initial-catalog-fail',workspace)
 assert not list(workspace.rglob('checks-passed.json'))


def test_new_batch_matching_failure_blocks_certificate_after_other_checks(workspace,monkeypatch):
 monkeypatch.setattr(h,'code_hashes',lambda root:{'code':'same'})
 calls=[]
 def execute(command,*args,**kwargs):
  calls.append(command)
  if 'tools/verify_batch_runtime.py' in command:
   raise subprocess.CalledProcessError(1,command)
 monkeypatch.setattr(h,'execute_logged',execute)
 with pytest.raises(subprocess.CalledProcessError):h.run('initial-catalog-batch-fail',workspace)
 assert any('tools/verify_reviewed_runtime.py' in command for command in calls)
 assert any('packages/crawler-admin/backend/tests/test_matching_enrichment.py' in command for command in calls)
 assert calls[-1][1:]==['tools/verify_batch_runtime.py','initial-catalog-batch-fail','--save']
 assert not list(workspace.rglob('checks-passed.json'))
