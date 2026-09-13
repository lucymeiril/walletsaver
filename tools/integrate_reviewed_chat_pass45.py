"""Materialize reviewed low-risk candidates from the pinned external diff."""
from audit_pass44_proposals import audit,ROOT
from build_chat_handoff import write_json
from services.initial_reviewed_chat import ROWS

DEFER={
 'food.meals.dumplings.steamed','food.meals.prepared.seasoned_meat',
 'food.meals.noodles.naengmyeon','food.seafood.fish.flounder','food.seafood.fish.croaker',
 'food.snacks.sweets.jelly','food.drinks.juice.fruit','food.meat.processed.sausage',
 'household.cleaning.general.deodorizer',
}
def key(r):return(r['mart'],r['source_record_key'],r['source_title'],tuple(r['source_path_parts']))

if __name__=='__main__':
 summary,records,raw,samples,skipped=audit()
 existing={key(r) for r in ROWS}; selected=[]
 for r in records:
  d=r['decision']
  if r['flags'] or d['decision']!='existing_leaf' or d.get('review_lane')!='clear_existing':continue
  if d['source_name']!='homeplus' or d['unified_category_id'] in DEFER:continue
  original=raw[d['raw_record_ids'][0]]
  c=original['classification']
  assert len({tuple(raw[i]['classification']['source_path_parts']) for i in d['raw_record_ids']})==1
  row={'mart':c['mart'],'source_record_key':original['source_record_key'],'source_title':original['source_title'],
       'source_path_parts':c['source_path_parts'],'leaf':d['unified_category_id'],
       'raw_record_ids':d['raw_record_ids'],'proposal_file':r['file'],
       'review_basis':'All source identities and current leaves checked; two deterministic samples per mart/leaf; risky forms excluded; no price/specification override.'}
  if key(row) in existing:continue
  existing.add(key(row));selected.append(row)
 out=ROOT/'packages/db-admin/backend/services/reviewed_chat_batch_pass45.json'
 if out.exists():raise ValueError('New output required')
 write_json(out,selected)
 print('Selected',len(selected),'listing/path records;',sum(len(r['raw_record_ids']) for r in selected),'observations')
