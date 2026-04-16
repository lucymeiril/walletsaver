/**
 * 상품 상세 모달 — 통합 제품 정보 뷰
 * 마트, 핫딜, 검색결과, 장바구니 항목 클릭 시 열림
 */
import { useState, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import {
  X, ShoppingCart, Heart, Share2, ExternalLink, Store,
  TrendingUp, TrendingDown, Minus, ChevronRight, Package,
} from 'lucide-react';
import { api } from '../services/api';
import useStore from '../stores/appStore';
import useCartStore from '../stores/cartStore';
import useActivityTracker from '../hooks/useActivityTracker';
import SafeImage from './common/SafeImage';
import { fmt } from '../utils/helpers';
import { MARTS } from '../utils/constants';
import s from './ProductDetailModal.module.css';

const STORE_ICONS = {
  emart: '🟡', homeplus: '🟠', lotte: '🔴', costco: '🔵',
};

const CATEGORY_ICONS = {
  식품: '🥩', 과일: '🍎', 채소: '🥬', 수산: '🐟', 축산: '🥩',
  유제품: '🥛', 음료: '🥤', 간식: '🍪', 생활: '🧴', 가전: '📱',
  패션: '👗', default: '📦',
};

export default function ProductDetailModal({ product, onClose }) {
  const addToast = useStore((st) => st.addToast);
  const isLoggedIn = useStore((st) => st.isLoggedIn);
  const favorites = useStore((st) => st.favorites);
  const addFavorite = useStore((st) => st.addFavorite);
  const removeFavorite = useStore((st) => st.removeFavorite);
  const addItem = useCartStore((st) => st.addItem);
  const { trackView, trackCartAdd, trackWishlistAdd } = useActivityTracker();

  const [comparison, setComparison] = useState(null);
  const [otherStores, setOtherStores] = useState([]);
  const [priceHistory, setPriceHistory] = useState([]);
  const [loading, setLoading] = useState(false);

  if (!product) return null;

  // Normalize product data (supports multiple shapes)
  const name = product.name || product.product_name || product.title || product.item_name || '상품명 없음';
  const price = product.sale ?? product.price ?? product.current_price ?? product.item_price ?? 0;
  const origPrice = product.orig ?? product.original_price ?? product.origPrice ?? 0;
  const discount = product.disc ?? product.discount_pct ?? product.discount ?? product.discountRate ?? 0;
  const image = product.img ?? product.image_url ?? product.image ?? product.thumbnail ?? '';
  const storeName = product.store_name ?? product.store ?? product.martName ?? product.source ?? '';
  const storeKey = product.store_key ?? product.martKey ?? product.source_key ?? '';
  const category = product.category ?? product.category_name ?? '';
  const unit = product.unit ?? product.spec ?? '';
  const brand = product.brand ?? '';
  const sourceUrl = product.source_url ?? product.detail_url ?? product.detailUrl ?? product.link ?? '';
  const productId = product.product_id ?? product.productId ?? product.id ?? '';
  const eventType = product.event ?? product.event_name ?? '';
  const period = product.period ?? '';

  const savingsAmount = origPrice > price && price > 0 ? origPrice - price : 0;
  const savingsPct = discount > 0 ? discount : (origPrice > 0 && price > 0 ? Math.round((1 - price / origPrice) * 100) : 0);
  const isFav = favorites.includes(productId);
  const categoryIcon = CATEGORY_ICONS[category] || CATEGORY_ICONS.default;
  const storeIcon = STORE_ICONS[storeKey] || '🏪';

  // Track view on mount
  useEffect(() => {
    if (productId) trackView('product', productId);
  }, [productId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch additional data
  useEffect(() => {
    if (!productId) return;
    setLoading(true);
    const fetchExtra = async () => {
      try {
        const [compRes, storesRes, histRes] = await Promise.allSettled([
          api.getJson(`/api/products/${productId}/comparison`).catch(() => null),
          api.getJson(`/api/products/${productId}/other-stores`).catch(() => null),
          api.getJson(`/api/products/${productId}/price-history`).catch(() => null),
        ]);
        if (compRes.status === 'fulfilled' && compRes.value) setComparison(compRes.value);
        if (storesRes.status === 'fulfilled' && storesRes.value) setOtherStores(storesRes.value?.stores || storesRes.value || []);
        if (histRes.status === 'fulfilled' && histRes.value) setPriceHistory(histRes.value?.history || histRes.value || []);
      } catch { /* ignore */ }
      setLoading(false);
    };
    fetchExtra();
  }, [productId]);

  const handleAddToCart = useCallback(() => {
    addItem({
      product_id: productId,
      name,
      price,
      original_price: origPrice,
      store_name: storeName,
      store_key: storeKey,
      category,
      image,
      unit,
    });
    trackCartAdd(productId, name);
    addToast(`${name} 장바구니에 추가했어요 🛒`, 'success');
  }, [productId, name, price, origPrice, storeName, storeKey, category, image, unit, addItem, trackCartAdd, addToast]);

  const handleToggleWishlist = useCallback(() => {
    if (!isLoggedIn) {
      addToast('로그인이 필요합니다', 'warning');
      return;
    }
    if (isFav) {
      removeFavorite(productId);
      addToast('찜 목록에서 제거했어요', 'info');
    } else {
      addFavorite(productId);
      trackWishlistAdd(productId, name);
      // Also notify backend
      api.post('/api/wishlist', {
        product_id: productId,
        product_name: name,
        price_at_add: price,
        store_name: storeName,
        image,
      }).catch(() => {});
      addToast(`${name} 찜했어요 ❤️`, 'success');
    }
  }, [isLoggedIn, isFav, productId, name, price, storeName, image, addFavorite, removeFavorite, addToast, trackWishlistAdd]);

  const handleShare = useCallback(async () => {
    const text = `${name} - ${fmt(price)}원 ${storeName ? `(${storeName})` : ''}`;
    if (navigator.share) {
      try {
        await navigator.share({ title: name, text, url: sourceUrl || window.location.href });
      } catch { /* cancelled */ }
    } else {
      await navigator.clipboard.writeText(text);
      addToast('클립보드에 복사했어요 📋', 'success');
    }
  }, [name, price, storeName, sourceUrl, addToast]);

  const handleKeyDown = useCallback((e) => {
    if (e.key === 'Escape') onClose();
  }, [onClose]);

  useEffect(() => {
    document.addEventListener('keydown', handleKeyDown);
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = '';
    };
  }, [handleKeyDown]);

  // Unit price calc
  let unitPrice = null;
  if (unit && price > 0) {
    const match = unit.match(/(\d+(?:\.\d+)?)\s*(g|kg|ml|l|개|입)/i);
    if (match) {
      const amount = parseFloat(match[1]);
      const unitType = match[2].toLowerCase();
      if (unitType === 'kg' || unitType === 'l') {
        unitPrice = `${fmt(Math.round(price / amount * 0.1))}원/100${unitType === 'kg' ? 'g' : 'ml'}`;
      } else if (unitType === 'g' || unitType === 'ml') {
        unitPrice = `${fmt(Math.round(price / amount * 100))}원/100${unitType}`;
      } else {
        unitPrice = `${fmt(Math.round(price / amount))}원/${unitType}`;
      }
    }
  }

  return createPortal(
    <div className={s.overlay} onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className={s.modal} role="dialog" aria-modal="true" aria-label={name}>
        {/* Header */}
        <div className={s.header}>
          <h2 className={s.title}>{name}</h2>
          <button className={s.closeBtn} onClick={onClose} aria-label="닫기">
            <X size={22} />
          </button>
        </div>

        <div className={s.body}>
          {/* Image */}
          <div className={s.imageSection}>
            {image ? (
              <SafeImage src={image} alt={name} className={s.productImage} />
            ) : (
              <div className={s.placeholderImage}>
                <span className={s.placeholderIcon}>{categoryIcon}</span>
              </div>
            )}
            {savingsPct > 0 && (
              <span className={s.discountBadge}>-{savingsPct}%</span>
            )}
          </div>

          {/* Basic info */}
          <div className={s.infoSection}>
            <div className={s.storeRow}>
              <span className={s.storeIcon}>{storeIcon}</span>
              <span className={s.storeName}>{storeName || '온라인'}</span>
              {category && <span className={s.categoryTag}>{categoryIcon} {category}</span>}
            </div>

            {brand && <div className={s.brand}>{brand}</div>}

            <div className={s.priceBlock}>
              <div className={s.priceMain}>
                <span className={s.salePrice}>{fmt(price)}원</span>
                {origPrice > 0 && origPrice !== price && (
                  <span className={s.origPrice}>{fmt(origPrice)}원</span>
                )}
              </div>
              {savingsAmount > 0 && (
                <div className={s.savingsRow}>
                  <span className={s.savingsBadge}>💰 {fmt(savingsAmount)}원 절약 ({savingsPct}%)</span>
                </div>
              )}
              {unitPrice && <div className={s.unitPrice}>{unitPrice}</div>}
            </div>

            {eventType && (
              <div className={s.eventTag}>🏷️ {eventType}</div>
            )}
            {period && <div className={s.period}>📅 {period}</div>}

            {/* Unit info */}
            {unit && <div className={s.metaRow}><span className={s.metaLabel}>규격</span> {unit}</div>}
          </div>

          {/* 시세 비교 */}
          <div className={s.section}>
            <h3 className={s.sectionTitle}>📊 시세 비교</h3>
            {comparison ? (
              <div className={s.comparisonGrid}>
                {comparison.kamis_price && (
                  <div className={s.compItem}>
                    <span className={s.compLabel}>KAMIS 정부 가격</span>
                    <span className={s.compValue}>{fmt(comparison.kamis_price)}원</span>
                    {price < comparison.kamis_price && (
                      <span className={s.compGood}>
                        {fmt(comparison.kamis_price - price)}원 저렴
                      </span>
                    )}
                  </div>
                )}
                {comparison.category_avg && (
                  <div className={s.compItem}>
                    <span className={s.compLabel}>카테고리 평균</span>
                    <span className={s.compValue}>{fmt(comparison.category_avg)}원</span>
                    {price < comparison.category_avg ? (
                      <span className={s.compGood}>평균보다 저렴</span>
                    ) : (
                      <span className={s.compBad}>평균보다 비쌈</span>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <p className={s.noData}>비교 데이터 부족 — 카테고리 평균가를 참고하세요</p>
            )}
          </div>

          {/* 다른 매장 가격 */}
          {otherStores.length > 0 && (
            <div className={s.section}>
              <h3 className={s.sectionTitle}>🏬 다른 매장 가격</h3>
              <div className={s.otherStores}>
                {otherStores.map((st, i) => (
                  <div key={i} className={s.otherStoreItem}>
                    <span className={s.osIcon}>{STORE_ICONS[st.store_key] || '🏪'}</span>
                    <span className={s.osName}>{st.store_name}</span>
                    <span className={s.osPrice}>{fmt(st.price)}원</span>
                    {st.price < price && <span className={s.osCheaper}>더 저렴!</span>}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 가격 추이 */}
          {priceHistory.length > 0 && (
            <div className={s.section}>
              <h3 className={s.sectionTitle}>📈 가격 추이</h3>
              <div className={s.priceHistoryChart}>
                {priceHistory.slice(-7).map((p, i) => {
                  const max = Math.max(...priceHistory.slice(-7).map((h) => h.price));
                  const height = max > 0 ? (p.price / max) * 100 : 50;
                  return (
                    <div key={i} className={s.chartBar}>
                      <div className={s.barFill} style={{ height: `${height}%` }} />
                      <span className={s.barLabel}>{p.date?.slice(5) || ''}</span>
                      <span className={s.barPrice}>{fmt(p.price)}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Source link */}
          {sourceUrl && (
            <a
              href={sourceUrl}
              target="_blank"
              rel="noopener noreferrer"
              className={s.sourceLink}
            >
              <ExternalLink size={14} />
              원본 페이지로 이동
              <ChevronRight size={14} />
            </a>
          )}
        </div>

        {/* Action buttons */}
        <div className={s.actions}>
          <button className={s.actionPrimary} onClick={handleAddToCart}>
            <ShoppingCart size={18} />
            장바구니 담기
          </button>
          <button
            className={`${s.actionSecondary} ${isFav ? s.wishActive : ''}`}
            onClick={handleToggleWishlist}
          >
            <Heart size={18} fill={isFav ? 'currentColor' : 'none'} />
            {isFav ? '찜 취소' : '찜하기'}
          </button>
          <button className={s.actionIcon} onClick={handleShare} aria-label="공유">
            <Share2 size={18} />
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}
