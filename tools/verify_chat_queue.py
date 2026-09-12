"""Read-only verification of a residual queue against its exact build."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--out', default='handoff/2026-09-12')
parser.add_argument('--stage', default='.debug-artifacts/initial-catalog-20260912-pass42')
args = parser.parse_args()
out = ROOT/args.out
read = lambda p:json.loads(p.read_text(encoding='utf-8'))
index = read(out/'remaining/index.json')
ids = []
for group in index:
    rows = [r for name in group['files'] for r in read(out/'remaining'/group['id']/name)]
    assert len(rows)==group['observations']
    assert group['unique_titles'] == len({r['source_title'] for r in rows})
    ids.extend(r['raw_record_id'] for r in rows)
bundle = read(ROOT/args.stage/'catalog-bundle.json')
manifest=read(out/'manifest.json')
assert len(ids)==len(set(ids))==manifest['pending']
assert set(ids)=={r['raw_record_id'] for r in bundle['unresolved']}
assert not set(ids)&set(read(out/'accepted.json')['new_included_ids'])
for name,info in manifest['files'].items():
    data=(out/name).read_bytes()
    assert len(data)==info['bytes'] and hashlib.sha256(data).hexdigest()==info['sha256'],name
print('PASS:',len(ids),'remaining IDs exact;',len(index),'group counts verified; manifest valid')
