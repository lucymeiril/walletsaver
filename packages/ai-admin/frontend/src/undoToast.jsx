/**
 * §4-E v5 — 5-second undo toast hook.
 *
 * Usage:
 *   const undo = useUndoToast();
 *   // ... after a decision succeeds
 *   undo.open({ decisionId, label: '카테고리 변경됨', onUndo, windowMs: 5000 });
 *
 * The component returns `{ open, close, toast }`. Render `{undo.toast}` in your
 * panel; it is `null` when nothing is pending.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { DEFAULT_UNDO_WINDOW_MS, buildPendingState } from './undoToastHelpers.js';

export function useUndoToast() {
  const [pending, setPending] = useState(null);
  const timerRef = useRef(null);

  const close = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    setPending(null);
  }, []);

  const open = useCallback(({ decisionId, label, onUndo, windowMs }) => {
    if (timerRef.current) clearTimeout(timerRef.current);
    const ttl = windowMs ?? DEFAULT_UNDO_WINDOW_MS;
    setPending(buildPendingState({ decisionId, label, onUndo, windowMs: ttl }));
    timerRef.current = setTimeout(() => {
      setPending(null);
      timerRef.current = null;
    }, ttl);
  }, []);

  useEffect(() => () => {
    if (timerRef.current) clearTimeout(timerRef.current);
  }, []);

  const onClickUndo = useCallback(async () => {
    if (!pending) return;
    try {
      await pending.onUndo(pending.decisionId);
    } finally {
      close();
    }
  }, [pending, close]);

  const toast = pending ? (
    <div
      className="undo-toast"
      role="status"
      aria-live="polite"
      style={{
        position: 'fixed', bottom: 24, right: 24, zIndex: 1000,
        padding: '12px 16px', background: '#222', color: '#fff',
        borderRadius: 8, display: 'flex', gap: 12, alignItems: 'center',
        boxShadow: '0 4px 16px rgba(0,0,0,0.25)',
      }}
    >
      <span>{pending.label}</span>
      <button
        type="button"
        onClick={onClickUndo}
        style={{
          background: '#ffcc00', color: '#222', border: 'none',
          padding: '6px 12px', borderRadius: 4, cursor: 'pointer',
          fontWeight: 600,
        }}
      >
        되돌리기 (30초)
      </button>
    </div>
  ) : null;

  return { open, close, toast, pending };
}

