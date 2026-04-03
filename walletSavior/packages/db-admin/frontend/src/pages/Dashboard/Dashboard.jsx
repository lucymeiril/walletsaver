import { useEffect, useCallback } from 'react';
import { Package, DollarSign, FolderTree, Search, Clock, Activity, Inbox, RefreshCw, AlertTriangle, Zap } from 'lucide-react';
import useDbAdminStore from '../../stores/dbAdminStore';
import { useNavigate } from 'react-router-dom';
import s from './Dashboard.module.css';

export default function Dashboard() {
  const { dashboardStats, loading, ingestionStats, fetchDashboard, fetchIngestionStats } = useDbAdminStore();
  const {
    totalProducts, totalPriceRecords, totalCategories, totalKeywords,
    lastUpdated, qualityScore, qualityDetails, recentIngestions,
    alerts, freshness, changes,
  } = dashboardStats;
  const navigate = useNavigate();

  useEffect(() => {
    fetchDashboard();
    fetchIngestionStats();
  }, [fetchDashboard, fetchIngestionStats]);

  const handleRefresh = useCallback(() => {
    fetchDashboard();
    fetchIngestionStats();
  }, [fetchDashboard, fetchIngestionStats]);

  const timeSince = getTimeSince(lastUpdated);
  const overallFreshness = timeSince.hours < 1 ? 'fresh' : timeSince.hours < 6 ? 'normal' : 'stale';
  const pendingCount = ingestionStats.pending || 0;
  const hasAlerts = alerts && alerts.length > 0;

  return (
    <div className={s.page}>
      <div className={s.titleRow}>
        <h2 className={s.title}>대시보드</h2>
        <button className={s.refreshBtn} onClick={handleRefresh} disabled={loading} title="새로고침">
          <RefreshCw size={16} className={loading ? s.spin : ''} />
          새로고침
        </button>
      </div>

      {/* 긴급 알림 배너 */}
      {hasAlerts && (
        <div className={s.alertBanner}>
          <AlertTriangle size={18} />
          <div className={s.alertContent}>
            <strong>⚠️ 긴급: {alerts.length}건의 수집 실패 감지</strong>
            <ul className={s.alertList}>
              {alerts.slice(0, 3).map((a) => (
                <li key={a.id}>{a.crawler} — {a.message}</li>
              ))}
              {alerts.length > 3 && <li>외 {alerts.length - 3}건...</li>}
            </ul>
          </div>
        </div>
      )}

      {/* 요약 카드 */}
      <div className={s.cards}>
        <StatCard icon={Package} label="총 상품 수" value={totalProducts} color="var(--accent)" change={changes?.products} />
        <StatCard icon={DollarSign} label="가격 이력 수" value={(totalPriceRecords ?? 0).toLocaleString()} color="var(--green)" change={changes?.priceRecords} />
        <StatCard icon={FolderTree} label="카테고리 수" value={totalCategories} color="var(--yellow)" change={changes?.categories} />
        <StatCard icon={Search} label="키워드 수" value={totalKeywords} color="var(--pink)" change={changes?.keywords} />
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
        {/* 데이터 신선도 패널 — 소스별 */}
        <div className={s.card}>
          <h3 className={s.cardTitle}><Zap size={16} /> 데이터 신선도</h3>
          {freshness && freshness.length > 0 ? (
            <div className={s.freshnessList}>
              {freshness.map((f) => (
                <div key={f.source} className={s.freshnessItem}>
                  <span className={`${s.dot} ${s[f.status]}`} />
                  <span className={s.freshnessSource}>{f.source}</span>
                  <span className={s.freshnessTime}>
                    {f.hoursSince <= 1
                      ? '방금 전'
                      : f.hoursSince <= 24
                        ? `${Math.floor(f.hoursSince)}시간 전`
                        : `${Math.floor(f.hoursSince / 24)}일 전`}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <div className={s.freshnessWrap}>
              <span className={`${s.dot} ${s[overallFreshness]}`} />
              <span className={s.freshnessText}>
                {overallFreshness === 'fresh' ? '최신 상태' : overallFreshness === 'normal' ? '정상' : '업데이트 필요'}
              </span>
            </div>
          )}
          <p className={s.timestamp}>{lastUpdated ? new Date(lastUpdated).toLocaleString('ko-KR') : '-'}</p>
        </div>

        {/* 품질 점수 게이지 — 실데이터 */}
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
          {qualityDetails && (
            <div className={s.qualityBreakdown}>
              <QualityBar label="필드 채움률" value={qualityDetails.fillRate} />
              <QualityBar label="중복률" value={qualityDetails.dupRate} invert />
              <QualityBar label="미분류율" value={qualityDetails.noCategoryRate} invert />
            </div>
          )}
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

function StatCard({ icon: Icon, label, value, color, change }) {
  return (
    <div className={s.statCard}>
      <div className={s.statIcon} style={{ background: `${color}15`, color }}>
        <Icon size={22} />
      </div>
      <div>
        <p className={s.statLabel}>{label}</p>
        <div className={s.statRow}>
          <p className={s.statValue}>{value}</p>
          {change !== undefined && change !== 0 && (
            <span className={`${s.changeBadge} ${change > 0 ? s.changeUp : s.changeDown}`}>
              △{change > 0 ? '+' : ''}{change}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

function QualityBar({ label, value, invert }) {
  const displayVal = value ?? 0;
  const barColor = invert
    ? (displayVal <= 5 ? 'var(--green)' : displayVal <= 20 ? 'var(--yellow)' : 'var(--red)')
    : (displayVal >= 80 ? 'var(--green)' : displayVal >= 50 ? 'var(--yellow)' : 'var(--red)');

  return (
    <div className={s.qualityRow}>
      <span className={s.qualityLabel}>{label}</span>
      <div className={s.qualityBarBg}>
        <div className={s.qualityBarFill} style={{ width: `${Math.min(displayVal, 100)}%`, background: barColor }} />
      </div>
      <span className={s.qualityVal}>{displayVal}%</span>
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
