"""Read-only audit of external changes after pass44, pinned to a fetched commit."""
import hashlib
import subprocess
from collections import Counter,defaultdict
from audit_chat_proposals import ROOT,load
from build_chat_handoff import write_json

BASE=ROOT/'handoff/2026-09-12-pass44'
END='0484e54'

def audit():
    raw={r['raw_record_id']:r for p in (BASE/'remaining').glob('*/*.json') for r in load(p)}
    leaves=set(load(BASE/'taxonomy.json')['leaf_ids'])
    files=[p for p in subprocess.check_output(['git','diff','--name-only','32d158b',END],cwd=ROOT,text=True).splitlines() if '/proposals/' in p and p.endswith('.json')]
    records=[]; skipped=[]
    for file in files:
        for d in load(ROOT/file).get('decisions',[]):
            if not d.get('raw_record_ids') or not d.get('decision'):
                skipped.append({'file':file,'value':d});continue
            flags=[]
            for rid in d['raw_record_ids']:
                r=raw.get(rid)
                if r is None: flags.append('not_current_pending');continue
                for key in ('source_title','source_record_key'):
                    if d.get(key)!=r[key]:flags.append(key+'_mismatch')
                if d.get('source_name')!=r['classification']['mart']:flags.append('mart_mismatch')
            if d['decision']=='existing_leaf' and d.get('unified_category_id') not in leaves:flags.append('invalid_leaf')
            records.append({'file':file,'decision':d,'flags':sorted(set(flags))})
    byid=defaultdict(list)
    for r in records:
        for rid in r['decision']['raw_record_ids']:byid[rid].append(r)
    conflicts={rid for rid,rs in byid.items() if len({(r['decision']['decision'],r['decision'].get('unified_category_id')) for r in rs})>1}
    for r in records:
        if conflicts.intersection(r['decision']['raw_record_ids']):r['flags'].append('conflicting_decisions')
    groups=defaultdict(list)
    for r in records:
        d=r['decision']
        if d['decision']=='existing_leaf':groups[(d.get('source_name',''),d['unified_category_id'])].append(r)
    samples=[]
    for key,rs in sorted(groups.items()):
        samples.extend(sorted(rs,key=lambda r:hashlib.sha256('|'.join(r['decision']['raw_record_ids']).encode()).hexdigest())[:2])
    summary={'commit':END,'files':len(files),'decisions':len(records),'unique_ids':len(byid),
             'duplicate_ids':sum(len(rs)>1 for rs in byid.values()),'conflicting_ids':len(conflicts),
             'flags':dict(Counter(f for r in records for f in r['flags'])),
             'decision_counts':dict(Counter(r['decision']['decision'] for r in records)),
             'nondecision_entries':len(skipped),'sample_count':len(samples)}
    return summary,records,raw,samples,skipped

if __name__=='__main__':
    summary,records,raw,samples,skipped=audit()
    write_json(ROOT/'.debug-artifacts/pass44-external-audit.json',{'summary':summary,'records':records,'samples':samples,'nondecisions':skipped})
    print(summary)
    for r in samples:
        d=r['decision'];print(d['source_name'],d['unified_category_id'],d['source_title'],r['flags'])
