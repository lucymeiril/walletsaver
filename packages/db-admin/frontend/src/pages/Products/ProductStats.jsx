import { AlertTriangle } from 'lucide-react';
import s from './Products.module.css';

const SOURCE_LABELS = {
  all: '전체', emart: '이마트', homeplus: '홈플러스',
  lottemart: '롯데마트', costco: '코스트코', hotdeal: '핫딜', government: '정부데이터',
};

export default function ProductStats({ stats }) {
  if (!stats) return null;
  return (
    <div className={s.statsBar}>
      <div className={s.statCard}>
        <span className={s.statLabel}>전체 상품</span>
        <span className={s.statValue}>{stats.total?.toLocaleString() ?? 0}</span>
      </div>
      {Object.entries(stats.by_source || {}).map(([src, cnt]) => (
        <div key={src} className={s.statCard}>
          <span className={s.statLabel}>{SOURCE_LABELS[src] || src}</span>
          <span className={s.statValue}>{cnt}</span>
          {stats.last_crawl?.[src] && (
            <span className={s.statMini}>
              최근: {new Date(stats.last_crawl[src]).toLocaleDateString('ko-KR')}
            </span>
          )}
        </div>
      ))}
      {(stats.by_category || []).slice(0, 5).map(cat => (
        <div key={cat.name} className={s.statCard}>
          <span className={s.statLabel}>{cat.name}</span>
          <span className={s.statValue}>{cat.count}</span>
        </div>
      ))}
      {stats.no_price > 0 && (
        <div className={s.statCard}>
          <span className={s.statLabel}>
            <AlertTriangle size={12} style={{ verticalAlign: 'middle', marginRight: 4, color: 'var(--red)' }} />
            가격 없음
          </span>
          <span className={s.statValue} style={{ color: 'var(--red)' }}>{stats.no_price}</span>
        </div>
      )}
    </div>
  );
}
