import { Fragment, useEffect, useState, useCallback } from 'react';
import { api } from '../../api/client';
import styles from './RunHistory.module.css';

const STATUS_LABELS = {
  success: '성공',
  partial: '부분 성공',
  failed: '실패',
  running: '실행 중',
};

function StatusBadge({ status }) {
  const cls = styles[`badge_${status}`] || styles.badge_default;
  return <span className={`${styles.badge} ${cls}`}>{STATUS_LABELS[status] || status}</span>;
}

export default function RunHistory() {
  const [runs, setRuns] = useState([]);
  const [plugins, setPlugins] = useState([]);
  const [pluginFilter, setPluginFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [expandedId, setExpandedId] = useState(null);
  const [logDetail, setLogDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = {};
      if (pluginFilter) params.plugin = pluginFilter;
      if (statusFilter) params.status = statusFilter;
      const data = await api.getRuns(params);
      setRuns(data.items || []);
      setError(null);
    } catch (e) {
      setError(e.message || '실행 이력을 불러올 수 없습니다.');
    } finally {
      setLoading(false);
    }
  }, [pluginFilter, statusFilter]);

  useEffect(() => {
    api.getOrchestratorPlugins()
      .then((d) => setPlugins(d.plugins || []))
      .catch(() => setPlugins([]));
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, [load]);

  const toggleExpand = async (runId) => {
    if (expandedId === runId) {
      setExpandedId(null);
      setLogDetail(null);
      return;
    }
    setExpandedId(runId);
    setLogDetail(null);
    try {
      const detail = await api.getRunLogs(runId);
      setLogDetail(detail);
    } catch (e) {
      setLogDetail({ error: e.message });
    }
  };

  const retry = async (runId, ev) => {
    ev.stopPropagation();
    try {
      await api.retryRun(runId);
      await load();
    } catch (e) {
      setError(e.message || '재시도 실패');
    }
  };

  return (
    <div className={styles.page}>
      <h1 className={styles.pageTitle}>실행 히스토리</h1>

      <div className={styles.filters}>
        <select value={pluginFilter} onChange={(e) => setPluginFilter(e.target.value)}>
          <option value="">모든 플러그인</option>
          {plugins.map((p) => (
            <option key={p.name} value={p.name}>{p.display_name || p.name}</option>
          ))}
        </select>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">모든 상태</option>
          <option value="success">성공</option>
          <option value="partial">부분 성공</option>
          <option value="failed">실패</option>
          <option value="running">실행 중</option>
        </select>
        <button className={styles.refresh} onClick={load} disabled={loading}>
          {loading ? '새로고침 중…' : '새로고침'}
        </button>
      </div>

      {error && <div className={styles.error}>{error}</div>}

      <div className={styles.tableCard}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>실행ID</th>
              <th>플러그인</th>
              <th>상태</th>
              <th>시작시각</th>
              <th>종료시각</th>
              <th>수집건수</th>
              <th>저장건수</th>
              <th>작업</th>
            </tr>
          </thead>
          <tbody>
            {runs.length === 0 && (
              <tr><td colSpan={8} className={styles.empty}>실행 이력이 없습니다.</td></tr>
            )}
            {runs.map((run) => (
              <Fragment key={run.run_id}>
                <tr
                  className={styles.row}
                  onClick={() => toggleExpand(run.run_id)}
                >
                  <td className={styles.mono}>{run.run_id}</td>
                  <td>{run.plugin_name}</td>
                  <td><StatusBadge status={run.status} /></td>
                  <td>{run.started_at || '-'}</td>
                  <td>{run.finished_at || '-'}</td>
                  <td>{run.items_found ?? 0}</td>
                  <td>{run.items_saved ?? 0}</td>
                  <td>
                    {run.status === 'failed' && (
                      <button className={styles.retry} onClick={(e) => retry(run.run_id, e)}>
                        재시도
                      </button>
                    )}
                  </td>
                </tr>
                {expandedId === run.run_id && (
                  <tr>
                    <td colSpan={8} className={styles.logPanel}>
                      {logDetail ? (
                        <div>
                          <div className={styles.logTitle}>로그</div>
                          <pre className={styles.logBody}>
                            {(logDetail.log_lines || []).join('\n') || '(없음)'}
                          </pre>
                          {(logDetail.failure_reasons || []).length > 0 && (
                            <>
                              <div className={styles.logTitle}>실패 원인</div>
                              <ul>
                                {logDetail.failure_reasons.map((r, i) => (
                                  <li key={i}>{r}</li>
                                ))}
                              </ul>
                            </>
                          )}
                        </div>
                      ) : (
                        <div>로그 로딩 중…</div>
                      )}
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
