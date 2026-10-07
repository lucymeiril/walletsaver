import { Fragment, useEffect, useState, useCallback } from 'react';
import { api } from '../../api/client';
import { Link } from 'react-router-dom';
import styles from './RunHistory.module.css';

const STATUS_LABELS = {
  success: '수집·저장 완료',
  partial: '부분 완료',
  partial_failure: '부분 완료',
  failed: '실패',
  running: '실행 중',
};

const countText = value => typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : '미확인';

function StatusBadge({ run }) {
  const incomplete = run.status === 'success' && !(typeof countText(run.items_found) === 'number' && run.items_found > 0
    && typeof countText(run.items_saved) === 'number' && run.items_saved > 0
    && (!Object.hasOwn(run, 'items_valid') || (typeof countText(run.items_valid) === 'number' && run.items_valid > 0)));
  const styleStatus = run.status === 'partial_failure' || incomplete ? 'partial' : run.status;
  const cls = styles[`badge_${styleStatus}`] || styles.badge_default;
  return <span className={`${styles.badge} ${cls}`} title={`서버 실행 상태: ${run.status}`}>
    {incomplete ? '완료 확인 미충족' : STATUS_LABELS[run.status] || `상태 미확인 (${run.status || '미기록'})`}
  </span>;
}

export default function RunHistory() {
  const [runs, setRuns] = useState([]);
  const [registeredRuns, setRegisteredRuns] = useState([]);
  const [registeredError, setRegisteredError] = useState(null);
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
      const [scheduled, registered] = await Promise.allSettled([api.getRuns(params), api.getCrawlers()]);
      if (scheduled.status === 'fulfilled') {
        setRuns(scheduled.value.items || []);
        setError(null);
      } else {
        setError(scheduled.reason?.message || '예약 실행 이력을 불러올 수 없습니다.');
      }
      if (registered.status === 'fulfilled') {
        const crawlers = Array.isArray(registered.value.crawlers) ? registered.value.crawlers : [];
        setRegisteredRuns(crawlers.flatMap(crawler => (Array.isArray(crawler.recentRuns) ? crawler.recentRuns : [])
          .filter(run => run && typeof run === 'object' && !Array.isArray(run))
          .map((run, index) => ({ ...run, crawler_name: crawler.name, crawler_label: crawler.display_name || crawler.name, record_index: index })))
          .filter(run => (!pluginFilter || run.crawler_name === pluginFilter) && (!statusFilter || run.status === statusFilter))
          .sort((a, b) => String(b.timestamp || '').localeCompare(String(a.timestamp || ''))));
        setRegisteredError(null);
      } else {
        setRegisteredRuns([]);
        setRegisteredError(registered.reason?.message || '등록 크롤러 실행 이력을 불러올 수 없습니다.');
      }
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
      <p>실행 기록의 발견·유효·저장 진단입니다. 저장 수는 검토 승인·공개 업데이트 수를 뜻하지 않습니다. 미기록 수치는 미확인으로 표시합니다.</p>

      <div className={styles.filters}>
        <select value={pluginFilter} onChange={(e) => setPluginFilter(e.target.value)}>
          <option value="">모든 플러그인</option>
          {plugins.map((p) => (
            <option key={p.name} value={p.name}>{p.display_name || p.name}</option>
          ))}
        </select>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">모든 상태</option>
          <option value="success">수집·저장 완료</option>
          <option value="partial">부분 완료 (partial)</option>
          <option value="partial_failure">부분 완료 (partial_failure)</option>
          <option value="failed">실패</option>
          <option value="running">실행 중</option>
        </select>
        <button className={styles.refresh} onClick={load} disabled={loading}>
          {loading ? '새로고침 중…' : '새로고침'}
        </button>
      </div>

      {error && <div className={styles.error}>{error}</div>}

      <h2>예약·오케스트레이터 실행 이력</h2>
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
              <th>유효건수</th>
              <th>저장건수</th>
              <th>실행 진단</th>
              <th>작업</th>
            </tr>
          </thead>
          <tbody>
            {runs.length === 0 && (
              <tr><td colSpan={10} className={styles.empty}>실행 이력이 없습니다.</td></tr>
            )}
            {runs.map((run) => (
              <Fragment key={run.run_id}>
                <tr
                  className={styles.row}
                  onClick={() => toggleExpand(run.run_id)}
                >
                  <td className={styles.mono}>{run.run_id}</td>
                  <td>{run.plugin_name}</td>
                  <td><StatusBadge run={run} /></td>
                  <td>{run.started_at || '-'}</td>
                  <td>{run.finished_at || '-'}</td>
                  <td>{countText(run.items_found)}</td>
                  <td>{countText(run.items_valid)}</td>
                  <td>{countText(run.items_saved)}</td>
                  <td>{Array.isArray(run.failure_reasons) && run.failure_reasons.length > 0
                    ? <ul>{run.failure_reasons.map((reason, index) => <li key={index}>{String(reason)}</li>)}</ul> : '진단 미기록'}</td>
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
                    <td colSpan={10} className={styles.logPanel}>
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

      <section aria-labelledby="registered-crawler-history-title">
        <h2 id="registered-crawler-history-title">등록 크롤러 실행 이력</h2>
        <p>크롤러 카드에서 실행한 기존 기록입니다. 크롤러별 최근 기록만 보이며 예약 실행 이력과 별개입니다. 기록 시각은 출처 관측 시각이나 시작 시각이 아닙니다. 없는 ID·수치는 미확인으로 표시하며 성공 기록만으로 검토 승인·공개 갱신을 확인하지 않습니다.</p>
        {registeredError && <div className={styles.error}>{registeredError}</div>}
        <div className={styles.tableCard}>
          <table className={styles.table}>
            <thead><tr><th>등록 크롤러</th><th>기록 상태</th><th>기록 시각</th><th>원본 실행ID</th><th>출처 URL</th><th>발견·유효·저장 기록</th><th>매칭·접수 기록</th><th>검토</th></tr></thead>
            <tbody>
              {!registeredError && registeredRuns.length === 0 && <tr><td colSpan={8}>등록 크롤러 실행 기록이 없습니다.</td></tr>}
              {registeredRuns.map(run => {
                const matching = run.quality_details?.matching;
                const delivery = run.quality_details?.delivery;
                const sourceUrl = typeof run.source_url === 'string' ? run.source_url : null;
                return <tr key={`${run.crawler_name}:${run.timestamp || ''}:${run.record_index}`}>
                  <td>{run.crawler_label}</td>
                  <td>{run.status === 'success' ? '성공 기록 · 승인 미확인' : STATUS_LABELS[run.status] || '상태 미확인'}</td>
                  <td>{typeof run.timestamp === 'string' ? run.timestamp : '미기록'}</td>
                  <td>{typeof run.run_id === 'string' && run.run_id ? run.run_id : '미기록'}</td>
                  <td>{sourceUrl && /^https?:\/\//.test(sourceUrl) ? <a href={sourceUrl} target="_blank" rel="noopener noreferrer">{sourceUrl}</a> : sourceUrl || '미기록'}</td>
                  <td>발견 {countText(run.items_found)} · 유효 {countText(run.items_valid)} · 저장 {countText(run.items_saved)}</td>
                  <td>HIT {countText(matching?.hits)} · MISS {countText(matching?.misses)}<br />접수 대상 {delivery?.target === 'pending_review' ? '검토 대기' : '미확인'} · 시도 {countText(delivery?.attempted)} · 확인 {countText(delivery?.acknowledged)}</td>
                  <td><Link to="/data-review">데이터 검토</Link></td>
                </tr>;
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
