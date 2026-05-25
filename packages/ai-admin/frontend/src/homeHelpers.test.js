import test from 'node:test';
import assert from 'node:assert/strict';

import {
  summarizeReviewQueue,
  countRecentPublished,
  nextActions,
  buildHomeKpis,
} from './homeHelpers.js';

test('summarizeReviewQueue counts statuses including review_needed combined bucket', () => {
  const r = summarizeReviewQueue([
    { status: 'ai_proposed' },
    { status: 'ai_proposed' },
    { status: 'human_reviewing' },
    { status: 'approved' },
    { status: 'published' },
    { status: 'rejected' },
  ]);
  assert.equal(r.ai_proposed, 2);
  assert.equal(r.human_reviewing, 1);
  assert.equal(r.review_needed, 3);
  assert.equal(r.approved, 1);
  assert.equal(r.published_total, 1);
  assert.equal(r.total, 6);
});

test('countRecentPublished only counts published items within window', () => {
  const now = new Date('2025-01-31T00:00:00Z');
  const items = [
    { status: 'published', decided_at: '2025-01-30T00:00:00Z' },
    { status: 'published', decided_at: '2024-11-01T00:00:00Z' },
    { status: 'approved', decided_at: '2025-01-30T00:00:00Z' },
    { status: 'published' },
  ];
  assert.equal(countRecentPublished(items, now, 30), 1);
});

test('nextActions returns reconnect when backend down', () => {
  const a = nextActions({ backendDown: true, counts: { review_needed: 5 } });
  assert.equal(a.length, 1);
  assert.equal(a[0].id, 'reconnect');
});

test('nextActions surfaces bulk-archive when queue exceeds 50', () => {
  const a = nextActions({ backendDown: false, counts: { review_needed: 34300 } });
  assert.equal(a[0].id, 'bulk-archive');
  assert.match(a[0].label, /34,300/);
  assert.equal(a[1].id, 'open-review');
});

test('nextActions falls back to publish or idle when nothing to review', () => {
  assert.equal(
    nextActions({ counts: { review_needed: 0, approved: 7 } })[0].id,
    'publish'
  );
  assert.equal(
    nextActions({ counts: { review_needed: 0, approved: 0 } })[0].id,
    'idle'
  );
});

test('buildHomeKpis returns exactly 3 cards mapped to user-meaningful labels', () => {
  const kpis = buildHomeKpis({
    counts: { review_needed: 12, approved: 3 },
    publishedRecent: 80,
    matchSummary: { auto_matched_week: 145 },
  });
  assert.equal(kpis.length, 3);
  assert.deepEqual(
    kpis.map((k) => k.id),
    ['review-needed', 'published-recent', 'auto-matched'],
  );
  assert.equal(kpis[0].value, 12);
  assert.equal(kpis[1].value, 80);
  assert.equal(kpis[2].value, 145);
});
