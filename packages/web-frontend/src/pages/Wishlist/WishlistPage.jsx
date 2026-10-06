/**
 * 찜 목록 페이지 — 위시리스트 관리, 가격 추적, 목표가 설정
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Heart, Trash2, TrendingUp, TrendingDown, Minus,
  Target, ShoppingCart, AlertCircle, ArrowRight,
} from 'lucide-react';
import useStore from '../../stores/appStore';
import useCartStore from '../../stores/cartStore';
import { api } from '../../services/api';
import SafeImage from '../../components/common/SafeImage';
import ProductDetailModal from '../../components/ProductDetailModal';
import { fmt } from '../../utils/helpers';
import { asNumericId } from '../../utils/productActions';
import { getSavedOfferConditionText, getSavedReceiptHoldText, isSavedReceiptValid, getWishlistHoldText } from '../../utils/productDecision';
import s from './WishlistPage.module.css';

const TREND_ICONS = {
  up: { icon: TrendingUp, color: '#ef4444', label: '상승' },
  down: { icon: TrendingDown, color: '#22c55e', label: '하락' },
  stable: { icon: Minus, color: '#94a3b8', label: '유지' },
};

function cartQuote(item) {
  const selected = item.variant_id || item.listing_id || item.offer_id;
  const normalized = item.product_id != null && asNumericId(item.product_id) == null;
  if (selected || normalized) {
    const context = item.current_offer_context;
    return isSavedReceiptValid(item) && item.variant_id && item.listing_id && item.current_offer_id
      && context?.current_eligible === true && !item.comparison_reason
      && Number(item.current_price) > 0 && Number(context.total_price) > 0
      ? { price: Number(context.total_price), offer_id: item.current_offer_id, context } : null;
  }
  const price = item.current_price !== undefined ? item.current_price : item.item_price;
  return price != null && Number.isFinite(Number(price)) && Number(price) >= 0
    ? { price: Number(price) } : null;
}

function detailSelection(item) {
  return { ...item, selected_variant_id: item.variant_id, selected_listing_id: item.listing_id,
    selected_offer_id: item.current_offer_id || item.offer_id };
}

export default function WishlistPage() {
  const navigate = useNavigate();
  const {
    isLoggedIn,
    favoriteItems,
    removeFavorite,
    hydrateFavorites,
    addToast,
  } = useStore();
  const addCartItem = useCartStore((st) => st.addItem);

  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [selectedProduct, setSelectedProduct] = useState(null);
  const [editingTarget, setEditingTarget] = useState(null);
  const [targetInput, setTargetInput] = useState('');

  useEffect(() => {
    if (!isLoggedIn) {
      addToast('로그인이 필요합니다', 'warning');
      navigate('/');
      return;
    }
    fetchWishlist();
  }, [isLoggedIn]); // eslint-disable-line react-hooks/exhaustive-deps

  const fetchWishlist = useCallback(async () => {
    setLoading(true);
    setLoadError(false);
    try {
      const data = await api.getJson('/api/wishlist');
      const rawItems = data.data || data.items || data || [];
      const wishItems = Array.isArray(rawItems) ? rawItems.map((item) => ({
        ...item,
        product_name: item.item_name || item.product_name || item.name || '상품',
        image: item.item_image_url || item.image || '',
        price_at_add: item.price_at_add !== undefined ? item.price_at_add : (item.item_price ?? null),
        current_price: item.current_price !== undefined ? item.current_price : (item.item_price ?? null),
      })) : [];
      hydrateFavorites(wishItems);
      setItems(wishItems);
    } catch {
      hydrateFavorites([]);
      setItems([]);
      setLoadError(true);
      addToast('찜 목록을 DB에서 불러오지 못했습니다.', 'error');
    } finally {
      setLoading(false);
    }
  }, [hydrateFavorites, addToast]);

  const handleRemove = async (item) => {
    const itemId = item.id;
    try {
      await api.delete(`/api/wishlist/${itemId}`);
      const match = Object.entries(favoriteItems || {}).find(([, fav]) => fav.remote_id === itemId);
      if (match) removeFavorite(match[0]);
      setItems((prev) => prev.filter((row) => row.id !== itemId));
      addToast('찜 목록에서 제거했어요', 'info');
    } catch {
      addToast('찜 삭제에 실패했습니다. 다시 시도해주세요.', 'error');
    }
  };

  const handleSetTarget = async (item) => {
    const price = parseInt(targetInput, 10);
    if (isNaN(price) || price <= 0) {
      addToast('올바른 가격을 입력해주세요', 'error');
      return;
    }
    const itemId = item.id;
    try {
      await api.put(`/api/wishlist/${itemId}`, { target_price: price, notify_on_drop: true });
      setItems((prev) =>
        prev.map((row) =>
          row.id === itemId ? { ...row, target_price: price, notify_on_drop: true } : row
        )
      );
      setEditingTarget(null);
      addToast('목표가를 설정했어요 🎯', 'success');
    } catch {
      addToast('목표가 저장에 실패했습니다. 다시 시도해주세요.', 'error');
    }
  };

  const handleAddToCart = async (item) => {
    try {
      const quote = cartQuote(item);
      if (!quote) throw new Error('선택한 거래의 현재 금액과 이용 조건을 확인한 뒤 담을 수 있습니다');
      await addCartItem({
        ...(item.product_id ? { product_id: item.product_id } : {}),
        ...(quote.offer_id ? { variant_id: item.variant_id, listing_id: item.listing_id,
          offer_id: quote.offer_id, offer_context: quote.context } : {}),
        name: item.product_name || item.item_name || item.name,
        price: quote.price,
        item_price: quote.price,
        quantity: 1,
        store_name: item.store_name || '',
        source_url: item.source_url || '',
        source_title: quote.context?.source_title || item.source_title || '',
        unit: quote.context?.display_unit || item.unit || '',
        image: item.image || item.item_image_url || '',
        category: item.category || '',
      });
      addToast(`${item.product_name || item.item_name || item.name} 장바구니에 추가했어요`, 'success');
    } catch {
      addToast('장바구니 저장에 실패했습니다. 다시 시도해주세요.', 'error');
    }
  };

  const getTrend = (item) => {
    if (item.price_at_add == null || item.current_price == null) return 'stable';
    if (item.current_price > item.price_at_add) return 'up';
    if (item.current_price < item.price_at_add) return 'down';
    return 'stable';
  };

  const getPriceDelta = (item) => {
    if (item.price_at_add == null || item.current_price == null) return null;
    const delta = item.current_price - item.price_at_add;
    if (delta === 0) return null;
    return delta;
  };

  if (!isLoggedIn) return null;

  return (
    <div className={s.page}>
      <div className={s.container}>
        <div className={s.header}>
          <h1 className={s.title}>
            <Heart size={24} /> 찜 목록
          </h1>
          <span className={s.count}>{items.length}개</span>
        </div>

        {loading ? (
          <div className={s.loadingState}>로딩 중...</div>
        ) : loadError ? (
          <div className={s.emptyState}>
            <AlertCircle size={48} />
            <h2 className={s.emptyTitle}>찜 목록을 불러오지 못했어요</h2>
            <p className={s.emptyDesc}>로컬 가짜 목록으로 대신 보여주지 않고 DB 연결을 다시 확인합니다.</p>
            <button className={s.emptyAction} onClick={fetchWishlist}>
              다시 불러오기
            </button>
          </div>
        ) : items.length === 0 ? (
          <div className={s.emptyState}>
            <Heart size={48} />
            <h2 className={s.emptyTitle}>아직 찜한 상품이 없어요</h2>
            <p className={s.emptyDesc}>관심 있는 상품을 찜하면 가격 변동을 추적할 수 있어요</p>
            <button className={s.emptyAction} onClick={() => navigate('/mart')}>
              🏪 마트 할인 둘러보기 <ArrowRight size={16} />
            </button>
          </div>
        ) : (
          <div className={s.list}>
            {items.map((item) => {
              const pid = item.id;
              const receiptValid = isSavedReceiptValid(item);
              const currentPrice = receiptValid ? item.current_price : null;
              const trend = getTrend({ ...item, current_price: currentPrice });
              const delta = getPriceDelta({ ...item, current_price: currentPrice });
              const TrendIcon = TREND_ICONS[trend].icon;

              return (
                <div key={pid} className={s.card}>
                  <div
                    className={s.cardMain}
                    onClick={() => setSelectedProduct(detailSelection(item))}
                    role="button"
                    tabIndex={0}
                  >
                    <div className={s.imageWrap}>
                      {item.image ? (
                        <SafeImage src={item.image} alt={item.product_name} className={s.image} />
                      ) : (
                        <div className={s.imagePlaceholder}>❤️</div>
                      )}
                    </div>

                    <div className={s.info}>
                      <div className={s.itemName}>{item.product_name || item.name || '상품'}</div>
                      {item.store_name && (
                        <div className={s.storeName}>🏪 {item.store_name}</div>
                      )}
                      {item.offer_context && (
                        <div className={s.storeName}>
                          {item.offer_context.display_unit || item.offer_context.variant_name || '규격 미확인'}
                          <div>저장한 거래 조건 · {getSavedOfferConditionText(item)}</div>
                        </div>
                      )}
                      {getSavedReceiptHoldText(item) && <div className={s.storeName}>{getSavedReceiptHoldText(item)}</div>}
                      {(item.unit || item.source_type || item.period) && (
                        <div className={s.storeName}>
                          {[item.source_type, item.unit, item.period].filter(Boolean).join(' · ')}
                        </div>
                      )}

                      <div className={s.priceRow}>
                        <div className={s.priceGroup}>
                          <span className={s.priceLabel}>찜할 때</span>
                          <span className={s.priceValue}>
                            {item.price_at_add != null ? `${fmt(item.price_at_add)}원` : '미확인'}
                          </span>
                        </div>
                        <span className={s.priceArrow}>→</span>
                        <div className={s.priceGroup}>
                          <span className={s.priceLabel}>비교 가능한 현재가</span>
                          <span className={`${s.priceValue} ${s.currentPrice}`}>
                            {currentPrice != null ? `${fmt(currentPrice)}원` : '미확인'}
                          </span>
                        </div>
                      </div>
                      {item.quoted_price > 0 && (
                        <div className={s.storeName}>선택한 판매처 관측 가격 · {fmt(item.quoted_price)}원</div>
                      )}
                      {item.current_offer_context && (
                        <div className={s.storeName}>최신 관측 거래 조건 · {getSavedOfferConditionText(item, item.current_offer_context)}</div>
                      )}
                      {item.current_offer_context?.availability_reason === 'expired' && (
                        <div className={s.storeName}>판매 기간 종료 · 과거 관측 가격
                          {item.current_offer_context.valid_to ? ` · 종료 ${item.current_offer_context.valid_to}` : ''}
                        </div>
                      )}
                      {item.current_offer_context?.crawled_at && (
                        <div className={s.storeName}>관측 시각 · {item.current_offer_context.crawled_at}</div>
                      )}
                      {currentPrice == null && (
                        <div className={s.storeName}>판정 보류 · {getWishlistHoldText(item.comparison_reason)}</div>
                      )}

                      {delta !== null && (
                        <div className={`${s.delta} ${delta < 0 ? s.deltaDown : s.deltaUp}`}>
                          <TrendIcon size={14} />
                          {delta > 0 ? '+' : ''}{fmt(delta)}원
                          ({trend === 'up' ? '상승' : '하락'})
                        </div>
                      )}

                      {item.target_price && (
                        <div className={s.targetRow}>
                          <Target size={12} />
                          <span>목표가: {fmt(item.target_price)}원</span>
                          {currentPrice != null && !item.comparison_reason && currentPrice <= item.target_price && (
                            <span className={s.targetReached}>🎉 목표 달성!</span>
                          )}
                        </div>
                      )}
                    </div>
                  </div>

                  <div className={s.cardActions}>
                    {editingTarget === pid ? (
                      <div className={s.targetEdit}>
                        <input
                          className={s.targetInput}
                          type="number"
                          value={targetInput}
                          onChange={(e) => setTargetInput(e.target.value)}
                          placeholder="목표 가격"
                          autoFocus
                        />
                        <button
                          className={s.targetSave}
                          onClick={() => handleSetTarget(item)}
                        >
                          설정
                        </button>
                        <button
                          className={s.targetCancel}
                          onClick={() => setEditingTarget(null)}
                        >
                          취소
                        </button>
                      </div>
                    ) : (
                      <button
                        className={s.actionBtn}
                        onClick={() => {
                          setEditingTarget(pid);
                          setTargetInput(item.target_price?.toString() || '');
                        }}
                        title="이 가격 이하면 알려줘"
                      >
                        <Target size={14} /> 목표가
                      </button>
                    )}
                    <button
                      className={s.actionBtn}
                      disabled={!cartQuote(item)}
                      title={!cartQuote(item) ? '현재 거래 금액과 이용 조건 미확인' : '선택한 현재 거래 담기'}
                      onClick={() => handleAddToCart(item)}
                    >
                      <ShoppingCart size={14} /> 담기
                    </button>
                    <button
                      className={`${s.actionBtn} ${s.removeBtn}`}
                      onClick={() => handleRemove(item)}
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {selectedProduct && (
        <ProductDetailModal
          product={selectedProduct}
          mode={selectedProduct.product_id ? 'product' : 'preview'}
          onClose={() => setSelectedProduct(null)}
        />
      )}
    </div>
  );
}
