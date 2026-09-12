"""Materialize the human-reviewed subset, never all external proposals.

Selection was reviewed on 2026-09-12 against original titles and source paths.
Other proposals remain unverified. Runtime category conflicts are not bypassed.
"""
import json
from pathlib import Path
from audit_chat_proposals import run, BASE, ROOT, load

SELECTED = {
    'homeplus-bean-sprouts-053.json', 'homeplus-fruit-jam-063.json',
    'homeplus-dried-vegetables-100.json', 'homeplus-corn-cereal-086.json',
    'homeplus-drain-bleach-077.json', 'homeplus-frozen-vegetables-081.json',
    'homeplus-canned-ham-094.json', 'homeplus-soy-protein-drinks-078.json',
}
EXCLUDED = {
    # Preparation usage or shelf name alone does not establish frozen form.
    '그린피아 만능찌개용 채소믹스 500G', '한끼채소 찌개용 360G',
    '한끼채소 카레짜장용 360G', '한끼채소 볶음밥용 360G',
    # Single pouches should not be silently treated as cans.
    'CJ 스팸 클래식 싱글 80G*3',
}


if __name__ == '__main__':
    report = run()
    pending = {r['raw_record_id']:r for p in (BASE/'pending').glob('*/*.json') for r in load(p)}
    accepted = {}
    for record in report['records']:
        title = record['decision'].get('source_title')
        if record['file'] not in SELECTED or title in EXCLUDED: continue
        assert not record['flags'], record
        for rid in record['ids']:
            row = pending[rid]
            c = row['classification']
            key = (c['mart'], row['source_record_key'], row['source_title'], tuple(c['source_path_parts']))
            entry = {'mart':key[0],'source_record_key':key[1],'source_title':key[2],'source_path_parts':list(key[3]),'leaf':record['leaf'],'proposal_file':record['file'],'raw_record_ids':[]}
            if key in accepted:
                assert accepted[key]['leaf']==entry['leaf']
            else: accepted[key]=entry
            accepted[key]['raw_record_ids'].append(rid)
    rows = list(accepted.values())
    path = ROOT/'packages/db-admin/backend/services/reviewed_chat_batch_20260912.json'
    if path.exists(): raise ValueError('Refusing to overwrite accepted review')
    path.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Accepted listing/path records:',len(rows),'observations:',sum(len(r['raw_record_ids']) for r in rows))
