"""Audit proposal identity/coverage and emit deterministic semantic-review samples."""
from collections import Counter, defaultdict
import hashlib
from audit_chat_proposals import ROOT, load
from build_chat_handoff import write_json

BASE = ROOT/'handoff/2026-09-12-pass43'

def audit():
    raw = {r['raw_record_id']:r for p in (BASE/'remaining').glob('*/*.json') for r in load(p)}
    leaves = set(load(BASE/'taxonomy.json')['leaf_ids'])
    records = []
    layouts = []
    def visit(v, file):
        if isinstance(v, dict):
            if v.get('raw_record_ids') and v.get('decision'):
                flags = []
                for rid in v['raw_record_ids']:
                    r = raw.get(rid)
                    if r is None:
                        flags.append('unknown_id'); continue
                    for key in ('source_title','source_record_key'):
                        if str(v.get(key,'')) != r[key]: flags.append(key+'_mismatch')
                    if not v.get('source_name'): flags.append('missing_mart')
                    elif v['source_name'] != r['classification']['mart']: flags.append('mart_mismatch')
                if v['decision']=='existing_leaf' and v.get('unified_category_id') not in leaves:
                    flags.append('invalid_leaf')
                records.append({'file':file,'decision':v,'flags':sorted(set(flags))})
            for child in v.values(): visit(child,file)
        elif isinstance(v,list):
            for child in v: visit(child,file)
    for p in sorted((BASE/'proposals').glob('*.json')):
        v=load(p)
        if 'decisions' not in v: layouts.append(p.name)
        visit(v,p.name)
    by_id=defaultdict(list)
    for r in records:
        for rid in r['decision']['raw_record_ids']: by_id[rid].append(r)
    summary={'files':len(list((BASE/'proposals').glob('*.json'))),'decisions':len(records),
             'unique_observations':len(by_id),'pending_observations':len(raw),
             'duplicate_ids':sum(len(rs)>1 for rs in by_id.values()),
             'flags':dict(Counter(f for r in records for f in r['flags'])),
             'decision_observations':dict(Counter(r['decision']['decision'] for rs in by_id.values() for r in rs)),
             'nested_layouts':layouts}
    scope_groups=set()
    for p in (BASE/'proposals').glob('*.json'):
        for scope in load(p).get('scope',[]):
            if isinstance(scope,str) and 'remaining/' in scope:
                scope_groups.add(scope.split('remaining/')[1].split('/')[0])
    summary['claimed_scope_groups']=len(scope_groups)
    return summary, records, raw

if __name__=='__main__':
    summary,records,raw=audit()
    write_json(ROOT/'.debug-artifacts/pass43-external-audit.json',{'summary':summary,'records':records})
    print(summary)
    grouped=defaultdict(list)
    for r in records:
        d=r['decision']
        if d['decision']=='existing_leaf': grouped[(raw[d['raw_record_ids'][0]]['classification']['mart'],d['unified_category_id'])].append(r)
    for (mart,leaf),rs in sorted(grouped.items()):
        chosen=sorted(rs,key=lambda r:hashlib.sha256('|'.join(r['decision']['raw_record_ids']).encode()).hexdigest())[:2]
        print(mart,leaf,len(rs),[(r['decision']['source_title'],r['flags']) for r in chosen])
