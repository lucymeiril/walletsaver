"""Promote the structurally checked, sampled low-risk subset; not all proposals."""
from audit_pass43_proposals import audit, ROOT
from build_chat_handoff import write_json

# Sample review found these product-form distinctions need more evidence.
DEFER_LEAVES = {
    'food.dairy.cream.fresh', 'food.meals.dumplings.steamed',
    'food.meals.prepared.seasoned_meat', 'food.produce.processed_fruit.cut',
    'household.cleaning.kitchen.degreaser', 'household.cleaning.general.deodorizer',
}

if __name__=='__main__':
    summary,records,raw=audit()
    rows=[]
    for r in records:
        d=r['decision']
        if d['decision']!='existing_leaf' or d.get('review_lane')!='clear_existing': continue
        if set(r['flags'])-{'missing_mart'}: continue
        if r['file']=='2026-09-12-batch-172-176.json': continue
        if d['unified_category_id'] in DEFER_LEAVES: continue
        original=raw[d['raw_record_ids'][0]]
        c=original['classification']
        if c['mart']!='homeplus': continue  # current accepted-review route is Homeplus-only
        paths={tuple(raw[i]['classification']['source_path_parts']) for i in d['raw_record_ids']}
        assert len(paths)==1
        rows.append({'mart':c['mart'],'source_record_key':original['source_record_key'],
                     'source_title':original['source_title'],'source_path_parts':c['source_path_parts'],
                     'leaf':d['unified_category_id'],'raw_record_ids':d['raw_record_ids'],
                     'proposal_file':r['file'],'proposal_base':'handoff/2026-09-12-pass43/proposals',
                     'review_basis':'All identities/leaves checked; deterministic two-title sample per mart/leaf reviewed. Missing mart recovered only from exact original IDs; no price/quantity/identity override.'})
    assert len({(r['mart'],r['source_record_key'],r['source_title'],tuple(r['source_path_parts'])) for r in rows})==len(rows)
    out=ROOT/'packages/db-admin/backend/services/reviewed_chat_batch_pass44.json'
    if out.exists(): raise ValueError('New output required')
    write_json(out,rows)
    print('Selected',len(rows),'listing/path records;',sum(len(r['raw_record_ids']) for r in rows),'observations')
