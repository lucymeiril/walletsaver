import { useState, useEffect } from 'react';
import useDbAdminStore from '../../stores/dbAdminStore';
import { CheckCircle, XCircle, MessageSquare, AlertTriangle, RefreshCw, ChevronDown, ChevronUp, X } from 'lucide-react';
import styles from './InboxPage.module.css';

export default function InboxPage() {
  const ingestions = useDbAdminStore((s) => s.ingestions);
  const fetchIngestions = useDbAdminStore((s) => s.fetchIngestions);
  const fetchIngestionStats = useDbAdminStore((s) => s.fetchIngestionStats);
  const ingestionStats = useDbAdminStore((s) => s.ingestionStats);
  const reviewIngestion = useDbAdminStore((s) => s.reviewIngestion);
  const loading = useDbAdminStore((s) => s.loading);
  const error = useDbAdminStore((s) => s.error);

  const [detailItem, setDetailItem] = useState(null);
  const [checkedItems, setCheckedItems] = useState(new Set());
  const [rejectReason, setRejectReason] = useState('');
  const [memo, setMemo] = useState('');
  const [showReject, setShowReject] = useState(false);
  const [showMemo, setShowMemo] = useState(false);

  useEffect(() => {
    fetchIngestions({ status: 'crawler_approved' });
    fetchIngestionStats();
  }, [fetchIngestions, fetchIngestionStats]);

  const handleApproveAll = async (id) => {
    await reviewIngestion(id, { action: 'approve_all', memo });
    setDetailItem(null);
    setMemo('');
  };

  const handlePartialApprove = async (id) => {
    const selectedIndices = [...checkedItems];
    if (selectedIndices.length === 0) return;
    await reviewIngestion(id, { action: 'partial_approve', selectedItems: selectedIndices, memo });
    setDetailItem(null);
    setCheckedItems(new Set());
    setMemo('');
  };

  const handleReject = async (id) => {
    if (!rejectReason.trim()) return;
    await reviewIngestion(id, { action: 'reject', reason: rejectReason });
    setDetailItem(null);
    setRejectReason('');
    setShowReject(false);
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

  const getDeviationClass = (deviation) => {
    if (deviation == null) return '';
    const abs = Math.abs(deviation);
    if (abs > 50) return styles.outlier;
    if (abs > 25) return styles.suspect;
    return styles.normal;
  };

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h2 className={styles.title}>📥 수신함 — 크롤러에서 1차 승인된 데이터</h2>
        <button className={styles.refreshBtn} onClick={() => fetchIngestions({ status: 'crawler_approved' })} disabled={loading}>
          <RefreshCw size={16} className={loading ? styles.spin : ''} />
          새로고침
        </button>
      </div>

      {error && <div className={styles.errorBanner}>{error}</div>}

      {/* Stats bar */}
      <div className={styles.statsBar}>
        <div className={styles.stat}>
          <span className={styles.statValue}>{ingestionStats.pending || ingestions.length}</span>
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

      {/* Ingestion list */}
      {loading && ingestions.length === 0 ? (
        <div className={styles.empty}>데이터를 불러오는 중...</div>
      ) : ingestions.length === 0 ? (
        <div className={styles.empty}>
          현재 1차 승인 대기 중인 데이터가 없습니다.
        </div>
      ) : (
        <div className={styles.list}>
          {ingestions.map((item) => {
            const items = item.items || item.data || [];
            const qualityScore = item.qualityScore ?? item.quality_score ?? 0;
            const crawlerMemo = item.crawlerMemo ?? item.crawler_memo ?? '';

            return (
              <div key={item.id} className={styles.card} onClick={() => { setDetailItem(item); setCheckedItems(new Set()); }}>
                <div className={styles.cardContent}>
                  <div className={styles.cardLeft}>
                    <span className={styles.crawlerName}>{item.crawlerName || item.crawler_name || item.crawler_id || '알 수 없음'}</span>
                    <span className={styles.cardTimestamp}>
                      1차 승인: {item.approvedAt ? new Date(item.approvedAt).toLocaleString('ko-KR') : '알 수 없음'}
                    </span>
                  </div>
                  <div className={styles.cardRight}>
                    <span className={styles.itemCount}>{items.length || item.itemCount || 0}건</span>
                    <span className={`${styles.qualityBadge} ${qualityScore >= 90 ? styles.qualityHigh : qualityScore >= 70 ? styles.qualityMid : styles.qualityLow}`}>
                      품질 {qualityScore}점
                    </span>
                    {crawlerMemo && (
                      <span className={styles.memoIcon} title={crawlerMemo}>📝</span>
                    )}
                  </div>
                </div>
                {crawlerMemo && (
                  <div className={styles.crawlerMemoPreview}>
                    크롤러 메모: {crawlerMemo}
                  </div>
                )}
              </div>
            );
          })}
        </div>
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
              {/* Items table with checkboxes */}
              {(() => {
                const items = detailItem.items || detailItem.data || [];
                if (items.length === 0) {
                  return <div className={styles.empty}>데이터 항목이 없습니다.</div>;
                }

                const keys = Object.keys(items[0]).slice(0, 7);

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
                    </div>
                    <div className={styles.tableWrap}>
                      <table className={styles.table}>
                        <thead>
                          <tr>
                            <th></th>
                            {keys.map((k) => <th key={k}>{k}</th>)}
                            <th>상태</th>
                          </tr>
                        </thead>
                        <tbody>
                          {items.map((row, idx) => {
                            const deviation = row.priceDeviation ?? row.price_deviation;
                            const devClass = getDeviationClass(deviation);
                            return (
                              <tr key={idx} className={devClass}>
                                <td>
                                  <input
                                    type="checkbox"
                                    checked={checkedItems.has(idx)}
                                    onChange={() => toggleCheck(idx)}
                                  />
                                </td>
                                {keys.map((k) => (
                                  <td key={k}>{String(row[k] ?? '').slice(0, 40)}</td>
                                ))}
                                <td>
                                  {deviation != null ? (
                                    <span className={`${styles.devBadge} ${devClass}`}>
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
