import { useCallback, useEffect, useState } from 'react';

function useMatchMonitor() {
  const [state, setState] = useState({ loading: true, error: null, cumulative: null, runs: [] });

  const refresh = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const [cum, runsResp] = await Promise.all([
        fetch('/api/match-monitor/cumulative').then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
        fetch('/api/match-monitor/runs?n=20').then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
      ]);
      setState({ loading: false, error: null, cumulative: cum, runs: runsResp.runs || [] });
    } catch (err) {
      setState((s) => ({ ...s, loading: false, error: err.message }));
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);
  return { ...state, refresh };
}

function AiCallRateChart({ runs }) {
  if (!runs || runs.length === 0) {
    return <div className="muted" style={{ padding: '16px 0' }}>런 기록 없음 — 라벨링 파이프라인을 실행하면 여기에 추이가 표시됩니다.</div>;
  }
  const ordered = [...runs].reverse();
  const max = Math.max(...ordered.map((r) => r.ai_call_rate), 1);
  return (
    <div>
      <div className="muted" style={{ marginBottom: 6, fontSize: 12 }}>AI 호출률 추이 (%) — 사이클이 쌓일수록 낮아져야 합니다</div>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 4, height: 80, borderBottom: '1px solid #444' }}>
        {ordered.map((run, i) => {
          const h = max > 0 ? (run.ai_call_rate / max) * 70 : 0;
          const isLow = run.ai_call_rate < 50;
          return (
            <div key={run.run_id} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'flex-end', minWidth: 12 }} title={`런 ${i + 1}: ${run.ai_call_rate}%`}>
              <div style={{ width: '100%', height: `${h}px`, background: isLow ? '#4caf50' : '#ff9800', borderRadius: '2px 2px 0 0', minHeight: run.ai_call_rate > 0 ? 2 : 0 }} />
            </div>
          );
        })}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: '#888', marginTop: 2 }}>
        <span>런 1</span>
        <span>런 {ordered.length}</span>
      </div>
    </div>
  );
}

function RunsTable({ runs }) {
  if (!runs || runs.length === 0) {
    return <div className="muted">런 기록 없음</div>;
  }
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr style={{ borderBottom: '1px solid #444', textAlign: 'left' }}>
            <th style={{ padding: '4px 8px' }}>일시</th>
            <th style={{ padding: '4px 8px' }}>모드</th>
            <th style={{ padding: '4px 8px' }}>입력</th>
            <th style={{ padding: '4px 8px' }}>큐진입</th>
            <th style={{ padding: '4px 8px' }}>AI해결</th>
            <th style={{ padding: '4px 8px' }}>Escalated</th>
            <th style={{ padding: '4px 8px' }}>게이트통과</th>
            <th style={{ padding: '4px 8px', color: '#ff9800' }}>AI호출률</th>
            <th style={{ padding: '4px 8px' }}>PM누적</th>
            <th style={{ padding: '4px 8px' }}>LK누적</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.run_id} style={{ borderBottom: '1px solid #333' }}>
              <td style={{ padding: '4px 8px', whiteSpace: 'nowrap' }}>{run.run_at ? run.run_at.slice(0, 19).replace('T', ' ') : '-'}</td>
              <td style={{ padding: '4px 8px' }}><span className={`badge ${run.mode === 'commit' ? 'ok' : ''}`}>{run.mode}</span></td>
              <td style={{ padding: '4px 8px' }}>{run.total_input}</td>
              <td style={{ padding: '4px 8px' }}>{run.queue_initial}</td>
              <td style={{ padding: '4px 8px' }}>{run.ai_resolved}</td>
              <td style={{ padding: '4px 8px' }}>{run.ai_escalated > 0 ? <span className="badge err">{run.ai_escalated}</span> : 0}</td>
              <td style={{ padding: '4px 8px' }}>{run.gate_passed}</td>
              <td style={{ padding: '4px 8px' }}>
                <span className={`badge ${run.ai_call_rate < 50 ? 'ok' : run.ai_call_rate < 80 ? '' : 'warn'}`}>
                  {run.ai_call_rate}%
                </span>
              </td>
              <td style={{ padding: '4px 8px' }}>{run.product_match_total_snapshot}</td>
              <td style={{ padding: '4px 8px' }}>{run.learned_knowledge_total_snapshot}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function MatchMonitorPanel() {
  const { loading, error, cumulative, runs, refresh } = useMatchMonitor();

  const pm = cumulative?.product_match || {};
  const lk = cumulative?.learned_knowledge || {};

  return (
    <section className="panel" id="match-monitor">
      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 12 }}>
        <div>
          <h2>📊 매칭 누적 모니터</h2>
          <div className="muted">사이클이 쌓일수록 ProductMatch↑ · AI호출률↓ 를 확인합니다</div>
        </div>
        <button className="primary-button" type="button" onClick={refresh} disabled={loading}>
          {loading ? '로딩 중...' : '새로고침'}
        </button>
      </div>

      {error && (
        <div className="muted" style={{ color: '#f66', marginBottom: 12 }}>
          오류: {error} — 백엔드 실행 여부를 확인하세요.
        </div>
      )}

      <div className="status-grid" style={{ marginBottom: 16 }}>
        <div className="card status-card">
          <strong>ProductMatch 누적</strong>
          <div style={{ fontSize: 28, fontWeight: 700, margin: '8px 0', color: '#4fc3f7' }}>
            {loading ? '...' : (pm.total ?? 0)}
          </div>
          <div className="muted" style={{ fontSize: 12 }}>
            {pm.by_status && Object.entries(pm.by_status).map(([s, c]) => (
              <span key={s} style={{ marginRight: 8 }}>{s}: {c}</span>
            ))}
          </div>
        </div>
        <div className="card status-card">
          <strong>LearnedKnowledge 누적</strong>
          <div style={{ fontSize: 28, fontWeight: 700, margin: '8px 0', color: '#81c784' }}>
            {loading ? '...' : (lk.total ?? 0)}
          </div>
          <div className="muted" style={{ fontSize: 12 }}>
            {lk.by_type && Object.entries(lk.by_type).map(([t, c]) => (
              <span key={t} style={{ marginRight: 8 }}>{t}: {c}</span>
            ))}
          </div>
        </div>
        <div className="card status-card">
          <strong>최근 AI 호출률</strong>
          <div style={{ fontSize: 28, fontWeight: 700, margin: '8px 0', color: runs[0]?.ai_call_rate < 50 ? '#81c784' : '#ff9800' }}>
            {loading ? '...' : runs.length > 0 ? `${runs[0].ai_call_rate}%` : '-'}
          </div>
          <div className="muted" style={{ fontSize: 12 }}>최근 런 기준 · 낮을수록 캐시 효과</div>
        </div>
        <div className="card status-card">
          <strong>총 런 횟수</strong>
          <div style={{ fontSize: 28, fontWeight: 700, margin: '8px 0' }}>
            {loading ? '...' : runs.length}
          </div>
          <div className="muted" style={{ fontSize: 12 }}>기록된 라벨링 런 수</div>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 16, padding: 16 }}>
        <strong style={{ display: 'block', marginBottom: 8 }}>AI 호출률 추이</strong>
        <AiCallRateChart runs={runs} />
      </div>

      <div className="card" style={{ padding: 16 }}>
        <strong style={{ display: 'block', marginBottom: 8 }}>최근 런 목록</strong>
        <RunsTable runs={runs} />
      </div>
    </section>
  );
}
