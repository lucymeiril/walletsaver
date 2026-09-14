"""Check newly staged source rows through actual recollection/export matching.

Reads only the named staging DB in SQLite read-only mode. The baseline's
included observations determine this batch; no operating DB fallback exists.
"""
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


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def check(out, baseline):
    bundle = read(out / 'catalog-bundle.json')
    old = {row['raw_record_id'] for row in read(baseline / 'catalog-bundle.json')['observation_accounting'] if row['status'] == 'included'}
    added = sorted(row['raw_record_id'] for row in bundle['observation_accounting'] if row['status'] == 'included' and row['raw_record_id'] not in old)
    source = read(out / 'source-ingestions.json')
    raw = {f"ingestion:{batch['id']}:{index}": item for batch in source for index, item in enumerate(json.loads(batch['items_json']))}
    rules = {rid: rule for rule in bundle['match_rules'] for rid in rule['source_raw_record_ids']}
    stage = out / 'staging.sqlite'
    before = hashlib.sha256(stage.read_bytes()).hexdigest()
    engine = create_engine('sqlite://', creator=lambda: sqlite3.connect(stage.as_uri() + '?mode=ro', uri=True))
    reset_db_admin_engine(engine)
    try:
        with Session(engine) as session:
            active = dict(session.execute(text('SELECT public_product_id, is_active FROM normalized_canonical_products')).all())
            originals = [deepcopy(raw[rid]) for rid in added]
            keys = [_match_key_for_row(deepcopy(row))[0] for row in originals]
            actual = enrich_items_with_matching_entries(deepcopy(originals))
            exported = lookup_row_match_statuses(session, list(zip(originals, keys)))
            for rid, key, result, status in zip(added, keys, actual, exported):
                rule = rules.get(rid)
                expected = 'hit' if rule and active[rule['public_product_id']] else 'miss'
                if rule:
                    assert key == rule['match_key'], (rid, 'key')
                assert result['matching_status'] == expected and (status == 'hit') == (expected == 'hit'), (rid, expected, result.get('matching_miss_reason'), status)
            changed_rows, stale_keys = [], []
            for original, key in zip(originals, keys):
                changed_rows.extend([
                    {**deepcopy(original), 'name': str(original.get('name') or original.get('productName') or original.get('title')) + ' 변경품'},
                    {**deepcopy(original), 'source_record_key': 'unseen-regression-listing'},
                    {**deepcopy(original), 'package_quantity': 987654, 'package_unit': 'g'},
                ])
                stale_keys.extend([key] * 3)
            changed = enrich_items_with_matching_entries(deepcopy(changed_rows))
            stale = lookup_row_match_statuses(session, list(zip(changed_rows, stale_keys)))
            assert all(row['matching_status'] == 'miss' and status != 'hit' for row, status in zip(changed, stale)), 'new batch mutation accepted'
    finally:
        reset_db_admin_engine()
        engine.dispose()
        assert hashlib.sha256(stage.read_bytes()).hexdigest() == before, 'stage modified'
    return {'status': 'passed', 'added_observations': len(added), 'original_hit': sum(row['matching_status'] == 'hit' for row in actual), 'original_miss': sum(row['matching_status'] == 'miss' for row in actual), 'mutations_per_path': len(changed_rows), 'stage_unchanged': True}


if __name__ == '__main__':
    out = (ROOT / '.debug-artifacts' / sys.argv[1]).resolve()
    baseline = (ROOT / read(ROOT / 'docs/catalog-state.json')['baseline']).resolve()
    assert out.is_relative_to(ROOT / '.debug-artifacts') and baseline.is_relative_to(ROOT / '.debug-artifacts')
    report = check(out, baseline)
    print(json.dumps(report, ensure_ascii=False))
    if '--save' in sys.argv:
        with (out / 'batch-runtime-check.json').open('xb') as stream:
            stream.write(json.dumps(report, ensure_ascii=False, indent=2).encode('utf-8'))
