import test from 'node:test';
import assert from 'node:assert/strict';

import {
  buildAutomationApplyMessage,
  buildBatchHealth,
  buildBulkPreview,
  buildPublishConfirmationMessage,
  buildRollbackConfirmationMessage,
  explainAutomationRow,
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
  assert.match(publishMessage, /보류\/차단 3개/);

  const rollbackMessage = buildRollbackConfirmationMessage({
    raw_record_id: 'emart-cabbage-800g',
    raw_title: '한끼 양배추 800g 통',
    db_ingestion_id: '777',
  });
  assert.match(rollbackMessage, /ingestion: 777/);
  assert.match(rollbackMessage, /승인하지 말고 reject\/delete/);
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
        blockers: ['raw record is missing image'],
      },
    ],
  };

  const summary = summarizeAutomationPreview(preview);
  assert.equal(summary.eligible, 1);
  assert.equal(summary.blocked, 2);
  assert.match(summary.help, /DB-admin 발행은 운영자가 별도로/);
  assert.match(explainAutomationRow(preview.blocked_items[0]), /missing image/);

  const message = buildAutomationApplyMessage(preview, 'exact_catalog_keyword');
  assert.match(message, /자동 승인/);
  assert.match(message, /rule id/);
  assert.match(message, /DB-admin 발행은 하지 않습니다/);
});
