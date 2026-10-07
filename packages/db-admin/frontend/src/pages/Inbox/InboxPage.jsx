import { useState, useEffect, useMemo, useCallback } from 'react';
import { useLocation } from 'react-router-dom';
import useDbAdminStore from '../../stores/dbAdminStore';
import { api } from '../../api/client';
import { CheckCircle, XCircle, AlertTriangle, RefreshCw, ChevronLeft, ChevronRight, X, Info, Inbox } from 'lucide-react';
import { useAbortController } from '../../hooks/useAbortController';
import LastUpdated from '../../components/LastUpdated';
import EmptyState from '../../components/EmptyState';
import styles from './InboxPage.module.css';

export function matchesReviewContext(row, context) {
  if (!context || row.public_product_id !== context.public_product_id) return false;
  if (context.public_variant_id && row.public_variant_id !== context.public_variant_id) return false;
  if (row.public_source_listing_id != null) return row.public_source_listing_id === context.public_source_listing_id;
  const url = row.detail_url || row.source_url;
  return Boolean(context.source_url && url === context.source_url
    && String(row.source || row.source_name || '').toLowerCase() === context.source.toLowerCase());
}

export default function InboxPage() {
  const location = useLocation();
  const reviewContext = useMemo(() => {
    const q = new URLSearchParams(location.search);
    return q.get('public_product_id') ? Object.fromEntries(['public_product_id','public_variant_id','public_source_listing_id','native_key','source','source_url'].map(key => [key,q.get(key) || ''])) : null;
  }, [location.search]);

  const [relatedLookup, setRelatedLookup] = useState({checked:0, items:[], loading:false, error:''});
  useEffect(() => {setRelatedLookup({checked:0,items:[],loading:false,error:''});}, [location.search]);
  const ingestions = useDbAdminStore((s) => s.ingestions);
  const fetchIngestions = useDbAdminStore((s) => s.fetchIngestions);
  const fetchIngestionStats = useDbAdminStore((s) => s.fetchIngestionStats);
  const ingestionStats = useDbAdminStore((s) => s.ingestionStats);
  const ingestionPagination = useDbAdminStore((s) => s.ingestionPagination);
  const reviewIngestion = useDbAdminStore((s) => s.reviewIngestion);
  const bulkApproveIngestions = useDbAdminStore((s) => s.bulkApproveIngestions);
  const loadingIngestions = useDbAdminStore((s) => s.loadingIngestions);
  const loading = loadingIngestions;
  const error = useDbAdminStore((s) => s.error);
  const lastFetchedAt = useDbAdminStore((s) => s.lastFetchedAt);

  const [detailItem, setDetailItem] = useState(null);
  const [checkedItems, setCheckedItems] = useState(new Set());
  const [rejectReason, setRejectReason] = useState('');
  const [memo, setMemo] = useState('');
  const [showReject, setShowReject] = useState(false);
  const [currentPage, setCurrentPage] = useState(1);
  // 벌크 승인용 목록 체크
  const [bulkChecked, setBulkChecked] = useState(new Set());
  // 품질 점수 breakdown 팝오버
  const [qualityPopover, setQualityPopover] = useState(null);
  // 카드 레벨 빠른 거부
  const [quickRejectId, setQuickRejectId] = useState(null);

  const REJECT_PRESETS = ['중복', '잘못된 데이터', '카테고리 불일치', '가격 이상'];

  const PER_PAGE = 20;
  const AUTO_REFRESH_MS = 30_000;
  const getSignal = useAbortController([currentPage]);

  const loadPage = useCallback((page) => {
    setCurrentPage(page);
    const signal = getSignal();
    fetchIngestions({ ...(reviewContext ? {} : {status:'crawler_approved'}), page, per_page: PER_PAGE }, { signal });
  }, [fetchIngestions, getSignal, reviewContext]);

  useEffect(() => {
    const signal = getSignal();
    fetchIngestions({ ...(reviewContext ? {} : {status:'crawler_approved'}), page: 1, per_page: PER_PAGE }, { signal });
    fetchIngestionStats({ signal });

    const interval = setInterval(() => {
      const sig = getSignal();
      fetchIngestions({ ...(reviewContext ? {} : {status:'crawler_approved'}), page: currentPage, per_page: PER_PAGE }, { signal: sig });
      fetchIngestionStats({ signal: sig });
    }, AUTO_REFRESH_MS);

    return () => clearInterval(interval);
  }, [fetchIngestions, fetchIngestionStats, getSignal, currentPage, reviewContext]);

  const openDetail = async (item) => {
    setCheckedItems(new Set());
    setShowReject(false);
    setRejectReason('');
    setMemo('');
    try {
      const detail = await api.getIngestion(item.id);
      setDetailItem(detail);
    } catch {
      setDetailItem(item);
    }
  };

  const findRelatedReceipt = async () => {
    const candidates = ingestions.filter(row => String(row.crawler_name || row.crawlerName || '').toLowerCase() === reviewContext.source.toLowerCase()).slice(0,8);
    setRelatedLookup({checked:0,items:[],loading:true,error:''});
    let checked = 0;
    try {
      for (const candidate of candidates) {
        const detail = await api.getIngestion(candidate.id);
        checked += 1;
        if ((detail.items || detail.data || []).some(row => matchesReviewContext(row, reviewContext))) {
          setRelatedLookup({checked,items:[detail],loading:false,error:''});
          return;
        }
      }
      setRelatedLookup({checked,items:[],loading:false,error:''});
    } catch (error) {
      setRelatedLookup({checked,items:[],loading:false,error:error.message || '접수 연결 확인 실패'});
    }
  };

  const handleApproveAll = async (id) => {
    await reviewIngestion(id, { action: 'approve', notes: memo || undefined });
    setDetailItem(null);
    setMemo('');
    fetchIngestionStats();
    loadPage(currentPage);
  };

  const handlePartialApprove = async (id) => {
    const selectedIndices = [...checkedItems];
    if (selectedIndices.length === 0) return;
    await reviewIngestion(id, { action: 'partial', approved_item_indices: selectedIndices, notes: memo || undefined });
    setDetailItem(null);
    setCheckedItems(new Set());
    setMemo('');
    fetchIngestionStats();
    loadPage(currentPage);
  };

  const handleReject = async (id) => {
    if (!rejectReason.trim()) return;
    await reviewIngestion(id, { action: 'reject', notes: rejectReason, rejected_reason: rejectReason });
    setDetailItem(null);
    setRejectReason('');
    setShowReject(false);
    fetchIngestionStats();
    loadPage(currentPage);
  };

  const handleQuickReject = async (id, reason) => {
    await reviewIngestion(id, { action: 'reject', notes: reason, rejected_reason: reason });
    setQuickRejectId(null);
    fetchIngestionStats();
    loadPage(currentPage);
  };

  const handleBulkApprove = async () => {
    if (bulkChecked.size === 0) return;
    const ids = [...bulkChecked];
    await bulkApproveIngestions(ids, 'db-admin', '벌크 승인');
    setBulkChecked(new Set());
    loadPage(currentPage);
  };

  const toggleBulkCheck = (id) => {
    setBulkChecked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleBulkAll = () => {
    if (bulkChecked.size === ingestions.length) {
      setBulkChecked(new Set());
    } else {
      setBulkChecked(new Set(ingestions.map((item) => item.id)));
    }
  };

  const toggleCheck = (idx) => {
    setCheckedItems((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  const toggleAll = (items) => {
    if (checkedItems.size === items.length) {
      setCheckedItems(new Set());
    } else {
      setCheckedItems(new Set(items.map((_, i) => i)));
    }
  };

  // 문제 항목 인덱스 → Set
  const problemIndexSet = useMemo(() => {
    if (!detailItem?.problem_indices) return new Set();
    return new Set(detailItem.problem_indices.map((p) => p.index));
  }, [detailItem]);

  const getProblemIssues = (idx) => {
    if (!detailItem?.problem_indices) return [];
    const found = detailItem.problem_indices.find((p) => p.index === idx);
    return found ? found.issues : [];
  };

  const getRowClass = (idx, deviation) => {
    const classes = [];
    if (problemIndexSet.has(idx)) classes.push(styles.problemRow);
    if (deviation != null) {
      const abs = Math.abs(deviation);
      if (abs > 50) classes.push(styles.outlier);
      else if (abs > 25) classes.push(styles.suspect);
    }
    return classes.join(' ');
  };

  const formatQualityScore = (score) => {
    if (score == null) return 0;
    return score <= 1 ? Math.round(score * 100) : Math.round(score);
  };

  const getQualityClass = (score) => {
    const s = score <= 1 ? score * 100 : score;
    if (s >= 90) return styles.qualityHigh;
    if (s >= 70) return styles.qualityMid;
    return styles.qualityLow;
  };

  // 페이지네이션 렌더링
  const totalPages = ingestionPagination.total_pages || 1;
  const pageNumbers = useMemo(() => {
    const pages = [];
    const maxVisible = 5;
    let start = Math.max(1, currentPage - Math.floor(maxVisible / 2));
    let end = Math.min(totalPages, start + maxVisible - 1);
    if (end - start < maxVisible - 1) start = Math.max(1, end - maxVisible + 1);
    for (let i = start; i <= end; i++) pages.push(i);
    return pages;
  }, [currentPage, totalPages]);

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <h2 className={styles.title}>{reviewContext ? '📥 선택 출처 검토 수신함' : '📥 수신함 — 크롤러에서 1차 승인된 데이터'}</h2>
          <LastUpdated
            timestamp={lastFetchedAt.ingestions}
            onRefresh={() => loadPage(currentPage)}
            isLoading={loading}
          />
        </div>
        <button className={styles.refreshBtn} onClick={() => loadPage(currentPage)} disabled={loading}>
          <RefreshCw size={16} className={loading ? styles.spin : ''} />
          새로고침
        </button>
      </div>

      {reviewContext && <section aria-label="선택 상품 출처 검토">
        <h3>선택 상품·규격·출처</h3>
        <p>상품 {reviewContext.public_product_id} · 규격 {reviewContext.public_variant_id || '미선택'} · 출처 {reviewContext.public_source_listing_id || '미선택'}</p>
        <p>원 출처 {reviewContext.source || '미확인'} · native {reviewContext.native_key || '미확인'}</p>
        <p>표시명·브랜드·분류·별칭·키워드·이미지·상태는 상품 표시 편집에서 변경합니다. 원가격·수량은 원문 검토와 검토된 묶음 적용을 거칩니다. 이 연결만으로 원가격·규격을 수정하지 않습니다.</p>
        <a href={`/prices?${new URLSearchParams(Object.fromEntries(Object.entries(reviewContext).filter(([key,value]) => value && ['public_product_id','public_variant_id','public_source_listing_id'].includes(key))))}`}>선택 출처 원가격·관측 이력</a>
        <p>{reviewContext.source_url ? '현재 페이지 접수 중 같은 원문 URL을 찾습니다. 상품·규격 ID로 접수를 검색하는 API는 없습니다.' : '접수 원문 URL이 없어 자동 연결을 확인하지 못했습니다. 접수 상세의 native·원문을 확인하세요.'}</p>
        {reviewContext.source_url && <p>{ingestions.filter(row => row.source_url === reviewContext.source_url).length}건의 같은 원문 URL 접수 · 전체 페이지 검색 완료나 동일 수량 승인을 뜻하지 않습니다.</p>}
        {ingestions.filter(row => reviewContext.source_url && row.source_url === reviewContext.source_url).map(row => <button key={row.id} type="button" onClick={() => openDetail(row)}>원문 접수 {row.id} 열기 · {row.status}</button>)}
        <button type="button" disabled={relatedLookup.loading} onClick={findRelatedReceipt}>{relatedLookup.loading ? '관련 접수 확인 중…' : '현재 페이지의 관련 접수 찾기'}</button>
        {relatedLookup.checked > 0 && <p>같은 출처 접수 {relatedLookup.checked}건 상세 확인 · 현재 페이지 최대 8건 · 첫 일치에서 중단합니다.</p>}
        {relatedLookup.error && <p role="alert">{relatedLookup.error}</p>}
        {relatedLookup.items.map(row => <button key={row.id} type="button" onClick={() => openDetail(row)}>연결 접수 {row.id} 열기 · 공개 상품·규격 및 원문 연결 확인</button>)}
        {relatedLookup.items.length > 0 && <p>접수에 listing ID가 없으면 공개 상품·규격 ID와 같은 원문 URL·출처로 확인합니다. 수량·행사 해석의 승인이나 공개 적용을 뜻하지 않습니다.</p>}
        <p>수량·가격의 숫자 수정 입력은 이 표시 편집 경로에 제공되지 않습니다. 검토된 출처 묶음은 기존 공식 검토·적용 절차를 사용합니다.</p>
      </section>}
      {error && <div className={styles.errorBanner}>{error}</div>}

      {/* Stats bar */}
      <div className={styles.statsBar}>
        <div className={styles.stat}>
          <span className={styles.statValue}>{ingestionStats?.pending ?? '미확인'}</span>
          <span className={styles.statLabel}>건 대기</span>
        </div>
        <div className={styles.stat}>
          <span className={styles.statValueGreen}>{ingestionStats.approved || 0}</span>
          <span className={styles.statLabel}>건 승인 완료</span>
        </div>
        <div className={styles.stat}>
          <span className={styles.statValueRed}>{ingestionStats.rejected || 0}</span>
          <span className={styles.statLabel}>건 거부</span>
        </div>
      </div>

      {/* 벌크 승인 바 */}
      {ingestions.length > 0 && (
        <div className={styles.bulkBar}>
          <label className={styles.checkAll}>
            <input type="checkbox" checked={bulkChecked.size === ingestions.length && ingestions.length > 0} onChange={toggleBulkAll} />
            전체 선택 ({bulkChecked.size}/{ingestions.length})
          </label>
          <button className={styles.bulkApproveBtn} onClick={handleBulkApprove} disabled={bulkChecked.size === 0 || loading}>
            <CheckCircle size={16} /> 선택 항목 전체 승인 ({bulkChecked.size}건)
          </button>
        </div>
      )}

      {/* Ingestion list */}
      {loading && ingestions.length === 0 ? (
        <div className={styles.empty}>데이터를 불러오는 중...</div>
      ) : ingestions.length === 0 ? (
        <EmptyState
          icon={Inbox}
          title="대기 중인 항목 없음"
          description="크롤러에서 수집된 새 데이터가 없습니다."
        />
      ) : (
        <>
          <div className={styles.list}>
            {ingestions.map((item) => {
              const itemCount = item.items_count ?? item.itemCount ?? (item.items || []).length ?? 0;
              const qualityScore = formatQualityScore(item.qualityScore ?? item.quality_score);
              const rawScore = item.qualityScore ?? item.quality_score ?? 0;
              const crawlerMemo = item.crawlerMemo ?? item.crawler_memo ?? '';
              const crawledAt = item.crawled_at ?? item.crawledAt;

              return (
                <div key={item.id} className={`${styles.card} ${bulkChecked.has(item.id) ? styles.cardChecked : ''}`}>
                  <div className={styles.cardContent}>
                    <div className={styles.cardCheckbox}>
                      <input
                        type="checkbox"
                        checked={bulkChecked.has(item.id)}
                        onChange={(e) => { e.stopPropagation(); toggleBulkCheck(item.id); }}
                      />
                    </div>
                    <div className={styles.cardMain} onClick={() => openDetail(item)}>
                      <div className={styles.cardLeft}>
                        <span className={styles.crawlerName}>{item.crawlerName || item.crawler_name || '알 수 없음'}</span>
                        <span className={styles.cardTimestamp}>
                          수집: {crawledAt ? new Date(crawledAt).toLocaleString('ko-KR') : '알 수 없음'}
                        </span>
                      </div>
                      <div className={styles.cardRight}>
                        <span className={styles.itemCount}>{itemCount}건</span>
                        <span
                          className={`${styles.qualityBadge} ${getQualityClass(rawScore)}`}
                          onClick={(e) => {
                            e.stopPropagation();
                            setQualityPopover(qualityPopover === item.id ? null : item.id);
                          }}
                          title="클릭하여 품질 상세 보기"
                        >
                          품질 {qualityScore}점
                        </span>
                        {crawlerMemo && <span className={styles.memoIcon} title={crawlerMemo}>📝</span>}
                        <button
                          className={styles.quickRejectToggle}
                          onClick={(e) => { e.stopPropagation(); setQuickRejectId(quickRejectId === item.id ? null : item.id); }}
                          title="빠른 거부"
                        >
                          <XCircle size={14} />
                        </button>
                      </div>
                    </div>
                  </div>
                  {crawlerMemo && (
                    <div className={styles.crawlerMemoPreview}>크롤러 메모: {crawlerMemo}</div>
                  )}
                  {/* 품질 점수 간략 breakdown (카드 레벨) */}
                  {qualityPopover === item.id && item.quality_details && (
                    <div className={styles.qualityPopover} onClick={(e) => e.stopPropagation()}>
                      <div className={styles.popoverHeader}>
                        <span>품질 점수 상세</span>
                        <button onClick={() => setQualityPopover(null)}><X size={14} /></button>
                      </div>
                      <div className={styles.popoverBody}>
                        <div className={styles.breakdownRow}>
                          <span>전체 항목</span><span>{item.quality_details.total_items ?? itemCount}</span>
                        </div>
                        <div className={styles.breakdownRow}>
                          <span>누락 필드</span>
                          <span className={item.quality_details.missing_fields > 0 ? styles.breakdownBad : ''}>
                            {item.quality_details.missing_fields ?? 0}건
                          </span>
                        </div>
                        <div className={styles.breakdownRow}>
                          <span>이상치</span>
                          <span className={item.quality_details.outliers > 0 ? styles.breakdownBad : ''}>
                            {item.quality_details.outliers ?? 0}건
                          </span>
                        </div>
                        <div className={styles.breakdownRow}>
                          <span>중복</span>
                          <span className={item.quality_details.duplicates > 0 ? styles.breakdownWarn : ''}>
                            {item.quality_details.duplicates ?? 0}건
                          </span>
                        </div>
                      </div>
                      <div className={styles.popoverLegend}>
                        <span className={styles.legendItem}><span className={styles.legendDotGreen} /> ≥90 높음</span>
                        <span className={styles.legendItem}><span className={styles.legendDotYellow} /> ≥70 보통</span>
                        <span className={styles.legendItem}><span className={styles.legendDotRed} /> &lt;70 낮음</span>
                      </div>
                    </div>
                  )}
                  {/* 빠른 거부 프리셋 버튼 */}
                  {quickRejectId === item.id && (
                    <div className={styles.quickRejectBar} onClick={(e) => e.stopPropagation()}>
                      <span className={styles.quickRejectLabel}>거부 사유:</span>
                      {REJECT_PRESETS.map((reason) => (
                        <button
                          key={reason}
                          className={styles.quickRejectBtn}
                          onClick={() => handleQuickReject(item.id, reason)}
                        >
                          {reason}
                        </button>
                      ))}
                      <button className={styles.quickRejectCancel} onClick={() => setQuickRejectId(null)}>취소</button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {/* 페이지네이션 */}
          {totalPages > 1 && (
            <div className={styles.pagination}>
              <button className={styles.pageBtn} onClick={() => loadPage(1)} disabled={currentPage <= 1}>«</button>
              <button className={styles.pageBtn} onClick={() => loadPage(currentPage - 1)} disabled={currentPage <= 1}>
                <ChevronLeft size={14} />
              </button>
              {pageNumbers.map((p) => (
                <button
                  key={p}
                  className={`${styles.pageBtn} ${p === currentPage ? styles.pageBtnActive : ''}`}
                  onClick={() => loadPage(p)}
                >
                  {p}
                </button>
              ))}
              <button className={styles.pageBtn} onClick={() => loadPage(currentPage + 1)} disabled={currentPage >= totalPages}>
                <ChevronRight size={14} />
              </button>
              <button className={styles.pageBtn} onClick={() => loadPage(totalPages)} disabled={currentPage >= totalPages}>»</button>
              <span className={styles.pageInfo}>{ingestionPagination.total}건 중 {currentPage}/{totalPages} 페이지</span>
            </div>
          )}
        </>
      )}

      {/* Detail Modal */}
      {detailItem && (
        <div className={styles.overlay} onClick={() => setDetailItem(null)}>
          <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h3>{detailItem.crawlerName || detailItem.crawler_name || '데이터 상세'}</h3>
              <button onClick={() => setDetailItem(null)}><X size={18} /></button>
            </div>

            <div className={styles.modalBody}>
              {/* 이전 크롤링 비교 */}
              {detailItem.previous_comparison && (
                <div className={styles.comparisonSection}>
                  <h4 className={styles.sectionTitle}>📊 이전 수집 비교</h4>
                  <div className={styles.comparisonGrid}>
                    <div className={styles.comparisonItem}>
                      <span className={styles.compLabel}>항목 수</span>
                      <span className={styles.compValue}>
                        {detailItem.previous_comparison.previous_items_count} → {detailItem.previous_comparison.current_items_count}
                        <span className={detailItem.previous_comparison.items_diff >= 0 ? styles.diffPositive : styles.diffNegative}>
                          ({detailItem.previous_comparison.items_diff >= 0 ? '+' : ''}{detailItem.previous_comparison.items_diff})
                        </span>
                      </span>
                    </div>
                    <div className={styles.comparisonItem}>
                      <span className={styles.compLabel}>품질 점수</span>
                      <span className={styles.compValue}>
                        {formatQualityScore(detailItem.previous_comparison.previous_quality_score)} → {formatQualityScore(detailItem.previous_comparison.current_quality_score)}
                        <span className={detailItem.previous_comparison.quality_diff >= 0 ? styles.diffPositive : styles.diffNegative}>
                          ({detailItem.previous_comparison.quality_diff >= 0 ? '+' : ''}{Math.round(detailItem.previous_comparison.quality_diff * 100)})
                        </span>
                      </span>
                    </div>
                    <div className={styles.comparisonItem}>
                      <span className={styles.compLabel}>이전 수집일</span>
                      <span className={styles.compValue}>
                        {detailItem.previous_comparison.previous_crawled_at
                          ? new Date(detailItem.previous_comparison.previous_crawled_at).toLocaleString('ko-KR')
                          : '-'}
                      </span>
                    </div>
                    <div className={styles.comparisonItem}>
                      <span className={styles.compLabel}>이전 상태</span>
                      <span className={styles.compValue}>{detailItem.previous_comparison.previous_status}</span>
                    </div>
                  </div>
                </div>
              )}

              {/* 품질 점수 상세 breakdown */}
              {detailItem.quality_breakdown && (
                <div className={styles.qualityBreakdownSection}>
                  <h4 className={styles.sectionTitle}>🔍 품질 점수 상세</h4>
                  <div className={styles.breakdownGrid}>
                    <div className={styles.breakdownCard}>
                      <span className={styles.breakdownLabel}>필드 완성도</span>
                      <span className={`${styles.breakdownValue} ${detailItem.quality_breakdown.field_completeness >= 90 ? styles.breakdownGood : detailItem.quality_breakdown.field_completeness >= 70 ? styles.breakdownWarn : styles.breakdownBad}`}>
                        {detailItem.quality_breakdown.field_completeness}%
                      </span>
                    </div>
                    <div className={styles.breakdownCard}>
                      <span className={styles.breakdownLabel}>누락 필드</span>
                      <span className={`${styles.breakdownValue} ${detailItem.quality_breakdown.missing_fields > 0 ? styles.breakdownBad : styles.breakdownGood}`}>
                        {detailItem.quality_breakdown.missing_fields}건
                      </span>
                    </div>
                    <div className={styles.breakdownCard}>
                      <span className={styles.breakdownLabel}>중복 수</span>
                      <span className={`${styles.breakdownValue} ${detailItem.quality_breakdown.duplicates > 0 ? styles.breakdownWarn : styles.breakdownGood}`}>
                        {detailItem.quality_breakdown.duplicates}건
                      </span>
                    </div>
                    <div className={styles.breakdownCard}>
                      <span className={styles.breakdownLabel}>이상치 수</span>
                      <span className={`${styles.breakdownValue} ${detailItem.quality_breakdown.outliers > 0 ? styles.breakdownBad : styles.breakdownGood}`}>
                        {detailItem.quality_breakdown.outliers}건
                      </span>
                    </div>
                    <div className={styles.breakdownCard}>
                      <span className={styles.breakdownLabel}>형식 오류</span>
                      <span className={`${styles.breakdownValue} ${detailItem.quality_breakdown.format_errors > 0 ? styles.breakdownBad : styles.breakdownGood}`}>
                        {detailItem.quality_breakdown.format_errors}건
                      </span>
                    </div>
                    <div className={styles.breakdownCard}>
                      <span className={styles.breakdownLabel}>전체 항목</span>
                      <span className={styles.breakdownValue}>{detailItem.quality_breakdown.total_items}건</span>
                    </div>
                  </div>
                </div>
              )}

              {/* Items table with checkboxes — 전체 데이터 */}
              {(() => {
                const items = detailItem.items || detailItem.data || [];
                if (items.length === 0) {
                  return <div className={styles.empty}>데이터 항목이 없습니다.</div>;
                }

                const keys = Object.keys(items[0]);

                return (
                  <>
                    <div className={styles.tableActions}>
                      <label className={styles.checkAll}>
                        <input
                          type="checkbox"
                          checked={checkedItems.size === items.length}
                          onChange={() => toggleAll(items)}
                        />
                        전체 선택 ({checkedItems.size}/{items.length})
                      </label>
                      {problemIndexSet.size > 0 && (
                        <span className={styles.problemCount}>
                          <AlertTriangle size={14} /> 문제 항목 {problemIndexSet.size}건
                        </span>
                      )}
                    </div>
                    <div className={styles.tableWrap}>
                      <table className={styles.table}>
                        <thead>
                          <tr>
                            <th className={styles.stickyCol}></th>
                            <th className={styles.stickyCol}>#</th>
                            {keys.map((k) => <th key={k}>{k}</th>)}
                            <th>상태</th>
                          </tr>
                        </thead>
                        <tbody>
                          {items.map((row, idx) => {
                            const deviation = row.priceDeviation ?? row.price_deviation;
                            const rowClass = getRowClass(idx, deviation);
                            const issues = getProblemIssues(idx);
                            return (
                              <tr key={idx} className={rowClass}>
                                <td className={styles.stickyCol}>
                                  <input
                                    type="checkbox"
                                    checked={checkedItems.has(idx)}
                                    onChange={() => toggleCheck(idx)}
                                  />
                                </td>
                                <td className={styles.stickyCol}>{idx + 1}</td>
                                {keys.map((k) => (
                                  <td key={k} className={styles.dataCell} title={String(row[k] ?? '')}>
                                    {String(row[k] ?? '')}
                                  </td>
                                ))}
                                <td>
                                  {issues.length > 0 ? (
                                    <span className={styles.issueBadge} title={issues.join(', ')}>
                                      {issues.map((iss) => {
                                        if (iss.startsWith('missing:')) return `누락:${iss.slice(8)}`;
                                        if (iss === 'outlier') return '이상치';
                                        if (iss === 'duplicate') return '중복';
                                        if (iss === 'format_error') return '형식오류';
                                        return iss;
                                      }).join(' / ')}
                                    </span>
                                  ) : deviation != null ? (
                                    <span className={`${styles.devBadge} ${Math.abs(deviation) > 50 ? styles.outlier : Math.abs(deviation) > 25 ? styles.suspect : styles.normal}`}>
                                      {deviation > 0 ? '+' : ''}{deviation}%
                                    </span>
                                  ) : (
                                    <span className={styles.normalBadge}>정상</span>
                                  )}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </>
                );
              })()}

              {/* Memo input */}
              <div className={styles.memoSection}>
                <textarea
                  className={styles.memoInput}
                  placeholder="메모를 입력하세요 (선택사항)..."
                  value={memo}
                  onChange={(e) => setMemo(e.target.value)}
                  rows={2}
                />
              </div>

              {/* Actions */}
              <div className={styles.modalActions}>
                <button className={styles.approveAllBtn} onClick={() => handleApproveAll(detailItem.id)}>
                  <CheckCircle size={16} /> 전체 승인
                </button>
                <button
                  className={styles.partialBtn}
                  onClick={() => handlePartialApprove(detailItem.id)}
                  disabled={checkedItems.size === 0}
                >
                  <AlertTriangle size={16} /> 부분 승인 ({checkedItems.size}건)
                </button>
                {showReject ? (
                  <div className={styles.rejectForm}>
                    <div className={styles.rejectPresets}>
                      {REJECT_PRESETS.map((reason) => (
                        <button
                          key={reason}
                          className={styles.quickRejectBtn}
                          onClick={() => setRejectReason(reason)}
                        >
                          {reason}
                        </button>
                      ))}
                    </div>
                    <input
                      className={styles.rejectInput}
                      placeholder="거부 사유..."
                      value={rejectReason}
                      onChange={(e) => setRejectReason(e.target.value)}
                    />
                    <button className={styles.rejectConfirmBtn} onClick={() => handleReject(detailItem.id)}>확인</button>
                    <button className={styles.cancelBtn} onClick={() => setShowReject(false)}>취소</button>
                  </div>
                ) : (
                  <button className={styles.rejectBtn} onClick={() => setShowReject(true)}>
                    <XCircle size={16} /> 거부
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
