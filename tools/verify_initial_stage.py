"""Independent read-only checks against the generated stage, not a source DB."""
from collections import Counter, defaultdict
import json
from pathlib import Path
import sqlite3
import sys

root = Path(__file__).resolve().parents[1]
out = root / '.debug-artifacts' / (sys.argv[1] if len(sys.argv) > 1 else 'initial-catalog-20260903-pass3')
bundle = json.loads((out / 'catalog-bundle.json').read_text(encoding='utf-8'))
review = json.loads((out / 'reviewed-decisions.json').read_text(encoding='utf-8'))
with sqlite3.connect((out / 'staging.sqlite').as_uri() + '?mode=ro', uri=True) as db:
    assert db.execute('PRAGMA integrity_check').fetchone() == ('ok',)
    assert not db.execute('PRAGMA foreign_key_check').fetchall()
    pending = db.execute("SELECT COUNT(*) FROM normalized_offer_events WHERE offer_state='pending_review'").fetchone()[0]
    assert pending == bundle['build_report']['pending_promotion_offers']
    assert db.execute("SELECT COUNT(*) FROM normalized_offer_events WHERE offer_state='pending_review' AND (standard_unit_price IS NOT NULL OR price_per_100g IS NOT NULL)").fetchone()[0] == 0
    assert db.execute('SELECT COUNT(*) FROM normalized_canonical_products p JOIN unified_categories c ON p.unified_category_id=c.parent_id').fetchone()[0] == 0
    assert db.execute('SELECT COUNT(*) FROM matching_entries m JOIN normalized_product_variants v ON m.public_variant_id=v.public_variant_id WHERE m.public_product_id<>v.public_product_id OR m.confidence<0.8').fetchone()[0] == 0
    groups = db.execute('SELECT v.public_product_id, COUNT(DISTINCT l.source_name), COUNT(*) FROM normalized_source_listings l JOIN normalized_product_variants v USING(public_variant_id) GROUP BY v.public_product_id HAVING COUNT(DISTINCT l.source_name)>1').fetchall()
    # Exact reviewed membership, not a hard-coded count or the bundle's claim.
    memberships = defaultdict(set)
    for family, mart, key in db.execute('SELECT v.public_product_id, l.source_name, l.source_record_key FROM normalized_source_listings l JOIN normalized_product_variants v USING(public_variant_id)'):
        memberships[family].add((mart, key))
    present = set().union(*memberships.values())
    expected = defaultdict(set)
    for decision in review['decisions']:
        key = (decision['source_name'], decision['source_record_key'])
        if decision.get('product_group_key') and key in present:
            expected[decision['product_group_key']].add(key)
    actual_multi = {frozenset(keys) for keys in memberships.values() if len(keys) > 1}
    expected_multi = {frozenset(keys) for keys in expected.values() if len(keys) > 1}
    assert actual_multi == expected_multi, 'Unexpected family merge or reviewed member lost'
    assert db.execute('SELECT COUNT(*) FROM products').fetchone()[0] == 0
    assert db.execute('SELECT COUNT(*) FROM categories').fetchone()[0] == 0
    by_mart = db.execute('SELECT l.source_name, COUNT(o.public_offer_event_id), COUNT(DISTINCT l.public_source_listing_id) FROM normalized_source_listings l JOIN normalized_offer_events o USING(public_source_listing_id) GROUP BY l.source_name').fetchall()
    rows = bundle['observation_accounting']
    assert len(rows) == len({row['raw_record_id'] for row in rows}) == 9196
    evidence_ids = set()
    for (evidence,) in db.execute('SELECT raw_evidence FROM normalized_offer_events'):
        evidence = json.loads(evidence)
        for observation in evidence['observations']:
            assert observation['raw_payload_sha256']
            evidence_ids.add(observation['raw_record_id'])
    assert evidence_ids == {row['raw_record_id'] for row in rows if row['status']=='included'}
    print(json.dumps({'checks':'passed','accounting':dict(Counter(row['status'] for row in rows)), 'offer_evidence':len(evidence_ids),'reviewed_cross_mart_groups':len(groups),'pending_promotion_noncomparable':pending,'by_mart_offers_listings':by_mart,'source_db_opened':False},ensure_ascii=True,indent=2))

if '--snapshot' in sys.argv:
    import hashlib
    sys.path.insert(0, str(root / 'packages/shared'))
    sys.path.insert(0, str(root / 'packages/db-admin/backend'))
    from sqlalchemy import create_engine
    from services.public_snapshot_v2 import _write_snapshot_file, validate_public_snapshot
    stage = out / 'staging.sqlite'
    snapshot = out / 'public-snapshot-rehearsal.sqlite'
    assert not snapshot.exists(), 'Never overwrite a prior artifact'
    before = hashlib.sha256(stage.read_bytes()).hexdigest()
    engine = create_engine('sqlite://', creator=lambda: sqlite3.connect(stage.as_uri() + '?mode=ro', uri=True))
    try:
        with engine.connect() as source_connection:
            with source_connection.begin():
                _write_snapshot_file(snapshot, source_connection, revision=1)
    finally:
        engine.dispose()
    validation = validate_public_snapshot(snapshot)
    with sqlite3.connect(snapshot.as_uri() + '?mode=ro', uri=True) as connection:
        pending_after = connection.execute("SELECT COUNT(*) FROM normalized_offer_events WHERE offer_state='pending_review'").fetchone()[0]
        assert pending_after == 0
        assert validation['row_counts']['normalized_offer_events'] == bundle['build_report']['active_offer_observations']
        inactive_after = connection.execute('SELECT COUNT(*) FROM normalized_canonical_products WHERE is_active=0').fetchone()[0]
        assert inactive_after == bundle['build_report']['inactive_product_groups']
        assert not connection.execute('PRAGMA foreign_key_check').fetchall()
    assert hashlib.sha256(stage.read_bytes()).hexdigest() == before
    print(json.dumps({'snapshot_rehearsal':'passed','pending_offers_removed':pending,'retained_offers':validation['row_counts']['normalized_offer_events'],'inactive_products_retained':inactive_after,'stage_unchanged':True,'published':False},ensure_ascii=True))
