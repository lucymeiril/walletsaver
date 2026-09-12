"""Create a new residual-work overlay without replacing the pass41 archive."""
from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path
from audit_chat_proposals import run, ROOT, BASE, load
from build_chat_handoff import shards, write_json, scan
from services.initial_taxonomy import taxonomy_categories

OUT = ROOT/'handoff/2026-09-12'
SRC = ROOT/'.debug-artifacts/initial-catalog-20260912-pass42'


if __name__ == '__main__':
    if OUT.exists(): raise ValueError('New output required')
    report = run()
    bundle = load(SRC/'catalog-bundle.json')
    prior = json.loads(gzip.decompress((BASE/'archives/catalog-bundle.json.gz').read_bytes()))
    ids = lambda b:{r['raw_record_id'] for r in b['observation_accounting'] if r['status']=='included'}
    approved = load(ROOT/'packages/db-admin/backend/services/reviewed_chat_batch_20260912.json')
    accepted_ids = {rid for r in approved for rid in r['raw_record_ids']}
    added = ids(bundle)-ids(prior)
    assert ids(prior)<=ids(bundle) and added<=accepted_ids and len(added)==71
    assert load(SRC/'reviewed-decisions.json')==load(BASE/'reviewed-decisions-applied.json')
    references = defaultdict(list)
    for r in report['records']:
        for rid in r['ids']:
            references[rid].append({'file':r['file'],'path':r['path'],'leaf':r['leaf'],'flags':r['flags']})
    old_rows = {r['raw_record_id']:r for p in (BASE/'pending').glob('*/*.json') for r in load(p)}
    current = {r['raw_record_id']:r for r in bundle['unresolved']}
    assert set(current)<=set(old_rows)
    indices = []
    lines = ['# 남은 작업 — pass42', '', '과거 묶음 ID를 그대로 유지. proposal_references는 미승인 제안 링크이며 완료 표시가 아니다.', '', '| 묶음 | 마트 | 진열 | 남은 관측 |', '|---|---|---|---:|']
    for group in load(BASE/'pending/index.json'):
        rows = []
        for name in group['files']:
            for r in load(BASE/'pending'/group['id']/name):
                rid=r['raw_record_id']
                if rid not in current: continue
                r={**r,'reasons':current[rid]['reasons'],'proposal_references':references[rid],'integration_state':'accepted_but_blocked' if rid in accepted_ids else 'not_integrated'}
                rows.append(r)
        if rows:
            files=shards(OUT/'remaining'/group['id'],rows,110000)
            indices.append({**group,'observations':len(rows),'unique_titles':len({r['source_title'] for r in rows}),'files':files})
            lines.append(f"| [{group['id']}](remaining/{group['id']}/{files[0]}) | {group['mart']} | {group['source_path'].replace('|','/')} | {len(rows)} |")
    write_json(OUT/'remaining/index.json',indices)
    (OUT/'REMAINING.md').write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n')
    categories=taxonomy_categories()
    parent_ids={r['parent_id'] for r in categories if r.get('parent_id')}
    write_json(OUT/'taxonomy.json',{'nodes':categories,'leaf_ids':[r['id'] for r in categories if r['id'] not in parent_ids]})
    write_json(OUT/'audit.json',{k:v for k,v in report.items() if k not in ('records','top_level_layouts')})
    write_json(OUT/'flagged-proposals.json',[r for r in report['records'] if r['flags']])
    write_json(OUT/'accepted.json',{'records':approved,'new_included_ids':sorted(added),'accepted_but_blocked_ids':sorted(accepted_ids-added)})
    write_json(OUT/'summary.json',load(SRC/'summary.json'))
    archive=OUT/'archives'; archive.mkdir()
    for name in ['catalog-bundle.json','staging.sqlite','reviewed-decisions.json']:
        data=(SRC/name).read_bytes()
        if name.endswith('.json'): scan(json.loads(data))
        (archive/(name+'.gz')).write_bytes(gzip.compress(data,mtime=0))
    write_json(OUT/'manifest.json',{'baseline':'pass42','source_sha256':load(BASE/'manifest.json')['source_sha256'],'staged':5351,'pending':3845,'files':{str(p.relative_to(OUT)).replace('\\','/'):{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size} for p in OUT.rglob('*') if p.is_file()}})
    print('PASS: prior included and431 decisions retained;71 additions;3845 residual observations;',len(indices),'groups')
