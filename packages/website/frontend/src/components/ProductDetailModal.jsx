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
import { buildCartPayload, buildWishlistPayload, normalizeProduct } from '../utils/productActions';
import { buildProductDecision } from '../utils/productDecision';
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
  const rawFavorites = useStore((st) => st.favorites);
  const favorites = Array.isArray(rawFavorites) ? rawFavorites : [];
  const favoriteItems = useStore((st) => st.favoriteItems);
  const addFavorite = useStore((st) => st.addFavorite);
  const removeFavorite = useStore((st) => st.removeFavorite);
  const setFavoriteRemoteId = useStore((st) => st.setFavoriteRemoteId);
  const addItem = useCartStore((st) => st.addItem);
  const { trackView, trackCartAdd, trackWishlistAdd } = useActivityTracker();

  const [priceCompare, setPriceCompare] = useState(null);
  const [priceHistory, setPriceHistory] = useState([]);
  const [priceTrust, setPriceTrust] = useState(null);
  const [loading, setLoading] = useState(false);

  if (!product) return null;

  // Normalize product data (supports public catalog, mart deals, hotdeals, and cart items)
  const normalized = normalizeProduct(product);
  const {
    name,
    price,
    originalPrice: origPrice,
    discount,
    image,
    storeName,
    storeKey,
    category,
    unit,
    brand,
    sourceUrl,
    eventType,
    period,
    keywords,
    sourceTitle,
    description,
    numericProductId,
    favoriteId,
    priceObservationOnly,
    hasDiscountMetadata,
    recordLabel,
    claimStatusLabel,
  } = normalized;
  const productId = numericProductId;
  const standardUnitPrice = normalized.standardUnitPrice ?? priceTrust?.standard_unit_price ?? null;
  const standardUnit = normalized.standardUnit ?? priceTrust?.standard_unit ?? '100g';

  // Determine mode: if explicitly set use that, otherwise auto-detect
  const mode = modeProp || (productId && !product.martKey && !product.source && product.type !== 'hotdeal' ? 'product' : 'preview');

  const verifiedDiscount = hasDiscountMetadata && !priceObservationOnly;
  const savingsAmount = verifiedDiscount && origPrice > price && price > 0 ? origPrice - price : 0;
  const savingsPct = verifiedDiscount && discount > 0 ? discount : (verifiedDiscount && origPrice > 0 && price > 0 ? Math.round((1 - price / origPrice) * 100) : 0);
  const isFav = favorites.includes(favoriteId);
  const categoryIcon = CATEGORY_ICONS[category] || CATEGORY_ICONS.default;
  const storeIcon = STORE_ICONS[storeKey] || '🏪';

  // Track view on mount
  useEffect(() => {
    trackView('product', productId || favoriteId);
  }, [productId, favoriteId]); // eslint-disable-line react-hooks/exhaustive-deps

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

  const handleAddToCart = useCallback(() => {
    addItem(buildCartPayload(product));
    trackCartAdd(productId || favoriteId, name);
    addToast(`${name} 장바구니에 추가했어요 🛒`, 'success');
  }, [product, productId, favoriteId, name, addItem, trackCartAdd, addToast]);

  const handleToggleWishlist = useCallback(() => {
    if (!isLoggedIn) {
      addToast('로그인이 필요합니다', 'warning');
      return;
    }
    if (isFav) {
      const remoteId = favoriteItems?.[favoriteId]?.remote_id;
      removeFavorite(favoriteId);
      if (remoteId) {
        api.delete(`/api/wishlist/${remoteId}`).catch(() => {});
      }
      addToast('찜 목록에서 제거했어요', 'info');
    } else {
      const payload = buildWishlistPayload(product);
      addFavorite(favoriteId, payload);
      trackWishlistAdd(productId || favoriteId, name);
      api.post('/api/wishlist', payload).then(async (res) => {
        const json = res?.json ? await res.json().catch(() => null) : null;
        const remoteId = json?.data?.id || json?.id;
        if (remoteId) setFavoriteRemoteId(favoriteId, remoteId);
      }).catch(() => {
        removeFavorite(favoriteId);
        addToast('찜 추가에 실패했어요. 잠시 후 다시 시도해주세요.', 'error');
      });
      addToast(`${name} 찜했어요 ❤️`, 'success');
    }
  }, [isLoggedIn, isFav, product, productId, favoriteId, name, favoriteItems, addFavorite, removeFavorite, setFavoriteRemoteId, addToast, trackWishlistAdd]);

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
  const decision = buildProductDecision(product, { priceCompare, priceHistory, priceTrust });
  const {
    historySummary,
    comparableOffers,
    judgment,
    trustSignals,
    currentOffer,
  } = decision;
  const otherOffers = comparableOffers.filter((offer) => !offer.current);
  const bestOffer = comparableOffers[0];
  const currentIsBest = bestOffer && bestOffer.price >= price;
  const trendLabel = {
    down: '최근 하락',
    up: '최근 상승',
    stable: '큰 변동 없음',
    unknown: '추세 부족',
  }[historySummary.trend] || '추세 부족';
  const formatDate = (value) => {
    if (!value) return '';
    const text = String(value);
    return text.length >= 10 ? text.slice(5, 10) : text;
  };

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
            {verifiedDiscount && savingsPct > 0 && (
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
                {verifiedDiscount && origPrice > 0 && origPrice !== price && (
                  <span className={s.origPrice}>{fmt(origPrice)}원</span>
                )}
              </div>
              {verifiedDiscount && savingsAmount > 0 && (
                <div className={s.savingsRow}>
                  <span className={s.savingsBadge}>💰 {fmt(savingsAmount)}원 절약 ({savingsPct}%)</span>
                </div>
              )}
              {priceObservationOnly && (
                <div className={s.observationNote}>
                  <span>{recordLabel || '관측 가격'}</span>
                  <small>{claimStatusLabel || '할인 여부 미확인'}</small>
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
            {description && (
              <div className={s.description}>
                {description}
              </div>
            )}
          </div>

          <div className={s.section}>
            <h3 className={s.sectionTitle}>🔥 구매 판단</h3>
            <div className={`${s.judgmentBox} ${s[`judgment-${judgment.tone}`] || ''}`}>
              <div className={s.judgmentHead}>
                <strong>{judgment.label}</strong>
                {loading && mode === 'product' && <span className={s.loadingPill}>계산 중</span>}
              </div>
              <p>{judgment.copy}</p>
            </div>
            <div className={s.decisionGrid}>
              <div>
                <span>판매 채널</span>
                <strong>{currentOffer.sourceName}</strong>
                <small>{currentOffer.sourceType}</small>
              </div>
              <div>
                <span>단위가</span>
                <strong>{displayUnitPrice || '정보 없음'}</strong>
                <small>{unit || '규격 미확인'}</small>
              </div>
              <div>
                <span>유효 기간</span>
                <strong>{currentOffer.period || '기간 미확인'}</strong>
                <small>{eventType || '행사 정보 없음'}</small>
              </div>
              <div>
                <span>다음 행동</span>
                <strong>{currentIsBest ? '현재 상품 확인' : '더 싼 판매처 확인'}</strong>
                <small>{sourceUrl ? '원본 이동 가능' : '찜/장바구니로 추적'}</small>
              </div>
            </div>
            {trustSignals.length > 0 ? (
              <div className={s.signalList}>
                {trustSignals.map((signal) => <span key={signal}>{signal}</span>)}
              </div>
            ) : (
              <p className={s.noData}>신뢰도/커뮤니티 신호는 아직 수집되지 않았습니다.</p>
            )}
          </div>

          <div className={s.section}>
            <h3 className={s.sectionTitle}>📈 가격 이력 요약</h3>
            {historySummary.hasData ? (
              <>
                <div className={s.historySummary}>
                  <div><span>최저</span><strong>{historySummary.min ? `${fmt(historySummary.min)}원` : '-'}</strong></div>
                  <div><span>평균</span><strong>{historySummary.avg ? `${fmt(historySummary.avg)}원` : '-'}</strong></div>
                  <div><span>최고</span><strong>{historySummary.max ? `${fmt(historySummary.max)}원` : '-'}</strong></div>
                  <div><span>최근</span><strong>{historySummary.latest ? `${fmt(historySummary.latest)}원` : `${fmt(price)}원`}</strong></div>
                </div>
                <div className={s.historyNote}>
                  <span>{trendLabel}</span>
                  {historySummary.lastDiscountDate && <span>마지막 할인 {formatDate(historySummary.lastDiscountDate)}</span>}
                  {historySummary.sparse && <span>표본이 적어 판단 신뢰도가 낮습니다</span>}
                </div>
                {historySummary.history.length > 0 && (
                  <div className={s.priceHistoryChart}>
                    {historySummary.history.slice(-7).map((p, i) => {
                      const recent = historySummary.history.slice(-7);
                      const max = Math.max(...recent.map((h) => h.price));
                      const min = Math.min(...recent.map((h) => h.price));
                      const height = max > min ? ((p.price - min) / (max - min)) * 70 + 25 : 55;
                      return (
                        <div key={`${p.date}-${i}`} className={s.chartBar}>
                          <div className={s.barFill} style={{ height: `${height}%` }} />
                          <span className={s.barLabel}>{formatDate(p.date)}</span>
                          <span className={s.barPrice}>{fmt(p.price)}</span>
                        </div>
                      );
                    })}
                  </div>
                )}
              </>
            ) : (
              <p className={s.noData}>가격 이력이 아직 없습니다. 찜해두면 이후 가격 변동을 추적할 수 있어요.</p>
            )}
          </div>

          <div className={s.section}>
            <h3 className={s.sectionTitle}>🏬 비교 가능한 판매처</h3>
            {otherOffers.length > 0 ? (
              <div className={s.otherStores}>
                {comparableOffers.map((offer, i) => (
                  <div key={`${offer.sourceName}-${offer.price}-${i}`} className={`${s.otherStoreItem} ${offer.current ? s.currentOffer : ''}`}>
                    <span className={s.osIcon}>{offer.current ? '✅' : '🏪'}</span>
                    <span className={s.osName}>
                      {offer.sourceName}
                      {offer.title && <small>{offer.title}</small>}
                    </span>
                    <span className={s.osPrice}>{fmt(offer.price)}원</span>
                    {offer.price < price && <span className={s.osCheaper}>더 저렴</span>}
                    {offer.price === bestOffer?.price && <span className={s.osBest}>최저</span>}
                  </div>
                ))}
              </div>
            ) : (
              <p className={s.noData}>아직 다른 마트/쇼핑몰/핫딜 사이트 비교 데이터가 없습니다.</p>
            )}
          </div>

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
