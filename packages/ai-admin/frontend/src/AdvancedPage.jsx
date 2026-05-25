import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import JobProgressBar from './JobProgressBar.jsx';
import MatchMonitorPanel from './MatchMonitorPanel.jsx';
import PendingEscalationPanel from './PendingEscalationPanel.jsx';
import ReviewQueuePanel from './ReviewQueuePanel.jsx';
import ProvidersPanel from './ProvidersPanel.jsx';
import JobsPanel from './JobsPanel.jsx';
import PromptPacksPanel from './PromptPacksPanel.jsx';
import BulkArchiveDialog from './BulkArchiveDialog.jsx';
import { classifyPipelineError, humanizeDetail } from './pipelineErrors.js';
import { fmtNumberKR as fmt } from './pipelineHelpers.js';
import { runProcessMissingLoop } from './advancedHelpers.js';

/**
 * rd4-advanced-rewrite: 고급 탭 전체를 한 화면으로 재구성한다.
 *
 * 사용자 비판 요지: "고급 탭에서 결국 처리를 하게 되는데, 사람이 쓸 수 있는
 * UI/UX 인지 모르겠음" — 기존 AdvancedPage 는 LivePipelinePanel + 6개 패널을
 * 단순 세로로 쌓아 정보 과부하 + 다음 행동 불명. 이번 rewrite 의 목표:
 *
 *  1) 3 단계 보드: 수집/AI/발행 의 현재 수치 + "다음 1개 행동" 만 노출.
 *  2) 에러 분류 → 분기별 다음 행동 버튼 (timeout=batch 줄이기 등).
 *  3) 라이브 잡 진행 표시: /api/jobs/{id} 폴링, batch X/Y, 평균 s/item, ETA.
 *  4) 키보드: R(refresh) / E(enqueue) / Esc(close panel)
 *  5) 고급 사용자 항목(Jobs 원본 테이블, Provider, MatchMonitor, Escalation,
 *     ReviewQueue, PromptPacks)은 별도 <details> 안으로 격리.
 *
 * 검수 탭(ReviewPage)/홈 탭(HomePage)은 건드리지 않는다. App.jsx 는 이 컴포넌트만
 * import 한다.
 */

async function fetchJson(url, opts = {}) {
  const res = await fetch(url, { cache: 'no-store', ...opts });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const msg = humanizeDetail(body?.detail ?? body) || `HTTP ${res.status}`;
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  return body;
}

function StepCard({ index, title, status, metrics }) {
  return (
    <li className={`pipeline-step pipeline-step-${status}`} data-testid={`adv-step-${index}`}>
      <div className="pipeline-step-num">{index + 1}</div>
      <div className="pipeline-step-body">
        <div className="pipeline-step-title">{title}</div>
        <div className="pipeline-step-meta">{metrics}</div>
      </div>
    </li>
  );
}

function ErrorPanel({ errInfo, onRetry, onOpenProviders, onOpenJobs }) {
  if (!errInfo) return null;
  const buttons = [];
  buttons.push(
    <button key="retry" type="button" className="primary-button" onClick={onRetry}>
      다시 시도 (R)
    </button>,
  );
  if (errInfo.kind === 'auth' || errInfo.kind === 'quota') {
    buttons.push(
      <button key="prov" type="button" className="secondary-button" onClick={onOpenProviders}>
        공급자/키 열기
      </button>,
    );
  }
  if (errInfo.kind === 'timeout' || errInfo.kind === 'provider_500' || errInfo.kind === 'connection') {
    buttons.push(
      <button key="jobs" type="button" className="secondary-button" onClick={onOpenJobs}>
        실패 잡 보기
      </button>,
    );
  }
  return (
    <div className="alert alert-err" data-testid="adv-error" data-error-kind={errInfo.kind}>
      <div className="alert-head">
        <strong>⚠ {errInfo.label}</strong>
        <span className="muted small">kind=<code>{errInfo.kind}</code></span>
      </div>
      <div className="muted">{errInfo.hint}</div>
      <div className="muted small" style={{ marginTop: 4 }}>원문: {errInfo.message}</div>
      <div className="row" style={{ marginTop: 10, gap: 8 }}>{buttons}</div>
    </div>
  );
}

export default function AdvancedPage({ onGoReview }) {
  const [state, setState] = useState({
    loading: true,
    error: null,
    rawCount: 0,
    auditMissing: 0,
    proposalCount: 0,
    pendingReviewCount: 0,
    publishedCount: 0,
    queuedJobs: 0,
    runningJobs: 0,
    failedJobs: 0,
    liveProviderCount: 0,
    enabledProviderCount: 0,
    defaultProviderId: null,
  });
  const [enqueue, setEnqueue] = useState({
    busy: false,
    jobId: null,
    error: null,
    progress: null,
    initialMissing: 0,
  });
  const cancelRef = useRef(false);
  const [openSection, setOpenSection] = useState(null);
  const [showBulkArchive, setShowBulkArchive] = useState(false);
  const [rawClear, setRawClear] = useState({ busy: false, preview: null, error: null, lastDelete: null });
  const lastDoneJobRef = useRef(null);

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
      const liveProvider = providers.find((p) => p.can_call_live) || providers.find((p) => p.is_enabled) || providers[0];
      const ps = props.reduce((acc, it) => {
        const k = it.status || 'unknown';
        acc[k] = (acc[k] || 0) + 1;
        return acc;
      }, {});
      const js = jobsArr.reduce((acc, it) => {
        const k = it.status || 'unknown';
        acc[k] = (acc[k] || 0) + 1;
        return acc;
      }, {});
      setState({
        loading: false,
        error: null,
        rawCount: audit?.raw_record_count ?? audit?.total_records ?? 0,
        auditMissing: audit?.missing_record_count || 0,
        proposalCount: props.length,
        pendingReviewCount:
          (ps.ai_proposed || 0) + (ps.human_reviewing || 0) + (ps.pending_review || 0),
        publishedCount: ps.published || 0,
        queuedJobs: js.queued || 0,
        runningJobs: js.running || 0,
        failedJobs: (js.failed || 0) + (js.dead_letter || 0),
        liveProviderCount: providers.filter((p) => p.can_call_live).length,
        enabledProviderCount: providers.filter((p) => p.is_enabled).length,
        defaultProviderId: liveProvider?.provider_id || liveProvider?.id || null,
      });
    } catch (err) {
      setState((p) => ({ ...p, loading: false, error: err }));
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const errInfo = useMemo(() => classifyPipelineError(state.error), [state.error]);

  const handleEnqueue = useCallback(async () => {
    if (enqueue.busy) return;
    const providerId = state.defaultProviderId;
    if (!providerId) {
      setEnqueue({
        busy: false,
        jobId: null,
        progress: null,
        initialMissing: 0,
        error: new Error('사용 가능한 공급자가 없습니다. 공급자/모델 설정에서 등록하세요.'),
      });
      return;
    }
    cancelRef.current = false;
    const initialMissing = state.auditMissing || 0;
    setEnqueue({ busy: true, jobId: null, error: null, progress: null, initialMissing });
    try {
      const summary = await runProcessMissingLoop({
        providerId,
        limit: 30,
        abortSignal: () => cancelRef.current,
        onProgress: (p) => {
          setEnqueue((prev) => ({ ...prev, progress: p }));
        },
      });
      setEnqueue({
        busy: false,
        jobId: null,
        error: null,
        progress: { ...summary, missingRemaining: summary.missingRemaining },
        initialMissing,
      });
      refresh();
    } catch (err) {
      setEnqueue({ busy: false, jobId: null, error: err, progress: null, initialMissing });
    }
  }, [enqueue.busy, refresh, state.defaultProviderId, state.auditMissing]);

  const handleCancel = useCallback(() => {
    cancelRef.current = true;
  }, []);

  const doRawClearPreview = useCallback(async (includeProposed) => {
    setRawClear({ busy: true, preview: null, error: null, lastDelete: null });
    try {
      const res = await fetch('/api/ingest/raw-records/clear-all', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ include_proposed: includeProposed, dry_run: true }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        const msg = humanizeDetail(body?.detail ?? body) || `HTTP ${res.status}`;
        throw new Error(msg);
      }
      setRawClear({ busy: false, preview: body, error: null, lastDelete: null });
    } catch (err) {
      setRawClear({ busy: false, preview: null, error: err.message || String(err), lastDelete: null });
    }
  }, []);

  const doRawClearExecute = useCallback(async (includeProposed) => {
    if (!window.confirm('⚠️ raw_crawl_records 를 정말 비웁니다. 되돌릴 수 없습니다. 계속할까요?')) return;
    setRawClear((p) => ({ ...p, busy: true, error: null }));
    try {
      const res = await fetch('/api/ingest/raw-records/clear-all', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          include_proposed: includeProposed,
          dry_run: false,
          reviewer_id: 'operator',
          reason: 'AdvancedPage raw clear-all',
        }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        const msg = humanizeDetail(body?.detail ?? body) || `HTTP ${res.status}`;
        throw new Error(msg);
      }
      setRawClear({ busy: false, preview: null, error: null, lastDelete: body });
      refresh();
    } catch (err) {
      setRawClear({ busy: false, preview: null, error: err.message || String(err), lastDelete: null });
    }
  }, [refresh]);

  // 키보드 단축키 R / E / Esc — 검수 탭의 J/K/Enter/X 와 충돌하지 않도록 고급 탭 전용.
  useEffect(() => {
    function onKey(e) {
      // 입력 폼 내부에서는 무시
      const tag = (e.target?.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === 'r' || e.key === 'R') {
        e.preventDefault();
        refresh();
      } else if (e.key === 'e' || e.key === 'E') {
        e.preventDefault();
        if (!enqueue.busy) handleEnqueue();
      } else if (e.key === 'Escape') {
        if (openSection) {
          e.preventDefault();
          setOpenSection(null);
        }
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [refresh, handleEnqueue, enqueue.busy, openSection]);

  const stepStatuses = [
    state.rawCount > 0 ? 'done' : 'todo',
    state.proposalCount > 0 ? (state.auditMissing > 0 ? 'partial' : 'done') : 'todo',
    state.publishedCount > 0 ? 'done' : state.pendingReviewCount > 0 ? 'todo' : 'idle',
  ];

  // 결정: 다음 1개 행동
  const nextAction = useMemo(() => {
    if (errInfo) return null;
    if (state.rawCount === 0) {
      return {
        label: '수집할 raw 가 없습니다',
        cta: 'crawler-admin 열기',
        run: () => window.open('http://localhost:5174', '_blank'),
      };
    }
    if (state.proposalCount === 0 || state.auditMissing > 0) {
      const progress = enqueue.progress;
      let cta;
      if (enqueue.busy) {
        const done = progress?.processedTotal || 0;
        const initial = enqueue.initialMissing || state.auditMissing || 0;
        cta = initial > 0 ? `처리 중… (${done}/${initial})` : `처리 중… (${done})`;
      } else {
        cta = 'AI 처리 가동 (E)';
      }
      return {
        label:
          state.auditMissing > 0
            ? `AI 제안 누락 ${fmt(state.auditMissing)}건 — 처리 가동`
            : 'AI 제안이 없습니다 — 처리 가동',
        cta,
        run: handleEnqueue,
        disabled: true, /* 2026-05-25 보류: AI 라이브 파이프라인 비활성화 */
      };
    }
    if (state.pendingReviewCount > 0) {
      return {
        label: `${fmt(state.pendingReviewCount)}건 검수/발행 대기`,
        cta: '검수 탭 열기',
        run: () => onGoReview?.(),
      };
    }
    if (state.failedJobs > 0) {
      return {
        label: `${fmt(state.failedJobs)}개 실패 잡 — 원인 확인 필요`,
        cta: '실패 잡 보기',
        run: () => setOpenSection('jobs'),
      };
    }
    return {
      label: `발행 완료 ${fmt(state.publishedCount)}건 — 정상`,
      cta: '새로고침 (R)',
      run: refresh,
    };
  }, [errInfo, state, enqueue.busy, handleEnqueue, onGoReview, refresh]);

  // 진행 막대용 effect job id — enqueue 직후 또는 running 잡 1건 picking
  const trackJobId = enqueue.jobId;

  const handleJobDone = useCallback(
    (job) => {
      lastDoneJobRef.current = job;
      refresh();
    },
    [refresh],
  );

  return (
    <div className="advanced advanced-v2" data-testid="advanced-page-v2">
      {/* 페이지 설명 */}
      <p className="page-desc muted small" style={{ marginBottom: 14 }}>
        수집 → AI 처리 → 발행까지의 파이프라인 운영 화면입니다.
        일반 사용자는 홈/검수 탭을 이용하고, 여기서는 잡 관리·공급자 설정·원시 데이터 비우기 등 고급 작업을 수행합니다.
      </p>
      <header className="adv-hero">
        <div>
          <h2>⚙️ 고급 — 파이프라인 운영</h2>
          <div className="muted small">
            수집 → AI → 발행 흐름을 한 화면에서. 단축키: <kbd>R</kbd> 새로고침 ·{' '}
            <kbd>E</kbd> AI 잡 등록 · <kbd>Esc</kbd> 펼친 패널 닫기.
          </div>
        </div>
        <button
          type="button"
          className="secondary-button"
          onClick={refresh}
          disabled={state.loading}
          data-testid="adv-refresh"
          title="R"
        >
          {state.loading ? '확인 중…' : '↻ 새로고침'}
        </button>
      </header>

      <ErrorPanel
        errInfo={errInfo}
        onRetry={refresh}
        onOpenProviders={() => setOpenSection('providers')}
        onOpenJobs={() => setOpenSection('jobs')}
      />

      {!errInfo && nextAction && (
        <div className="next-action" data-testid="adv-next-action">
          <span
            className={`badge ${nextAction.cta === '새로고침 (R)' ? 'ok' : 'warn'}`}
            data-testid="adv-next-badge"
          >
            다음
          </span>
          {/* 2026-05-25 보류: AI 라이브 파이프라인 비활성화 배지 */}
          {nextAction.disabled && nextAction.cta === 'AI 처리 가동 (E)' && (
            <span className="badge deprecated" style={{ marginLeft: 6 }}>
              🚧 보류 — 외부 분류 워크플로우 사용
            </span>
          )}
          <strong>{nextAction.label}</strong>
          <button
            type="button"
            className="primary-button"
            onClick={nextAction.run}
            disabled={nextAction.disabled}
            data-testid="adv-next-cta"
          >
            {nextAction.cta}
          </button>
        </div>
      )}

      {enqueue.busy && enqueue.progress && (
        <div className="alert" data-testid="adv-enqueue-progress">
          <div>
            <strong>AI 처리 진행 중…</strong>
            <span className="muted small" style={{ marginLeft: 8 }}>
              처리 {fmt(enqueue.progress.processedTotal || 0)}건 · 제안 {fmt(enqueue.progress.proposalsTotal || 0)}건 · 남음 {fmt(enqueue.progress.missingRemaining || 0)}건 · 라운드 {enqueue.progress.iterations || 0}
            </span>
          </div>
          <button type="button" className="secondary-button" onClick={handleCancel}>중단</button>
        </div>
      )}
      {!enqueue.busy && enqueue.progress && (enqueue.progress.processedTotal || 0) > 0 && (
        <div className="alert alert-ok" data-testid="adv-enqueue-done">
          <strong>AI 처리 완료</strong>{' '}
          <span className="muted small">
            처리 {fmt(enqueue.progress.processedTotal || 0)}건 · 제안 {fmt(enqueue.progress.proposalsTotal || 0)}건 · 남음 {fmt(enqueue.progress.missingRemaining || 0)}건
            {enqueue.progress.aborted ? ' · 사용자 중단' : ''}
          </span>
        </div>
      )}

      {enqueue.error && (
        <ErrorPanel
          errInfo={classifyPipelineError(enqueue.error)}
          onRetry={handleEnqueue}
          onOpenProviders={() => setOpenSection('providers')}
          onOpenJobs={() => setOpenSection('jobs')}
        />
      )}

      <ol className="pipeline-steps" data-testid="adv-pipeline-steps">
        <StepCard
          index={0}
          title="수집"
          status={stepStatuses[0]}
          metrics={<>raw {fmt(state.rawCount)} · 누락 {fmt(state.auditMissing)}</>}
        />
        <StepCard
          index={1}
          title="AI 처리"
          status={stepStatuses[1]}
          metrics={
            <>
              제안 {fmt(state.proposalCount)} · 실행 {fmt(state.runningJobs)} · 대기{' '}
              {fmt(state.queuedJobs)} · 실패 {fmt(state.failedJobs)}
            </>
          }
        />
        <StepCard
          index={2}
          title="발행"
          status={stepStatuses[2]}
          metrics={
            <>
              검수 대기 {fmt(state.pendingReviewCount)} · 발행 {fmt(state.publishedCount)}
            </>
          }
        />
      </ol>

      {trackJobId && (
        <section className="panel adv-job-progress" data-testid="adv-job-progress">
          <h3>진행 중인 AI 잡</h3>
          <JobProgressBar jobId={trackJobId} onDone={handleJobDone} />
        </section>
      )}

      {/* 고급 패널 — 모두 collapse */}
      <section className="adv-section-list">
        <h3 className="muted small" style={{ marginBottom: 8 }}>
          상세 운영 패널 (필요할 때만 펼치기)
        </h3>

        <details
          className="inline-details"
          open={openSection === 'jobs'}
          onToggle={(e) => e.currentTarget.open && setOpenSection('jobs')}
        >
          <summary>잡 큐 (raw 테이블/필터/직접 등록)</summary>
          <div style={{ marginTop: 12 }}>
            <JobsPanel />
          </div>
        </details>

        <details
          className="inline-details"
          open={openSection === 'providers'}
          onToggle={(e) => e.currentTarget.open && setOpenSection('providers')}
        >
          <summary>
            공급자/모델 설정{' '}
            <span className="muted small">
              (enabled {state.enabledProviderCount} · live {state.liveProviderCount})
            </span>
          </summary>
          <div style={{ marginTop: 12 }}>
            <ProvidersPanel />
          </div>
        </details>

        <details
          className="inline-details"
          open={openSection === 'match'}
          onToggle={(e) => e.currentTarget.open && setOpenSection('match')}
        >
          <summary>매칭 모니터</summary>
          <div style={{ marginTop: 12 }}>
            <MatchMonitorPanel />
          </div>
        </details>

        <details
          className="inline-details"
          open={openSection === 'esc'}
          onToggle={(e) => e.currentTarget.open && setOpenSection('esc')}
        >
          <summary>에스컬레이션 대기</summary>
          <div style={{ marginTop: 12 }}>
            <PendingEscalationPanel />
          </div>
        </details>

        <details
          className="inline-details"
          open={openSection === 'publish'}
          onToggle={(e) => e.currentTarget.open && setOpenSection('publish')}
        >
          <summary>발행 큐 (raw 테이블)</summary>
          <div style={{ marginTop: 12 }}>
            <ReviewQueuePanel />
          </div>
        </details>

        <details
          className="inline-details"
          open={openSection === 'prompts'}
          onToggle={(e) => e.currentTarget.open && setOpenSection('prompts')}
        >
          <summary>프롬프트 팩</summary>
          <div style={{ marginTop: 12 }}>
            <PromptPacksPanel />
          </div>
        </details>
      </section>

      {/* rd5-danger-zone: 사용자 비판 "비우기 어디 갔냐" — 고급 탭에서 직접 접근 가능. */}
      <section className="adv-section-list" data-testid="adv-danger-zone">
        <h3 style={{ marginBottom: 8, fontSize: '0.88rem', color: 'var(--danger)' }}>
          ⚠ 데이터 비우기 — AI 제안·raw 레코드 일괄 삭제 (펼쳐서 사용)
        </h3>
        <details
          className="inline-details"
          open={openSection === 'danger'}
          onToggle={(e) => e.currentTarget.open && setOpenSection('danger')}
          style={{ borderColor: 'var(--danger)' }}
        >
          <summary style={{ color: 'var(--danger)', fontWeight: 600 }}>
            ⚠ 검수 큐 비우기 / raw 레코드 비우기 (위험)
          </summary>
          <div style={{ marginTop: 12, display: 'grid', gap: 16 }}>
            <div className="panel" style={{ borderColor: '#c00' }}>
              <h4>AI 제안 비우기 (BulkArchiveDialog)</h4>
              <p className="muted small">
                상태/타입/생성일 필터로 좁힌 뒤 미리보기 → 비우기. 30초 안에 되돌릴 수 있습니다.
                위험 옵션(발행대기/승인/발행됨)도 셋 다 opt-in 으로 켤 수 있습니다.
              </p>
              <button
                type="button"
                className="btn btn-danger"
                onClick={() => setShowBulkArchive(true)}
                data-testid="adv-open-bulk-archive"
              >
                AI 제안 비우기 열기…
              </button>
            </div>

            <div className="panel" style={{ borderColor: '#c00' }}>
              <h4>raw_crawl_records 비우기</h4>
              <p className="muted small">
                DB 를 처음부터 다시 시작할 때만. 기본은 dry-run 미리보기. include_proposed=false 면
                이미 AI 제안이 만들어진 raw 행은 보호됩니다.
              </p>
              <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
                <button
                  type="button"
                  className="btn"
                  onClick={() => doRawClearPreview(false)}
                  disabled={rawClear.busy}
                  data-testid="adv-raw-clear-preview"
                >
                  미리보기 (제안 있는 행 보호)
                </button>
                <button
                  type="button"
                  className="btn"
                  onClick={() => doRawClearPreview(true)}
                  disabled={rawClear.busy}
                >
                  미리보기 (전체 — 제안도 같이 비움)
                </button>
                {rawClear.preview && (
                  <>
                    <button
                      type="button"
                      className="btn btn-danger"
                      onClick={() => doRawClearExecute(rawClear.preview.include_proposed)}
                      disabled={rawClear.busy || (rawClear.preview.would_delete || 0) === 0}
                      data-testid="adv-raw-clear-execute"
                    >
                      {rawClear.preview.would_delete || 0}건 비우기 실행
                    </button>
                  </>
                )}
              </div>
              {rawClear.preview && (
                <div className="muted small" style={{ marginTop: 8 }}>
                  미리보기: 삭제 대상 {fmt(rawClear.preview.would_delete || 0)}건 · 보호 {fmt(rawClear.preview.protected_with_proposals || 0)}건
                  (include_proposed={String(rawClear.preview.include_proposed)})
                </div>
              )}
              {rawClear.lastDelete && (
                <div className="alert alert-ok" style={{ marginTop: 8 }}>
                  완료: raw {fmt(rawClear.lastDelete.deleted_records || 0)}건 · 빈 배치 {fmt(rawClear.lastDelete.deleted_batches || 0)}건 정리
                </div>
              )}
              {rawClear.error && (
                <div className="alert alert-err" style={{ marginTop: 8 }}>{rawClear.error}</div>
              )}
            </div>
          </div>
        </details>
      </section>

      <BulkArchiveDialog
        open={showBulkArchive}
        onClose={() => setShowBulkArchive(false)}
        onArchived={() => refresh()}
      />
    </div>
  );
}
