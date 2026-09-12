"""Read-only structural audit. Passing these checks is NOT semantic approval."""
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT/'handoff/2026-09-11'
sys.path[:0] = [str(ROOT/'packages/shared'),str(ROOT/'packages/db-admin/backend')]
from services.initial_taxonomy import taxonomy_categories


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def run():
    pending = {r['raw_record_id']: r for p in (BASE/'pending').glob('*/*.json') for r in load(p)}
    leaves = {r['id'] for p in (BASE/'catalog/categories').glob('*.json') for r in load(p)}
    if not leaves:
        raise ValueError('Missing category baseline')
    current = taxonomy_categories()
    parents = {r['parent_id'] for r in current if r.get('parent_id')}
    current_leaves = {r['id'] for r in current} - parents
    records, errors, layouts = [], [], Counter()
    def visit(value, file, path=''):
        if isinstance(value,dict):
            ids = value.get('raw_record_ids') or ([value['raw_record_id']] if value.get('raw_record_id') else [])
            leaf = next((value[k] for k in ('proposed_unified_category_id','unified_category_id','proposed_leaf','existing_leaf') if value.get(k)),None)
            if ids and leaf:
                flags = []
                if leaf not in leaves: flags.append('absent_from_snapshot')
                if leaf not in current_leaves: flags.append('unknown_current_leaf')
                for rid in ids:
                    if rid not in pending:
                        flags.append('unknown_pending_id'); continue
                    row = pending[rid]
                    if value.get('source_record_key') and str(value['source_record_key']) != row['source_record_key']: flags.append('source_key_mismatch')
                    if value.get('source_name') and value['source_name'] != row['classification']['mart']: flags.append('mart_mismatch')
                    if value.get('source_title') and value['source_title'] != row['source_title']: flags.append('title_mismatch')
                records.append({'file':file,'path':path,'ids':ids,'leaf':leaf,'flags':sorted(set(flags)),'decision':value})
            for k,v in value.items(): visit(v,file,path+'/'+k)
        elif isinstance(value,list):
            for i,v in enumerate(value): visit(v,file,path+'/'+str(i))
    files = sorted((BASE/'proposals').glob('*.json'))
    for file in files:
        try:
            value = load(file)
            layouts.update(value.keys())
            visit(value,file.name)
        except (ValueError,TypeError) as exc: errors.append({'file':file.name,'error':str(exc)})
    by_id = defaultdict(list)
    for r in records:
        for rid in r['ids']: by_id[rid].append(r)
    conflicts = {rid:[{'file':r['file'],'leaf':r['leaf']} for r in rows] for rid,rows in by_id.items() if len({r['leaf'] for r in rows})>1}
    report = {'proposal_files':len(files),'parse_errors':errors,'explicit_leaf_records':len(records),'unique_ids_with_leaf':len(by_id),'duplicate_id_count':sum(len(rows)>1 for rows in by_id.values()),'conflicting_ids':conflicts,'flag_counts':dict(Counter(f for r in records for f in r['flags'])),'top_level_layouts':dict(layouts),'records':records}
    return report


if __name__ == '__main__':
    report = run()
    out = ROOT/'.debug-artifacts/chat-proposal-audit-20260912.json'
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('records','top_level_layouts','conflicting_ids')},ensure_ascii=False))
    print('conflicting_ids',len(report['conflicting_ids']))
    for r in report['records']:
        if r['flags']: print(r['file'],r['ids'],r['leaf'],r['flags'])
