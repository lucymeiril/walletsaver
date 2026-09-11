"""Actual runtime/export matching against an immutable staging DB."""
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'packages/shared'), str(ROOT / 'packages/crawler-admin/backend')]
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from services.db_admin_readonly import reset_db_admin_engine
from services.matching_enrichment import _match_key_for_row, enrich_items_with_matching_entries, lookup_row_match_statuses

out = ROOT / '.debug-artifacts' / sys.argv[1]
bundle = json.loads((out / 'catalog-bundle.json').read_text(encoding='utf-8'))
source = json.loads((out / 'source-ingestions.json').read_text(encoding='utf-8'))
review = json.loads((out / 'reviewed-decisions.json').read_text(encoding='utf-8'))
raw = {f"ingestion:{batch['id']}:{index}": item for batch in source for index, item in enumerate(json.loads(batch['items_json']))}
rules = {rid: rule for rule in bundle['match_rules'] for rid in rule['source_raw_record_ids']}
stage = out / 'staging.sqlite'
before = hashlib.sha256(stage.read_bytes()).hexdigest()
engine = create_engine('sqlite://', creator=lambda: sqlite3.connect(stage.as_uri() + '?mode=ro', uri=True))
reset_db_admin_engine(engine)
results = []
try:
    with Session(engine) as session:
        for decision in review['decisions']:
            if not decision.get('product_group_key'):
                continue
            for observation in decision['expected_observations']:
                rid = observation['raw_record_id']
                item = deepcopy(raw[rid])
                rule = rules.get(rid)
                key, reason = _match_key_for_row(deepcopy(item))
                assert reason is None
                if rule:
                    assert key == rule['match_key'], rid
                    active = session.execute(text('SELECT is_active FROM normalized_canonical_products WHERE public_product_id=:id'), {'id': rule['public_product_id']}).scalar_one()
                else:
                    active = False
                actual = enrich_items_with_matching_entries([deepcopy(item)])[0]
                exported = lookup_row_match_statuses(session, [(item, key)])[0]
                assert actual['matching_status'] == ('hit' if active else 'miss'), (rid, actual.get('matching_miss_reason'))
                assert (exported == 'hit') == bool(active), (rid, exported)
                mutations = {
                    'renamed': {**item, 'name': str(item['name']) + ' 변경품'},
                    'new_listing': {**item, 'source_record_key': 'unseen-regression-listing'},
                    'spec_changed': {**item, 'package_quantity': 987654, 'package_unit': 'g'},
                }
                for label, changed in mutations.items():
                    result = enrich_items_with_matching_entries([deepcopy(changed)])[0]
                    # Explicitly keep old key on export to test stale-key defence.
                    status = lookup_row_match_statuses(session, [(changed, key)])[0]
                    assert result['matching_status'] == 'miss' and status != 'hit', (rid, label, status)
                results.append({'raw_record_id': rid, 'family': decision['product_group_key'], 'original': actual['matching_status'], 'export': exported, 'mutations_rejected': list(mutations)})
finally:
    reset_db_admin_engine()
    engine.dispose()
assert hashlib.sha256(stage.read_bytes()).hexdigest() == before
report = {'status': 'passed', 'families': len({r['family'] for r in results}), 'original_observations': dict(Counter(r['original'] for r in results)), 'mutation_cases_per_path': 3 * len(results), 'stage_unchanged': True, 'details': results}
print(json.dumps({k:v for k,v in report.items() if k != 'details'}, ensure_ascii=False, indent=2))
if '--save' in sys.argv:
    with (out / 'reviewed-runtime-check.json').open('xb') as stream:
        stream.write(json.dumps(report, ensure_ascii=False, indent=2).encode('utf-8'))
