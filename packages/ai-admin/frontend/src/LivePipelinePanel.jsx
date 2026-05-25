import { useCallback, useEffect, useMemo, useState } from 'react';
import { classifyError, pickNextStep, fmtNumberKR as fmt } from './pipelineHelpers.js';

/**
 * 사용자 비판 해소:
 *  - "동일 워크플로 4중 중복" → 단일 파이프 (수집 → AI → 발행) 1개로 통합
 *  - "묶음 처리 진입점 불명" → hero 위치 최상단 3-step 버튼
 *  - "정보 과부하" → 50개 카드 → 3 step + 5개 메트릭 으로 압축
 *  - "고급/초보 분리 실패" → 전문 용어는 tooltip(title)으로 빠짐
 */

const STEP_TITLES = ['1. 수집', '2. AI 처리', '3. 발행'];

async function fetchJson(url) {
  const res = await fetch(url, { cache: 'no-store' });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    // rd4-error-display-fix: detail dict → [object Object] 방지.
    const d = body && body.detail;
    if (typeof d === 'string') throw new Error(d);
    if (d && typeof d === 'object') throw new Error(d.message || d.detail || JSON.stringify(d));
    throw new Error(`HTTP ${res.status}`);
  }
  return body;
}

export default function LivePipelinePanel({ onGoToReview, onGoToAdvanced }) {
  const [state, setState] = useState({
    loading: true,
    error: null,
    rawCount: 0,
    proposalCount: 0,
    pendingReviewCount: 0,
    publishedCount: 0,
    failedJobs: 0,
    queuedJobs: 0,
    runningJobs: 0,
    liveProviderCount: 0,
    enabledProviderCount: 0,
    auditMissing: 0,
  });
  const [enqueueState, setEnqueueState] = useState({ busy: false, msg: null, ok: null });

  const refresh = useCallback(async () => {
    setState((p) => ({ ...p, loading: true, error: null }));
    try {
      const [audit, proposals, jobs, setup] = await Promise.all([
        fetchJson('/api/review/audit'),
        fetchJson('/api/review/proposals'),
        fetchJson('/api/jobs'),
        fetchJson('/api/providers/setup-state'),
      ]);
      const props = proposals.items || [];
      const jobsArr = jobs.jobs || [];
      const providers = setup.providers || [];
      const byStatus = (arr, key) =>
        arr.reduce((acc, item) => {
          const k = item[key] || 'unknown';
          acc[k] = (acc[k] || 0) + 1;
          return acc;
        }, {});
      const ps = byStatus(props, 'status');
      const js = byStatus(jobsArr, 'status');
      setState({
        loading: false,
        error: null,
        rawCount: audit?.raw_record_count ?? audit?.total_records ?? 0,
        proposalCount: props.length,
        pendingReviewCount: (ps.ai_proposed || 0) + (ps.human_reviewing || 0) + (ps.pending_review || 0),
        publishedCount: ps.published || 0,
        failedJobs: (js.failed || 0) + (js.dead_letter || 0),
        queuedJobs: js.queued || 0,
        runningJobs: js.running || 0,
        liveProviderCount: providers.filter((p) => p.can_call_live).length,
        enabledProviderCount: providers.filter((p) => p.is_enabled).length,
        auditMissing: audit?.missing_record_count || 0,
      });
    } catch (err) {
      setState((p) => ({ ...p, loading: false, error: err }));
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const errInfo = useMemo(() => classifyError(state.error), [state.error]);

  // rd5-process-missing-fix: 'product_match_propose' 는 AIWorkerRole enum 에 없는
  // 값이라 /api/jobs 422 를 유발했다. legacy 파일이지만 사용자 직격 방지를 위해
  // 신규 process-missing 엔드포인트로 교체한다. role enum 값 (예: classifier) 으로
  // 만든 단순 enqueue 는 실제 라벨링 워커 가동을 보장하지 않는다.
  const handleEnqueueAI = useCallback(async () => {
    setEnqueueState({ busy: true, msg: '처리 중…', ok: null });
    try {
      const res = await fetch('/api/ingest/process-missing', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider_id: 'google-dev', limit: 30 }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        const detail = body && body.detail;
        let msg;
        if (typeof detail === 'string') {
          msg = detail;
        } else if (detail && typeof detail === 'object') {
          msg = detail.message || detail.detail || JSON.stringify(detail);
        } else {
          msg = `HTTP ${res.status}`;
        }
        throw new Error(msg);
      }
      const body = await res.json();
      setEnqueueState({
        busy: false,
        ok: true,
        msg: `처리 완료: ${body.processed || 0}건 (제안 ${body.proposals_created || 0})`,
      });
      refresh();
    } catch (err) {
      setEnqueueState({ busy: false, ok: false, msg: `처리 실패: ${err.message}` });
    }
  }, [refresh]);

  const nextStep = useMemo(() => {
    const pick = pickNextStep({
      errKind: errInfo?.kind,
      rawCount: state.rawCount,
      proposalCount: state.proposalCount,
      pendingReviewCount: state.pendingReviewCount,
      publishedCount: state.publishedCount,
      failedJobs: state.failedJobs,
      auditMissing: state.auditMissing,
    });
    const handlers = {
      error: () => refresh(),
      crawl: () => window.open('http://localhost:5174', '_blank'),
      ai: handleEnqueueAI,
      review: onGoToReview,
      failed: () => onGoToAdvanced?.('#advanced-jobs'),
      idle: refresh,
    };
    const labelOverride = errInfo
      ? errInfo.label
      : pick.key === 'crawl'
        ? '원본(raw)이 없습니다 — crawler-admin에서 수집을 먼저 실행하세요.'
        : pick.key === 'ai'
          ? `AI 제안이 ${state.auditMissing > 0 ? '부족' : '없음'} — AI 처리를 가동하세요.`
          : pick.key === 'review'
            ? `${state.pendingReviewCount}건이 검수/발행 대기 — 묶음 처리하세요.`
            : pick.key === 'failed'
              ? `${state.failedJobs}개 실패 잡 — 고급 → Jobs에서 원인 확인.`
              : `발행 완료 ${fmt(state.publishedCount)}건. 새 데이터가 들어오면 자동으로 다음 단계가 표시됩니다.`;
    return {
      idx: pick.idx,
      key: pick.key,
      label: labelOverride,
      action: pick.action,
      go: handlers[pick.key] || refresh,
    };
  }, [errInfo, state, refresh, handleEnqueueAI, onGoToReview, onGoToAdvanced]);

  const stepStatuses = [
    state.rawCount > 0 ? 'done' : 'todo',
    state.proposalCount > 0 ? (state.auditMissing > 0 ? 'partial' : 'done') : 'todo',
    state.publishedCount > 0 ? 'done' : state.pendingReviewCount > 0 ? 'todo' : 'idle',
  ];
  if (nextStep.idx >= 0) stepStatuses[nextStep.idx] = 'active';

  return (
    <section className="panel pipeline-panel" data-testid="pipeline-panel">
      <div className="row pipeline-header">
        <div>
          <h2>라이브 파이프라인</h2>
          <div className="muted">수집 → AI → 발행. 한 줄, 한 버튼, 한 흐름.</div>
        </div>
        <button
          className="primary-button"
          type="button"
          onClick={refresh}
          disabled={state.loading}
          data-testid="pipeline-refresh"
        >
          {state.loading ? '확인 중…' : '상태 새로고침'}
        </button>
      </div>

      {/* 한 줄 next-action — 사용자 헌법: "딸깍 3번에 라이브 가동" 진입점 */}
      <div
        className={`next-action ${errInfo ? 'next-action-err' : ''}`}
        data-testid="next-action"
      >
        <span
          className={`badge ${errInfo ? 'err' : nextStep.idx === 3 ? 'ok' : 'warn'}`}
          data-testid="next-action-badge"
        >
          {errInfo ? '문제' : nextStep.idx === 3 ? '정상' : `다음: ${STEP_TITLES[nextStep.idx] || '확인'}`}
        </span>
        {/* 2026-05-25 보류: AI 라이브 파이프라인 비활성화 배지 */}
        {nextStep.idx === 1 && (
          <span className="badge deprecated" style={{ marginLeft: 6 }}>
            🚧 보류 — 외부 분류 워크플로우 사용
          </span>
        )}
        <div>
          <strong>{nextStep.label}</strong>
          {enqueueState.msg && (
            <div className={`muted ${enqueueState.ok === false ? 'text-err' : ''}`}>
              {enqueueState.msg}
            </div>
          )}
        </div>
        <button
          type="button"
          className="primary-button"
          onClick={nextStep.go}
          disabled={enqueueState.busy || nextStep.idx === 1}
          data-testid="next-action-button"
        >
          {enqueueState.busy ? '실행 중…' : nextStep.action}
        </button>
      </div>

      {/* 3-step progress — 단일 파이프, 4중 중복 제거 */}
      <ol className="pipeline-steps" data-testid="pipeline-steps">
        {STEP_TITLES.map((title, i) => (
          <li
            key={title}
            className={`pipeline-step pipeline-step-${stepStatuses[i]}`}
            data-testid={`pipeline-step-${i}`}
          >
            <div className="pipeline-step-num">{i + 1}</div>
            <div className="pipeline-step-body">
              <div className="pipeline-step-title">{title.replace(/^\d+\.\s*/, '')}</div>
              <div className="pipeline-step-meta">
                {i === 0 && <>raw {fmt(state.rawCount)} · 누락 {fmt(state.auditMissing)}</>}
                {i === 1 && (
                  <>제안 {fmt(state.proposalCount)} · 실행 {fmt(state.runningJobs)} · 대기 {fmt(state.queuedJobs)} · 실패 {fmt(state.failedJobs)}</>
                )}
                {i === 2 && (
                  <>검수 대기 {fmt(state.pendingReviewCount)} · 발행 {fmt(state.publishedCount)}</>
                )}
              </div>
            </div>
          </li>
        ))}
      </ol>

      {/* 펼쳐야 보이는 고급 정보 (전문 용어) — 3-tier 정보 밀도 */}
      <details className="inline-details pipeline-advanced">
        <summary>고급 정보 (provider · 임계값 · audit)</summary>
        <ul className="items" style={{ marginTop: 10 }}>
          <li>
            <span>활성 provider</span>
            <span className="muted">
              <span title="config의 is_enabled=true 인 provider 수">enabled {state.enabledProviderCount}</span>
              {' · '}
              <span title="LIVE 모델 호출 가능한 provider 수 (API key 등록 완료)">live {state.liveProviderCount}</span>
            </span>
          </li>
          <li>
            <span title="raw record 중 AI 제안이 누락된 건수">audit 누락</span>
            <span className={`badge ${state.auditMissing > 0 ? 'warn' : 'ok'}`}>{fmt(state.auditMissing)}</span>
          </li>
          <li>
            <span>현재 잡 큐</span>
            <span className="muted">
              queued {state.queuedJobs} · running {state.runningJobs} · failed {state.failedJobs}
            </span>
          </li>
        </ul>
      </details>
    </section>
  );
}
