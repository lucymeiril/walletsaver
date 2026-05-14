import { useCallback, useEffect, useMemo, useState } from 'react';
import ProvidersPanel from './ProvidersPanel.jsx';
import JobsPanel from './JobsPanel.jsx';
import PromptPacksPanel from './PromptPacksPanel.jsx';
import ReviewQueuePanel from './ReviewQueuePanel.jsx';

function useFetchJson(url) {
  const [state, setState] = useState({ status: 'loading', data: null, error: null });
  useEffect(() => {
    let cancelled = false;
    fetch(url)
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data) => { if (!cancelled) setState({ status: 'ok', data, error: null }); })
      .catch((err) => { if (!cancelled) setState({ status: 'error', data: null, error: err.message }); });
    return () => { cancelled = true; };
  }, [url]);
  return state;
}

function HealthPanel() {
  const { status, data, error } = useFetchJson('/health');
  let badge = <span className="badge warn">확인 중</span>;
  if (status === 'ok') badge = <span className="badge ok">{data?.status ?? 'ok'}</span>;
  else if (status === 'error') badge = <span className="badge err">오류</span>;

  return (
    <section className="panel">
      <h2>헬스체크</h2>
      <div className="row">
        <code>GET /health</code>
        {badge}
        {data?.uptime_seconds != null && (
          <span className="muted">uptime {data.uptime_seconds}s</span>
        )}
      </div>
      {error && <div className="muted" style={{ marginTop: 8 }}>error: {error}</div>}
    </section>
  );
}

function CapabilitiesPanel() {
  const { status, data, error } = useFetchJson('/api/capabilities');

  if (status === 'loading') {
    return (
      <section className="panel"><h2>capabilities</h2><div className="muted">로딩 중...</div></section>
    );
  }
  if (status === 'error') {
    return (
      <section className="panel">
        <h2>capabilities</h2>
        <div className="muted">불러올 수 없습니다 — 백엔드 실행 여부를 확인하세요. ({error})</div>
      </section>
    );
  }

  return (
    <>
      <section className="panel">
        <h2>AI 워커 역할 <span className="muted">({data.roles.length})</span></h2>
        <ul className="items">
          {data.roles.map((r) => (
            <li key={r.value}>
              <span>{r.label} <code>{r.value}</code></span>
              <span className={`badge ${r.supported ? 'ok' : ''}`}>
                {r.supported ? '지원' : '미구현'}
              </span>
            </li>
          ))}
        </ul>
      </section>

      <section className="panel">
        <h2>Provider <span className="muted">({data.providers.length})</span></h2>
        <ul className="items">
          {data.providers.map((p) => (
            <li key={p.value}>
              <span>{p.label} <code>{p.value}</code></span>
              <span className={`badge ${p.supported ? 'ok' : ''}`}>
                {p.supported ? '연결됨' : '플레이스홀더'}
              </span>
            </li>
          ))}
        </ul>
        <div className="muted" style={{ marginTop: 8 }}>
          provider SDK는 추후 단계에서 추가됩니다.
        </div>
      </section>
    </>
  );
}

async function fetchJson(url) {
  const res = await fetch(url);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
  return body;
}

function countBy(items, field) {
  return (items || []).reduce((acc, item) => {
    const key = item[field] || 'unknown';
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});
}

function DashboardCard({ title, badge, badgeClass = '', children, action }) {
  return (
    <div className="card status-card">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <strong>{title}</strong>
        <span className={`badge ${badgeClass}`}>{badge}</span>
      </div>
      <div className="status-card-body">{children}</div>
      {action}
    </div>
  );
}

function GuidedHomePanel({ onOpenAdvanced }) {
  const [state, setState] = useState({ loading: true, error: null, data: null });

  const refresh = useCallback(async () => {
    setState((prev) => ({ ...prev, loading: true, error: null }));
    try {
      const [health, setup, jobs, audit, proposals, records] = await Promise.all([
        fetchJson('/health'),
        fetchJson('/api/providers/setup-state'),
        fetchJson('/api/jobs'),
        fetchJson('/api/review/audit'),
        fetchJson('/api/review/proposals'),
        fetchJson('/api/review/raw-records?include_proposals=true'),
      ]);
      setState({
        loading: false,
        error: null,
        data: {
          health,
          setupProviders: setup.providers || [],
          jobs: jobs.jobs || [],
          audit,
          proposals: proposals.items || [],
          records: records.items || [],
        },
      });
    } catch (err) {
      setState((prev) => ({ ...prev, loading: false, error: err.message }));
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const summary = useMemo(() => {
    const data = state.data || {};
    const jobsByStatus = countBy(data.jobs, 'status');
    const proposalsByStatus = countBy(data.proposals, 'status');
    const liveReady = (data.setupProviders || []).filter((p) => p.can_call_live).length;
    const enabledProviders = (data.setupProviders || []).filter((p) => p.is_enabled).length;
    const hasFailedJobs = (jobsByStatus.failed || 0) + (jobsByStatus.dead_letter || 0) > 0;
    const reviewReady = (proposalsByStatus.ai_proposed || 0) + (proposalsByStatus.human_reviewing || 0);
    const missing = data.audit?.missing_record_count || 0;

    if (state.error) {
      return {
        label: '백엔드 연결 확인',
        target: '#advanced-health',
        advanced: true,
        badge: '문제',
        badgeClass: 'err',
        text: `상태를 불러오지 못했습니다: ${state.error}`,
      };
    }
    if (!data.records?.length) {
      return {
        label: '크롤러 결과 확인',
        target: '#review',
        badge: '시작',
        badgeClass: 'warn',
        text: '원본 raw record가 없습니다. crawler-admin에서 수집/내보내기를 먼저 실행하세요.',
      };
    }
    if (missing > 0) {
      return {
        label: '누락 이슈 보기',
        target: '#review',
        badge: '복구 필요',
        badgeClass: 'warn',
        text: `${missing}개 raw record에 AI 제안이 부족합니다. 검수 큐의 이슈 배지를 눌러 확인하세요.`,
      };
    }
    if (hasFailedJobs) {
      return {
        label: '실패 job 확인',
        target: '#advanced-jobs',
        advanced: true,
        badge: '복구 필요',
        badgeClass: 'err',
        text: '실패/Dead letter job이 있습니다. 상세에서 원인을 확인하고 재시도 계획을 세우세요.',
      };
    }
    if (reviewReady > 0) {
      return {
        label: '검수 계속하기',
        target: '#review',
        badge: '다음',
        badgeClass: 'ok',
        text: `${reviewReady}개 AI 제안이 사람 검수를 기다립니다. 기본 액션은 모델을 호출하지 않습니다.`,
      };
    }
    if (!enabledProviders || !liveReady) {
      return {
        label: 'Provider 설정 확인',
        target: '#advanced-providers',
        advanced: true,
        badge: '설정',
        badgeClass: 'warn',
        text: 'LIVE 호출 준비가 된 provider가 없습니다. 필요할 때만 고급 설정에서 연결하세요.',
      };
    }
    return {
      label: '새로고침',
      target: '#review',
      badge: '정상',
      badgeClass: 'ok',
      text: '크롤러 → AI → 검수 흐름이 정리되어 있습니다. 필요하면 새로고침으로 상태만 갱신하세요.',
    };
  }, [state.data, state.error]);

  const data = state.data || {};
  const jobsByStatus = countBy(data.jobs, 'status');
  const proposalsByStatus = countBy(data.proposals, 'status');
  const liveReady = (data.setupProviders || []).filter((p) => p.can_call_live).length;

  return (
    <section className="panel hero-panel">
      <div className="row hero-header">
        <div>
          <h2>오늘 할 일</h2>
          <div className="muted">복잡한 설정은 접어두고, 상태 확인 → 다음 액션만 진행하세요.</div>
        </div>
        <button className="primary-button" type="button" onClick={refresh} disabled={state.loading}>
          {state.loading ? '확인 중...' : '상태 새로고침'}
        </button>
      </div>

      <div className="next-action">
        <span className={`badge ${summary.badgeClass}`}>{summary.badge}</span>
        <div>
          <strong>추천 다음 액션: {summary.label}</strong>
          <div className="muted">{summary.text}</div>
        </div>
        {summary.advanced ? (
          <button className="primary-button" type="button" onClick={() => onOpenAdvanced(summary.target)}>
            {summary.label}
          </button>
        ) : (
          <a className="primary-link-button" href={summary.target}>{summary.label}</a>
        )}
      </div>

      <div className="status-grid">
        <DashboardCard
          title="1. 크롤러 입력"
          badge={state.error ? '확인 불가' : `${data.records?.length || 0} raw`}
          badgeClass={(data.records?.length || 0) > 0 ? 'ok' : 'warn'}
          action={<a href="#review">원본/이슈 보기</a>}
        >
          crawler-admin에서 들어온 원본과 audit 누락을 확인합니다.
          <div className="muted">누락 {data.audit?.missing_record_count ?? '-'} · 이슈 {data.audit?.issue_count ?? '-'}</div>
        </DashboardCard>
        <DashboardCard
          title="2. AI 처리"
          badge={(jobsByStatus.running || jobsByStatus.queued) ? '진행 중' : `${data.proposals?.length || 0} 제안`}
          badgeClass={(jobsByStatus.failed || jobsByStatus.dead_letter) ? 'err' : (data.proposals?.length ? 'ok' : 'warn')}
          action={<button className="link-button" type="button" onClick={() => onOpenAdvanced('#advanced-jobs')}>Job 상태 보기</button>}
        >
          큐 상태만 보여줍니다. 워커가 실행될 때만 LIVE 모델 호출 가능성이 있습니다.
          <div className="muted">queued {jobsByStatus.queued || 0} · running {jobsByStatus.running || 0} · failed {(jobsByStatus.failed || 0) + (jobsByStatus.dead_letter || 0)}</div>
        </DashboardCard>
        <DashboardCard
          title="3. 사람 검수"
          badge={`${(proposalsByStatus.ai_proposed || 0) + (proposalsByStatus.human_reviewing || 0)} 대기`}
          badgeClass={(proposalsByStatus.ai_proposed || proposalsByStatus.human_reviewing) ? 'warn' : 'ok'}
          action={<a href="#review">검수 계속하기</a>}
        >
          시작/승인/반려 같은 기본 검수 액션은 로컬 review API만 호출합니다.
          <div className="muted">approved {proposalsByStatus.approved || 0} · needs rework {proposalsByStatus.needs_rework || 0}</div>
        </DashboardCard>
        <DashboardCard
          title="안전장치"
          badge={liveReady ? `${liveReady} LIVE 준비` : 'LIVE 미준비'}
          badgeClass={liveReady ? 'warn' : 'ok'}
          action={<button className="link-button" type="button" onClick={() => onOpenAdvanced('#advanced-providers')}>Provider 확인</button>}
        >
          모델 목록 조회 등 LIVE 액션은 별도 버튼과 확인창을 거쳐야 실행됩니다.
        </DashboardCard>
      </div>
    </section>
  );
}

export default function App() {
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const openAdvanced = useCallback((target) => {
    setAdvancedOpen(true);
    window.setTimeout(() => {
      document.querySelector(target)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 0);
  }, []);

  return (
    <div className="app">
      <h1>🤖 WalletSavior AI 관리</h1>
      <p className="subtitle">초보자용 운영 홈 — 먼저 추천 액션만 따라가세요.</p>
      <GuidedHomePanel onOpenAdvanced={openAdvanced} />
      <ReviewQueuePanel />
      <details
        id="advanced-controls"
        className="panel advanced-shell anchor-offset"
        open={advancedOpen}
        onToggle={(e) => setAdvancedOpen(e.currentTarget.open)}
      >
        <summary>고급 설정 열기: provider · job 등록 · prompt · health</summary>
        <div id="advanced-health" className="anchor-offset"><HealthPanel /></div>
        <CapabilitiesPanel />
        <div id="advanced-providers" className="anchor-offset"><ProvidersPanel /></div>
        <div id="advanced-jobs" className="anchor-offset"><JobsPanel /></div>
        <PromptPacksPanel />
      </details>
    </div>
  );
}
