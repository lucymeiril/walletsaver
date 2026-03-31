import { useState, useEffect } from 'react';
import useAdminStore from '../../stores/adminStore';
import { Play, Settings, Plus, Power } from 'lucide-react';
import styles from './Crawlers.module.css';

const CATEGORIES = [
  { key: 'all', label: '전체' },
  { key: 'mart', label: '마트' },
  { key: 'hotdeal', label: '핫딜' },
  { key: 'delivery', label: '배달' },
  { key: 'shopping', label: '쇼핑' },
];

const STATUS_MAP = {
  active: { dot: styles.statusActive, label: '활성' },
  error: { dot: styles.statusError, label: '에러' },
  inactive: { dot: styles.statusInactive, label: '비활성' },
};

export default function Crawlers() {
  const crawlerFilter = useAdminStore((s) => s.crawlerFilter);
  const setCrawlerFilter = useAdminStore((s) => s.setCrawlerFilter);
  const getFilteredCrawlers = useAdminStore((s) => s.getFilteredCrawlers);
  const toggleCrawlerStatus = useAdminStore((s) => s.toggleCrawlerStatus);
  const fetchCrawlers = useAdminStore((s) => s.fetchCrawlers);
  const runCrawler = useAdminStore((s) => s.runCrawler);
  const loading = useAdminStore((s) => s.loading);
  const filtered = getFilteredCrawlers();

  const [runResult, setRunResult] = useState(null);

  useEffect(() => {
    fetchCrawlers();
  }, [fetchCrawlers]);

  const handleRun = async (id) => {
    setRunResult(null);
    const result = await runCrawler(id);
    if (result) {
      setRunResult({ id, success: true, message: result.message || '크롤러 실행 요청 완료' });
    } else {
      setRunResult({ id, success: false, message: '크롤러 실행 요청 실패' });
    }
    setTimeout(() => setRunResult(null), 4000);
  };

  const formatTime = (iso) => {
    const d = new Date(iso);
    return d.toLocaleString('ko-KR', {
      month: 'numeric',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.pageTitle}>크롤러 관리</h1>
        <div className={styles.actions}>
          <button className={styles.addBtn}>
            <Plus size={16} />
            크롤러 추가
          </button>
        </div>
      </div>

      <div className={styles.filters}>
        {CATEGORIES.map((cat) => (
          <button
            key={cat.key}
            className={
              crawlerFilter === cat.key
                ? styles.filterBtnActive
                : styles.filterBtn
            }
            onClick={() => setCrawlerFilter(cat.key)}
          >
            {cat.label}
          </button>
        ))}
      </div>

      <div className={styles.grid}>
        {runResult && (
          <div style={{
            gridColumn: '1 / -1',
            padding: '12px 16px',
            borderRadius: '8px',
            background: runResult.success ? 'rgba(52,211,153,0.15)' : 'rgba(248,113,113,0.15)',
            color: runResult.success ? 'var(--green)' : 'var(--red)',
            fontSize: 'var(--fs-sm)',
            fontWeight: 'var(--fw-medium)',
          }}>
            {runResult.message}
          </div>
        )}
        {filtered.map((crawler) => {
          const st = STATUS_MAP[crawler.status] || STATUS_MAP.inactive;
          return (
            <div key={crawler.id} className={styles.card}>
              <div className={styles.cardHeader}>
                <div className={styles.cardTitle}>
                  <span className={`${styles.statusDot} ${st.dot}`} />
                  {crawler.name}
                </div>
                <span className={styles.category}>{crawler.category}</span>
              </div>

              <div className={styles.cardMeta}>
                <div className={styles.metaRow}>
                  <span className={styles.metaLabel}>난이도</span>
                  <span className={styles.metaValue}>{crawler.difficulty}</span>
                </div>
                <div className={styles.metaRow}>
                  <span className={styles.metaLabel}>마지막 크롤</span>
                  <span className={styles.metaValue}>
                    {formatTime(crawler.lastCrawl)}
                  </span>
                </div>
                <div className={styles.metaRow}>
                  <span className={styles.metaLabel}>성공률</span>
                  <span className={styles.metaValue}>
                    {crawler.successRate}%
                  </span>
                </div>
                <div className={styles.metaRow}>
                  <span className={styles.metaLabel}>총 실행 횟수</span>
                  <span className={styles.metaValue}>
                    {(crawler.totalRuns || 0).toLocaleString()}회
                  </span>
                </div>
              </div>

              <div className={styles.cardActions}>
                <button
                  className={styles.actionBtn}
                  title="수동 실행"
                  onClick={() => handleRun(crawler.id)}
                  disabled={loading}
                >
                  <Play size={14} />
                  {loading && runResult?.id === crawler.id ? '실행중...' : '실행'}
                </button>
                <button className={styles.actionBtn} title="설정">
                  <Settings size={14} />
                  설정
                </button>
                <button
                  className={
                    crawler.status === 'active'
                      ? styles.toggleBtnActive
                      : styles.toggleBtn
                  }
                  onClick={() => toggleCrawlerStatus(crawler.id)}
                  title={
                    crawler.status === 'active' ? '비활성화' : '활성화'
                  }
                >
                  <Power size={14} />
                  {crawler.status === 'active' ? '활성' : '비활성'}
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
