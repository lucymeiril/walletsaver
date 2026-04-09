import { useState, useEffect, useRef } from 'react';
import useAdminStore from '../../stores/adminStore';
import { ChevronLeft, ChevronRight, Download } from 'lucide-react';
import styles from './Logs.module.css';

const STATUS_LABEL = { success: '성공', failure: '실패', failed: '실패', partial: '부분' };
// 디바운스 지연: 검색 입력 시 매 키스트로크마다 필터링하지 않고 300ms 후 반영
const DEBOUNCE_MS = 300;

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
  const loading = useAdminStore((s) => s.logsLoading);
  const error = useAdminStore((s) => s.logsError);

  const [expandedLog, setExpandedLog] = useState(null);
  // 검색 디바운스용 로컬 상태
  const [searchInput, setSearchInput] = useState(logFilters.crawlerName);
  const debounceRef = useRef(null);

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
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    const h = String(d.getHours()).padStart(2, '0');
    const min = String(d.getMinutes()).padStart(2, '0');
    return `${y}.${m}.${day} ${h}:${min}`;
  };

  const isError = (status) => status === 'failure' || status === 'failed';

  const getEntryClass = (status) => {
    if (isError(status)) return styles.logEntryError;
    if (status === 'partial') return styles.logEntryPartial;
    return styles.logEntrySuccess;
  };

  const getStatusClass = (status) => {
    if (isError(status)) return styles.statusFailure;
    if (status === 'partial') return styles.statusPartial;
    return styles.statusSuccess;
  };

  const handleExport = () => {
    const params = {};
    if (logFilters.status !== 'all') params.status = logFilters.status;
    if (logFilters.dateFrom) params.date_from = logFilters.dateFrom;
    if (logFilters.dateTo) params.date_to = logFilters.dateTo;
    exportLogs(params);
  };

  // 디바운스된 크롤러명 검색 — 매 키스트로크마다 필터링하지 않음
  const handleSearchChange = (e) => {
    const value = e.target.value;
    setSearchInput(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setLogFilters({ crawlerName: value });
    }, DEBOUNCE_MS);
  };

  useEffect(() => {
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, []);

  return (
    <div className={styles.page}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
        <h1 className={styles.pageTitle} style={{ marginBottom: 0 }}>크롤 로그</h1>
        <button
          onClick={handleExport}
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

      {/* Filters — 크롤러명 + 상태 + 날짜 복합 필터 */}
      <div className={styles.filtersBar}>
        <input
          className={styles.filterInput}
          type="text"
          placeholder="크롤러명 검색..."
          value={searchInput}
          onChange={handleSearchChange}
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
        <input
          className={styles.filterDate}
          type="date"
          value={logFilters.dateFrom}
          onChange={(e) => setLogFilters({ dateFrom: e.target.value })}
          title="시작일"
        />
        <span className={styles.dateSep}>~</span>
        <input
          className={styles.filterDate}
          type="date"
          value={logFilters.dateTo}
          onChange={(e) => setLogFilters({ dateTo: e.target.value })}
          title="종료일"
        />
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
                <span className={`${getStatusClass(log.status)} ${log.status === 'partial' ? styles.partialBadge : ''}`}>
                  {STATUS_LABEL[log.status] || log.status}
                  {log.status === 'partial' && (
                    <span className={styles.tooltip}>일부 항목만 수집 성공</span>
                  )}
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
                    {log.result?.quality_score != null && (
                      <div className={styles.detailItem}>
                        <div className={styles.detailLabel}>품질 점수</div>
                        <div className={styles.detailValue}>{log.result.quality_score > 0 && log.result.quality_score <= 1 ? Math.round(log.result.quality_score * 100) : log.result.quality_score}점</div>
                      </div>
                    )}
                  </div>

                  {/* 데이터 샘플 상위 5건 미리보기 */}
                  {log.dataSample && log.dataSample.length > 0 && (
                    <div className={styles.sampleSection}>
                      <div className={styles.sampleTitle}>수집 데이터 샘플 (상위 {log.dataSample.length}건)</div>
                      <div className={styles.sampleList}>
                        {log.dataSample.map((item, i) => (
                          <div key={i} className={styles.sampleItem}>
                            {typeof item === 'object'
                              ? Object.entries(item).slice(0, 4).map(([k, v]) => (
                                  <span key={k} className={styles.sampleField}>
                                    <span className={styles.sampleKey}>{k}:</span> {String(v).slice(0, 60)}
                                  </span>
                                ))
                              : String(item).slice(0, 120)}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

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
