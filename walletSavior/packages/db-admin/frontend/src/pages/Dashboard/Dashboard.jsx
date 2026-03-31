import { useEffect } from 'react';
import { Package, DollarSign, FolderTree, Search, Clock, Activity, Inbox } from 'lucide-react';
import useDbAdminStore from '../../stores/dbAdminStore';
import { useNavigate } from 'react-router-dom';
import s from './Dashboard.module.css';

export default function Dashboard() {
  const { dashboardStats, loading, ingestionStats, fetchDashboard, fetchIngestionStats } = useDbAdminStore();
  const { totalProducts, totalPriceRecords, totalCategories, totalKeywords, lastUpdated, qualityScore, recentIngestions } = dashboardStats;
  const navigate = useNavigate();

  useEffect(() => {
    fetchDashboard();
    fetchIngestionStats();
  }, [fetchDashboard, fetchIngestionStats]);

  const timeSince = getTimeSince(lastUpdated);
  const freshness = timeSince.hours < 1 ? 'fresh' : timeSince.hours < 6 ? 'normal' : 'stale';
  const pendingCount = ingestionStats.pending || 0;

  return (
    <div className={s.page}>
      <h2 className={s.title}>대시보드</h2>

      {/* 요약 카드 */}
      <div className={s.cards}>
        <StatCard icon={Package} label="총 상품 수" value={totalProducts} color="var(--accent)" />
        <StatCard icon={DollarSign} label="가격 이력 수" value={(totalPriceRecords ?? 0).toLocaleString()} color="var(--green)" />
        <StatCard icon={FolderTree} label="카테고리 수" value={totalCategories} color="var(--yellow)" />
        <StatCard icon={Search} label="키워드 수" value={totalKeywords} color="var(--pink)" />
      </div>

      {/* 수신함 대기 알림 */}
      {pendingCount > 0 && (
        <div
          className={s.card}
          style={{ marginBottom: 'var(--space-md)', cursor: 'pointer', borderColor: 'var(--accent)' }}
          onClick={() => navigate('/inbox')}
        >
          <h3 className={s.cardTitle}><Inbox size={16} /> 📥 수신함 대기</h3>
          <p style={{ color: 'var(--accent)', fontSize: 'var(--fs-lg)', fontWeight: 'var(--fw-bold)' }}>
            {pendingCount}건의 데이터가 승인 대기 중입니다
          </p>
          <p style={{ color: 'var(--text3)', fontSize: 'var(--fs-sm)', marginTop: 4 }}>
            클릭하여 수신함으로 이동
          </p>
        </div>
      )}

      <div className={s.grid}>
        {/* 데이터 최신성 */}
        <div className={s.card}>
          <h3 className={s.cardTitle}><Clock size={16} /> 최근 업데이트</h3>
          <div className={s.freshnessWrap}>
            <span className={`${s.dot} ${s[freshness]}`} />
            <span className={s.freshnessText}>
              {freshness === 'fresh' ? '최신 상태' : freshness === 'normal' ? '정상' : '업데이트 필요'}
            </span>
          </div>
          <p className={s.timeAgo}>{timeSince.text}</p>
          <p className={s.timestamp}>{lastUpdated ? new Date(lastUpdated).toLocaleString('ko-KR') : '-'}</p>
        </div>

        {/* 품질 점수 게이지 */}
        <div className={s.card}>
          <h3 className={s.cardTitle}><Activity size={16} /> 데이터 품질 점수</h3>
          <div className={s.gaugeWrap}>
            <svg viewBox="0 0 120 70" className={s.gauge}>
              <path d="M 10 65 A 50 50 0 0 1 110 65" fill="none" stroke="var(--border2)" strokeWidth="8" strokeLinecap="round" />
              <path
                d="M 10 65 A 50 50 0 0 1 110 65"
                fill="none"
                stroke={qualityScore >= 80 ? 'var(--green)' : qualityScore >= 60 ? 'var(--yellow)' : 'var(--red)'}
                strokeWidth="8"
                strokeLinecap="round"
                strokeDasharray={`${qualityScore * 1.57} 157`}
              />
            </svg>
            <span className={s.gaugeValue}>{qualityScore}점</span>
          </div>
          <p className={s.gaugeLabel}>
            {qualityScore >= 80 ? '양호' : qualityScore >= 60 ? '보통' : '주의 필요'}
          </p>
        </div>

        {/* 최근 데이터 수집 활동 */}
        <div className={`${s.card} ${s.wideCard}`}>
          <h3 className={s.cardTitle}>최근 데이터 수집 활동</h3>
          <table className={s.table}>
            <thead>
              <tr>
                <th>출처</th>
                <th>수집 건수</th>
                <th>날짜</th>
                <th>상태</th>
              </tr>
            </thead>
            <tbody>
              {recentIngestions.map((item) => (
                <tr key={item.id}>
                  <td>{item.source}</td>
                  <td>{(item.count ?? 0).toLocaleString()}</td>
                  <td>{item.date}</td>
                  <td>
                    <span className={`${s.status} ${s[item.status]}`}>
                      {item.status === 'success' ? '성공' : item.status === 'warning' ? '경고' : '오류'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function StatCard({ icon: Icon, label, value, color }) {
  return (
    <div className={s.statCard}>
      <div className={s.statIcon} style={{ background: `${color}15`, color }}>
        <Icon size={22} />
      </div>
      <div>
        <p className={s.statLabel}>{label}</p>
        <p className={s.statValue}>{value}</p>
      </div>
    </div>
  );
}

function getTimeSince(dateStr) {
  if (!dateStr) return { hours: 999, text: '알 수 없음' };
  const diff = Date.now() - new Date(dateStr).getTime();
  if (isNaN(diff)) return { hours: 999, text: '알 수 없음' };
  const hours = Math.floor(diff / 3600000);
  const minutes = Math.floor((diff % 3600000) / 60000);
  if (hours > 24) return { hours, text: `${Math.floor(hours / 24)}일 전` };
  if (hours > 0) return { hours, text: `${hours}시간 ${minutes}분 전` };
  return { hours: 0, text: `${minutes}분 전` };
}
