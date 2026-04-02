import { useEffect } from 'react';
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
import styles from './Dashboard.module.css';

const STATUS_LABEL = { success: '성공', failure: '실패', partial: '부분' };
const STATUS_COLORS = { '성공': 'var(--green)', '실패': 'var(--red)', '부분': 'var(--yellow)' };

export default function Dashboard() {
  const stats = useAdminStore((s) => s.dashboardStats);
  const loading = useAdminStore((s) => s.loading);
  const error = useAdminStore((s) => s.error);
  const fetchDashboard = useAdminStore((s) => s.fetchDashboard);

  useEffect(() => {
    fetchDashboard();
  }, [fetchDashboard]);

  // 실시간 데이터로 파이 차트 데이터 구성
  const dist = stats.statusDistribution || {};
  const statusDistributionData = [
    { name: '성공', value: dist.success || 0, color: 'var(--green)' },
    { name: '실패', value: dist.failure || 0, color: 'var(--red)' },
    { name: '부분', value: dist.partial || 0, color: 'var(--yellow)' },
  ].filter((d) => d.value > 0);

  const errorTrendData = stats.errorTrend || [];

  if (loading && !stats.totalCrawlers) {
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
      <h1 className={styles.pageTitle}>대시보드</h1>

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
            <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--text3)' }}>
              아직 실행 데이터가 없습니다
            </div>
          )}
        </div>

        <div className={styles.chartCard}>
          <h3 className={styles.chartTitle}>에러 추이 (최근 7일)</h3>
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
            <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--text3)' }}>
              아직 에러 데이터가 없습니다
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
