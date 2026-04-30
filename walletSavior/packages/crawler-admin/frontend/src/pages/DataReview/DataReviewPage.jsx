import { useState, useEffect, useMemo, useCallback, memo, useRef } from 'react';
import useAdminStore from '../../stores/adminStore';
import { api } from '../../api/client';
import { CheckCircle, XCircle, MessageSquare, ChevronDown, ChevronUp, ChevronLeft, ChevronRight, RefreshCw, Info, Trash2 } from 'lucide-react';
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

const FIELD_STATUS_ICON = { ok: '✅', warn: '⚠️', missing: '❌' };

function parseAsUTC(dateStr) {
  if (!dateStr) return NaN;
  if (!dateStr.endsWith('Z') && !dateStr.includes('+') && !/[-+]\d{2}:\d{2}$/.test(dateStr)) {
    return new Date(dateStr + 'Z').getTime();
  }
  return new Date(dateStr).getTime();
}

function getRelativeTime(dateStr) {
  if (!dateStr) return null;
  const now = Date.now();
  const then = parseAsUTC(dateStr);
  if (isNaN(then)) return null;
  const diffMs = now - then;
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return '방금 전';
  if (diffMin < 60) return `${diffMin}분 전`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}시간 전`;
  const diffDay = Math.floor(diffHr / 24);
  return `${diffDay}일 전`;
}

function getFreshnessTier(dateStr) {
  if (!dateStr) return { color: 'gray', emoji: '⚪' };
  const diffHr = (Date.now() - parseAsUTC(dateStr)) / 3600000;
  if (diffHr < 24) return { color: 'green', emoji: '🟢' };
  if (diffHr < 72) return { color: 'yellow', emoji: '🟡' };
  if (diffHr < 168) return { color: 'orange', emoji: '🟠' };
  return { color: 'red', emoji: '🔴' };
}

function getDDay(dateStr) {
  if (!dateStr) return null;
  const target = new Date(dateStr);
  if (isNaN(target.getTime())) return null;
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  target.setHours(0, 0, 0, 0);
  const diff = Math.ceil((target - now) / 86400000);
  if (diff > 0) return `D-${diff}`;
  if (diff === 0) return 'D-Day';
  return `D+${Math.abs(diff)}`;
}

function formatShortDate(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return dateStr;
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

export default function DataReviewPage() {
  const ingestions = useAdminStore((s) => s.ingestions);
  const fetchIngestions = useAdminStore((s) => s.fetchIngestions);
  const reviewIngestion = useAdminStore((s) => s.reviewIngestion);
  const cleanupIngestions = useAdminStore((s) => s.cleanupIngestions);
  const deleteIngestion = useAdminStore((s) => s.deleteIngestion);
  const loading = useAdminStore((s) => s.ingestionsLoading);
  const error = useAdminStore((s) => s.ingestionsError);

  const [filter, setFilter] = useState('all');
  const [expandedId, setExpandedId] = useState(null);
  const [rejectReason, setRejectReason] = useState('');
  const [memo, setMemo] = useState('');
  const [showRejectInput, setShowRejectInput] = useState(null);
  const [showMemoInput, setShowMemoInput] = useState(null);
  const [detailCache, setDetailCache] = useState({});
  const [detailLoading, setDetailLoading] = useState(null);
  const [detailError, setDetailError] = useState({});

  const [currentPage, setCurrentPage] = useState(1);
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [qualityTooltipId, setQualityTooltipId] = useState(null);
  const [errorStackExpanded, setErrorStackExpanded] = useState({});
  const [bulkRejectMode, setBulkRejectMode] = useState(false);
  const [bulkRejectReason, setBulkRejectReason] = useState('');

  const [showCleanupModal, setShowCleanupModal] = useState(false);
  const [cleanupLoading, setCleanupLoading] = useState(false);

  useEffect(() => {
    fetchIngestions();
  }, [fetchIngestions]);

  useEffect(() => {
    setCurrentPage(1);
    setSelectedIds(new Set());
  }, [filter]);

  // useMemo: 탭별 건수 계산을 ingestions 변경 시에만 수행
  const approvedCount = useMemo(() => ingestions.filter(i => i.status === 'approved').length, [ingestions]);
  const rejectedCount = useMemo(() => ingestions.filter(i => i.status === 'rejected').length, [ingestions]);
  const processedCount = approvedCount + rejectedCount;

  // 탭별 건수 캐시 — 매 렌더마다 재계산 방지
  const tabCounts = useMemo(() => {
    const counts = {};
    for (const tab of FILTER_TABS) {
      if (tab.key !== 'all') {
        counts[tab.key] = ingestions.filter((i) => i.status === tab.key).length;
      }
    }
    return counts;
  }, [ingestions]);

  const expandCard = async (id) => {
    if (expandedId === id) { setExpandedId(null); return; }
    setExpandedId(id);
    if (!detailCache[id]) {
      await fetchDetail(id);
    }
  };

  const fetchDetail = async (id) => {
    setDetailLoading(id);
    setDetailError(prev => ({ ...prev, [id]: null }));
    try {
      const detail = await api.getIngestion(id);
      setDetailCache(prev => ({ ...prev, [id]: detail }));
    } catch (err) {
      setDetailError(prev => ({ ...prev, [id]: err.message || '데이터 로드 실패' }));
    } finally {
      setDetailLoading(null);
    }
  };

  // useMemo: 필터 변경 시에만 재계산
  const filtered = useMemo(() => {
    return filter === 'all'
      ? ingestions
      : ingestions.filter((item) => item.status === filter);
  }, [ingestions, filter]);

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

  const handleCleanup = useCallback(async (statusList) => {
    setCleanupLoading(true);
    try {
      await cleanupIngestions({ status: statusList, confirm: true });
    } finally {
      setCleanupLoading(false);
      setShowCleanupModal(false);
    }
  }, [cleanupIngestions]);

  const handleDeleteItem = useCallback(async (id) => {
    if (!window.confirm('이 항목을 삭제하시겠습니까?')) return;
    await deleteIngestion(id);
    if (expandedId === id) setExpandedId(null);
  }, [deleteIngestion, expandedId]);

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

  const normalizeScore = (s) => s > 0 && s <= 1 ? Math.round(s * 100) : s;

  const getQualityBreakdown = (item, detail) => {
    const bd = detail?.quality_breakdown || item.quality_breakdown || {};
    const parts = [];
    if (bd.completeness != null) parts.push({ label: '완전성', score: normalizeScore(bd.completeness) });
    if (bd.accuracy != null) parts.push({ label: '정확성', score: normalizeScore(bd.accuracy) });
    if (bd.consistency != null) parts.push({ label: '일관성', score: normalizeScore(bd.consistency) });
    if (bd.freshness != null) parts.push({ label: '신선도', score: normalizeScore(bd.freshness) });
    if (bd.uniqueness != null) parts.push({ label: '고유성', score: normalizeScore(bd.uniqueness) });
    if (parts.length === 0) {
      if (item.missingFields != null) parts.push({ label: '누락 필드', value: `${item.missingFields}개`, raw: true });
      if (item.duplicates != null) parts.push({ label: '중복 항목', value: `${item.duplicates}건`, raw: true });
      if (item.priceOutliers != null) parts.push({ label: '가격 이상치', value: `${item.priceOutliers}건`, raw: true });
    }
    return parts;
  };

  const renderFieldQuality = (item) => {
    const fq = item.field_quality;
    if (!fq || !fq.fields || fq.fields.length === 0) return null;
    const gradeLabel = fq.filled >= fq.total ? '우수' : fq.filled >= fq.total * 0.6 ? '양호' : '부족';
    return (
      <div className={styles.fieldQuality}>
        <div className={styles.fieldChecklist}>
          {fq.fields.map((f) => (
            <span key={f.key} className={styles.fieldCheckItem} title={`${f.label}: ${Math.round(f.ratio * 100)}%`}>
              {FIELD_STATUS_ICON[f.status]} {f.label}
            </span>
          ))}
        </div>
        <span className={styles.fieldSummary}>종합: {gradeLabel} ({fq.filled}/{fq.total})</span>
      </div>
    );
  };

  const renderFreshness = (item) => {
    const dateStr = item.crawled_at || item.timestamp;
    const tier = getFreshnessTier(dateStr);
    const relative = getRelativeTime(dateStr);
    if (!relative) return null;
    return (
      <span className={`${styles.freshnessBadge} ${styles[`freshness_${tier.color}`]}`}>
        {tier.emoji} {relative}
      </span>
    );
  };

  const renderDateRange = (item) => {
    const from = item.valid_from;
    const to = item.valid_to;
    if (!from && !to) return null;
    const dday = to ? getDDay(to) : null;
    return (
      <div className={styles.dateRange}>
        <span className={styles.dateRangeLabel}>할인기간:</span>
        <span className={styles.dateRangeValue}>
          {from ? formatShortDate(from) : '?'} ~ {to ? formatShortDate(to) : '?'}
          {dday && <span className={styles.ddayBadge}>{dday}</span>}
        </span>
      </div>
    );
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
        <div className={styles.headerActions}>
          {processedCount > 0 && (
            <button className={styles.cleanupBtn} onClick={() => setShowCleanupModal(true)} disabled={loading}>
              <Trash2 size={16} />
              처리 완료 정리 ({processedCount})
            </button>
          )}
          <button className={styles.refreshBtn} onClick={() => fetchIngestions()} disabled={loading}>
            <RefreshCw size={16} className={loading ? styles.spin : ''} />
            새로고침
          </button>
        </div>
      </div>

      {/* Cleanup Modal */}
      {showCleanupModal && (
        <div className={styles.modalOverlay} onClick={() => setShowCleanupModal(false)}>
          <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
            <h3 className={styles.modalTitle}>🗑️ 처리 완료 항목 정리</h3>
            <p className={styles.modalDesc}>
              승인 <strong>{approvedCount}</strong>건, 거부 <strong>{rejectedCount}</strong>건을 삭제합니다.
            </p>
            <div className={styles.modalActions}>
              <button
                className={styles.modalBtnApproved}
                onClick={() => handleCleanup(['approved'])}
                disabled={cleanupLoading || approvedCount === 0}
              >
                승인만 삭제 ({approvedCount})
              </button>
              <button
                className={styles.modalBtnRejected}
                onClick={() => handleCleanup(['rejected'])}
                disabled={cleanupLoading || rejectedCount === 0}
              >
                거부만 삭제 ({rejectedCount})
              </button>
              <button
                className={styles.modalBtnAll}
                onClick={() => handleCleanup(['approved', 'rejected'])}
                disabled={cleanupLoading || processedCount === 0}
              >
                전부 삭제 ({processedCount})
              </button>
            </div>
            <button className={styles.modalClose} onClick={() => setShowCleanupModal(false)} disabled={cleanupLoading}>
              취소
            </button>
          </div>
        </div>
      )}

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
                {tabCounts[tab.key] || 0}
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
              const rawQuality = detail?.quality_score ?? item.qualityScore ?? item.quality_score ?? 0;
              const qualityScore = rawQuality > 0 && rawQuality <= 1 ? Math.round(rawQuality * 100) : rawQuality;
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
                        <div className={styles.cardInfoRow}>
                          <span className={styles.crawlerName}>
                            {item.crawlerName || item.crawler_name || item.crawler_id || '알 수 없음'}
                          </span>
                          {renderFreshness(item)}
                        </div>
                        <span className={styles.timestamp}>
                          {(item.timestamp || item.crawled_at) ? new Date(item.timestamp || item.crawled_at).toLocaleString('ko-KR') : ''}
                          {item.processed_at && (
                            <span className={styles.processedAt}> · 처리: {new Date(item.processed_at).toLocaleString('ko-KR')}</span>
                          )}
                        </span>
                        {renderDateRange(item)}
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

                  {/* Field Quality (on card, not expanded) */}
                  {item.field_quality && item.field_quality.fields && item.field_quality.fields.length > 0 && (
                    <div className={styles.cardFieldQuality}>
                      {renderFieldQuality(item)}
                    </div>
                  )}

                  {/* Expanded Detail */}
                  {isExpanded && (
                    <div className={styles.detail}>
                      {detailLoading === item.id && (
                        <div className={styles.detailLoading}>
                          <RefreshCw size={16} className={styles.spin} /> 데이터를 불러오는 중...
                        </div>
                      )}
                      {detailError[item.id] && (
                        <div className={styles.detailError}>
                          <span>⚠️ 데이터 로드 실패: {detailError[item.id]}</span>
                          <button className={styles.retryBtn} onClick={() => fetchDetail(item.id)}>
                            <RefreshCw size={14} /> 다시 시도
                          </button>
                        </div>
                      )}
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

                      {/* 개별 삭제 버튼 (처리 완료 항목) */}
                      {item.status !== 'pending' && (
                        <div className={styles.actions}>
                          <button className={styles.rejectBtn} onClick={() => handleDeleteItem(item.id)} disabled={loading}>
                            <Trash2 size={16} /> 삭제
                          </button>
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
