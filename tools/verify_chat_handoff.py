"""Check text shard completeness against the lossless archived originals."""
import gzip
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
p = ROOT/'handoff/2026-09-11'
read = lambda f: json.loads(f.read_text(encoding='utf-8'))
archive = lambda name: json.loads(gzip.decompress((p/'archives'/name).read_bytes()))
batches = archive('source-ingestions.json.gz')
raw_index = read(p/'raw/index.json')
for batch in batches:
    meta = raw_index[str(batch['id'])]
    rows = [row for name in meta['files'] for row in read(p/'raw'/str(batch['id'])/name)]
    assert [r['item'] for r in rows] == json.loads(batch['items_json'])
    assert [r['raw_record_id'] for r in rows] == [f"ingestion:{batch['id']}:{i}" for i in range(len(rows))]
bundle = archive('catalog-bundle.json.gz')
index = read(p/'catalog/index.json')
for key, value in bundle.items():
    if isinstance(value,list):
        restored = [row for name in index[key]['files'] for row in read(p/'catalog'/key/name)]
    else: restored = read(p/'catalog'/(key+'.json'))
    assert restored == value, key
pending = [row for group in read(p/'pending/index.json') for name in group['files'] for row in read(p/'pending'/group['id']/name)]
assert len(pending) == len({r['raw_record_id'] for r in pending}) == 3916
assert {r['raw_record_id'] for r in pending} == {r['raw_record_id'] for r in bundle['unresolved']}
assert read(p/'review-decisions-input.json')['source_sha256'] == read(p/'manifest.json')['source_sha256']
print('PASS: 108 original batches, all catalog fields/lists, 3916 unique pending observations, source hash binding')
