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
import s from './WishlistPage.module.css';

const TREND_ICONS = {
  up: { icon: TrendingUp, color: '#ef4444', label: '상승' },
  down: { icon: TrendingDown, color: '#22c55e', label: '하락' },
  stable: { icon: Minus, color: '#94a3b8', label: '유지' },
};

export default function WishlistPage() {
  const navigate = useNavigate();
  const { isLoggedIn, favorites, removeFavorite, addToast } = useStore();
  const addCartItem = useCartStore((st) => st.addItem);

  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
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
    try {
      const data = await api.getJson('/api/wishlist');
      const rawItems = data.data || data.items || data || [];
      const wishItems = Array.isArray(rawItems) ? rawItems.map((item) => ({
        ...item,
        product_name: item.item_name || item.product_name || item.name || '상품',
        image: item.item_image_url || item.image || '',
        price_at_add: item.price_at_add || item.item_price || 0,
        current_price: item.current_price || item.item_price || 0,
      })) : [];
      setItems(wishItems);
    } catch {
      setItems(
        favorites.map((id) => ({
          id: id,
          product_name: `상품 ${id}`,
          price_at_add: 0,
          current_price: 0,
        }))
      );
    }
    setLoading(false);
  }, [favorites]);

  const handleRemove = async (item) => {
    const itemId = item.id;
    const pid = item.product_id || item.id;
    removeFavorite(pid);
    setItems((prev) => prev.filter((i) => i.id !== itemId));
    try {
      await api.delete(`/api/wishlist/${itemId}`);
    } catch { /* ignore */ }
    addToast('찜 목록에서 제거했어요', 'info');
  };

  const handleSetTarget = async (item) => {
    const price = parseInt(targetInput, 10);
    if (isNaN(price) || price <= 0) {
      addToast('올바른 가격을 입력해주세요', 'error');
      return;
    }
    const itemId = item.id;
    setItems((prev) =>
      prev.map((i) =>
        i.id === itemId ? { ...i, target_price: price } : i
      )
    );
    setEditingTarget(null);
    try {
      await api.put(`/api/wishlist/${itemId}`, { target_price: price, notify_on_drop: true });
      addToast('목표가를 설정했어요 🎯', 'success');
    } catch { /* ignore */ }
  };

  const handleAddToCart = (item) => {
    addCartItem({
      product_id: item.product_id || item.id,
      name: item.product_name || item.item_name || item.name,
      price: item.current_price || item.item_price || item.price_at_add,
      store_name: item.store_name || '',
      image: item.image || item.item_image_url || '',
    });
    addToast(`${item.product_name || item.item_name || item.name} 장바구니에 추가했어요`, 'success');
  };

  const getTrend = (item) => {
    if (!item.price_at_add || !item.current_price) return 'stable';
    if (item.current_price > item.price_at_add) return 'up';
    if (item.current_price < item.price_at_add) return 'down';
    return 'stable';
  };

  const getPriceDelta = (item) => {
    if (!item.price_at_add || !item.current_price) return null;
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
              const trend = getTrend(item);
              const delta = getPriceDelta(item);
              const TrendIcon = TREND_ICONS[trend].icon;

              return (
                <div key={pid} className={s.card}>
                  <div
                    className={s.cardMain}
                    onClick={() => setSelectedProduct(item)}
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

                      <div className={s.priceRow}>
                        <div className={s.priceGroup}>
                          <span className={s.priceLabel}>찜할 때</span>
                          <span className={s.priceValue}>
                            {item.price_at_add ? `${fmt(item.price_at_add)}원` : '-'}
                          </span>
                        </div>
                        <span className={s.priceArrow}>→</span>
                        <div className={s.priceGroup}>
                          <span className={s.priceLabel}>현재가</span>
                          <span className={`${s.priceValue} ${s.currentPrice}`}>
                            {item.current_price ? `${fmt(item.current_price)}원` : '-'}
                          </span>
                        </div>
                      </div>

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
                          {item.current_price && item.current_price <= item.target_price && (
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
          onClose={() => setSelectedProduct(null)}
        />
      )}
    </div>
  );
}
