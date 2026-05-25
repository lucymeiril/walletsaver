import test from 'node:test';
import assert from 'node:assert/strict';

import {
  serializeFilters,
  describeFilters,
  classifyImpact,
  confirmMessage,
  undoCountdown,
} from './bulkArchiveHelpers.js';

test('serializeFilters drops empty arrays and converts dates to ISO', () => {
  const out = serializeFilters({
    statuses: [],
    proposal_types: ['keyword'],
    source_names: [],
    target_fields: [],
    created_before: '2025-01-01',
    created_after: '',
  });
  assert.deepEqual(Object.keys(out).sort(), ['created_before', 'proposal_types']);
  assert.equal(out.proposal_types[0], 'keyword');
  assert.ok(out.created_before.endsWith('Z'));
});

test('describeFilters returns Korean human summary or default text', () => {
  assert.equal(describeFilters({}), '전체 검수 대기·반려·보류 제안');
  assert.match(
    describeFilters({ statuses: ['ai_proposed'], proposal_types: ['keyword'] }),
    /상태.*ai_proposed.*타입.*keyword/,
  );
});

test('classifyImpact tier escalates by matched count', () => {
  assert.equal(classifyImpact(0).tone, 'muted');
  assert.equal(classifyImpact(50).tone, 'safe');
  assert.equal(classifyImpact(500).tone, 'warn');
  assert.equal(classifyImpact(34300).tone, 'danger');
});

test('confirmMessage shows pretty count and 30-second undo promise', () => {
  const msg = confirmMessage(34300, { proposal_types: ['keyword'] });
  assert.match(msg, /34,300건/);
  assert.match(msg, /타입 = keyword/);
  assert.match(msg, /30초/);
});

test('undoCountdown reports secondsLeft and expired correctly', () => {
  const now = new Date('2025-01-01T00:00:00Z');
  const future = new Date('2025-01-01T00:00:25Z').toISOString();
  const past = new Date('2024-12-31T23:59:50Z').toISOString();
  const live = undoCountdown({ expiresAt: future, now });
  assert.equal(live.secondsLeft, 25);
  assert.equal(live.expired, false);
  assert.ok(live.ratio > 0.8);
  const dead = undoCountdown({ expiresAt: past, now });
  assert.equal(dead.expired, true);
  assert.equal(dead.secondsLeft, 0);
});
