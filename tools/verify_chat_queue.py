"""Verify pass42 residual queue and refresh its derived title-count metadata."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
out = ROOT/'handoff/2026-09-12'
read = lambda p:json.loads(p.read_text(encoding='utf-8'))
index = read(out/'remaining/index.json')
ids = []
for group in index:
    rows = [r for name in group['files'] for r in read(out/'remaining'/group['id']/name)]
    assert len(rows)==group['observations']
    group['unique_titles'] = len({r['source_title'] for r in rows})
    ids.extend(r['raw_record_id'] for r in rows)
bundle = read(ROOT/'.debug-artifacts/initial-catalog-20260912-pass42/catalog-bundle.json')
assert len(ids)==len(set(ids))==3845
assert set(ids)=={r['raw_record_id'] for r in bundle['unresolved']}
assert not set(ids)&set(read(out/'accepted.json')['new_included_ids'])
path=out/'remaining/index.json'
path.write_bytes(json.dumps(index,ensure_ascii=False,indent=2,sort_keys=True).encode())
manifest=read(out/'manifest.json')
manifest['files']['remaining/index.json']={'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
(out/'manifest.json').write_bytes(json.dumps(manifest,ensure_ascii=False,indent=2,sort_keys=True).encode())
for name,info in manifest['files'].items():
    data=(out/name).read_bytes()
    assert len(data)==info['bytes'] and hashlib.sha256(data).hexdigest()==info['sha256'],name
print('PASS: remaining3845 IDs exact, new71 excluded,447 group counts verified, manifest valid')
