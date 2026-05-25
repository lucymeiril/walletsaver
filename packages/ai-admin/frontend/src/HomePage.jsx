import { useCallback, useEffect, useMemo, useState } from 'react';
import BulkArchiveDialog from './BulkArchiveDialog.jsx';
import {
  summarizeReviewQueue,
  countRecentPublished,
  nextActions,
  buildHomeKpis,
} from './homeHelpers.js';

/**
 * 홈: "지금 해야 할 단 한 가지". 카드 3개 + 다음 액션 1~2개 + 비우기 진입.
 */
export default function HomePage({ onGoReview, onGoAdvanced }) {
  const [proposals, setProposals] = useState([]);
  const [matchSummary, setMatchSummary] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showBulk, setShowBulk] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [pRes, mRes] = await Promise.all([
        fetch('/api/review/proposals'),
        fetch('/api/match-monitor/summary').catch(() => null),
      ]);
      if (!pRes.ok) throw new Error(`proposals HTTP ${pRes.status}`);
      const pBody = await pRes.json();
      setProposals(pBody.items || []);
      if (mRes && mRes.ok) {
        const mBody = await mRes.json();
        setMatchSummary({ auto_matched_week: mBody?.auto_matched_week ?? mBody?.total ?? 0 });
      }
    } catch (err) {
      setError(err.message || '조회 실패');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const counts = useMemo(() => summarizeReviewQueue(proposals), [proposals]);
  const publishedRecent = useMemo(() => countRecentPublished(proposals), [proposals]);
  const actions = useMemo(
    () => nextActions({ backendDown: false, counts }),
    [counts],
  );
  const kpis = useMemo(
    () => buildHomeKpis({ counts, publishedRecent, matchSummary }),
    [counts, publishedRecent, matchSummary],
  );

  const handleAction = (action) => {
    if (action.target === 'bulk-archive') setShowBulk(true);
    else if (action.target === 'review') onGoReview?.();
    else if (action.target?.startsWith('advanced')) onGoAdvanced?.(action.target);
  };

  return (
    <div className="home">
      {/* 페이지 설명 — 운영자가 지금 해야 할 것만 보여주는 대시보드 */}
      <p className="page-desc muted small">
        AI 제안 큐 상태와 다음 액션을 한눈에 확인하세요. 검수가 필요한 경우 검수 탭으로 이동합니다.
      </p>
      <section className="hero">
        <div className="hero-head">
          <h2>지금 해야 할 것</h2>
          <button className="link-btn" onClick={refresh} disabled={loading}>
            {loading ? '새로고침 중…' : '↻ 새로고침'}
          </button>
        </div>
        {error && <div className="alert alert-err">{error}</div>}
        <div className="hero-actions">
          {actions.map((a) => (
            <button
              key={a.id}
              type="button"
              className={`hero-action hero-action-${a.tone}`}
              onClick={() => handleAction(a)}
              disabled={a.tone === 'muted'}
            >
              {a.label}
            </button>
          ))}
        </div>
      </section>

      <section className="kpis">
        {kpis.map((k) => (
          <button
            key={k.id}
            type="button"
            className="kpi"
            onClick={() => {
              if (k.target === 'review') onGoReview?.();
              else if (k.target?.startsWith('advanced')) onGoAdvanced?.(k.target);
            }}
            disabled={!k.target}
          >
            <div className="kpi-label">{k.label}</div>
            <div className="kpi-value">{(k.value || 0).toLocaleString()}</div>
            <div className="kpi-hint">{k.hint}</div>
          </button>
        ))}
      </section>

      <section className="home-tools">
        <button type="button" className="btn btn-secondary" onClick={() => setShowBulk(true)}>
          AI 제안 비우기…
        </button>
        <button type="button" className="btn btn-secondary" onClick={() => onGoAdvanced?.('advanced-jobs')}>
          AI 처리 가동(고급)…
        </button>
        <div className="muted small">큐 총 {counts.total.toLocaleString()}건 · 검토 필요 {counts.review_needed.toLocaleString()}건 · 발행 대기 {counts.approved.toLocaleString()}건</div>
      </section>

      <BulkArchiveDialog
        open={showBulk}
        onClose={() => setShowBulk(false)}
        onArchived={() => refresh()}
      />
    </div>
  );
}
