import { useState, useEffect } from 'react';
import useAdminStore from '../../stores/adminStore';
import { ChevronLeft, ChevronRight, Download } from 'lucide-react';
import styles from './Logs.module.css';

const STATUS_LABEL = { success: '성공', failure: '실패', failed: '실패', partial: '부분' };

export default function Logs() {
  const logs = useAdminStore((s) => s.logs);
  const logFilters = useAdminStore((s) => s.logFilters);
  const setLogFilters = useAdminStore((s) => s.setLogFilters);
  const logPage = useAdminStore((s) => s.logPage);
  const setLogPage = useAdminStore((s) => s.setLogPage);
  const logsPerPage = useAdminStore((s) => s.logsPerPage);
  const getFilteredLogs = useAdminStore((s) => s.getFilteredLogs);
  const fetchLogs = useAdminStore((s) => s.fetchLogs);
  const exportLogs = useAdminStore((s) => s.exportLogs);
  const loading = useAdminStore((s) => s.loading);
  const error = useAdminStore((s) => s.error);

  const [expandedLog, setExpandedLog] = useState(null);

  useEffect(() => {
    fetchLogs();
  }, [fetchLogs]);

  const filtered = getFilteredLogs();
  const totalPages = Math.ceil(filtered.length / logsPerPage);
  const paginated = filtered.slice(
    (logPage - 1) * logsPerPage,
    logPage * logsPerPage
  );

  const formatDateTime = (iso) => {
    if (!iso) return '-';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '-';
    return d.toLocaleString('ko-KR', {
      month: 'numeric',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  };

  const getEntryClass = (status) => {
    if (status === 'failure' || status === 'failed') return styles.logEntryError;
    if (status === 'partial') return styles.logEntryPartial;
    return styles.logEntrySuccess;
  };

  const getStatusClass = (status) => {
    if (status === 'failure' || status === 'failed') return styles.statusFailure;
    if (status === 'partial') return styles.statusPartial;
    return styles.statusSuccess;
  };

  return (
    <div className={styles.page}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
        <h1 className={styles.pageTitle} style={{ marginBottom: 0 }}>크롤 로그</h1>
        <button
          onClick={() => exportLogs()}
          style={{
            display: 'flex', alignItems: 'center', gap: '6px',
            padding: '8px 16px', borderRadius: '6px', border: '1px solid var(--border)',
            background: 'var(--bg2)', color: 'var(--text2)', cursor: 'pointer',
            fontSize: '13px',
          }}
        >
          <Download size={14} />
          CSV 내보내기
        </button>
      </div>

      {error && (
        <div style={{
          padding: '12px 16px', borderRadius: '8px', marginBottom: '16px',
          background: 'rgba(248,113,113,0.15)', color: 'var(--red)',
          fontSize: 'var(--fs-sm)',
        }}>
          {error}
        </div>
      )}

      {/* Filters */}
      <div className={styles.filtersBar}>
        <input
          className={styles.filterInput}
          type="text"
          placeholder="크롤러명 검색..."
          value={logFilters.crawlerName}
          onChange={(e) => setLogFilters({ crawlerName: e.target.value })}
        />
        <select
          className={styles.filterSelect}
          value={logFilters.status}
          onChange={(e) => setLogFilters({ status: e.target.value })}
        >
          <option value="all">전체 상태</option>
          <option value="success">성공</option>
          <option value="failure">실패</option>
          <option value="failed">실패 (failed)</option>
          <option value="partial">부분</option>
        </select>
      </div>

      {/* Log List */}
      <div className={styles.logList}>
        {paginated.length === 0 && (
          <div className={styles.empty}>
            {loading ? '로그를 불러오는 중...' : '아직 실행 기록이 없습니다'}
          </div>
        )}
        {paginated.map((log, idx) => {
          const logId = log.id || `${log.job_id}-${log.started_at}-${idx}`;
          const logName = log.crawlerName || log.job_id || '알 수 없음';
          return (
            <div
              key={logId}
              className={getEntryClass(log.status)}
              onClick={() =>
                setExpandedLog(expandedLog === logId ? null : logId)
              }
            >
              <div className={styles.logHeader}>
                <span className={styles.logCrawlerName}>{logName}</span>
                <span className={getStatusClass(log.status)}>
                  {STATUS_LABEL[log.status] || log.status}
                </span>
              </div>

              <div className={styles.logMeta}>
                <div className={styles.logMetaItem}>
                  <span className={styles.logMetaLabel}>시작:</span>
                  {formatDateTime(log.startTime || log.started_at)}
                </div>
                <div className={styles.logMetaItem}>
                  <span className={styles.logMetaLabel}>수집:</span>
                  {log.collected ?? log.result?.items_found ?? '-'}건
                </div>
                <div className={styles.logMetaItem}>
                  <span className={styles.logMetaLabel}>소요:</span>
                  {log.duration || (log.result?.duration ? `${log.result.duration.toFixed(1)}초` : '-')}
                </div>
              </div>

              {expandedLog === logId && (
                <div className={styles.logDetail}>
                  <div className={styles.detailGrid}>
                    <div className={styles.detailItem}>
                      <div className={styles.detailLabel}>시작 시간</div>
                      <div className={styles.detailValue}>
                        {formatDateTime(log.startTime || log.started_at)}
                      </div>
                    </div>
                    <div className={styles.detailItem}>
                      <div className={styles.detailLabel}>종료 시간</div>
                      <div className={styles.detailValue}>
                        {formatDateTime(log.endTime || log.ended_at)}
                      </div>
                    </div>
                    <div className={styles.detailItem}>
                      <div className={styles.detailLabel}>전략</div>
                      <div className={styles.detailValue}>{log.strategy || log.result?.strategy_used || '-'}</div>
                    </div>
                    <div className={styles.detailItem}>
                      <div className={styles.detailLabel}>수집 건수</div>
                      <div className={styles.detailValue}>{log.collected ?? log.result?.items_found ?? '-'}건</div>
                    </div>
                    <div className={styles.detailItem}>
                      <div className={styles.detailLabel}>저장 건수</div>
                      <div className={styles.detailValue}>{log.saved ?? log.result?.items_saved ?? '-'}건</div>
                    </div>
                    <div className={styles.detailItem}>
                      <div className={styles.detailLabel}>소요 시간</div>
                      <div className={styles.detailValue}>{log.duration || (log.result?.duration ? `${log.result.duration.toFixed(1)}초` : '-')}</div>
                    </div>
                  </div>
                  {(log.error || log.result?.error) && (
                    <div className={styles.errorMsg}>{log.error || log.result?.error}</div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className={styles.pagination}>
          <button
            className={styles.pageBtn}
            onClick={() => setLogPage(logPage - 1)}
            disabled={logPage <= 1}
          >
            <ChevronLeft size={16} />
          </button>
          {Array.from({ length: totalPages }, (_, i) => i + 1).map((p) => (
            <button
              key={p}
              className={
                p === logPage ? styles.pageBtnActive : styles.pageBtn
              }
              onClick={() => setLogPage(p)}
            >
              {p}
            </button>
          ))}
          <button
            className={styles.pageBtn}
            onClick={() => setLogPage(logPage + 1)}
            disabled={logPage >= totalPages}
          >
            <ChevronRight size={16} />
          </button>
        </div>
      )}
    </div>
  );
}
