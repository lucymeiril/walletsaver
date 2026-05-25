import { useEffect, useCallback, useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import useAdminStore from '../../stores/adminStore';
import {
  PieChart,
  Pie,
  Cell,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';
import { RefreshCw, AlertTriangle, ExternalLink, Clock, Rocket, Database } from 'lucide-react';
import styles from './Dashboard.module.css';
import EmptyState from '../../components/EmptyState';
import FirstCrawlModal from '../../components/FirstCrawlModal';

const STATUS_LABEL = { success: '성공', failure: '실패', partial: '부분', running: '실행중' };
const STATUS_COLORS = {
  '성공': 'var(--green)', '실패': 'var(--red)',
  '부분': 'var(--yellow)', '실행중': 'var(--accent)',
};
const CARD_STATUS_CLASS = {
  success: 'Success', failure: 'Failure', running: 'Running',
};
const FRESHNESS_CLASS = { fresh: 'Fresh', stale: 'Stale', expired: 'Expired', unknown: 'Unknown' };
const FRESHNESS_LABEL = { fresh: '최신', stale: '주의', expired: '만료', unknown: '없음' };
const DAYS_OPTIONS = [7, 14, 30];

function parseAsUTC(iso) {
  if (!iso) return null;
  if (!iso.endsWith('Z') && !iso.includes('+') && !/[-+]\d{2}:\d{2}$/.test(iso)) {
    return new Date(iso + 'Z');
  }
  return new Date(iso);
}

function formatTime(iso) {
  if (!iso) return '-';
  try {
    const d = parseAsUTC(iso);
    return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, '0')}.${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  } catch { return iso; }
}

export default function Dashboard() {
  const stats = useAdminStore((s) => s.dashboardStats);
  const loading = useAdminStore((s) => s.dashboardLoading);
  const error = useAdminStore((s) => s.dashboardError);
  const fetchDashboard = useAdminStore((s) => s.fetchDashboard);
  const lastRefreshed = useAdminStore((s) => s.lastRefreshed);
  const errorTrendDays = useAdminStore((s) => s.errorTrendDays);
  const setErrorTrendDays = useAdminStore((s) => s.setErrorTrendDays);
  const navigate = useNavigate();

  useEffect(() => {
    fetchDashboard();
  }, [fetchDashboard]);

  const handleRefresh = useCallback(() => {
    fetchDashboard();
  }, [fetchDashboard]);

  const handleDaysChange = useCallback((d) => {
    setErrorTrendDays(d);
    fetchDashboard(d);
  }, [setErrorTrendDays, fetchDashboard]);

  // 파이 차트 데이터
  const dist = stats.statusDistribution || {};
  const statusDistributionData = [
    { name: '성공', value: dist.success || 0, color: 'var(--green)' },
    { name: '실패', value: dist.failure || 0, color: 'var(--red)' },
    { name: '부분', value: dist.partial || 0, color: 'var(--yellow)' },
  ].filter((d) => d.value > 0);

  const errorTrendData = stats.errorTrend || [];
  const alerts = stats.alerts || [];
  const crawlerCards = stats.crawlerCards || [];
  const freshness = stats.freshness || [];

  const [firstCrawlOpen, setFirstCrawlOpen] = useState(false);

  // 빈 상태 판정: 어떤 실행 데이터도 없고, 신선도 전부 unknown 또는 비어있는 경우
  const isFreshAllUnknown = freshness.length === 0 || freshness.every((f) => f.status === 'unknown' || !f.lastUpdate);
  const isInitialEmpty = useMemo(() => (
    (stats.todayCrawls || 0) === 0 &&
    crawlerCards.length === 0 &&
    errorTrendData.length === 0 &&
    isFreshAllUnknown
  ), [stats.todayCrawls, crawlerCards.length, errorTrendData.length, isFreshAllUnknown]);

  if (loading) {
    return (
      <div className={styles.page}>
        <h1 className={styles.pageTitle}>대시보드</h1>
        <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--text3)' }}>
          데이터 로딩 중...
        </div>
      </div>
    );
  }

  return (
    <div className={styles.page}>
      {/* 헤더: 제목 + 새로고침 */}
      <div className={styles.header}>
        <div>
          <h1 className={styles.pageTitle}>대시보드</h1>
          {/* 페이지 설명 — 크롤러 전체 상태를 한눈에 */}
          <p style={{ margin: '4px 0 0', fontSize: '0.82rem', color: 'var(--text3)' }}>
            마트별 크롤러 실행 상태, 데이터 신선도, 에러 추이를 한눈에 확인합니다.
          </p>
        </div>
        <div className={styles.headerRight}>
          {lastRefreshed && (
            <span className={styles.lastRefreshed}>
              <Clock size={14} />
              {formatTime(lastRefreshed)}
            </span>
          )}
          <button
            className={styles.refreshBtn}
            onClick={handleRefresh}
            disabled={loading}
            title="새로고침"
          >
            <RefreshCw size={16} className={loading ? styles.spinning : ''} />
            새로고침
          </button>
        </div>
      </div>

      {/* 긴급 알림 배너 */}
      {alerts.length > 0 && (
        <div className={styles.alertBanner}>
          <AlertTriangle size={18} />
          <span>
            실패 크롤러: {alerts.map((a, i) => (
              <span key={a.crawlerName}>
                {i > 0 && ', '}
                <strong>{a.crawlerName}</strong>
              </span>
            ))}
          </span>
          <button
            className={styles.alertLink}
            onClick={() => navigate('/logs')}
          >
            로그 보기 <ExternalLink size={14} />
          </button>
        </div>
      )}

      {error && (
        <div style={{
          padding: '12px 16px', borderRadius: '8px', marginBottom: '16px',
          background: 'rgba(248,113,113,0.15)', color: 'var(--red)',
          fontSize: 'var(--fs-sm)',
        }}>
          {error}
        </div>
      )}

      {/* Summary Cards */}
      <div className={styles.statsGrid}>
        <div className={styles.statCard}>
          <span className={styles.statLabel}>총 크롤러 수</span>
          <span className={styles.statValue}>{stats.totalCrawlers}</span>
        </div>
        <div className={styles.statCard}>
          <span className={styles.statLabel}>활성 크롤러</span>
          <span className={styles.statAccent}>{stats.activeCrawlers}</span>
        </div>
        <div className={styles.statCard}>
          <span className={styles.statLabel}>오늘 크롤 횟수</span>
          <span className={styles.statValue}>{stats.todayCrawls}</span>
        </div>
        <div className={styles.statCard}>
          <span className={styles.statLabel}>성공률</span>
          <span className={styles.statSuccess}>{stats.successRate}%</span>
        </div>
      </div>

      {/* 초기 빈 상태 — 다음 액션 명시 (db-admin EmptyState 패턴 적용) */}
      {isInitialEmpty && (
        <EmptyState
          icon={Rocket}
          title="크롤 실행 이력이 아직 없어요"
          description="첫 크롤을 실행해 마트 데이터를 수집해 보세요. 크롤러 관리에서 개별 실행도 가능합니다."
          action={() => setFirstCrawlOpen(true)}
          actionLabel="첫 크롤 실행하기"
          secondaryAction={() => navigate('/crawlers')}
          secondaryActionLabel="크롤러 관리로 이동"
        />
      )}

      {/* 크롤러별 상태 카드 */}
      {crawlerCards.length > 0 && (
        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>크롤러 상태</h2>
          <div className={styles.crawlerGrid}>
            {crawlerCards.map((c) => (
              <div
                key={c.name}
                className={`${styles.crawlerCard} ${styles[`card${CARD_STATUS_CLASS[c.status] || 'Inactive'}`] || ''}`}
              >
                <div className={styles.crawlerCardHeader}>
                  <span className={`${styles.statusDot} ${styles[`dot${CARD_STATUS_CLASS[c.status] || 'Inactive'}`]}`} />
                  <span className={styles.crawlerName}>{c.name}</span>
                </div>
                <div className={styles.crawlerMeta}>
                  <span>마지막 실행: {formatTime(c.lastRun)}</span>
                  <span>수집: {c.itemsCount}건</span>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* 데이터 신선도 패널 */}
      {freshness.length > 0 && (
        <section className={styles.section}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
            <h2 className={styles.sectionTitle}>데이터 신선도</h2>
            {isFreshAllUnknown && (
              <button
                onClick={() => setFirstCrawlOpen(true)}
                style={{
                  padding: '6px 12px', borderRadius: 8, border: 0,
                  background: 'var(--accent, #38bdf8)', color: '#0b1220',
                  cursor: 'pointer', fontWeight: 600, fontSize: '.82rem',
                  display: 'inline-flex', alignItems: 'center', gap: 6,
                }}
              >
                <Rocket size={14} /> 첫 크롤 실행하기
              </button>
            )}
          </div>
          <div className={styles.freshnessGrid}>
            {freshness.map((f) => (
              <div
                key={f.category}
                className={`${styles.freshnessCard} ${styles[`freshness${FRESHNESS_CLASS[f.status]}`] || ''}`}
              >
                <span className={styles.freshnessLabel}>{f.label}</span>
                <span className={styles.freshnessBadge}>
                  {FRESHNESS_LABEL[f.status]}
                </span>
                <span className={styles.freshnessTime}>
                  {f.lastUpdate ? formatTime(f.lastUpdate) : '아직 적재 전 — 크롤 실행 필요'}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Charts */}
      <div className={styles.chartsGrid}>
        <div className={styles.chartCard}>
          <h3 className={styles.chartTitle}>크롤러 상태 분포</h3>
          {statusDistributionData.length > 0 ? (
            <ResponsiveContainer width="100%" height={250}>
              <PieChart>
                <Pie
                  data={statusDistributionData}
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={90}
                  dataKey="value"
                  label={({ name, value }) => `${name}: ${value}`}
                >
                  {statusDistributionData.map((entry, i) => (
                    <Cell key={i} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{
                    background: '#1e293b',
                    border: '1px solid rgba(148,163,184,0.12)',
                    borderRadius: '8px',
                    color: '#f1f5f9',
                  }}
                />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <EmptyState
              icon={Database}
              title="아직 실행 데이터가 없어요"
              description="크롤을 실행하면 성공/실패/부분 분포가 여기에 표시됩니다."
              action={() => setFirstCrawlOpen(true)}
              actionLabel="첫 크롤 실행하기"
            />
          )}
        </div>

        <div className={styles.chartCard}>
          <div className={styles.chartHeader}>
            <h3 className={styles.chartTitle}>에러 추이</h3>
            <div className={styles.daysSelector}>
              {DAYS_OPTIONS.map((d) => (
                <button
                  key={d}
                  className={`${styles.dayBtn} ${errorTrendDays === d ? styles.dayBtnActive : ''}`}
                  onClick={() => handleDaysChange(d)}
                >
                  {d}일
                </button>
              ))}
            </div>
          </div>
          {errorTrendData.length > 0 ? (
            <ResponsiveContainer width="100%" height={250}>
              <LineChart data={errorTrendData}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.12)" />
                <XAxis dataKey="date" stroke="#64748b" fontSize={12} />
                <YAxis stroke="#64748b" fontSize={12} />
                <Tooltip
                  contentStyle={{
                    background: '#1e293b',
                    border: '1px solid rgba(148,163,184,0.12)',
                    borderRadius: '8px',
                    color: '#f1f5f9',
                  }}
                />
                <Line
                  type="monotone"
                  dataKey="errors"
                  stroke="#f87171"
                  strokeWidth={2}
                  dot={{ fill: '#f87171', r: 4 }}
                  name="에러 수"
                />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <EmptyState
              icon={AlertTriangle}
              title="에러 데이터가 없어요"
              description="크롤 실행 후 발생한 에러가 여기에 누적됩니다."
              action={() => navigate('/logs')}
              actionLabel="로그 보기"
            />
          )}
        </div>
      </div>

      <FirstCrawlModal
        isOpen={firstCrawlOpen}
        onClose={() => setFirstCrawlOpen(false)}
        onLaunched={() => {
          setTimeout(() => fetchDashboard(), 1500);
        }}
      />
    </div>
  );
}
