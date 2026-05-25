/**
 * Pure helpers for the §4-E v5 undo toast. JSX-free so node:test can import them.
 */

export const DEFAULT_UNDO_WINDOW_MS = 30000;

export function remainingMs(pending, now) {
  if (!pending) return 0;
  return Math.max(0, pending.closesAt - now);
}

export function buildPendingState({ decisionId, label, onUndo, windowMs, now }) {
  const ttl = windowMs ?? DEFAULT_UNDO_WINDOW_MS;
  return {
    decisionId,
    label,
    onUndo,
    closesAt: (now ?? Date.now()) + ttl,
  };
}
