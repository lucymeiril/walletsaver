"""Guarded local catalog run. No arbitrary input DB, overwrite or publication.

This is not a security sandbox. A process with filesystem access can bypass it.
Only the final certificate records a successfully verified build.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
TESTS=[
 'packages/shared/tests/test_product_units.py',
 'packages/db-admin/backend/tests/test_initial_catalog_seed.py',
 'packages/db-admin/backend/tests/test_initial_product_forms.py',
 'packages/db-admin/backend/tests/test_initial_taxonomy.py',
 'packages/db-admin/backend/tests/test_initial_reviewed_chat.py',
 'tools/tests/test_catalog_harness.py',
]

def read(path):return json.loads(path.read_text(encoding='utf-8'))
def sha(path):
 with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def require(ok,message):
 if not ok:raise ValueError(message)

def safe_path(root,relative,prefix):
 raw=Path(relative)
 require(not raw.is_absolute() and '..' not in raw.parts,'Relative contained path required')
 p=(root/raw).resolve()
 allowed=(root/prefix).resolve()
 require(allowed.is_relative_to(root.resolve()),'Escaping root/symlink')
 require(p.is_relative_to(allowed) and p!=allowed,'Path outside allowed directory')
 return p

def preflight(root=ROOT):
 root=root.resolve();state=read(root/'docs/catalog-state.json')
 source=safe_path(root,state['source'],'.debug-artifacts')
 baseline=safe_path(root,state['baseline'],'.debug-artifacts')
 protected=safe_path(root,state['protected_db'],'.walletsavior')
 decisions=safe_path(root,state['decisions'],'handoff')
 require(source.is_file() and baseline.is_dir(),'Missing restored source or baseline; do not use operating DB as fallback')
 require(not (baseline/'DO_NOT_USE.md').exists(),'Invalid draft baseline')
 require(sha(source)==state['source_file_sha256'],'Restored source hash changed')
 require(sha(protected)==state['protected_db_sha256'],'Operating DB hash changed; investigate, do not reset hash silently')
 doc=read(decisions)
 require(len(doc['decisions'])==431,'Missing explicit decisions')
 require(doc==read(baseline/'reviewed-decisions.json'),'Explicit decisions differ from baseline')
 summary=read(baseline/'summary.json')
 require(summary['build_report']['included_observations']==state['included'],'Stale baseline count')
 require(summary['build_report']['unresolved_observations']==state['unresolved'],'Stale pending count')
 return state,source,baseline,protected,decisions

def output_path(root,run_id):
 require(bool(re.fullmatch(r'initial-catalog-[a-z0-9][a-z0-9-]{0,95}',run_id)),'Invalid run ID')
 out=safe_path(root,'.debug-artifacts/'+run_id,'.debug-artifacts')
 require(not out.exists(),'Run exists: never overwrite or silently resume a partial build')
 return out

def compare_bundles(old,new):
 def accounting(b):
  rows=b['observation_accounting'];ids=[r['raw_record_id'] for r in rows]
  require(len(ids)==len(set(ids)),'Duplicate raw accounting IDs')
  return set(ids),{r['raw_record_id'] for r in rows if r['status']=='included'}
 old_all,old_ids=accounting(old);new_all,new_ids=accounting(new)
 require(old_all==new_all,'Original observation universe changed')
 require(old_ids<=new_ids,'Previously included records disappeared')
 require(old['source_manifest']['source_sha256']==new['source_manifest']['source_sha256'],'Source snapshot changed')
 return sorted(new_ids-old_ids)

def code_hashes(root):
 paths=list((root/'packages/db-admin/backend/services').glob('*.py'))
 paths+=list((root/'packages/shared').rglob('*.py'))
 paths+=list((root/'packages/db-admin/backend/services').glob('reviewed_chat_batch*.json'))
 paths += [root/'tools'/name for name in ('catalog_harness.py','prepare_initial_catalog.py','verify_initial_stage.py','verify_reviewed_runtime.py','verify_batch_runtime.py')]
 paths += [root/'packages/crawler-admin/backend/services/matching_enrichment.py', root/'packages/crawler-admin/backend/tests/test_matching_enrichment.py']
 paths += [root/p for p in TESTS]+[root/'docs/catalog-state.json']
 return {str(p.relative_to(root)):sha(p) for p in sorted(paths)}

def execute_logged(command,root,log):
 """Keep complete diagnostics on disk and bound console output."""
 started=time.monotonic()
 with log.open('x',encoding='utf-8') as stream:
  result=subprocess.run(command,cwd=root,stdout=stream,stderr=subprocess.STDOUT)
 if result.returncode:
  from collections import deque
  with log.open(encoding='utf-8',errors='replace') as stream:
   print(''.join(deque(stream,maxlen=25))[-4000:],flush=True)
  raise subprocess.CalledProcessError(result.returncode,command)
 return {'seconds':round(time.monotonic()-started,2),'output_bytes':log.stat().st_size,'log':str(log.relative_to(root))}

def run(run_id,root=ROOT):
 state,source,baseline,protected,decisions=preflight(root)
 out=output_path(root,run_id);fingerprints=code_hashes(root)
 log_dir=safe_path(root,'.debug-artifacts/catalog-logs/'+run_id,'.debug-artifacts')
 log_dir.mkdir(parents=True,exist_ok=False)
 commands=[
  [sys.executable,'-m','pytest',*TESTS,'-q','--disable-warnings','--tb=short'],
  [sys.executable,'-m','pytest','packages/crawler-admin/backend/tests/test_matching_enrichment.py','-q','--disable-warnings','--tb=short'],
  [sys.executable,'tools/prepare_initial_catalog.py','--db',str(source),'--out',str(out),'--run-id',run_id,'--review-decisions',str(decisions)],
  [sys.executable,'tools/verify_initial_stage.py',run_id],
  [sys.executable,'tools/verify_reviewed_runtime.py',run_id],
  [sys.executable,'tools/verify_batch_runtime.py',run_id,'--save'],
 ]
 try:
  metrics=[]
  for index,command in enumerate(commands,1):
   log=log_dir/f'{index:02d}.log'
   print(f'STEP {index}/{len(commands)} log={log.relative_to(root)}',flush=True)
   metrics.append(execute_logged(command,root,log))
  preflight(root)
  require(code_hashes(root)==fingerprints,'Code changed during run; results are stale')
  new=read(out/'catalog-bundle.json');old=read(baseline/'catalog-bundle.json')
  added=compare_bundles(old,new)
  require(read(out/'reviewed-decisions.json')==read(decisions),'Review decisions changed during build')
  summary=read(out/'summary.json')
  require(summary['rehearsal']['validation']['ok'],'Import validation failed')
  require(summary['rehearsal']['second_idempotent'],'Retry is not idempotent')
  require(not summary['public_approval'],'Unexpected public approval')
  certificate={'status':'checks_passed_not_published','baseline':state['baseline'],
   'run_id':run_id,'new_included_ids':added,'build_report':summary['build_report'],
   'code_sha256':fingerprints,'bundle_sha256':sha(out/'catalog-bundle.json'),
   'staging_sha256':sha(out/'staging.sqlite'),'commands':commands,'execution_metrics':metrics}
  # Exclusive create: a successful certificate must never be overwritten.
  with (out/'checks-passed.json').open('x',encoding='utf-8') as f:json.dump(certificate,f,ensure_ascii=False,indent=2)
  report=summary['build_report'];runtime=read(out/'batch-runtime-check.json')
  counts=report['entity_counts'];old_counts=old['build_report']['entity_counts']
  print(json.dumps({'status':'passed','run_id':run_id,'added_observations':len(added),
   'added_products':counts['products']-old_counts['products'],
   'added_listings':counts['source_listings']-old_counts['source_listings'],
   'included':report['included_observations'],'unresolved':report['unresolved_observations'],
   'runtime':runtime,'logs':str(log_dir.relative_to(root))},ensure_ascii=False))
 finally:
  require(sha(source)==state['source_file_sha256'],'SOURCE CHANGED DURING RUN')
  require(sha(protected)==state['protected_db_sha256'],'OPERATING DB CHANGED DURING RUN')

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('action',choices=['preflight','run'])
 parser.add_argument('--run-id')
 args=parser.parse_args()
 if args.action=='preflight':
  state,*_=preflight();print('PREFLIGHT PASSED',state['baseline'],state['included'],state['unresolved'])
 else:
  require(bool(args.run_id),'--run-id required');run(args.run_id)

if __name__=='__main__':main()
