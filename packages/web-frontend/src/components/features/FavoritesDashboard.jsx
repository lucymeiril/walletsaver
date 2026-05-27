import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { X, TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { fmt } from '../../utils/helpers';
import useStore from '../../stores/appStore';
import s from './FavoritesDashboard.module.css';

function getTimingBadge(product) {
  if (!product.cur || !product.avg) return { cls: s.badgeOk, label: '✅ 가격 정보 없음' };
  const ratio = product.cur / product.avg;
  if (ratio <= 0.7)  return { cls: s.badgeUltra, label: '🔥 지금 당장 사세요!' };
  if (ratio <= 0.85) return { cls: s.badgeGreat, label: '💙 좋은 가격이에요' };
  if (ratio <= 1.05) return { cls: s.badgeOk,    label: '✅ 사도 괜찮아요' };
  return                      { cls: s.badgeWait,  label: '⏳ 좀 기다려보세요' };
}

export default function FavoritesDashboard() {
  const navigate = useNavigate();
  const { favorites, removeFavorite, setSelectedProduct } = useStore();
  const [products, setProducts] = useState([]);

  // 상품 목록을 API에서 조회
  useEffect(() => {
    fetch('/api/products/search?per_page=50').then(r => r.json())
      .then(res => setProducts(res.data || []))
      .catch(console.error);
  }, []);

  const favProducts = favorites
    .map(id => products.find(p => p.id === id))
    .filter(Boolean);

  if (favProducts.length === 0) {
    return (
      <div className={s.empty}>
        관심 품목을 추가해보세요! 🔔<br />매일 가격을 확인할 수 있어요
      </div>
    );
  }

  return (
    <div className={s.wrap}>
      {favProducts.map(p => {
        const diff = p.cur - p.avg;
        const pct = ((diff / p.avg) * 100).toFixed(1);
        let trendCls = s.trendSame, trendIcon = <Minus size={12} />;
        if (diff < -p.avg * 0.03) { trendCls = s.trendDown; trendIcon = <TrendingDown size={12} />; }
        else if (diff > p.avg * 0.03) { trendCls = s.trendUp; trendIcon = <TrendingUp size={12} />; }
        const badge = getTimingBadge(p);

        return (
          <div
            key={p.id}
            className={s.card}
            onClick={() => { setSelectedProduct(p); navigate(`/price/${p.id}`); }}
          >
            <div className={s.cardTop}>
              <span className={s.icon}>{p.icon}</span>
              <button
                className={s.removeBtn}
                onClick={(e) => { e.stopPropagation(); removeFavorite(p.id); }}
                title="관심 해제"
              >
                <X size={16} />
              </button>
            </div>
            <div className={s.name}>{p.name} ({p.unit})</div>
            <div className={s.price}>{fmt(p.cur)}원</div>
            <span className={`${s.trend} ${trendCls}`}>
              {trendIcon} {diff === 0 ? '→' : `${Math.abs(pct)}%`}
            </span>
            <div className={`${s.badge} ${badge.cls}`}>{badge.label}</div>
          </div>
        );
      })}
    </div>
  );
}
