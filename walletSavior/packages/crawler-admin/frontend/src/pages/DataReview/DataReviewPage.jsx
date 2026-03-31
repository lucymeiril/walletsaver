import { useState, useEffect } from 'react';
import useAdminStore from '../../stores/adminStore';
import { CheckCircle, XCircle, MessageSquare, ChevronDown, ChevronUp, AlertTriangle, RefreshCw } from 'lucide-react';
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

  useEffect(() => {
    fetchIngestions();
  }, [fetchIngestions]);

  const filtered = filter === 'all'
    ? ingestions
    : ingestions.filter((item) => item.status === filter);

  const handleApprove = async (id) => {
    await reviewIngestion(id, { action: 'approve', memo });
    setMemo('');
    setExpandedId(null);
  };

  const handleReject = async (id) => {
    if (!rejectReason.trim()) return;
    await reviewIngestion(id, { action: 'reject', reason: rejectReason });
    setRejectReason('');
    setShowRejectInput(null);
    setExpandedId(null);
  };

  const handleMemo = async (id) => {
    if (!memo.trim()) return;
    await reviewIngestion(id, { action: 'memo', memo });
    setMemo('');
    setShowMemoInput(null);
  };

  const getQualityColor = (score) => {
    if (score >= 90) return styles.qualityHigh;
    if (score >= 70) return styles.qualityMid;
    return styles.qualityLow;
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

      {error && (
        <div className={styles.errorBanner}>{error}</div>
      )}

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
        <div className={styles.list}>
          {filtered.map((item) => {
            const st = STATUS_MAP[item.status] || STATUS_MAP.pending;
            const isExpanded = expandedId === item.id;
            const items = item.items || item.data || [];
            const qualityScore = item.qualityScore ?? item.quality_score ?? 0;
            const schemaType = item.schemaType ?? item.schema_type ?? 'Unknown';

            return (
              <div key={item.id} className={styles.card}>
                {/* Card Header */}
                <div className={styles.cardHeader} onClick={() => setExpandedId(isExpanded ? null : item.id)}>
                  <div className={styles.cardInfo}>
                    <span className={styles.crawlerName}>{item.crawlerName || item.crawler_name || item.crawler_id || '알 수 없음'}</span>
                    <span className={styles.timestamp}>
                      {(item.timestamp || item.crawled_at) ? new Date(item.timestamp || item.crawled_at).toLocaleString('ko-KR') : ''}
                    </span>
                  </div>
                  <div className={styles.cardMeta}>
                    <span className={styles.itemCount}>{items.length || item.itemCount || item.items_count || 0}건</span>
                    <span className={`${styles.qualityBadge} ${getQualityColor(qualityScore)}`}>
                      품질 {qualityScore}점
                    </span>
                    <span className={styles.schemaTag}>{schemaType}</span>
                    <span className={`${styles.statusBadge} ${styles[st.cls]}`}>{st.label}</span>
                    {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                  </div>
                </div>

                {/* Expanded Detail */}
                {isExpanded && (
                  <div className={styles.detail}>
                    {/* 스키마 정보 */}
                    {items.length > 0 && (
                      <div className={styles.section}>
                        <h4 className={styles.sectionTitle}>📋 스키마 정보</h4>
                        <div className={styles.schemaGrid}>
                          {Object.entries(items[0] || {}).map(([key, val]) => (
                            <div key={key} className={styles.schemaItem}>
                              <span className={styles.schemaKey}>{key}</span>
                              <span className={styles.schemaType}>{typeof val}</span>
                              <span className={styles.schemaValue}>{String(val).slice(0, 50)}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* 데이터 미리보기 */}
                    {items.length > 0 && (
                      <div className={styles.section}>
                        <h4 className={styles.sectionTitle}>🔍 데이터 미리보기 (최대 10건)</h4>
                        <div className={styles.previewTable}>
                          <table className={styles.table}>
                            <thead>
                              <tr>
                                {Object.keys(items[0]).slice(0, 6).map((key) => (
                                  <th key={key}>{key}</th>
                                ))}
                              </tr>
                            </thead>
                            <tbody>
                              {items.slice(0, 10).map((row, idx) => (
                                <tr key={idx}>
                                  {Object.keys(items[0]).slice(0, 6).map((key) => (
                                    <td key={key}>{String(row[key] ?? '').slice(0, 40)}</td>
                                  ))}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )}

                    {/* 품질 분석 */}
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
                      </div>
                    </div>

                    {/* 에러 정보 */}
                    {item.error && (
                      <div className={styles.section}>
                        <h4 className={styles.sectionTitle}>⚠️ 에러 정보</h4>
                        <div className={styles.errorBox}>
                          <p><strong>유형:</strong> {item.error.type || '알 수 없음'}</p>
                          <p><strong>메시지:</strong> {item.error.message || item.error}</p>
                          {item.error.strategy && <p><strong>전략:</strong> {item.error.strategy}</p>}
                        </div>
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
      )}
    </div>
  );
}
