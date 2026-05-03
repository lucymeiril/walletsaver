/**
 * 상품 상세 모달 — 통합 제품 정보 뷰
 * 마트, 핫딜, 검색결과, 장바구니 항목 클릭 시 열림
 *
 * mode="product" (기본) — productId가 있으면 API에서 추가 데이터 로드
 * mode="preview" — 전달받은 props 데이터만 표시, API 호출 없음
 */
import { useState, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import {
  X, ShoppingCart, Heart, Share2, ExternalLink, ChevronRight,
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

export default function ProductDetailModal({ product, onClose, mode: modeProp }) {
  const addToast = useStore((st) => st.addToast);
  const isLoggedIn = useStore((st) => st.isLoggedIn);
  const favorites = useStore((st) => st.favorites);
  const addFavorite = useStore((st) => st.addFavorite);
  const removeFavorite = useStore((st) => st.removeFavorite);
  const addItem = useCartStore((st) => st.addItem);
  const { trackView, trackCartAdd, trackWishlistAdd } = useActivityTracker();

  const [priceCompare, setPriceCompare] = useState(null);
  const [priceHistory, setPriceHistory] = useState([]);
  const [priceTrust, setPriceTrust] = useState(null);
  const [loading, setLoading] = useState(false);

  if (!product) return null;

  // Normalize product data (supports multiple shapes)
  const name = product.name || product.canonical_name || product.product_name || product.title || product.source_title || product.item_name || '상품명 없음';
  const price = product.sale ?? product.price ?? product.current_price ?? product.item_price ?? 0;
  const origPrice = product.orig ?? product.original_price ?? product.origPrice ?? 0;
  const discount = product.disc ?? product.discount_pct ?? product.discount ?? product.discountRate ?? 0;
  const image = product.img ?? product.image_url ?? product.image ?? product.item_image_url ?? product.thumbnail ?? '';
  const storeName = product.store_name ?? product.store ?? product.martName ?? product.source_name ?? product.source ?? '';
  const storeKey = product.store_key ?? product.martKey ?? product.source_key ?? '';
  const category = product.category ?? product.category_name ?? product.category_id ?? '';
  const unit = product.unit ?? product.spec ?? '';
  const brand = product.brand ?? '';
  const sourceUrl = product.source_url ?? product.detail_url ?? product.detailUrl ?? product.link ?? '';
  const productId = product.product_id ?? product.productId ?? product.id ?? '';
  const eventType = product.event ?? product.event_name ?? '';
  const period = product.period ?? '';
  const keywords = Array.isArray(product.keywords) ? product.keywords.filter(Boolean) : [];
  const sourceTitle = product.source_title ?? product.offer_title ?? '';
  const standardUnitPrice = product.standard_unit_price ?? product.unit_price ?? priceTrust?.standard_unit_price ?? null;
  const standardUnit = product.standard_unit ?? priceTrust?.standard_unit ?? '100g';

  // Determine mode: if explicitly set use that, otherwise auto-detect
  const mode = modeProp || (productId && !product.martKey && !product.source ? 'product' : 'preview');

  const savingsAmount = origPrice > price && price > 0 ? origPrice - price : 0;
  const savingsPct = discount > 0 ? discount : (origPrice > 0 && price > 0 ? Math.round((1 - price / origPrice) * 100) : 0);
  const isFav = favorites.includes(productId);
  const categoryIcon = CATEGORY_ICONS[category] || CATEGORY_ICONS.default;
  const storeIcon = STORE_ICONS[storeKey] || '🏪';

  // Track view on mount
  useEffect(() => {
    if (productId) trackView('product', productId);
  }, [productId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch additional data (only in product mode)
  useEffect(() => {
    if (mode !== 'product' || !productId) return;
    setLoading(true);
    const fetchExtra = async () => {
      try {
        const [compRes, histRes, trustRes] = await Promise.allSettled([
          api.getJson(`/api/products/${productId}/price-compare`).catch(() => null),
          api.getJson(`/api/products/${productId}/price-history`).catch(() => null),
          api.getJson(`/api/products/${productId}/trust`).catch(() => null),
        ]);
        if (compRes.status === 'fulfilled' && compRes.value) {
          const compData = compRes.value.data || compRes.value;
          setPriceCompare(compData);
        }
        if (histRes.status === 'fulfilled' && histRes.value) {
          const histData = histRes.value.data || histRes.value;
          setPriceHistory(histData?.history || histData || []);
        }
        if (trustRes.status === 'fulfilled' && trustRes.value) {
          setPriceTrust(trustRes.value.data || trustRes.value);
        }
      } catch { /* ignore */ }
      setLoading(false);
    };
    fetchExtra();
  }, [productId, mode]);

  // Extract other stores from price-compare data
  const otherStores = Array.isArray(priceCompare)
    ? priceCompare
    : (priceCompare?.other_stores || priceCompare?.stores || priceCompare?.sources || priceCompare?.items || []);

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
  const displayUnitPrice = standardUnitPrice
    ? `${fmt(Math.round(standardUnitPrice))}원/${standardUnit}`
    : unitPrice;

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
              {displayUnitPrice && <div className={s.unitPrice}>{displayUnitPrice}</div>}
            </div>

            {eventType && (
              <div className={s.eventTag}>🏷️ {eventType}</div>
            )}
            {period && <div className={s.period}>📅 {period}</div>}

            {/* Unit info */}
            {unit && <div className={s.metaRow}><span className={s.metaLabel}>규격</span> {unit}</div>}
            {sourceTitle && sourceTitle !== name && (
              <div className={s.metaRow}><span className={s.metaLabel}>판매명</span> {sourceTitle}</div>
            )}
            {keywords.length > 0 && (
              <div className={s.metaRow}>
                <span className={s.metaLabel}>키워드</span>
                {keywords.slice(0, 5).map((keyword) => (
                  <span key={keyword} className={s.categoryTag}>{keyword}</span>
                ))}
              </div>
            )}
          </div>

          {/* 시세 비교 (product mode only) */}
          {mode === 'product' && (
            <div className={s.section}>
              <h3 className={s.sectionTitle}>🔥 진짜 핫딜 판단</h3>
              {priceTrust ? (
                <div className={s.trustBox}>
                  <div className={s.trustScoreRow}>
                    <span className={s.trustScore}>{priceTrust.hotdeal_score ?? 0}</span>
                    <span className={s.trustScoreLabel}>/ 100</span>
                    <span className={s.trustReason}>{priceTrust.rationale}</span>
                  </div>
                  <div className={s.trustMetrics}>
                    <div>
                      <span>현재가</span>
                      <strong>{fmt(priceTrust.current_price)}원</strong>
                    </div>
                    <div>
                      <span>과거 최저</span>
                      <strong>{priceTrust.historical_low_price ? `${fmt(priceTrust.historical_low_price)}원` : '-'}</strong>
                    </div>
                    <div>
                      <span>과거 평균</span>
                      <strong>{priceTrust.historical_average_price ? `${fmt(priceTrust.historical_average_price)}원` : '-'}</strong>
                    </div>
                    <div>
                      <span>비교 출처</span>
                      <strong>{priceTrust.reference_count ?? 0}개</strong>
                    </div>
                  </div>
                </div>
              ) : (
                <p className={s.noData}>{loading ? '가격 신뢰도 계산 중...' : '가격 신뢰도 데이터가 아직 부족합니다.'}</p>
              )}

              <h3 className={s.sectionTitle}>📊 시세 비교</h3>
              {priceCompare ? (
                <div className={s.comparisonGrid}>
                  {priceCompare.kamis_price && (
                    <div className={s.compItem}>
                      <span className={s.compLabel}>KAMIS 정부 가격</span>
                      <span className={s.compValue}>{fmt(priceCompare.kamis_price)}원</span>
                      {price < priceCompare.kamis_price && (
                        <span className={s.compGood}>
                          {fmt(priceCompare.kamis_price - price)}원 저렴
                        </span>
                      )}
                    </div>
                  )}
                  {priceCompare.category_avg && (
                    <div className={s.compItem}>
                      <span className={s.compLabel}>카테고리 평균</span>
                      <span className={s.compValue}>{fmt(priceCompare.category_avg)}원</span>
                      {price < priceCompare.category_avg ? (
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
          )}

          {/* 다른 매장 가격 (from price-compare data) */}
          {otherStores.length > 0 && (
            <div className={s.section}>
              <h3 className={s.sectionTitle}>🏬 다른 매장 가격</h3>
              <div className={s.otherStores}>
                {otherStores.map((st, i) => (
                  <div key={i} className={s.otherStoreItem}>
                    <span className={s.osIcon}>{STORE_ICONS[st.store_key] || '🏪'}</span>
                    <span className={s.osName}>{st.store_name || st.source_name || st.source || st.store || '출처'}</span>
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
