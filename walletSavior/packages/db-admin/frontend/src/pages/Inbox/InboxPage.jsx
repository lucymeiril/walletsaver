import { useState, useEffect, useMemo, useCallback } from 'react';
import useDbAdminStore from '../../stores/dbAdminStore';
import { api } from '../../api/client';
import { CheckCircle, XCircle, AlertTriangle, RefreshCw, ChevronLeft, ChevronRight, X, Info } from 'lucide-react';
import styles from './InboxPage.module.css';

export default function InboxPage() {
  const ingestions = useDbAdminStore((s) => s.ingestions);
  const fetchIngestions = useDbAdminStore((s) => s.fetchIngestions);
  const fetchIngestionStats = useDbAdminStore((s) => s.fetchIngestionStats);
  const ingestionStats = useDbAdminStore((s) => s.ingestionStats);
  const ingestionPagination = useDbAdminStore((s) => s.ingestionPagination);
  const reviewIngestion = useDbAdminStore((s) => s.reviewIngestion);
  const bulkApproveIngestions = useDbAdminStore((s) => s.bulkApproveIngestions);
  const loading = useDbAdminStore((s) => s.loading);
  const error = useDbAdminStore((s) => s.error);

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

  const PER_PAGE = 20;

  const loadPage = useCallback((page) => {
    setCurrentPage(page);
    fetchIngestions({ status: 'crawler_approved', page, per_page: PER_PAGE });
  }, [fetchIngestions]);

  useEffect(() => {
    loadPage(1);
    fetchIngestionStats();
  }, [loadPage, fetchIngestionStats]);

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

  const handleApproveAll = async (id) => {
    await reviewIngestion(id, { action: 'approve', notes: memo || undefined });
    setDetailItem(null);
    setMemo('');
    fetchIngestionStats();
  };

  const handlePartialApprove = async (id) => {
    const selectedIndices = [...checkedItems];
    if (selectedIndices.length === 0) return;
    await reviewIngestion(id, { action: 'partial', approved_item_indices: selectedIndices, notes: memo || undefined });
    setDetailItem(null);
    setCheckedItems(new Set());
    setMemo('');
    fetchIngestionStats();
  };

  const handleReject = async (id) => {
    if (!rejectReason.trim()) return;
    await reviewIngestion(id, { action: 'reject', notes: rejectReason, rejected_reason: rejectReason });
    setDetailItem(null);
    setRejectReason('');
    setShowReject(false);
    fetchIngestionStats();
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
        <h2 className={styles.title}>📥 수신함 — 크롤러에서 1차 승인된 데이터</h2>
        <button className={styles.refreshBtn} onClick={() => loadPage(currentPage)} disabled={loading}>
          <RefreshCw size={16} className={loading ? styles.spin : ''} />
          새로고침
        </button>
      </div>

      {error && <div className={styles.errorBanner}>{error}</div>}

      {/* Stats bar */}
      <div className={styles.statsBar}>
        <div className={styles.stat}>
          <span className={styles.statValue}>{ingestionStats.pending || ingestionPagination.total || ingestions.length}</span>
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
        <div className={styles.empty}>현재 1차 승인 대기 중인 데이터가 없습니다.</div>
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
