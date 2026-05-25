import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  DEFAULT_UNDO_WINDOW_MS,
  buildPendingState,
  remainingMs,
} from './undoToastHelpers.js';

test('remainingMs returns 0 when nothing pending', () => {
  assert.equal(remainingMs(null, Date.now()), 0);
});

test('remainingMs returns positive remaining time', () => {
  assert.equal(remainingMs({ closesAt: 1500 }, 1000), 500);
});

test('remainingMs clamps to 0 after deadline', () => {
  assert.equal(remainingMs({ closesAt: 1500 }, 2000), 0);
});

test('buildPendingState picks default window when none given', () => {
  const p = buildPendingState({ decisionId: 'd', label: 'x', now: 0 });
  assert.equal(p.closesAt, DEFAULT_UNDO_WINDOW_MS);
  assert.equal(p.decisionId, 'd');
});

test('buildPendingState honours custom windowMs', () => {
  const p = buildPendingState({
    decisionId: 'd2', label: 'y', windowMs: 1000, now: 500,
  });
  assert.equal(p.closesAt, 1500);
});
