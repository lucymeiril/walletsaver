import { useEffect } from 'react';
import useAdminStore from '../../stores/adminStore';
import { errorTrend, statusDistribution } from '../../data/mockData';
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

export default function Dashboard() {
  const stats = useAdminStore((s) => s.dashboardStats);
  const logs = useAdminStore((s) => s.logs);
  const loading = useAdminStore((s) => s.loading);
  const fetchDashboard = useAdminStore((s) => s.fetchDashboard);

  useEffect(() => {
    fetchDashboard();
  }, [fetchDashboard]);

  const recentLogs = logs.slice(0, 7);

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
          <ResponsiveContainer width="100%" height={250}>
            <PieChart>
              <Pie
                data={statusDistribution}
                cx="50%"
                cy="50%"
                innerRadius={60}
                outerRadius={90}
                dataKey="value"
                label={({ name, value }) => `${name}: ${value}`}
              >
                {statusDistribution.map((entry, i) => (
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
        </div>

        <div className={styles.chartCard}>
          <h3 className={styles.chartTitle}>에러 추이 (최근 7일)</h3>
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={errorTrend}>
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
        </div>
      </div>

      {/* Recent Activity */}
      <div className={styles.tableCard}>
        <h3 className={styles.tableTitle}>최근 크롤 활동</h3>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>시간</th>
              <th>크롤러명</th>
              <th>상태</th>
              <th>수집 건수</th>
              <th>소요 시간</th>
            </tr>
          </thead>
          <tbody>
            {recentLogs.map((log) => (
              <tr key={log.id}>
                <td>{new Date(log.startTime).toLocaleTimeString('ko-KR')}</td>
                <td>{log.crawlerName}</td>
                <td>
                  <span
                    className={
                      log.status === 'success'
                        ? styles.statusSuccess
                        : log.status === 'failure'
                        ? styles.statusFailure
                        : styles.statusPartial
                    }
                  >
                    {STATUS_LABEL[log.status]}
                  </span>
                </td>
                <td>{log.collected}</td>
                <td>{log.duration}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
