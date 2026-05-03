import { useState, useEffect, useMemo, useCallback } from 'react';
import useAdminStore from '../../stores/adminStore';
import { api } from '../../api/client';
import { CheckCircle, XCircle, MessageSquare, ChevronDown, ChevronUp, ChevronLeft, ChevronRight, RefreshCw, Info, Trash2, Send } from 'lucide-react';
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

const ISSUE_FILTERS = [
  { key: 'all', label: '전체 문제' },
  { key: 'missing', label: '누락 필드' },
  { key: 'format_error', label: '형식 오류' },
  { key: 'duplicate', label: '중복' },
  { key: 'outlier', label: '이상치' },
];

const issueMatchesFilter = (issues, filterKey) => {
  if (!filterKey) return true;
  if (filterKey === 'all') return issues.length > 0;
  if (filterKey === 'missing') return issues.some((issue) => issue.startsWith('missing:'));
  return issues.includes(filterKey);
};

const getIssueText = (issue) => {
  if (issue.startsWith('missing:')) return `누락:${issue.slice(8)}`;
  if (issue === 'outlier') return '이상치';
  if (issue === 'duplicate') return '중복';
  if (issue === 'format_error') return '형식오류';
  return issue;
};

const getProblemIssueMap = (detail) => {
  const map = new Map();
  const addIssue = (index, issue) => {
    if (!Number.isInteger(index)) return;
    const issues = map.get(index) || [];
    if (!issues.includes(issue)) issues.push(issue);
    map.set(index, issues);
  };

  for (const problem of detail?.problem_indices || []) {
    if (Number.isInteger(problem.index)) {
      map.set(problem.index, Array.isArray(problem.issues) ? problem.issues : []);
    }
  }

  const bd = detail?.quality_breakdown || {};
  for (const item of bd.missing_fields_detail || []) {
    for (const field of item.fields || []) addIssue(item.index, `missing:${field}`);
  }
  for (const item of bd.format_errors_detail || []) addIssue(item.index, 'format_error');
  for (const index of bd.duplicate_indices || []) addIssue(index, 'duplicate');
  for (const index of bd.outlier_indices || []) addIssue(index, 'outlier');

  return map;
};

const getIssueCounts = (detail) => {
  const bd = detail?.quality_breakdown || {};
  const issueMap = getProblemIssueMap(detail);
  const derived = { missing: 0, format_error: 0, duplicate: 0, outlier: 0 };
  for (const issues of issueMap.values()) {
    if (issues.some((issue) => issue.startsWith('missing:'))) derived.missing += 1;
    if (issues.includes('format_error')) derived.format_error += 1;
    if (issues.includes('duplicate')) derived.duplicate += 1;
    if (issues.includes('outlier')) derived.outlier += 1;
  }
  const counts = {
    all: issueMap.size,
    missing: bd.missing_fields ?? derived.missing,
    format_error: bd.format_errors ?? derived.format_error,
    duplicate: bd.duplicates ?? derived.duplicate,
    outlier: bd.outliers ?? derived.outlier,
  };

  if (counts.all === 0 && (counts.missing || counts.format_error || counts.duplicate || counts.outlier)) {
    counts.all = counts.missing + counts.format_error + counts.duplicate + counts.outlier;
  }
  return counts;
};

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
  const [aiBaseUrl, setAiBaseUrl] = useState(() => localStorage.getItem('crawler-ai-base-url') || 'http://localhost:8003');
  const [aiProviderId, setAiProviderId] = useState(() => localStorage.getItem('crawler-ai-provider-id') || '');
  const [aiProviders, setAiProviders] = useState([]);
  const [aiProviderLoading, setAiProviderLoading] = useState(false);
  const [aiExportState, setAiExportState] = useState({});
  const [activeIssueFilters, setActiveIssueFilters] = useState({});

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
    if (expandedId === id) {
      setExpandedId(null);
      setActiveIssueFilters(prev => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
      return;
    }
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

  const loadAiProviders = useCallback(async (baseUrl = aiBaseUrl) => {
    const normalized = baseUrl.trim().replace(/\/$/, '');
    if (!normalized) return;
    setAiProviderLoading(true);
    try {
      const res = await fetch(`${normalized}/api/providers`);
      if (!res.ok) throw new Error(`AI-admin provider 조회 실패 (HTTP ${res.status})`);
      const data = await res.json();
      const providers = data.providers || [];
      setAiProviders(providers);
      if (!aiProviderId && providers[0]?.provider_id) {
        setAiProviderId(providers[0].provider_id);
        localStorage.setItem('crawler-ai-provider-id', providers[0].provider_id);
      }
    } catch (err) {
      setAiExportState(prev => ({
        ...prev,
        providerLoad: { ok: false, message: err.message || 'AI provider 조회 실패' },
      }));
    } finally {
      setAiProviderLoading(false);
    }
  }, [aiBaseUrl, aiProviderId]);

  const handleAiBaseUrlChange = useCallback((value) => {
    setAiBaseUrl(value);
    localStorage.setItem('crawler-ai-base-url', value);
  }, []);

  const handleAiProviderChange = useCallback((value) => {
    setAiProviderId(value);
    localStorage.setItem('crawler-ai-provider-id', value);
  }, []);

  const handleSendToAi = useCallback(async (item, detail) => {
    const records = detail?.items || item.items || item.data || [];
    if (!records.length) {
      setAiExportState(prev => ({ ...prev, [item.id]: { ok: false, message: '전송할 크롤링 데이터가 없습니다.' } }));
      return;
    }
    if (!aiBaseUrl.trim() || !aiProviderId.trim()) {
      setAiExportState(prev => ({ ...prev, [item.id]: { ok: false, message: 'AI-admin 주소와 provider를 먼저 선택하세요.' } }));
      return;
    }
    setAiExportState(prev => ({ ...prev, [item.id]: { loading: true, message: 'AI-admin으로 전송 중...' } }));
    try {
      const result = await api.forwardRawRecordsToAi({
        ai_admin_base_url: aiBaseUrl.trim(),
        provider_id: aiProviderId.trim(),
        source_name: item.crawler_name || item.crawlerName || item.crawler_id || 'crawler-admin',
        crawler_name: item.crawler_name || item.crawlerName || item.crawler_id || 'crawler-admin',
        schema_type: item.schema_type || item.schemaType || 'DiscountItem',
        source_url: detail?.source_url || item.source_url || undefined,
        items: records,
      });
      const responses = result.responses || [];
      setAiExportState(prev => ({
        ...prev,
        [item.id]: {
          ok: true,
          message: `AI-admin 전송 완료: ${result.records_sent ?? records.length}건, batch ${result.batches_sent ?? responses.length}개`,
          result,
        },
      }));
    } catch (err) {
      setAiExportState(prev => ({
        ...prev,
        [item.id]: { ok: false, message: err.message || 'AI-admin 전송 실패' },
      }));
    }
  }, [aiBaseUrl, aiProviderId]);

  const getQualityColor = (score) => {
    if (score >= 90) return styles.qualityHigh;
    if (score >= 70) return styles.qualityMid;
    return styles.qualityLow;
  };

  const setIssueFilter = (itemId, filterKey) => {
    setActiveIssueFilters(prev => ({ ...prev, [itemId]: filterKey }));
  };

  const clearIssueFilter = (itemId) => {
    setActiveIssueFilters(prev => {
      const next = { ...prev };
      delete next[itemId];
      return next;
    });
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
              const allKeys = items.length > 0 ? Array.from(new Set(items.flatMap((row) => Object.keys(row)))) : [];
              const qualityBreakdown = getQualityBreakdown(item, detail);
              const issueMap = getProblemIssueMap(detail);
              const issueCounts = getIssueCounts(detail);
              const activeIssueFilter = activeIssueFilters[item.id] || null;
              const displayedRows = activeIssueFilter
                ? items.map((row, idx) => ({ row, idx, issues: issueMap.get(idx) || [] }))
                    .filter(({ issues }) => issueMatchesFilter(issues, activeIssueFilter))
                : items.map((row, idx) => ({ row, idx, issues: issueMap.get(idx) || [] }));
              const activeIssueLabel = ISSUE_FILTERS.find((f) => f.key === activeIssueFilter)?.label;

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
                          <div className={styles.tableHeaderRow}>
                            <h4 className={styles.sectionTitle}>
                              🔍 데이터 전체 보기 ({activeIssueFilter ? `${displayedRows.length}/${items.length}` : items.length}건)
                            </h4>
                            {activeIssueFilter && (
                              <button className={styles.resetIssueFilterBtn} onClick={() => clearIssueFilter(item.id)}>
                                필터 초기화
                              </button>
                            )}
                          </div>
                          {issueCounts.all > 0 && (
                            <div className={styles.issueFilterPanel}>
                              <span className={styles.issueFilterLabel}>문제 행 필터:</span>
                              {ISSUE_FILTERS.map((filterDef) => {
                                const count = filterDef.key === 'all' ? issueCounts.all : issueCounts[filterDef.key];
                                if (!count) return null;
                                return (
                                  <button
                                    key={filterDef.key}
                                    className={activeIssueFilter === filterDef.key ? styles.issueChipActive : styles.issueChip}
                                    onClick={() => setIssueFilter(item.id, filterDef.key)}
                                    aria-pressed={activeIssueFilter === filterDef.key}
                                  >
                                    {filterDef.label} {count}건
                                  </button>
                                );
                              })}
                              {activeIssueFilter && (
                                <span className={styles.activeIssueState}>
                                  {activeIssueLabel}만 표시 중 · 원본 행 번호 유지
                                </span>
                              )}
                            </div>
                          )}
                          {activeIssueFilter && displayedRows.length === 0 ? (
                            <div className={styles.emptyFilteredRows}>해당 문제 유형의 행이 없습니다.</div>
                          ) : (
                            <div className={styles.fullTableWrapper}>
                              <table className={styles.fullTable}>
                                <thead>
                                  <tr>
                                    <th className={styles.rowNumTh}>#</th>
                                    {allKeys.map((key) => (
                                      <th key={key}>{key}</th>
                                    ))}
                                    {issueCounts.all > 0 && <th>문제</th>}
                                  </tr>
                                </thead>
                                <tbody>
                                  {displayedRows.map(({ row, idx, issues }) => (
                                    <tr key={idx} className={issues.length > 0 ? styles.problemRow : ''}>
                                      <td className={styles.rowNum}>{idx + 1}</td>
                                      {allKeys.map((key) => (
                                        <td key={key} className={`${styles.dataCell} ${getCellClassName(key, row[key])}`}>
                                          {String(row[key] ?? '')}
                                        </td>
                                      ))}
                                      {issueCounts.all > 0 && (
                                        <td className={styles.issueCell}>
                                          {issues.length > 0 ? issues.map(getIssueText).join(' / ') : '정상'}
                                        </td>
                                      )}
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          )}
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

                      <div className={styles.section}>
                        <h4 className={styles.sectionTitle}>🤖 AI 정제 파이프라인 전송</h4>
                        <p className={styles.sectionDesc}>
                          이 버튼은 현재 검토 중인 원본 크롤링 데이터를 AI-admin의 실제 ingest 형식으로 보냅니다.
                          터미널 명령 없이 여기서 크롤러 → AI 검수 큐 연결을 시작합니다.
                        </p>
                        <div className={styles.aiExportPanel}>
                          <label className={styles.aiExportField}>
                            AI-admin 주소
                            <input
                              value={aiBaseUrl}
                              onChange={(e) => handleAiBaseUrlChange(e.target.value)}
                              placeholder="http://localhost:8003"
                            />
                          </label>
                          <label className={styles.aiExportField}>
                            Provider
                            <select value={aiProviderId} onChange={(e) => handleAiProviderChange(e.target.value)}>
                              <option value="">provider 선택</option>
                              {aiProviders.map((provider) => (
                                <option key={provider.provider_id} value={provider.provider_id}>
                                  {provider.provider_id} · {provider.provider_kind} · {provider.default_model}
                                </option>
                              ))}
                              {aiProviderId && !aiProviders.some((p) => p.provider_id === aiProviderId) && (
                                <option value={aiProviderId}>{aiProviderId}</option>
                              )}
                            </select>
                          </label>
                          <button
                            className={styles.secondaryActionBtn}
                            onClick={() => loadAiProviders(aiBaseUrl)}
                            disabled={aiProviderLoading}
                          >
                            <RefreshCw size={14} className={aiProviderLoading ? styles.spin : ''} />
                            provider 불러오기
                          </button>
                          <button
                            className={styles.aiSendBtn}
                            onClick={() => handleSendToAi(item, detail)}
                            disabled={aiExportState[item.id]?.loading || !items.length}
                          >
                            <Send size={14} />
                            이 크롤링 결과를 AI 검수 큐로 보내기
                          </button>
                        </div>
                        {aiExportState.providerLoad && !aiExportState.providerLoad.ok && (
                          <div className={styles.aiExportMessageError}>{aiExportState.providerLoad.message}</div>
                        )}
                        {aiExportState[item.id] && (
                          <div className={aiExportState[item.id].ok ? styles.aiExportMessageOk : styles.aiExportMessageError}>
                            {aiExportState[item.id].message}
                          </div>
                        )}
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
