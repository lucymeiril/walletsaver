import { useEffect, useState } from 'react';
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

export default function App() {
  return (
    <div className="app">
      <h1>🤖 WalletSavior AI 관리</h1>
      <p className="subtitle">로컬 전용 스켈레톤 — port 8003 / 5176</p>
      <HealthPanel />
      <CapabilitiesPanel />
      <ProvidersPanel />
      <JobsPanel />
      <PromptPacksPanel />
      <ReviewQueuePanel />
    </div>
  );
}
