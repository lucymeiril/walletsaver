"""Export independently computed audit, not external completion counters."""
from audit_pass44_proposals import audit,ROOT
from build_chat_handoff import write_json
summary,records,raw,samples,skipped=audit()
write_json(ROOT/'handoff/2026-09-14-pass45/external-review.json',{
 'summary':summary,'samples':samples,'errors':[r for r in records if any('mismatch' in f for f in r['flags'])],
 'unsupported_format_entries':skipped,
 'limits':'Diff-only audit; no claim of all historical proposals being reviewed. Existing-leaf semantics sampled; risky forms/new leaves/merges/quantity decisions not promoted.',
 'already_included_observations_referenced':156})
print('Exported audit with',len(samples),'sample decisions')
