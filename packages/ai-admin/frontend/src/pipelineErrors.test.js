import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  classifyPipelineError,
  humanizeDetail,
  computeJobProgress,
  fmtEta,
} from './pipelineErrors.js';

test('classifyPipelineError returns null for falsy', () => {
  assert.equal(classifyPipelineError(null), null);
  assert.equal(classifyPipelineError(''), null);
  assert.equal(classifyPipelineError(undefined), null);
});

test('classifyPipelineError: Failed to fetch → down', () => {
  const r = classifyPipelineError(new TypeError('Failed to fetch'));
  assert.equal(r.kind, 'down');
  assert.match(r.label, /백엔드 끊김/);
  assert.match(r.next, /R/);
});

test('classifyPipelineError: HTTP 504 → timeout', () => {
  const r = classifyPipelineError(new Error('HTTP 504'));
  assert.equal(r.kind, 'timeout');
  assert.match(r.hint, /batch size/);
});

test('classifyPipelineError: "timed out after 600s" → timeout (no status)', () => {
  const r = classifyPipelineError('failed to call ai-admin ingest endpoint: timed out after 600s');
  assert.equal(r.kind, 'timeout');
});

test('classifyPipelineError: HTTP 502 → connection', () => {
  const r = classifyPipelineError(new Error('HTTP 502'));
  assert.equal(r.kind, 'connection');
});

test('classifyPipelineError: ECONNREFUSED → connection', () => {
  const r = classifyPipelineError(new Error('connect ECONNREFUSED 127.0.0.1:8200'));
  assert.equal(r.kind, 'connection');
});

test('classifyPipelineError: HTTP 401 → auth', () => {
  const r = classifyPipelineError(new Error('HTTP 401 Unauthorized'));
  assert.equal(r.kind, 'auth');
  assert.match(r.hint, /API 키/);
});

test('classifyPipelineError: invalid api key text → auth', () => {
  const r = classifyPipelineError('invalid API key supplied');
  assert.equal(r.kind, 'auth');
});

test('classifyPipelineError: HTTP 429 / quota → quota', () => {
  assert.equal(classifyPipelineError(new Error('HTTP 429')).kind, 'quota');
  assert.equal(classifyPipelineError('Provider quota exceeded').kind, 'quota');
  assert.equal(classifyPipelineError('rate-limit hit').kind, 'quota');
});

test('classifyPipelineError: HTTP 422 → validation', () => {
  const r = classifyPipelineError(new Error('HTTP 422'));
  assert.equal(r.kind, 'validation');
});

test('classifyPipelineError: HTTP 500 (not timeout/connection) → provider_500', () => {
  const r = classifyPipelineError(new Error('HTTP 500 Internal Server Error'));
  assert.equal(r.kind, 'provider_500');
});

test('classifyPipelineError: HTTP 503 → provider_500', () => {
  assert.equal(classifyPipelineError(new Error('HTTP 503')).kind, 'provider_500');
});

test('classifyPipelineError: unclassified 4xx → other', () => {
  assert.equal(classifyPipelineError(new Error('HTTP 418 I am a teapot')).kind, 'other');
});

test('classifyPipelineError: status object form', () => {
  const r = classifyPipelineError({ status: 504, detail: 'timed out' });
  assert.equal(r.kind, 'timeout');
});

test('humanizeDetail: plain string passes through', () => {
  assert.equal(humanizeDetail('boom'), 'boom');
});

test('humanizeDetail: dict { message } → message string (no [object Object])', () => {
  // 사용자 비판 정확히 이 케이스. [object Object] 가 나오면 안 됨.
  const out = humanizeDetail({ message: 'provider quota exceeded', provider_id: 'gemma' });
  assert.equal(out, 'provider quota exceeded');
  assert.ok(!/\[object Object\]/.test(out));
});

test('humanizeDetail: dict without message → JSON', () => {
  const out = humanizeDetail({ a: 1, b: 'x' });
  assert.ok(!/\[object Object\]/.test(out));
  assert.match(out, /"a":1/);
});

test('humanizeDetail: FastAPI 422 list', () => {
  const out = humanizeDetail([
    { loc: ['body', 'timeout_seconds'], msg: 'ensure this value is less than or equal to 1800', type: 'value_error' },
  ]);
  assert.match(out, /body\.timeout_seconds/);
  assert.match(out, /1800/);
});

test('humanizeDetail: Error instance', () => {
  assert.equal(humanizeDetail(new Error('e')), 'e');
});

test('computeJobProgress: zero state', () => {
  const p = computeJobProgress(null);
  assert.equal(p.percent, 0);
  assert.equal(p.done, false);
});

test('computeJobProgress: 50% midway', () => {
  const p = computeJobProgress({ processed_count: 5, total_count: 10, status: 'running' });
  assert.equal(p.percent, 50);
  assert.equal(p.done, false);
  assert.equal(p.failed, false);
});

test('computeJobProgress: ETA computed from elapsed', () => {
  const started = new Date(Date.now() - 60_000).toISOString();
  const p = computeJobProgress({
    processed_count: 4,
    total_count: 8,
    status: 'running',
    started_at: started,
  });
  assert.equal(p.percent, 50);
  assert.ok(p.avgSecPerItem != null && p.avgSecPerItem > 0);
  assert.ok(p.etaSec != null && p.etaSec > 0);
});

test('computeJobProgress: completed flag', () => {
  const p = computeJobProgress({ status: 'completed', processed_count: 10, total_count: 10 });
  assert.equal(p.done, true);
  assert.equal(p.percent, 100);
});

test('computeJobProgress: failed flag', () => {
  assert.equal(computeJobProgress({ status: 'failed' }).failed, true);
  assert.equal(computeJobProgress({ status: 'dead_letter' }).failed, true);
});

test('fmtEta: nullish', () => {
  assert.equal(fmtEta(null), '—');
  assert.equal(fmtEta(0), '—');
});

test('fmtEta: under a minute', () => {
  assert.match(fmtEta(45), /~45s/);
});

test('fmtEta: minutes + seconds', () => {
  assert.match(fmtEta(125), /~2m05s/);
});

test('fmtEta: hours', () => {
  assert.match(fmtEta(3700), /~1h/);
});
