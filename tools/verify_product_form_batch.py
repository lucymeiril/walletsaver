"""Verify a form-rule rebuild against pass45 and record its small delta.

Reads only already-built JSON and hashes source files; never opens operating DB.
"""
import hashlib
import json
from pathlib import Path
from collections import Counter

ROOT=Path(__file__).resolve().parents[1]
OLD=ROOT/'.debug-artifacts/initial-catalog-20260914-pass45'
NEW=ROOT/'.debug-artifacts/initial-catalog-20260914-pass46-final'
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
old,new=read(OLD/'catalog-bundle.json'),read(NEW/'catalog-bundle.json')
included=lambda b:{r['raw_record_id'] for r in b['observation_accounting'] if r['status']=='included'}
assert included(old)<=included(new)
assert read(OLD/'reviewed-decisions.json')==read(NEW/'reviewed-decisions.json')
assert read(OLD/'summary.json')['source_sha256']==read(NEW/'summary.json')['source_sha256']
assert sha(ROOT/'.walletsavior/admin.sqlite')=='ef1dbdae18c371ae9402202e2fee9be2396e7c9a6807f6e8e47eaded0908b0d2'
assert sha(ROOT/'.debug-artifacts/handoff-roundtrip-20260911/source-pending.sqlite')=='1406daf131add703d5dac0021d9c6f5194823ad59aef66bd3869f402907bf7e5'
added=sorted(included(new)-included(old))
delta={'baseline':'pass45','stage':'initial-catalog-20260914-pass46-final',
       'new_included_ids':added,'included':len(included(new)),'unresolved':len(new['unresolved']),
       'original_db_bytes_unchanged':True,'restored_source_bytes_unchanged':True,
       'prior_included_retained':True,'explicit_431_decisions_retained':True}
(NEW/'verified-delta.json').write_text(json.dumps(delta,ensure_ascii=False,indent=2),encoding='utf-8')
print({k:v for k,v in delta.items() if k!='new_included_ids'},'added',len(added))
