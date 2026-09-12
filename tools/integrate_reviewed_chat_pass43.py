"""Materialize only the seven independently title/path-reviewed food groups."""
from audit_chat_proposals import run, BASE, ROOT, load
from build_chat_handoff import write_json

SELECTED = {
    'homeplus-frozen-pizza-045.json', 'homeplus-refrigerated-pastes-049.json',
    'homeplus-laver-bugak-052.json', 'homeplus-cup-rice-054.json',
    'homeplus-instant-noodles-074.json', 'homeplus-kimchi-dumplings-090.json',
    'homeplus-surimi-093.json',
}

if __name__ == '__main__':
    pending = {r['raw_record_id']: r for p in (BASE/'pending').glob('*/*.json') for r in load(p)}
    accepted = {}
    for record in run()['records']:
        if record['file'] not in SELECTED:
            continue
        assert not record['flags'], record
        for rid in record['ids']:
            row = pending[rid]
            c = row['classification']
            key = (c['mart'], row['source_record_key'], row['source_title'], tuple(c['source_path_parts']))
            entry = {'mart':key[0], 'source_record_key':key[1], 'source_title':key[2],
                     'source_path_parts':list(key[3]), 'leaf':record['leaf'],
                     'proposal_file':record['file'], 'raw_record_ids':[],
                     'review_basis':'Exact source title establishes the food type; original path corroborates it. No quantity, promotion, or cross-listing identity override.'}
            if key in accepted:
                assert accepted[key]['leaf'] == entry['leaf']
            else:
                accepted[key] = entry
            assert rid not in accepted[key]['raw_record_ids']
            accepted[key]['raw_record_ids'].append(rid)
    assert len(accepted) == 53
    out = ROOT/'packages/db-admin/backend/services/reviewed_chat_batch_pass43.json'
    if out.exists():
        raise ValueError('Refusing to overwrite accepted review')
    write_json(out, list(accepted.values()))
    print('Accepted',len(accepted),'listing/path records;',sum(len(r['raw_record_ids']) for r in accepted.values()),'observations')
