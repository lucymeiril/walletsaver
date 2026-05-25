import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import BulkArchiveDialog from './BulkArchiveDialog.jsx';

/**
 * 사용자 요구 "1-2 click 완료":
 *  - 카드 = AI 제안 + 신뢰도 + 1-click 승인/반려.
 *  - 키보드: J/K 이동, Enter 승인, X 반려, Shift+클릭 묶음 선택, A 묶음 승인.
 *  - 페이지네이션 대신 무한 스크롤 (한 번에 10건).
 */

const TYPE_LABEL = {
  normalized_field: '상품명/단위',
  canonical_match: '기존 상품 연결',
  category: '카테고리',
  keyword: '검색 키워드',
  alias: '별칭',
  attribute_definition: '속성 정의',
  attribute_value: '속성 값',
};
const STATUS_LABEL = {
  ai_proposed: '검수 대기',
  human_reviewing: '확인 중',
  approved: '승인',
  rejected: '반려',
};

const PAGE = 10;

function fmtConfidence(c) {
  if (c == null) return '—';
  const n = Number(c);
  if (!Number.isFinite(n)) return '—';
  const pct = Math.round(n * 100);
  return `${pct}%`;
}

function confidenceTone(c) {
  if (c == null) return 'muted';
  const n = Number(c);
  if (n >= 0.9) return 'safe';
  if (n >= 0.7) return 'warn';
  return 'danger';
}

function ProposalCard({ p, selected, focused, onClick, onApprove, onReject }) {
  const conf = p?.provenance?.confidence;
  return (
    <article
      className={`pcard ${focused ? 'pcard-focused' : ''} ${selected ? 'pcard-selected' : ''}`}
      onClick={onClick}
      tabIndex={-1}
      data-proposal-id={p.proposal_id}
    >
      <header className="pcard-head">
        <span className={`badge badge-${confidenceTone(conf)}`}>신뢰도 {fmtConfidence(conf)}</span>
        <span className="badge">{TYPE_LABEL[p.proposal_type] || p.proposal_type}</span>
        <span className="muted small">{STATUS_LABEL[p.status] || p.status}</span>
      </header>
      <div className="pcard-body">
        <div className="pcard-field">{p.target_field}</div>
        <div className="pcard-value">{typeof p.proposed_value === 'string' ? p.proposed_value : JSON.stringify(p.proposed_value)}</div>
        <div className="muted small">근거: {p.provenance?.evidence_text || '—'}</div>
      </div>
      <footer className="pcard-foot">
        <button
          type="button"
          className="btn btn-primary"
          onClick={(e) => {
            e.stopPropagation();
            onApprove(p);
          }}
        >
          승인 (Enter)
        </button>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={(e) => {
            e.stopPropagation();
            onReject(p);
          }}
        >
          반려 (X)
        </button>
      </footer>
    </article>
  );
}

export default function ReviewPage() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [shown, setShown] = useState(PAGE);
  const [focusIdx, setFocusIdx] = useState(0);
  const [selected, setSelected] = useState(() => new Set());
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState(null);
  const [showBulk, setShowBulk] = useState(false);
  const sentinelRef = useRef(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch('/api/review/proposals?status=ai_proposed');
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const body = await r.json();
      setItems(body.items || []);
      setShown(PAGE);
      setFocusIdx(0);
    } catch (err) {
      setError(err.message || '조회 실패');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const visible = useMemo(() => items.slice(0, shown), [items, shown]);

  // 무한 스크롤
  useEffect(() => {
    if (!sentinelRef.current) return undefined;
    const obs = new IntersectionObserver((entries) => {
      if (entries[0]?.isIntersecting) {
        setShown((s) => Math.min(items.length, s + PAGE));
      }
    });
    obs.observe(sentinelRef.current);
    return () => obs.disconnect();
  }, [items.length]);

  const flashToast = (msg) => {
    setToast(msg);
    setTimeout(() => setToast(null), 2500);
  };

  const approve = useCallback(async (p) => {
    setBusy(true);
    try {
      // start → approve
      await fetch(`/api/review/proposals/${p.proposal_id}/start`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reviewer_id: 'operator' }),
      });
      const r = await fetch(`/api/review/proposals/${p.proposal_id}/approve`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reviewer_id: 'operator', create_learning_rule: true }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setItems((prev) => prev.filter((x) => x.proposal_id !== p.proposal_id));
      flashToast(`승인: ${p.proposal_id}`);
    } catch (err) {
      flashToast(`승인 실패: ${err.message || err}`);
    } finally {
      setBusy(false);
    }
  }, []);

  const reject = useCallback(async (p) => {
    setBusy(true);
    try {
      await fetch(`/api/review/proposals/${p.proposal_id}/start`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reviewer_id: 'operator' }),
      });
      const r = await fetch(`/api/review/proposals/${p.proposal_id}/reject`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reviewer_id: 'operator', reason: '운영자 1-click 반려' }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setItems((prev) => prev.filter((x) => x.proposal_id !== p.proposal_id));
      flashToast(`반려: ${p.proposal_id}`);
    } catch (err) {
      flashToast(`반려 실패: ${err.message || err}`);
    } finally {
      setBusy(false);
    }
  }, []);

  const approveSelected = useCallback(async () => {
    const ids = [...selected];
    if (!ids.length) return;
    if (!window.confirm(`${ids.length}건을 일괄 승인합니다. 계속할까요?`)) return;
    setBusy(true);
    for (const id of ids) {
      const p = items.find((x) => x.proposal_id === id);
      if (p) await approve(p);
    }
    setSelected(new Set());
    setBusy(false);
  }, [selected, items, approve]);

  // 키보드 단축키
  useEffect(() => {
    const onKey = (e) => {
      if (e.target?.tagName === 'INPUT' || e.target?.tagName === 'TEXTAREA') return;
      if (showBulk) return;
      if (e.key === 'j' || e.key === 'ArrowDown') {
        e.preventDefault();
        setFocusIdx((i) => Math.min(visible.length - 1, i + 1));
      } else if (e.key === 'k' || e.key === 'ArrowUp') {
        e.preventDefault();
        setFocusIdx((i) => Math.max(0, i - 1));
      } else if (e.key === 'Enter') {
        e.preventDefault();
        const p = visible[focusIdx];
        if (p) approve(p);
      } else if (e.key === 'x' || e.key === 'X') {
        e.preventDefault();
        const p = visible[focusIdx];
        if (p) reject(p);
      } else if (e.key === 'a' || e.key === 'A') {
        e.preventDefault();
        approveSelected();
      } else if (e.key === ' ') {
        e.preventDefault();
        const p = visible[focusIdx];
        if (p) {
          setSelected((prev) => {
            const next = new Set(prev);
            if (next.has(p.proposal_id)) next.delete(p.proposal_id); else next.add(p.proposal_id);
            return next;
          });
        }
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [visible, focusIdx, approve, reject, approveSelected, showBulk]);

  const handleCardClick = (p, idx, ev) => {
    if (ev.shiftKey) {
      setSelected((prev) => {
        const next = new Set(prev);
        if (next.has(p.proposal_id)) next.delete(p.proposal_id); else next.add(p.proposal_id);
        return next;
      });
    }
    setFocusIdx(idx);
  };

  return (
    <div className="review-page">
      {/* 페이지 설명 */}
      <p className="page-desc muted small">
        AI가 제안한 정규화·분류 항목을 1-click으로 승인/반려합니다.
        키보드 단축키 <kbd>J</kbd>/<kbd>K</kbd>로 이동, <kbd>Enter</kbd> 승인, <kbd>X</kbd> 반려.
      </p>
      <div className="review-head">
        <h2>검수 대기 {items.length.toLocaleString()}건</h2>
        <div className="review-actions">
          <button className="btn btn-secondary" onClick={refresh} disabled={loading}>↻ 새로고침</button>
          <button
            className="btn btn-danger"
            onClick={() => setShowBulk(true)}
            title="AI 제안 전체 또는 조건부 비우기"
          >
            🗑 AI 제안 비우기…
          </button>
          <button className="btn btn-primary" onClick={approveSelected} disabled={selected.size === 0 || busy}>
            선택 {selected.size}건 묶음 승인 (A)
          </button>
        </div>
      </div>

      <div className="shortcuts muted small">
        키보드: <kbd>J</kbd>/<kbd>K</kbd> 이동 · <kbd>Enter</kbd> 승인 · <kbd>X</kbd> 반려 · <kbd>Space</kbd> 선택 · <kbd>A</kbd> 묶음 승인
      </div>

      {error && <div className="alert alert-err">{error}</div>}

      {!loading && items.length === 0 && (
        <div className="empty">검수 대기 큐가 비어있습니다.</div>
      )}

      <div className="pcard-list" role="list">
        {visible.map((p, idx) => (
          <ProposalCard
            key={p.proposal_id}
            p={p}
            focused={idx === focusIdx}
            selected={selected.has(p.proposal_id)}
            onClick={(ev) => handleCardClick(p, idx, ev)}
            onApprove={approve}
            onReject={reject}
          />
        ))}
        <div ref={sentinelRef} className="sentinel" aria-hidden />
        {shown < items.length && <div className="muted small">… 더 불러오는 중 ({shown}/{items.length})</div>}
      </div>

      {toast && <div className="toast" role="status">{toast}</div>}

      <BulkArchiveDialog open={showBulk} onClose={() => setShowBulk(false)} onArchived={refresh} />
    </div>
  );
}
