import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  callProcessMissing,
  runProcessMissingLoop,
  formatProcessMissingLabel,
} from './advancedHelpers.js';

function mockFetch(scriptedResponses) {
  const calls = [];
  let i = 0;
  const fetchImpl = async (url, init) => {
    calls.push({ url, init: init && { ...init, body: JSON.parse(init.body) } });
    const r = scriptedResponses[Math.min(i, scriptedResponses.length - 1)];
    i += 1;
    return {
      ok: r.ok ?? true,
      status: r.status ?? 200,
      json: async () => r.body,
    };
  };
  return { fetchImpl, calls };
}

test('callProcessMissing posts to /api/ingest/process-missing with provider_id+limit', async () => {
  const { fetchImpl, calls } = mockFetch([
    { body: { ok: true, processed: 3, proposals_created: 6, missing_remaining: 0, errors: [] } },
  ]);
  const body = await callProcessMissing({ providerId: 'google-dev', limit: 30, fetchImpl });
  assert.equal(body.processed, 3);
  assert.equal(body.missing_remaining, 0);
  assert.equal(calls[0].url, '/api/ingest/process-missing');
  assert.equal(calls[0].init.body.provider_id, 'google-dev');
  assert.equal(calls[0].init.body.limit, 30);
  assert.equal(calls[0].init.body.dry_run, false);
});

test('callProcessMissing throws humanized error on 422 validation', async () => {
  const detail = [
    { loc: ['body', 'role'], msg: "Input should be 'normalizer'…", type: 'enum' },
  ];
  const { fetchImpl } = mockFetch([{ ok: false, status: 422, body: { detail } }]);
  await assert.rejects(
    () => callProcessMissing({ providerId: 'p', fetchImpl }),
    (err) => {
      assert.equal(err.status, 422);
      // 절대 [object Object] 가 나오면 안 된다.
      assert.ok(!/\[object Object\]/.test(err.message), `humanized: ${err.message}`);
      assert.match(err.message, /role/);
      return true;
    },
  );
});

test('callProcessMissing throws on 504 timeout with body message', async () => {
  const { fetchImpl } = mockFetch([{ ok: false, status: 504, body: { detail: 'timed out after 600s' } }]);
  await assert.rejects(
    () => callProcessMissing({ providerId: 'p', fetchImpl }),
    (err) => {
      assert.equal(err.status, 504);
      assert.match(err.message, /timed out/);
      return true;
    },
  );
});

test('callProcessMissing throws "HTTP 502" when body has no detail (connection)', async () => {
  const { fetchImpl } = mockFetch([{ ok: false, status: 502, body: {} }]);
  await assert.rejects(
    () => callProcessMissing({ providerId: 'p', fetchImpl }),
    (err) => err.status === 502 && /HTTP 502/.test(err.message),
  );
});

test('runProcessMissingLoop iterates until missing_remaining=0', async () => {
  const { fetchImpl, calls } = mockFetch([
    { body: { ok: true, processed: 30, proposals_created: 50, missing_remaining: 25, errors: [] } },
    { body: { ok: true, processed: 25, proposals_created: 40, missing_remaining: 0, errors: [] } },
  ]);
  const progress = [];
  const result = await runProcessMissingLoop({
    providerId: 'p',
    limit: 30,
    fetchImpl,
    onProgress: (s) => progress.push(s),
  });
  assert.equal(result.iterations, 2);
  assert.equal(result.processedTotal, 55);
  assert.equal(result.proposalsTotal, 90);
  assert.equal(result.missingRemaining, 0);
  assert.equal(calls.length, 2);
  assert.equal(progress.length, 2);
});

test('runProcessMissingLoop respects abortSignal mid-loop', async () => {
  const { fetchImpl } = mockFetch([
    { body: { ok: true, processed: 30, proposals_created: 30, missing_remaining: 100, errors: [] } },
  ]);
  let cancelAfterFirst = false;
  const result = await runProcessMissingLoop({
    providerId: 'p',
    fetchImpl,
    abortSignal: () => cancelAfterFirst,
    onProgress: () => { cancelAfterFirst = true; },
  });
  assert.equal(result.aborted, true);
  assert.equal(result.iterations, 1);
  assert.equal(result.processedTotal, 30);
});

test('runProcessMissingLoop stops if processed=0 to avoid infinite loop', async () => {
  const { fetchImpl } = mockFetch([
    { body: { ok: true, processed: 0, proposals_created: 0, missing_remaining: 5, errors: [] } },
  ]);
  const result = await runProcessMissingLoop({ providerId: 'p', fetchImpl });
  assert.equal(result.iterations, 1);
  assert.equal(result.missingRemaining, 5);
});

test('formatProcessMissingLabel renders progress with initial total', () => {
  const label = formatProcessMissingLabel({ processedTotal: 30, missingRemaining: 931, initialMissing: 961 });
  assert.match(label, /30\/961/);
  assert.match(label, /남음 931/);
});
