from __future__ import annotations
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import sys

repo = Path.cwd()
sys.path.insert(0, str(repo / 'packages' / 'ai-admin' / 'backend'))
sys.path.insert(0, str(repo / 'packages' / 'shared'))
from core.contracts.ai_pipeline import AIProviderRef, ProviderKind, RawCrawlRecord
from services.ai_ingestion import _reviewer_safe_fallback_response_item, proposals_from_labeling_response
from services.review_publish import build_raw_ai_audit, db_item_from_review, publish_blockers
from services.seed_taxonomy import is_safe_seed_category, normalize_category_id

source = repo / '.walletsavior-live-validation' / 'ai-541-live-provider-pass-after-cap' / 'live-validation-v2-20260516-131636-8e257893.json'
data = json.loads(source.read_text(encoding='utf-8'))
records = [RawCrawlRecord.model_validate(row) for row in data['raw_records']]
provider = AIProviderRef(provider_kind=ProviderKind.CUSTOM, provider_name='reviewer-safe-replay', model_name='deterministic-fallback')
response = {'items': [_reviewer_safe_fallback_response_item(record) for record in records]}
proposals = proposals_from_labeling_response(batch_id='ai-quality-replay:fallback', provider=provider, records=records, response=response, require_all_labels=True)
audit = build_raw_ai_audit(records, proposals, batch_id='ai-quality-replay')
issues_by_code = Counter(issue['code'] for issue in audit.get('issues', []))
rows_with_issue = {}
for issue in audit.get('issues', []):
    rows_with_issue.setdefault(issue['raw_record_id'], set()).add(issue['code'])
missing_category_rows = sum(1 for codes in rows_with_issue.values() if 'missing_category_id_signal' in codes or 'missing_category_signal' in codes)
unknown_category_rows = sum(1 for codes in rows_with_issue.values() if 'unknown_taxonomy_category' in codes or 'invalid_category_id_format' in codes)
missing_keyword_rows = sum(1 for codes in rows_with_issue.values() if 'missing_keywords_signal' in codes)
missing_unit_rows = sum(1 for codes in rows_with_issue.values() if 'missing_unit_signal' in codes)
items = [db_item_from_review(record, proposals, {}) for record in records]
unsafe_categories = Counter(str(item.get('category_id')) for item in items if item.get('category_id') and not is_safe_seed_category(item.get('category_id')))
quality = data['quality_batch_validation']
metrics = {
    'created_at': datetime.now(timezone.utc).isoformat(),
    'source_artifact': str(source),
    'replay_mode': 'live_safe_deterministic_reviewer_fallback_no_provider_no_db',
    'input_rows': len(records),
    'before': {
        'missing_label_count': quality['missing_label_retry']['missing_label_count'],
        'category_anomaly_rows': quality['anomaly_counts']['category'],
        'keyword_anomaly_rows': quality['anomaly_counts']['keyword'],
        'unit_anomaly_rows': quality['anomaly_counts']['unit'],
        'rows_with_any_anomaly': quality['rows_with_any_anomaly'],
    },
    'after_replay': {
        'missing_label_count': 0,
        'proposal_count': len(proposals),
        'covered_record_count': audit.get('covered_record_count'),
        'missing_record_count': audit.get('missing_record_count'),
        'missing_or_invalid_category_rows': missing_category_rows + unknown_category_rows,
        'missing_keyword_rows': missing_keyword_rows,
        'missing_unit_rows': missing_unit_rows,
        'unsafe_category_counts': dict(unsafe_categories),
        'top_audit_issues': issues_by_code.most_common(20),
    },
    'changed_code_paths': [
        'packages\\ai-admin\\backend\\services\\ai_ingestion.py',
        'packages\\ai-admin\\backend\\services\\seed_taxonomy.py',
        'packages\\shared\\core\\product_units.py',
        'packages\\ai-admin\\backend\\workers\\classifier.py',
        'packages\\ai-admin\\backend\\workers\\unit_converter.py',
    ],
}
out = repo / '.walletsavior-live-validation' / 'ai-quality-anomaly-reduction-loop' / 'deterministic-replay-metrics-20260516.json'
out.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'artifact_path': str(out), 'before': metrics['before'], 'after_replay': metrics['after_replay']}, ensure_ascii=False, indent=2))
