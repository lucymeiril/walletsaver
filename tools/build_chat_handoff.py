"""Package only reviewed catalog data for a public GitHub handoff.

Never copies the live admin/account DB. Builds a pending-only source database.
New destination required; payloads are scanned before publication.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
import gzip
import gc
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'packages/shared'), str(ROOT/'packages/db-admin/backend')]
from services.initial_catalog_workspace import read_pending_source
from services.initial_catalog_seed import normalize_pending_ingestions

SUSPICIOUS = re.compile(r'password|passwd|secret|access.?token|refresh.?token|authorization|cookie|api.?key|email|phone', re.I)
SECRET_VALUE = re.compile(r'gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-(?:proj-)?[A-Za-z0-9_-]{30,}|-----BEGIN .*PRIVATE KEY-----|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')


def scan(value, path='root'):
    if isinstance(value, dict):
        for key, item in value.items():
            if SUSPICIOUS.search(key) and item not in (None, '', [], {}):
                raise ValueError('Potential private field at ' + path + '/' + key)
            scan(item, path+'/'+key)
    elif isinstance(value, list):
        for item in value: scan(item, path+'/*')
    elif isinstance(value, str):
        if SECRET_VALUE.search(value):
            raise ValueError('Potential secret/private value at ' + path)
        if value[:1] in '[{':
            try: decoded = json.loads(value)
            except ValueError: return
            scan(decoded, path+'/decoded')


def encode(value):
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False).encode('utf-8')


def write_json(path, value):
    scan(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encode(value))


def shards(folder, rows, max_bytes=180000):
    """Bound tool-readable files by bytes, not just row count."""
    files, chunk, size = [], [], 2
    for row in rows:
        length = len(encode(row)) + 4
        if chunk and size + length > max_bytes:
            name = f'{len(files)+1:03}.json'
            write_json(folder/name, chunk); files.append(name); chunk, size = [], 2
        chunk.append(row); size += length
    if chunk:
        name = f'{len(files)+1:03}.json'
        write_json(folder/name, chunk); files.append(name)
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    if out.exists(): raise ValueError('Refusing to replace an existing handoff')
    src = ROOT/'.debug-artifacts/initial-catalog-20260910-pass41'
    load = lambda name: json.loads((src/name).read_text(encoding='utf-8'))
    batches, bundle, decisions = load('source-ingestions.json'), load('catalog-bundle.json'), load('classification-decisions.json')
    for value in (batches,bundle,decisions,load('reviewed-decisions.json')): scan(value)
    # Fresh target has no deleted pages containing passwords or account data.
    out.mkdir(parents=True)
    archives = out/'archives'; archives.mkdir()
    db_path = out/'source-pending.sqlite'
    with sqlite3.connect(db_path) as db:
        db.execute('CREATE TABLE pending_ingestions (id INTEGER PRIMARY KEY, crawler_name TEXT, crawled_at TEXT, items_json TEXT, items_count INTEGER, status TEXT)')
        db.executemany('INSERT INTO pending_ingestions VALUES (:id,:crawler_name,:crawled_at,:items_json,:items_count,:status)', batches)
    restored, manifest = read_pending_source(db_path)
    assert restored == batches
    assert manifest['source_sha256'] == 'c4431eea85f0c1c2f54c202030daed8f8904d8c7b832491a126b8541590845e0'
    (archives/'source-pending.sqlite.gz').write_bytes(gzip.compress(db_path.read_bytes(),mtime=0))
    db.close()
    gc.collect()  # read_pending_source's SQLite context commits but does not close.
    db_path.unlink()  # Only this newly generated temporary DB; source is untouched.
    with sqlite3.connect((src/'staging.sqlite').as_uri()+'?mode=ro',uri=True) as db:
        for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            columns = [r[1] for r in db.execute(f'PRAGMA table_info("{table}")')]
            rows = [dict(zip(columns,row)) for row in db.execute(f'SELECT * FROM "{table}"')]
            scan(rows, 'stage/'+table)
    (archives/'staging-pass41.sqlite.gz').write_bytes(gzip.compress((src/'staging.sqlite').read_bytes(),mtime=0))
    for name in ['source-ingestions.json','catalog-bundle.json','classification-decisions.json','summary.json','product-group-candidates.json']:
        data = (src/name).read_bytes(); scan(json.loads(data))
        (archives/(name+'.gz')).write_bytes(gzip.compress(data,mtime=0))
    review_input = ROOT/'.debug-artifacts/reviewed-initial-decisions-20260908-remaining-exact.json'
    write_json(out/'review-decisions-input.json', json.loads(review_input.read_text(encoding='utf-8')))
    write_json(out/'reviewed-decisions-applied.json', load('reviewed-decisions.json'))
    write_json(out/'summary.json', load('summary.json'))
    raw_files = {}
    for batch in batches:
        records = [{'raw_record_id': f"ingestion:{batch['id']}:{i}", 'item':item} for i,item in enumerate(json.loads(batch['items_json']))]
        raw_files[str(batch['id'])] = {'mart':batch['crawler_name'],'crawled_at':batch['crawled_at'],'count':len(records),'files': shards(out/'raw'/str(batch['id']), records)}
    write_json(out/'raw'/'index.json', raw_files)
    catalog_index = {}
    for key, value in bundle.items():
        if isinstance(value,list):
            catalog_index[key] = {'count':len(value),'files':shards(out/'catalog'/key,value)}
        else: write_json(out/'catalog'/(key+'.json'),value)
    write_json(out/'catalog'/'index.json', catalog_index)
    by_id = {d['raw_record_id']:d for d in decisions}
    normalized = {r['raw_record_id']:r for r in normalize_pending_ingestions(batches)}
    grouped = defaultdict(list)
    for row in bundle['unresolved']:
        rid = row['raw_record_id']; d = by_id[rid]
        grouped[(d['mart'],d['source_path'])].append({'raw_record_id':rid,'source_title':d['source_title'],'source_record_key':normalized[rid]['source_record_key'],'reasons':row['reasons'],'classification':d,'normalized':normalized[rid]})
    pending_index = []
    lines = ['# 보류 검토 묶음', '', '숫자는 수집 관측 수입니다. 동일 판매 페이지/반복 수집을 중복 상품으로 만들지 마세요.', '', '| 묶음 | 마트 | 원본 진열 | 관측 | 제목 수 |', '|---|---|---|---:|---:|']
    for number, ((mart,path),rows) in enumerate(sorted(grouped.items(),key=lambda pair:(-len(pair[1]),pair[0])),1):
        group_id = f'{number:03}'
        files = shards(out/'pending'/group_id, rows, 110000)
        titles = len({r['source_title'] for r in rows})
        pending_index.append({'id':group_id,'mart':mart,'source_path':path,'observations':len(rows),'unique_titles':titles,'files':files})
        lines.append(f'| [{group_id}](pending/{group_id}/{files[0]}) | {mart} | {path.replace("|","/")} | {len(rows)} | {titles} |')
    write_json(out/'pending'/'index.json',pending_index)
    (out/'PENDING_INDEX.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    files = {str(p.relative_to(out)).replace('\\','/'):{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in out.rglob('*') if p.is_file()}
    write_json(out/'manifest.json', {'baseline_commit':'18e8fc9','baseline_pass':'pass41','source_sha256':manifest['source_sha256'],'observations':9196,'pending_observations':3916,'staged_observations':5280,'original_admin_db_uploaded':False,'files':files})
    print(json.dumps({'files':len(files),'bytes':sum(r['bytes'] for r in files.values()),'pending_groups':len(pending_index),'source_hash_verified':True,'sensitive_field_scan':'passed'},indent=2))


if __name__ == '__main__': main()
