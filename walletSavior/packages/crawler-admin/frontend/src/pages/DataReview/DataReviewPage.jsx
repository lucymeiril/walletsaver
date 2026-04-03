import { useState, useEffect } from 'react';
import useAdminStore from '../../stores/adminStore';
import { CheckCircle, XCircle, MessageSquare, ChevronDown, ChevronUp, ChevronLeft, ChevronRight, RefreshCw, Info } from 'lucide-react';
import styles from './DataReviewPage.module.css';

const STATUS_MAP = {
  pending: { label: '대기', cls: 'statusPending' },
  crawler_approved: { label: '1차 승인', cls: 'statusApproved' },
  approved: { label: '승인', cls: 'statusDone' },
  rejected: { label: '거부', cls: 'statusRejected' },
};

const FILTER_TABS = [
  { key: 'all', label: '전체' },
  { key: 'pending', label: '대기' },
  { key: 'crawler_approved', label: '1차 승인' },
  { key: 'approved', label: '승인' },
  { key: 'rejected', label: '거부' },
];

const ITEMS_PER_PAGE = 10;

const isMissingValue = (val) => val === null || val === undefined || val === '';
const isOutlierValue = (key, val) => {
  if (typeof val !== 'number') return false;
  const k = key.toLowerCase();
  return (k.includes('price') || k.includes('가격')) && (val < 0 || val > 10000000);
};

export default function DataReviewPage() {
  const ingestions = useAdminStore((s) => s.ingestions);
  const fetchIngestions = useAdminStore((s) => s.fetchIngestions);
  const reviewIngestion = useAdminStore((s) => s.reviewIngestion);
  const loading = useAdminStore((s) => s.loading);
  const error = useAdminStore((s) => s.error);

  const [filter, setFilter] = useState('all');
  const [expandedId, setExpandedId] = useState(null);
  const [rejectReason, setRejectReason] = useState('');
  const [memo, setMemo] = useState('');
  const [showRejectInput, setShowRejectInput] = useState(null);
  const [showMemoInput, setShowMemoInput] = useState(null);
  const [detailCache, setDetailCache] = useState({});

  const [currentPage, setCurrentPage] = useState(1);
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [qualityTooltipId, setQualityTooltipId] = useState(null);
  const [errorStackExpanded, setErrorStackExpanded] = useState({});
  const [bulkRejectMode, setBulkRejectMode] = useState(false);
  const [bulkRejectReason, setBulkRejectReason] = useState('');

  useEffect(() => {
    fetchIngestions();
  }, [fetchIngestions]);

  useEffect(() => {
    setCurrentPage(1);
    setSelectedIds(new Set());
  }, [filter]);

  const expandCard = async (id) => {
    if (expandedId === id) { setExpandedId(null); return; }
    setExpandedId(id);
    if (!detailCache[id]) {
      try {
        const detail = await fetch(`/api/ingestions/${id}`).then(r => r.json());
        setDetailCache(prev => ({ ...prev, [id]: detail }));
      } catch { /* fallback */ }
    }
  };

  const filtered = filter === 'all'
    ? ingestions
    : ingestions.filter((item) => item.status === filter);

  const totalPages = Math.ceil(filtered.length / ITEMS_PER_PAGE);
  const paginatedItems = filtered.slice(
    (currentPage - 1) * ITEMS_PER_PAGE,
    currentPage * ITEMS_PER_PAGE
  );

  const pendingOnPage = paginatedItems.filter(i => i.status === 'pending');
  const allPendingSelected = pendingOnPage.length > 0 && pendingOnPage.every(i => selectedIds.has(i.id));

  const toggleSelect = (id) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (allPendingSelected) pendingOnPage.forEach(i => next.delete(i.id));
      else pendingOnPage.forEach(i => next.add(i.id));
      return next;
    });
  };

  const handleApprove = async (id) => {
    await reviewIngestion(id, { action: 'approve', notes: memo || undefined });
    setMemo('');
    setExpandedId(null);
  };

  const handleReject = async (id) => {
    if (!rejectReason.trim()) return;
    await reviewIngestion(id, { action: 'reject', notes: rejectReason, rejected_reason: rejectReason });
    setRejectReason('');
    setShowRejectInput(null);
    setExpandedId(null);
  };

  const handleMemo = async (id) => {
    if (!memo.trim()) return;
    await reviewIngestion(id, { action: 'approve', notes: memo });
    setMemo('');
    setShowMemoInput(null);
  };

  const handleBulkApprove = async () => {
    const ids = [...selectedIds];
    for (const id of ids) {
      await reviewIngestion(id, { action: 'approve' });
    }
    setSelectedIds(new Set());
  };

  const handleBulkReject = async () => {
    if (!bulkRejectReason.trim()) return;
    const ids = [...selectedIds];
    for (const id of ids) {
      await reviewIngestion(id, { action: 'reject', notes: bulkRejectReason, rejected_reason: bulkRejectReason });
    }
    setSelectedIds(new Set());
    setBulkRejectMode(false);
    setBulkRejectReason('');
  };

  const getQualityColor = (score) => {
    if (score >= 90) return styles.qualityHigh;
    if (score >= 70) return styles.qualityMid;
    return styles.qualityLow;
  };

  const getCellClassName = (key, value) => {
    if (isMissingValue(value)) return styles.cellMissing;
    if (isOutlierValue(key, value)) return styles.cellOutlier;
    return '';
  };

  const getQualityBreakdown = (item, detail) => {
    const bd = detail?.quality_breakdown || item.quality_breakdown || {};
    const parts = [];
    if (bd.completeness != null) parts.push({ label: '완전성', score: bd.completeness });
    if (bd.accuracy != null) parts.push({ label: '정확성', score: bd.accuracy });
    if (bd.consistency != null) parts.push({ label: '일관성', score: bd.consistency });
    if (bd.freshness != null) parts.push({ label: '신선도', score: bd.freshness });
    if (bd.uniqueness != null) parts.push({ label: '고유성', score: bd.uniqueness });
    if (parts.length === 0) {
      if (item.missingFields != null) parts.push({ label: '누락 필드', value: `${item.missingFields}개`, raw: true });
      if (item.duplicates != null) parts.push({ label: '중복 항목', value: `${item.duplicates}건`, raw: true });
      if (item.priceOutliers != null) parts.push({ label: '가격 이상치', value: `${item.priceOutliers}건`, raw: true });
    }
    return parts;
  };

  const renderError = (err, itemId) => {
    if (!err) return null;
    const errorObj = typeof err === 'string' ? { message: err } : err;
    const type = errorObj.type || errorObj.name || '알 수 없음';
    const message = errorObj.message || JSON.stringify(errorObj);
    const stack = errorObj.stack || errorObj.traceback;
    const strategy = errorObj.strategy;
    const isExpanded = errorStackExpanded[itemId];

    return (
      <div className={styles.errorBox}>
        <div className={styles.errorHeader}>
          <span className={styles.errorTypeBadge}>{type}</span>
          {strategy && <span className={styles.errorStrategy}>{strategy}</span>}
        </div>
        <p className={styles.errorMessage}>{message}</p>
        {stack && (
          <div className={styles.errorStackWrap}>
            <button
              className={styles.stackToggle}
              onClick={() => setErrorStackExpanded(prev => ({ ...prev, [itemId]: !isExpanded }))}
            >
              {isExpanded ? '▼ 스택 접기' : '▶ 스택 트레이스 보기'}
            </button>
            {isExpanded && <pre className={styles.stackTrace}>{stack}</pre>}
          </div>
        )}
      </div>
    );
  };

  const renderPagination = () => {
    if (totalPages <= 1) return null;
    let start = Math.max(1, currentPage - 2);
    const end = Math.min(totalPages, start + 4);
    if (end - start < 4) start = Math.max(1, end - 4);
    const pages = [];
    for (let i = start; i <= end; i++) pages.push(i);

    return (
      <div className={styles.pagination}>
        <button className={styles.pageBtn} disabled={currentPage === 1} onClick={() => setCurrentPage(1)}>«</button>
        <button className={styles.pageBtn} disabled={currentPage === 1} onClick={() => setCurrentPage(p => p - 1)}>
          <ChevronLeft size={14} />
        </button>
        {pages.map(p => (
          <button key={p} className={p === currentPage ? styles.pageBtnActive : styles.pageBtn} onClick={() => setCurrentPage(p)}>
            {p}
          </button>
        ))}
        <button className={styles.pageBtn} disabled={currentPage === totalPages} onClick={() => setCurrentPage(p => p + 1)}>
          <ChevronRight size={14} />
        </button>
        <button className={styles.pageBtn} disabled={currentPage === totalPages} onClick={() => setCurrentPage(totalPages)}>»</button>
        <span className={styles.pageInfo}>
          {filtered.length}건 중 {(currentPage - 1) * ITEMS_PER_PAGE + 1}–{Math.min(currentPage * ITEMS_PER_PAGE, filtered.length)}
        </span>
      </div>
    );
  };

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.pageTitle}>데이터 검토</h1>
        <button className={styles.refreshBtn} onClick={() => fetchIngestions()} disabled={loading}>
          <RefreshCw size={16} className={loading ? styles.spin : ''} />
          새로고침
        </button>
      </div>

      {error && <div className={styles.errorBanner}>{error}</div>}

      {/* Filter Tabs */}
      <div className={styles.tabs}>
        {FILTER_TABS.map((tab) => (
          <button
            key={tab.key}
            className={filter === tab.key ? styles.tabActive : styles.tab}
            onClick={() => setFilter(tab.key)}
          >
            {tab.label}
            {tab.key !== 'all' && (
              <span className={styles.tabCount}>
                {ingestions.filter((i) => i.status === tab.key).length}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Bulk Actions Bar */}
      {selectedIds.size > 0 && (
        <div className={styles.bulkBar}>
          <span className={styles.bulkInfo}>{selectedIds.size}개 선택됨</span>
          <button className={styles.bulkApproveBtn} onClick={handleBulkApprove} disabled={loading}>
            <CheckCircle size={14} /> 선택 승인
          </button>
          {bulkRejectMode ? (
            <div className={styles.inlineForm}>
              <input
                className={styles.reasonInput}
                placeholder="거부 사유..."
                value={bulkRejectReason}
                onChange={(e) => setBulkRejectReason(e.target.value)}
              />
              <button className={styles.rejectConfirmBtn} onClick={handleBulkReject}>확인</button>
              <button className={styles.cancelBtn} onClick={() => { setBulkRejectMode(false); setBulkRejectReason(''); }}>취소</button>
            </div>
          ) : (
            <button className={styles.bulkRejectBtn} onClick={() => setBulkRejectMode(true)} disabled={loading}>
              <XCircle size={14} /> 선택 거부
            </button>
          )}
          <button className={styles.bulkClearBtn} onClick={() => setSelectedIds(new Set())}>선택 해제</button>
        </div>
      )}

      {/* List */}
      {loading && ingestions.length === 0 ? (
        <div className={styles.empty}>데이터를 불러오는 중...</div>
      ) : filtered.length === 0 ? (
        <div className={styles.empty}>
          {ingestions.length === 0
            ? '검토할 데이터가 없습니다. 크롤러를 실행한 후 여기에서 결과를 확인하세요.'
            : '해당 상태의 데이터가 없습니다.'}
        </div>
      ) : (
        <>
          {/* Select All */}
          {pendingOnPage.length > 0 && (
            <div className={styles.selectAllBar}>
              <label className={styles.checkLabel}>
                <input type="checkbox" checked={allPendingSelected} onChange={toggleSelectAll} className={styles.checkbox} />
                이 페이지 대기 항목 전체 선택 ({pendingOnPage.length}건)
              </label>
            </div>
          )}

          <div className={styles.list}>
            {paginatedItems.map((item) => {
              const st = STATUS_MAP[item.status] || STATUS_MAP.pending;
              const isExpanded = expandedId === item.id;
              const detail = detailCache[item.id];
              const items = detail?.items || item.items || item.data || [];
              const qualityScore = detail?.quality_score ?? item.qualityScore ?? item.quality_score ?? 0;
              const schemaType = item.schemaType ?? item.schema_type ?? 'Unknown';
              const allKeys = items.length > 0 ? Object.keys(items[0]) : [];
              const qualityBreakdown = getQualityBreakdown(item, detail);

              return (
                <div key={item.id} className={styles.card}>
                  {/* Card Header */}
                  <div className={styles.cardHeader}>
                    {item.status === 'pending' && (
                      <input
                        type="checkbox"
                        checked={selectedIds.has(item.id)}
                        onChange={() => toggleSelect(item.id)}
                        onClick={(e) => e.stopPropagation()}
                        className={styles.checkbox}
                      />
                    )}
                    <div className={styles.cardClickArea} onClick={() => expandCard(item.id)}>
                      <div className={styles.cardInfo}>
                        <span className={styles.crawlerName}>
                          {item.crawlerName || item.crawler_name || item.crawler_id || '알 수 없음'}
                        </span>
                        <span className={styles.timestamp}>
                          {(item.timestamp || item.crawled_at) ? new Date(item.timestamp || item.crawled_at).toLocaleString('ko-KR') : ''}
                        </span>
                      </div>
                      <div className={styles.cardMeta}>
                        <span className={styles.itemCount}>
                          {items.length || item.itemCount || item.items_count || 0}건
                        </span>
                        <span
                          className={`${styles.qualityBadge} ${getQualityColor(qualityScore)}`}
                          onMouseEnter={() => setQualityTooltipId(item.id)}
                          onMouseLeave={() => setQualityTooltipId(null)}
                        >
                          품질 {qualityScore}점
                          <Info size={12} className={styles.infoIcon} />
                          {qualityTooltipId === item.id && qualityBreakdown.length > 0 && (
                            <div className={styles.qualityTooltip}>
                              <div className={styles.tooltipTitle}>품질 점수 상세</div>
                              {qualityBreakdown.map((b, i) => (
                                <div key={i} className={styles.tooltipRow}>
                                  <span>{b.label}</span>
                                  <span className={b.raw ? '' : getQualityColor(b.score)}>
                                    {b.raw ? b.value : `${b.score}점`}
                                  </span>
                                </div>
                              ))}
                            </div>
                          )}
                        </span>
                        <span className={styles.schemaTag}>{schemaType}</span>
                        <span className={`${styles.statusBadge} ${styles[st.cls]}`}>{st.label}</span>
                        {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                      </div>
                    </div>
                  </div>

                  {/* Expanded Detail */}
                  {isExpanded && (
                    <div className={styles.detail}>
                      {/* 스키마 정보 — 전체 텍스트 표시 */}
                      {items.length > 0 && (
                        <div className={styles.section}>
                          <h4 className={styles.sectionTitle}>📋 스키마 정보</h4>
                          <div className={styles.schemaGrid}>
                            {Object.entries(items[0] || {}).map(([key, val]) => (
                              <div key={key} className={`${styles.schemaItem} ${getCellClassName(key, val)}`}>
                                <span className={styles.schemaKey}>{key}</span>
                                <span className={styles.schemaType}>{typeof val}</span>
                                <span className={styles.schemaValueFull}>{String(val)}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* 데이터 전체 보기 — 모든 행·열, 잘림 해제, 하이라이트 */}
                      {items.length > 0 && (
                        <div className={styles.section}>
                          <h4 className={styles.sectionTitle}>🔍 데이터 전체 보기 ({items.length}건)</h4>
                          <div className={styles.fullTableWrapper}>
                            <table className={styles.fullTable}>
                              <thead>
                                <tr>
                                  <th className={styles.rowNumTh}>#</th>
                                  {allKeys.map((key) => (
                                    <th key={key}>{key}</th>
                                  ))}
                                </tr>
                              </thead>
                              <tbody>
                                {items.map((row, idx) => (
                                  <tr key={idx}>
                                    <td className={styles.rowNum}>{idx + 1}</td>
                                    {allKeys.map((key) => (
                                      <td key={key} className={`${styles.dataCell} ${getCellClassName(key, row[key])}`}>
                                        {String(row[key] ?? '')}
                                      </td>
                                    ))}
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      )}

                      {/* 품질 분석 + breakdown */}
                      <div className={styles.section}>
                        <h4 className={styles.sectionTitle}>📊 품질 분석</h4>
                        <div className={styles.qualityGrid}>
                          <div className={styles.qualityItem}>
                            <span className={styles.qualityLabel}>전체 품질 점수</span>
                            <span className={`${styles.qualityValue} ${getQualityColor(qualityScore)}`}>
                              {qualityScore}점
                            </span>
                          </div>
                          {item.missingFields != null && (
                            <div className={styles.qualityItem}>
                              <span className={styles.qualityLabel}>누락 필드</span>
                              <span className={styles.qualityValue}>{item.missingFields}개</span>
                            </div>
                          )}
                          {item.duplicates != null && (
                            <div className={styles.qualityItem}>
                              <span className={styles.qualityLabel}>중복 항목</span>
                              <span className={styles.qualityValue}>{item.duplicates}건</span>
                            </div>
                          )}
                          {item.priceOutliers != null && (
                            <div className={styles.qualityItem}>
                              <span className={styles.qualityLabel}>가격 이상치</span>
                              <span className={styles.qualityValue} style={{ color: item.priceOutliers > 0 ? 'var(--red)' : 'inherit' }}>
                                {item.priceOutliers}건
                              </span>
                            </div>
                          )}
                          {qualityBreakdown.filter(b => !b.raw).map((b, i) => (
                            <div key={i} className={styles.qualityItem}>
                              <span className={styles.qualityLabel}>{b.label}</span>
                              <span className={`${styles.qualityValue} ${getQualityColor(b.score)}`}>
                                {b.score}점
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>

                      {/* 에러 정보 — 포매팅 + 스택 접기 */}
                      {item.error && (
                        <div className={styles.section}>
                          <h4 className={styles.sectionTitle}>⚠️ 에러 정보</h4>
                          {renderError(item.error, item.id)}
                        </div>
                      )}

                      {/* Actions */}
                      {item.status === 'pending' && (
                        <div className={styles.actions}>
                          <button className={styles.approveBtn} onClick={() => handleApprove(item.id)}>
                            <CheckCircle size={16} /> 1차 승인
                          </button>

                          {showRejectInput === item.id ? (
                            <div className={styles.inlineForm}>
                              <input
                                className={styles.reasonInput}
                                placeholder="거부 사유를 입력하세요..."
                                value={rejectReason}
                                onChange={(e) => setRejectReason(e.target.value)}
                              />
                              <button className={styles.rejectConfirmBtn} onClick={() => handleReject(item.id)}>확인</button>
                              <button className={styles.cancelBtn} onClick={() => setShowRejectInput(null)}>취소</button>
                            </div>
                          ) : (
                            <button className={styles.rejectBtn} onClick={() => setShowRejectInput(item.id)}>
                              <XCircle size={16} /> 거부
                            </button>
                          )}

                          {showMemoInput === item.id ? (
                            <div className={styles.inlineForm}>
                              <input
                                className={styles.reasonInput}
                                placeholder="메모를 입력하세요..."
                                value={memo}
                                onChange={(e) => setMemo(e.target.value)}
                              />
                              <button className={styles.memoConfirmBtn} onClick={() => handleMemo(item.id)}>저장</button>
                              <button className={styles.cancelBtn} onClick={() => setShowMemoInput(null)}>취소</button>
                            </div>
                          ) : (
                            <button className={styles.memoBtn} onClick={() => setShowMemoInput(item.id)}>
                              <MessageSquare size={16} /> 메모 추가
                            </button>
                          )}
                        </div>
                      )}

                      {item.memo && (
                        <div className={styles.memoDisplay}>
                          <strong>📝 메모:</strong> {item.memo}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {/* Pagination */}
          {renderPagination()}
        </>
      )}
    </div>
  );
}
