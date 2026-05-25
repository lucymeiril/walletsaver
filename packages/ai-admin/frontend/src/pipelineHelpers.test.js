import { test } from 'node:test';
import assert from 'node:assert/strict';
import { classifyError, pickNextStep, fmtNumberKR } from './pipelineHelpers.js';

test('classifyError returns null for falsy', () => {
  assert.equal(classifyError(null), null);
  assert.equal(classifyError(''), null);
});

test('classifyError detects network-down', () => {
  const r = classifyError(new TypeError('Failed to fetch'));
  assert.equal(r.kind, 'down');
  assert.match(r.label, /백엔드 끊김/);
});

test('classifyError detects 5xx server error', () => {
  const r = classifyError(new Error('HTTP 502'));
  assert.equal(r.kind, 'server');
  assert.match(r.label, /5xx/);
});

test('classifyError detects 401 auth error', () => {
  const r = classifyError(new Error('HTTP 401'));
  assert.equal(r.kind, 'auth');
});

test('classifyError catches 4xx client error', () => {
  const r = classifyError(new Error('HTTP 404'));
  assert.equal(r.kind, 'client');
});

test('pickNextStep — error first', () => {
  const r = pickNextStep({ errKind: 'down', rawCount: 100 });
  assert.equal(r.key, 'error');
  assert.equal(r.idx, -1);
});

test('pickNextStep — empty raw triggers crawl step', () => {
  const r = pickNextStep({ rawCount: 0 });
  assert.equal(r.key, 'crawl');
  assert.equal(r.idx, 0);
});

test('pickNextStep — raw exists but no proposals triggers AI', () => {
  const r = pickNextStep({ rawCount: 100, proposalCount: 0 });
  assert.equal(r.key, 'ai');
  assert.equal(r.idx, 1);
});

test('pickNextStep — audit missing forces AI step even with proposals', () => {
  const r = pickNextStep({ rawCount: 100, proposalCount: 50, auditMissing: 5 });
  assert.equal(r.key, 'ai');
});

test('pickNextStep — pending review goes to review step', () => {
  const r = pickNextStep({ rawCount: 100, proposalCount: 50, pendingReviewCount: 7 });
  assert.equal(r.key, 'review');
  assert.equal(r.idx, 2);
});

test('pickNextStep — failed jobs surface as next action', () => {
  const r = pickNextStep({ rawCount: 100, proposalCount: 50, pendingReviewCount: 0, failedJobs: 3 });
  assert.equal(r.key, 'failed');
});

test('pickNextStep — idle when everything green', () => {
  const r = pickNextStep({ rawCount: 100, proposalCount: 50, pendingReviewCount: 0, publishedCount: 30 });
  assert.equal(r.key, 'idle');
  assert.equal(r.idx, 3);
});

test('fmtNumberKR formats numbers and handles null', () => {
  assert.equal(fmtNumberKR(null), '—');
  assert.equal(fmtNumberKR(undefined), '—');
  assert.equal(fmtNumberKR(1234567), '1,234,567');
  assert.equal(fmtNumberKR('abc'), 'abc');
});
