"""Publish compact reproducible audit evidence, without claims of full semantic review."""
import hashlib
from collections import defaultdict
from audit_pass43_proposals import audit,ROOT
from build_chat_handoff import write_json

summary,records,raw=audit()
grouped=defaultdict(list)
for r in records:
    d=r['decision']
    if d['decision']=='existing_leaf':
        grouped[(raw[d['raw_record_ids'][0]]['classification']['mart'],d['unified_category_id'])].append(r)
samples=[]
for key,rs in sorted(grouped.items()):
    samples.extend(sorted(rs,key=lambda r:hashlib.sha256('|'.join(r['decision']['raw_record_ids']).encode()).hexdigest())[:2])
write_json(ROOT/'handoff/2026-09-12-pass44/external-review.json',{
    'remote_commit':'afcc97a','summary':summary,'sampling':'SHA256(raw_record_ids), first two per original mart/leaf',
    'semantic_samples':samples,'identity_errors':[r for r in records if set(r['flags'])-{'missing_mart'}],
    'limitations':'Nested ID-free group112-116 excluded; missing mart recovered from originals only after exact identity checks; not full semantic approval; needs_review and deferred forms not promoted.'})
print('Published',len(samples),'deterministic sample entries and structural errors')
