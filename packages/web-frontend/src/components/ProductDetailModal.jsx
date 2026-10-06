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
  X, ShoppingCart, Heart, Share2, ExternalLink, ChevronRight, BellRing,
} from 'lucide-react';
import { api } from '../services/api';
import useStore from '../stores/appStore';
import useCartStore from '../stores/cartStore';
import useActivityTracker from '../hooks/useActivityTracker';
import SafeImage from './common/SafeImage';
import { fmt } from '../utils/helpers';
import { buildCartPayload, buildWishlistPayload, buildProductShareUrl, normalizeProduct, selectProductOffer, getProductSelection } from '../utils/productActions';
import { buildProductDecision, getOfferUnitPrice, getVariantBestOffer, getOfferConditionText, getOfferReceiptText, getQuantityComponentTexts, getConditionalOfferConditionText, getObservedOfferPriceText, isObservationReceiptEligible, getOfferAmountLabel } from '../utils/productDecision';
import s from './ProductDetailModal.module.css';

const STORE_ICONS = {
  emart: '🟡', homeplus: '🟠', lotte: '🔴', costco: '🔵',
};

const CATEGORY_ICONS = {
  식품: '🥩', 과일: '🍎', 채소: '🥬', 수산: '🐟', 축산: '🥩',
  유제품: '🥛', 음료: '🥤', 간식: '🍪', 생활: '🧴', 가전: '📱',
  패션: '👗', default: '📦',
};

export default function ProductDetailModal({ product: suppliedProduct, onClose, mode: modeProp }) {
  const addToast = useStore((st) => st.addToast);
  const isLoggedIn = useStore((st) => st.isLoggedIn);
  const rawFavorites = useStore((st) => st.favorites);
  const favorites = Array.isArray(rawFavorites) ? rawFavorites : [];
  const favoriteItems = useStore((st) => st.favoriteItems);
  const addFavorite = useStore((st) => st.addFavorite);
  const removeFavorite = useStore((st) => st.removeFavorite);
  const setFavoriteRemoteId = useStore((st) => st.setFavoriteRemoteId);
  const addPriceAlert = useStore((st) => st.addPriceAlert);
  const addItem = useCartStore((st) => st.addItem);
  const { trackView, trackCartAdd, trackWishlistAdd } = useActivityTracker();

  const [priceCompare, setPriceCompare] = useState(null);
  const [priceHistory, setPriceHistory] = useState([]);
  const [priceTrust, setPriceTrust] = useState(null);
  const [loading, setLoading] = useState(false);
  const [showAlertForm, setShowAlertForm] = useState(false);
  const [alertTarget, setAlertTarget] = useState('');
  const [savingAlert, setSavingAlert] = useState(false);
  const [detail, setDetail] = useState(null);
  const [offerSelection, setOfferSelection] = useState({});
  const suppliedIdentity = normalizeProduct(suppliedProduct || {});
  const productId = suppliedIdentity.catalogProductId || suppliedIdentity.numericProductId;
  const baseProduct = detail && String(detail.id) === String(productId)
    ? { ...suppliedProduct, ...detail } : suppliedProduct || {};
  const chosen = getProductSelection(baseProduct, offerSelection);
  const product = selectProductOffer(baseProduct, offerSelection);
  const normalizedAlert = Boolean(baseProduct.public_product_id || Object.hasOwn(baseProduct, 'best_offer'));
  const alertQuote = isObservationReceiptEligible(chosen?.offer) ? chosen?.offer?.total_price : null;
  const alertQuotePrice = typeof alertQuote !== 'boolean' && Number.isFinite(Number(alertQuote)) && Number(alertQuote) > 0 ? Number(alertQuote) : null;
  useEffect(() => { setAlertTarget(''); setShowAlertForm(false); },
    [productId, chosen?.variant?.id, chosen?.listing?.id, chosen?.offer?.id]);
  useEffect(() => { setOfferSelection({}); }, [productId]);

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
    favoriteId,
    priceObservationOnly,
    hasDiscountMetadata,
    recordLabel,
    claimStatusLabel,
    unitPriceDisplay,
  } = normalized;
  const standardUnitPrice = normalized.standardUnitPrice ?? priceTrust?.standard_unit_price ?? null;
  const standardUnit = normalized.standardUnit ?? priceTrust?.standard_unit ?? null;

  // Determine mode: if explicitly set use that, otherwise auto-detect
  const mode = modeProp || (productId && !suppliedProduct?.martKey && !suppliedProduct?.source && suppliedProduct?.type !== 'hotdeal' ? 'product' : 'preview');

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
    let active = true;
    setDetail(null);
    setPriceCompare(null);
    setPriceHistory([]);
    setPriceTrust(null);
    setLoading(true);
    const fetchExtra = async () => {
      try {
        const response = await api.getJson(`/api/products/${encodeURIComponent(productId)}`).catch(() => null);
        const resolved = response?.data || response;
        if (!active) return;
        if (resolved && String(resolved.id) === String(productId)) setDetail(resolved);
        const [compRes, histRes, trustRes] = await Promise.allSettled([
          api.getJson(`/api/products/${encodeURIComponent(productId)}/price-compare`).catch(() => null),
          api.getJson(`/api/products/${encodeURIComponent(productId)}/price-history`).catch(() => null),
          api.getJson(`/api/products/${encodeURIComponent(productId)}/trust`).catch(() => null),
        ]);
        if (!active) return;
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
      if (active) setLoading(false);
    };
    fetchExtra();
    return () => { active = false; };
  }, [productId, mode]);

  const handleAddToCart = useCallback(async () => {
    try {
      await addItem(buildCartPayload(product));
      trackCartAdd(productId || favoriteId, name);
      addToast(`${name} 장바구니에 추가했어요 🛒`, 'success');
    } catch (error) {
      addToast(error?.message || '장바구니 저장에 실패했습니다. 다시 시도해주세요.', 'error');
    }
  }, [product, productId, favoriteId, name, addItem, trackCartAdd, addToast]);

  const handleToggleWishlist = useCallback(async () => {
    if (!isLoggedIn) {
      addToast('로그인이 필요합니다', 'warning');
      return;
    }

    if (isFav) {
      try {
        let remoteId = favoriteItems?.[favoriteId]?.remote_id;
        if (!remoteId) {
          const result = await api.getJson('/api/wishlist');
          const items = result?.data || result?.items || result || [];
          const saved = Array.isArray(items)
            ? items.find((item) => normalizeProduct(item).favoriteId === favoriteId)
            : null;
          remoteId = saved?.id || null;
        }
        if (!remoteId) {
          throw new Error('wishlist item is not synchronized');
        }
        await api.delete(`/api/wishlist/${remoteId}`);
        removeFavorite(favoriteId);
        addToast('찜 목록에서 제거했어요', 'info');
      } catch {
        addToast('찜 삭제에 실패했어요. 목록을 다시 불러온 뒤 시도해주세요.', 'error');
      }
      return;
    }

    try {
      const payload = buildWishlistPayload(product);
      const res = await api.post('/api/wishlist', payload);
      const json = await res.json();
      const remoteId = json?.data?.id || json?.id;
      if (!remoteId) {
        throw new Error('wishlist id missing from server response');
      }
      addFavorite(favoriteId, payload);
      setFavoriteRemoteId(favoriteId, remoteId);
      trackWishlistAdd(productId || favoriteId, name);
      addToast(`${name} 찜했어요 ❤️`, 'success');
    } catch {
      addToast('찜 추가에 실패했어요. 잠시 후 다시 시도해주세요.', 'error');
    }
  }, [isLoggedIn, isFav, product, productId, favoriteId, name, favoriteItems, addFavorite, removeFavorite, setFavoriteRemoteId, addToast, trackWishlistAdd]);

  const handleShare = useCallback(async () => {
    const quote = chosen?.offer;
    const receiptEligible = isObservationReceiptEligible(quote);
    const amount = normalizedAlert ? (receiptEligible ? quote?.total_price ?? quote?.listed_price : quote?.listed_price) : price;
    const known = amount != null && Number.isFinite(Number(amount)) && (!normalizedAlert || Number(amount) > 0);
    const moneyLabel = normalizedAlert ? (receiptEligible && quote?.total_price != null ? getOfferAmountLabel(quote) : '관측 표시 가격') : '표시 가격';
    const spec = chosen?.variant?.display_unit || unit;
    const text = [name, spec, `${moneyLabel} ${known ? getObservedOfferPriceText(quote, amount) : '미확인'}`,
      storeName && `판매처 ${storeName}`, quote?.availability_reason === 'expired' && '판매 기간 종료 · 과거 관측 가격',
      quote && getOfferConditionText(quote)].filter(Boolean).join(' · ');
    let url;
    try {
      url = normalizedAlert ? buildProductShareUrl(product, offerSelection) : sourceUrl || window.location.href;
    } catch (error) {
      addToast(error.message, 'warning');
      return;
    }
    if (navigator.share) {
      try {
        await navigator.share({ title: name, text, url });
      } catch { /* cancelled */ }
    } else {
      try {
        if (typeof navigator.clipboard?.writeText !== 'function') throw new Error('clipboard unavailable');
        await navigator.clipboard.writeText(`${text}\n${url}`);
        addToast('상품 링크를 복사했어요 📋', 'success');
      } catch {
        addToast('이 브라우저에서는 링크 복사를 사용할 수 없습니다', 'warning');
      }
    }
  }, [name, price, storeName, sourceUrl, unit, chosen, normalizedAlert, productId, product, offerSelection, addToast]);

  const handleSaveAlert = useCallback(async () => {
    if (!isLoggedIn) {
      addToast('가격 알림을 설정하려면 로그인이 필요합니다', 'warning');
      return;
    }
    if (!productId) {
      addToast('공개 카탈로그 상품만 가격 알림을 설정할 수 있습니다', 'warning');
      return;
    }
    if (normalizedAlert && (!chosen?.variant?.id || !chosen?.listing?.id || !chosen?.offer?.id)) {
      addToast('규격·판매처·거래를 먼저 선택해주세요', 'warning');
      return;
    }
    const target = Number(alertTarget);
    if (!Number.isInteger(target) || target <= 0) {
      addToast('목표 가격을 1원 이상의 정수로 입력해주세요', 'warning');
      return;
    }
    setSavingAlert(true);
    try {
      const response = await api.postJson('/api/users/me/alerts', {
        product_id: productId,
        target_price: target,
        ...(normalizedAlert ? { variant_id: chosen.variant.id, listing_id: chosen.listing.id, offer_id: chosen.offer.id } : {}),
      });
      addPriceAlert(response?.data || response);
      setShowAlertForm(false);
      addToast(`${fmt(target)}원 이하 가격 알림을 저장했습니다`, 'success');
    } catch (error) {
      addToast(error?.message || '가격 알림 저장에 실패했습니다', 'error');
    } finally {
      setSavingAlert(false);
    }
  }, [isLoggedIn, productId, alertTarget, normalizedAlert, chosen, addPriceAlert, addToast]);

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

  // Public normalized prices already include reviewed package/promotion math.
  // Display text is a label, never independent evidence of a sold quantity.
  const isNormalizedCatalog = Boolean(product.public_product_id || Object.hasOwn(product, 'best_offer'));
  const verifiedUnitPrice = getOfferUnitPrice(product.best_offer, chosen?.variant.quantity_components || []);
  const displayUnitPrice = isNormalizedCatalog
    ? (verifiedUnitPrice ? `${fmt(Math.round(verifiedUnitPrice.price))}원/${verifiedUnitPrice.unit}` : null)
    : (unitPriceDisplay || (standardUnitPrice && standardUnit
      ? `${fmt(Math.round(standardUnitPrice))}원/${standardUnit}` : null));
  const decision = buildProductDecision(product, { priceCompare, priceHistory, priceTrust });
  const {
    historySummary,
    comparableOffers,
    judgment,
    trustSignals,
    currentOffer,
  } = decision;
  const otherOffers = comparableOffers.filter((offer) => !offer.current);
  const comparableRows = comparableOffers.filter(offer => offer.comparisonValue != null);
  const bestValue = comparableRows.length > 1 ? Math.min(...comparableRows.map(offer => offer.comparisonValue)) : null;
  const selectedValue = comparableRows.find(offer => offer.current)?.comparisonValue;
  const currentIsBest = bestValue != null && selectedValue != null && selectedValue <= bestValue;
  const hasCheaperOffer = bestValue != null && selectedValue != null && bestValue < selectedValue;
  const offerFacts = (offer = {}, components = offer.quantity_components || []) => <small>
    {offer.availability_reason === 'expired' && <span> · 판매 기간 종료 · {isObservationReceiptEligible(offer) ? '과거 관측 거래' : '과거 표시 가격 관측'}</span>}
    {offer.current_eligible === false && offer.availability_reason !== 'expired' && <span> · 현재 비교 대상 아님</span>}
    {isObservationReceiptEligible(offer) && offer.total_price != null && <span> · {getOfferAmountLabel(offer)} {fmt(offer.total_price)}원</span>}
    <span> · {getOfferReceiptText(offer, { components })}</span>
    {offer.minimum_quantity != null && <span> · {!isObservationReceiptEligible(offer) && '출처 행사 규칙: '}최소 구매 {offer.minimum_quantity}</span>}
    {offer.promotion_condition && <span> · {!isObservationReceiptEligible(offer) && '출처 행사 규칙: '}{offer.promotion_condition}</span>}
    {getConditionalOfferConditionText(offer) && <span> · {getConditionalOfferConditionText(offer)}</span>}
    {offer.promotion_conditions?.buy_quantity != null && <span> · {!isObservationReceiptEligible(offer) && '출처 행사 규칙: '}구매 {offer.promotion_conditions.buy_quantity}</span>}
    {offer.promotion_conditions?.free_quantity != null && <span> · {!isObservationReceiptEligible(offer) && '출처 행사 규칙: '}추가 증정 {offer.promotion_conditions.free_quantity}</span>}
    {offer.membership_required === true && <span> · 회원 필요</span>}
    {offer.membership_required === false && <span> · 회원 제한 없음</span>}
    {offer.membership_required == null && <span> · 회원 조건 미확인</span>}
    {offer.coupon_required === true && <span> · 쿠폰 필요</span>}
    {offer.coupon_required === false && <span> · 쿠폰 필요 없음</span>}
    {offer.coupon_required == null && <span> · 쿠폰 조건 미확인</span>}
  </small>;
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

  if (!suppliedProduct) return null;
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
            {product.classification_warning && (
              <div className={s.classificationWarning}>분류 확인 필요</div>
            )}
            {['selection_context_missing', 'selection_required'].includes(product.comparison_reason) && !chosen && (
              <p>저장된 규격·판매처 선택이 없습니다. 아래에서 원하는 거래를 직접 선택하세요.</p>
            )}

            <div className={s.priceBlock}>
              <div className={s.priceMain}>
                <span className={s.salePrice}>{isNormalizedCatalog && (price <= 0 || !isObservationReceiptEligible(chosen?.offer)) ? '비교 가격 미확인' : `${fmt(price)}원`}</span>
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
            {isNormalizedCatalog && product.variants?.length > 0 && (
              <div className={s.metaRow}>
                <span className={s.metaLabel}>판매 규격</span>
                <div>
                  {product.variants.map((variant) => (
                    <div key={variant.id}>
                      <button type="button" aria-label={`규격 선택: ${variant.name || variant.display_unit || '규격 미확인'}`} aria-pressed={chosen?.variant.id === variant.id} onClick={() => {
                        const candidate = getVariantBestOffer(variant);
                        const listing = variant.listings?.find(row => row.id === candidate?.listingId) || variant.listings?.[0];
                        setOfferSelection({ variantId: variant.id, listingId: listing?.id, offerId: listing?.offers?.[0]?.id });
                      }}><strong>{variant.name || variant.display_unit || '규격 미확인'}</strong></button>
                      {variant.package_quantity == null && <small> · 판매 수량 미확인</small>}
                      {(variant.listings || []).map((listing) => {
                        const offer = listing.offers?.[0];
                        return <div key={listing.id}>
                          <button type="button" aria-label={`판매처 선택: ${listing.source} · ${listing.title}`} aria-pressed={chosen?.listing.id === listing.id} onClick={() => setOfferSelection({ variantId: variant.id, listingId: listing.id, offerId: offer?.id })}>{listing.source} · {listing.title}</button>
                          {offer?.listed_price != null && <span> · 표시 가격 {getObservedOfferPriceText(offer)}</span>}
                          {offer && offer.comparable_price == null && <small> · 비교 조건 미확인</small>}
                          {offer && offerFacts(offer, variant.quantity_components || [])}
                        </div>;
                      })}
                    </div>
                  ))}
                </div>
              </div>
            )}
            {chosen?.variant.quantity_components?.length > 0 && <div aria-label="선택 규격 구성">
              <strong>선택 규격 구성 · 구성별 수량</strong>
              {getQuantityComponentTexts(chosen.variant.quantity_components).map((text, index) => <div key={index}>{text}</div>)}
              <small>구성품의 내용량·수량을 개별 표시합니다. 전체 구성의 정확한 단위가는 표시하지 않습니다.</small>
            </div>}
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
                <small>{currentOffer.conditionText || eventType || '행사 조건 미확인'}</small>
              </div>
              <div>
                <span>다음 행동</span>
                <strong>{currentIsBest ? '현재 선택 확인' : hasCheaperOffer ? '비교 기준·조건 확인' : '가격·조건 확인'}</strong>
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
                {isNormalizedCatalog && <p>선택 규격·같은 수령 및 행사 조건의 관측 통계 · {historySummary.comparableCount}건</p>}
                <div className={s.historySummary}>
                  <div><span>최저</span><strong>{historySummary.min ? `${fmt(historySummary.min)}원` : '-'}</strong></div>
                  <div><span>평균</span><strong>{historySummary.avg ? `${fmt(historySummary.avg)}원` : '-'}</strong></div>
                  <div><span>최고</span><strong>{historySummary.max ? `${fmt(historySummary.max)}원` : '-'}</strong></div>
                  <div><span>최근</span><strong>{historySummary.latest ? getObservedOfferPriceText(historySummary.history.at(-1), historySummary.latest) : '미확인'}</strong></div>
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
                          {isNormalizedCatalog && (!isObservationReceiptEligible(p) || !(p.comparablePrice > 0) || (p.offerState && p.offerState !== 'active')) && <small>비교 조건 미확인</small>}
                          <span className={s.barPrice}>{isNormalizedCatalog ? getObservedOfferPriceText(p, p.price) : fmt(p.price)}</span>
                          {isNormalizedCatalog && <small>{getOfferConditionText(p)}{isObservationReceiptEligible(p) && p.total_price > 0 ? ` · ${getOfferAmountLabel(p, '실제 거래 금액')} ${fmt(p.total_price)}원` : ''}</small>}
                        </div>
                      );
                    })}
                  </div>
                )}
              </>
            ) : (
              <p className={s.noData}>{isNormalizedCatalog
                ? '이 화면에 연결된 조회 기간의 선택 규격 관측 이력 미확인 · 전체 기간 이력·통계는 미확인입니다.'
                : '가격 이력이 아직 없습니다. 찜해두면 이후 가격 변동을 추적할 수 있어요.'}</p>
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
                    {offer.unitPrice != null && offer.unit && <small>{fmt(offer.unitPrice)}원/{offer.unit}</small>}
                    {offerFacts({ total_price: offer.totalPrice, total_quantity: offer.totalQuantity, quantity_unit: offer.quantityUnit, quantity_basis: offer.quantityBasis, scalar_basis: offer.scalarBasis, received_package_count_scope: offer.receivedPackageCountScope, quantity_components: offer.quantityComponents, pricing_measure_quantity: offer.pricingMeasureQuantity, pricing_measure_unit: offer.pricingMeasureUnit, pricing_measure_basis: offer.pricingMeasureBasis, minimum_quantity: offer.minimumQuantity, received_package_count: offer.receivedPackageCount, promotion_condition: offer.promotionCondition, promotion_conditions: offer.promotionConditions, membership_required: offer.membershipRequired, coupon_required: offer.couponRequired })}
                    {selectedValue != null && offer.comparisonValue != null && offer.comparisonValue < selectedValue && <span className={s.osCheaper}>{offer.comparisonBasis} 기준 표시 조건에서 더 저렴</span>}
                    {bestValue != null && offer.comparisonValue === bestValue && <span className={s.osBest}>{offer.comparisonBasis} 기준 표시 조건의 관측 최저</span>}
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
        {showAlertForm && (
          <div className={s.alertForm}>
            {normalizedAlert && <>
              <strong>{chosen ? `${chosen.variant.display_unit || chosen.variant.name || '규격 미확인'} · ${chosen.listing.source || '판매처 미확인'}` : '규격·판매처·거래 선택 필요'}</strong>
              <small>{chosen ? getOfferConditionText(chosen.offer) : '선택한 거래를 기준으로 저장합니다.'}</small>
              <small>{alertQuotePrice != null ? `선택 거래 표시 금액 ${fmt(alertQuotePrice)}원` : '선택 거래 금액 미확인'} · 수령 구성이나 이용 조건이 확인되지 않으면 목표 도달 판정을 보류합니다.</small>
            </>}
            <label htmlFor="product-alert-target">목표 가격</label>
            <input
              id="product-alert-target"
              type="number"
              min="1"
              step="1"
              value={alertTarget}
              onChange={(event) => setAlertTarget(event.target.value)}
              placeholder={(normalizedAlert ? alertQuotePrice : price) > 0 ? String(Math.round(normalizedAlert ? alertQuotePrice : price)) : '예: 5000'}
            />
            <button type="button" onClick={handleSaveAlert} disabled={savingAlert || (normalizedAlert && !chosen)}>
              {savingAlert ? '저장 중' : '저장'}
            </button>
          </div>
        )}
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
          <button
            className={s.actionIcon}
            onClick={() => {
              const quote = normalizedAlert ? alertQuotePrice : price;
              setAlertTarget((current) => current || (quote > 0 ? String(Math.round(quote)) : ''));
              setShowAlertForm((current) => !current);
            }}
            aria-label="가격 알림 설정"
          >
            <BellRing size={18} />
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}
