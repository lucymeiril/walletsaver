import test from 'node:test';
import assert from 'node:assert/strict';

import {
  buildAutomationApplyMessage,
  buildBatchHealth,
  buildBulkPreview,
  buildOperatorDashboardReport,
  buildOpsTriageCounters,
  buildPublishConfirmationMessage,
  buildRollbackConfirmationMessage,
  categoryDisplayLabel,
  explainAutomationRow,
  formatCategoryDisplay,
  normalizeCategoryId,
  nextOperatorAction,
  publishRowAction,
  summarizeAutomationPreview,
  summarizeProviderSetup,
} from './reviewQueueHelpers.js';

test('5-row E-Mart partial batch health shows exact operator counts and next action', () => {
  const summary = {
    raw_count: 5,
    ai_record_count: 5,
    eligible_count: 1,
    held_count: 4,
    blocked_count: 4,
    published_count: 0,
    unresolved_field_proposal_count: 34,
    unresolved_keyword_proposal_count: 7,
    batch_status: 'partial_only',
  };

  const cards = buildBatchHealth(summary, [], [], []);
  const byKey = Object.fromEntries(cards.map((card) => [card.key, card]));

  assert.equal(byKey.raw.value, 5);
  assert.equal(byKey.ai.value, 5);
  assert.equal(byKey.eligible.value, 1);
  assert.equal(byKey.held.value, 4);
  assert.equal(byKey.published.value, 0);
  assert.equal(byKey.unresolved.value, 41);
  assert.match(nextOperatorAction(summary, summarizeProviderSetup([])), /키워드/);
});

test('provider summary explains blocked LIVE failures without exposing secrets', () => {
  const summary = summarizeProviderSetup([
    {
      provider_id: 'gemini-prod',
      display_name: 'Gemini 운영',
      is_enabled: true,
      requires_secret: true,
      can_call_live: false,
      secret_alias: 'GEMINI_API_KEY',
      model_capability: { model_name: 'gemini-2.0', availability_status: 'missing_secret' },
    },
  ]);

  assert.equal(summary.blocked, 1);
  assert.equal(summary.liveReady, 0);
  assert.match(summary.failures[0].reason, /GEMINI_API_KEY/);
  assert.doesNotMatch(summary.failures[0].reason, /AIza|sk-/);
});

test('ops triage counters explain AI automation, suspicious rows, and rollback work', () => {
  const counters = buildOpsTriageCounters({
    auto_approved_count: 12,
    auto_approved_raw_count: 4,
    suspicious_count: 3,
    pending_db_review_count: 2,
    published_count: 1,
    publish_failed_count: 1,
    rolled_back_count: 1,
  });
  const byKey = Object.fromEntries(counters.map((card) => [card.key, card]));

  assert.equal(byKey['auto-approved'].value, 12);
  assert.match(byKey['auto-approved'].help, /DB 발행은 별도/);
  assert.equal(byKey.suspicious.value, 3);
  assert.match(byKey.suspicious.help, /가격·카테고리·누락/);
  assert.equal(byKey['post-publish-audit'].value, 3);
  assert.match(byKey['post-publish-audit'].help, /DB-admin/);
  assert.equal(byKey['rollback-rereview'].value, 5);
  assert.match(byKey['rollback-rereview'].help, /롤백·재발행/);
});

test('operator dashboard report surfaces blockers, anomaly buckets, and DB handoff work', () => {
  const report = buildOperatorDashboardReport({
    stats: {
      blocked_count: 2,
      held_count: 1,
      unresolved_field_proposal_count: 3,
      unresolved_keyword_proposal_count: 4,
      pending_db_review_count: 1,
      published_count: 2,
      publish_failed_count: 1,
    },
    publish_blockers: [
      { raw_record_id: 'raw-1', blockers: ['data_quality: price_mismatch_raw'] },
      { raw_record_id: 'raw-2', blockers: ['keyword: pending'] },
    ],
    publish_blocker_counts_by_reason: {
      'data_quality: price_mismatch_raw': 1,
      'keyword: pending': 1,
    },
    anomaly_summary: { suspicious_row_count: 5, retained_row_count: 8 },
    anomaly_buckets: [
      { code: 'price_mismatch_raw', count: 5, message: '가격 확인 필요' },
      { code: 'empty_bucket', count: 0, rows: [] },
    ],
  });
  const byKey = Object.fromEntries(report.cards.map((card) => [card.key, card]));

  assert.equal(byKey['publish-blockers'].value, 2);
  assert.equal(byKey['publish-blockers'].tone, 'err');
  assert.match(byKey['review-queue'].help, /필드 3 · 키워드 4/);
  assert.equal(byKey.anomalies.value, 5);
  assert.equal(byKey['db-handoff'].value, 4);
  assert.equal(report.topBlockers.length, 2);
  assert.deepEqual(report.topAnomalies.map((bucket) => bucket.code), ['price_mismatch_raw']);
});

test('bulk preview is concise and tied to real proposal identifiers', () => {
  const preview = buildBulkPreview([
    { proposal_id: 'p1', target_field: 'category_id', provenance: { raw_record_id: 'emart-1' } },
    { proposal_id: 'p2', target_field: 'keywords', provenance: { raw_record_id: 'emart-2' } },
  ]);

  assert.deepEqual(preview, [
    'p1 (emart-1: category_id)',
    'p2 (emart-2: keywords)',
  ]);
});

test('publish row actions distinguish retry from rollback to avoid operator mistakes', () => {
  assert.deepEqual(publishRowAction({ status: 'publish_failed', eligible: true }), {
    kind: 'retry',
    label: 'DB 발행 재시도',
    danger: false,
  });
  assert.deepEqual(publishRowAction({ status: 'published', db_ingestion_id: '777' }), {
    kind: 'rollback',
    label: '롤백 요청',
    danger: true,
  });
  assert.deepEqual(publishRowAction({ status: 'pending_db_review', db_ingestion_id: '778' }), {
    kind: 'rollback',
    label: 'DB 검수 대기/롤백',
    danger: true,
  });
  assert.deepEqual(publishRowAction({ status: 'approved', eligible: true, ai_safe_final_approve_eligible: true }), {
    kind: 'publish',
    label: '최종 승인 요청',
    danger: false,
  });
  assert.deepEqual(publishRowAction({ status: 'approved', eligible: true, ai_safe_final_approve_eligible: false }), {
    kind: 'publish',
    label: 'DB-admin 검수 큐로 발행',
    danger: false,
  });
  assert.equal(publishRowAction({ status: 'rolled_back' }).label, '롤백 요청됨');
});

test('publish and rollback confirmations preview exact rows and DB-admin consequences', () => {
  const rows = [
    { raw_record_id: 'emart-cabbage-800g', raw_title: '한끼 양배추 800g 통', retryable: false },
    { raw_record_id: 'emart-beef-300g', item: { name: '한우 불고기 300g' }, retryable: true },
  ];
  const publishMessage = buildPublishConfirmationMessage(rows, { blocked_count: 3 });
  assert.match(publishMessage, /emart-cabbage-800g/);
  assert.match(publishMessage, /emart-beef-300g/);
  assert.match(publishMessage, /DB-admin 최종 승인은 별도/);
  assert.match(publishMessage, /제출만으로는 공개 DB 저장이 아닙니다/);
  assert.match(publishMessage, /operator_final_approval_required/);
  assert.match(publishMessage, /pending_db_review/);
  assert.match(publishMessage, /보류\/차단 3개/);

  const rollbackMessage = buildRollbackConfirmationMessage({
    raw_record_id: 'emart-cabbage-800g',
    raw_title: '한끼 양배추 800g 통',
    db_ingestion_id: '777',
  });
  assert.match(rollbackMessage, /ingestion: 777/);
  assert.match(rollbackMessage, /승인하지 말고 reject\/delete/);
});

test('safe final approval copy is explicit and keeps DB review fallback visible', () => {
  const rows = [
    {
      raw_record_id: 'safe-final',
      raw_title: '오리온 오징어땅콩 98g',
      ai_safe_final_approve_eligible: true,
    },
    {
      raw_record_id: 'needs-db-review',
      raw_title: '서울우유 1L',
      ai_safe_final_approve_eligible: false,
    },
  ];
  const message = buildPublishConfirmationMessage(rows, {
    ai_safe_final_approve_count: 1,
    db_review_handoff_count: 1,
  });

  assert.match(message, /최종 승인 후보 1개 · DB 검수 큐 1개/);
  assert.match(message, /ai-safe-final-approve/);
  assert.match(message, /DB save complete/);
  assert.match(message, /실패하면 검수 큐 대기/);
  assert.match(nextOperatorAction({ eligible_count: 2, ai_safe_final_approve_count: 1 }, {}), /최종 승인 후보 1개/);
});

test('publish confirmation separates approved and held rows with no silent DB mutation copy', () => {
  const message = buildPublishConfirmationMessage([
    { raw_record_id: 'ready-1', ai_safe_final_approve_eligible: true },
  ], {
    approved_rows: [{ raw_record_id: 'ready-1' }],
    held_rows: [{ raw_record_id: 'held-1' }, { raw_record_id: 'held-2' }],
  });

  assert.match(message, /승인\/발행 가능 1개 · 보류\/차단 2개/);
  assert.match(message, /no silent DB mutation before final approve/);
});

test('automation preview and apply copy make dry-run and no-publish behavior explicit', () => {
  const preview = {
    eligible_count: 1,
    blocked_count: 2,
    candidate_count: 3,
    eligible_items: [
      {
        raw_record_id: 'emart-tofu',
        target_field: 'keywords',
        rule_id: 'exact_catalog_keyword',
        reason: 'exact active catalog keyword match',
        eligible: true,
      },
    ],
    blocked_items: [
      {
        raw_record_id: 'emart-milk',
        target_field: 'keywords',
        eligible: false,
        blockers: ['raw record is missing unit/package'],
      },
    ],
  };

  const summary = summarizeAutomationPreview(preview);
  assert.equal(summary.eligible, 1);
  assert.equal(summary.blocked, 2);
  assert.match(summary.help, /DB-admin 발행은 운영자가 별도로/);
  assert.match(explainAutomationRow(preview.blocked_items[0]), /missing unit\/package/);

  const message = buildAutomationApplyMessage(preview, 'exact_catalog_keyword');
  assert.match(message, /자동 승인/);
  assert.match(message, /rule id/);
  assert.match(message, /DB-admin 발행은 하지 않습니다/);
});

test('category helpers keep dot IDs stable while showing Korean labels', () => {
  assert.equal(categoryDisplayLabel('prepared_food.meal_kit'), '밀키트/델리');
  assert.equal(formatCategoryDisplay('seafood.frozen'), '수산/냉동 (seafood.frozen)');
  assert.equal(normalizeCategoryId('수산/냉동'), 'seafood.frozen');
  assert.equal(normalizeCategoryId('밀키트/델리'), 'prepared_food.meal_kit');
});

