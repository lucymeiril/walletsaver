import { useState, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate } from 'react-router-dom';
import { X, Plus, Minus as MinusIcon, Trash2, ShoppingCart, Zap, Package } from 'lucide-react';
import useStore from '../../stores/appStore';
import useCartStore from '../../stores/cartStore';
import useModalStore from '../../stores/modalStore';
import SafeImage from './SafeImage';
import s from './ShoppingListPanel.module.css';

const fmt = (n) => n?.toLocaleString('ko-KR') ?? '0';

const STORE_ICONS = {
  emart: '🟡', homeplus: '🟠', lotte: '🔴', costco: '🔵',
};

const CATEGORY_ICONS = {
  식품: '🥩', 과일: '🍎', 채소: '🥬', 수산: '🐟', 음료: '🥤',
  간식: '🍪', 생활: '🧴', 가전: '📱', 패션: '👗',
};

export default function ShoppingListPanel() {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const { addToast } = useStore();
  const { items, updateQuantity, removeItem, clearCart } = useCartStore();
  const { openProductDetailModal } = useModalStore();

  const toggle = useCallback(() => setOpen((v) => !v), []);

  useEffect(() => {
    if (!open) return;
    const handleKey = (e) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('keydown', handleKey);
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', handleKey);
      document.body.style.overflow = '';
    };
  }, [open]);

  const totalPrice = items.reduce((sum, i) => sum + (i.price || 0) * (i.quantity || 1), 0);
  const totalSavings = items.reduce((sum, i) => {
    const orig = i.original_price || 0;
    const sale = i.price || 0;
    if (orig > sale && sale > 0) return sum + (orig - sale) * (i.quantity || 1);
    return sum;
  }, 0);
  const totalCount = items.reduce((sum, i) => sum + (i.quantity || 1), 0);

  const handleClear = () => {
    clearCart();
    addToast('장바구니를 비웠습니다', 'info');
  };

  const handleRemove = (item) => {
    const id = item.cart_id || item.id || item.product_id;
    removeItem(id);
  };

  const handleQuantity = (item, delta) => {
    const id = item.cart_id || item.id || item.product_id;
    const newQty = (item.quantity || 1) + delta;
    updateQuantity(id, newQty);
  };

  const handleItemClick = (item) => {
    openProductDetailModal(item);
    setOpen(false);
  };

  return (
    <>
      {/* FAB */}
      <button className={s.fab} onClick={toggle} aria-label="장바구니 열기">
        🛒
        {items.length > 0 && (
          <span className={s.badge}>{totalCount}</span>
        )}
      </button>

      {/* Panel */}
      {open && createPortal(
        <>
          <div className={s.overlay} onClick={() => setOpen(false)} />
          <aside className={s.panel} role="dialog" aria-label="장바구니">
            <div className={s.panelHeader}>
              <div className={s.panelTitle}>
                🛒 장바구니
                <span className={s.panelCount}>{totalCount}개</span>
              </div>
              <button className={s.closeBtn} onClick={() => setOpen(false)} aria-label="닫기">
                <X size={20} />
              </button>
            </div>

            {items.length === 0 ? (
              <div className={s.empty}>
                <span className={s.emptyIcon}>🛒</span>
                <span className={s.emptyText}>장바구니가 비어있어요</span>
                <button
                  className={s.emptyAction}
                  onClick={() => { setOpen(false); navigate('/hotdeal'); }}
                >
                  <Zap size={14} /> 핫딜 찾아보기
                </button>
              </div>
            ) : (
              <>
                <div className={s.itemList}>
                  {items.map((item) => {
                    const id = item.cart_id || item.id || item.product_id || item.name;
                    const storeIcon = STORE_ICONS[item.store_key] || '🏪';
                    const catIcon = CATEGORY_ICONS[item.category] || '';
                    const hasOrigPrice = item.original_price > 0 && item.original_price > item.price;
                    const savingPct = hasOrigPrice
                      ? Math.round((1 - item.price / item.original_price) * 100)
                      : 0;

                    return (
                      <div key={id} className={s.item}>
                        <div className={s.itemClickArea} onClick={() => handleItemClick(item)}>
                          {/* Image */}
                          <div className={s.itemImageWrap}>
                            {item.image ? (
                              <SafeImage src={item.image} alt={item.name} className={s.itemImage} />
                            ) : (
                              <div className={s.itemImagePlaceholder}>
                                {catIcon || <Package size={20} />}
                              </div>
                            )}
                          </div>

                          {/* Info */}
                          <div className={s.itemInfo}>
                            <div className={s.itemName}>{item.name}</div>
                            {item.store_name && (
                              <div className={s.itemStore}>
                                <span>{storeIcon}</span> {item.store_name}
                              </div>
                            )}
                            {item.category && (
                              <span className={s.itemCategory}>{catIcon} {item.category}</span>
                            )}
                            <div className={s.itemPrices}>
                              <span className={s.itemSalePrice}>{fmt(item.price)}원</span>
                              {hasOrigPrice && (
                                <>
                                  <span className={s.itemOrigPrice}>{fmt(item.original_price)}원</span>
                                  <span className={s.itemDiscount}>-{savingPct}%</span>
                                </>
                              )}
                            </div>
                          </div>
                        </div>

                        {/* Quantity + remove */}
                        <div className={s.itemActions}>
                          <div className={s.qtyControls}>
                            <button
                              className={s.qtyBtn}
                              onClick={() => handleQuantity(item, -1)}
                              aria-label="수량 줄이기"
                            >
                              <MinusIcon size={14} />
                            </button>
                            <span className={s.qtyValue}>{item.quantity || 1}</span>
                            <button
                              className={s.qtyBtn}
                              onClick={() => handleQuantity(item, 1)}
                              aria-label="수량 늘리기"
                            >
                              <Plus size={14} />
                            </button>
                          </div>
                          <span className={s.itemTotalPrice}>
                            {fmt((item.price || 0) * (item.quantity || 1))}원
                          </span>
                          <button
                            className={s.removeBtn}
                            onClick={() => handleRemove(item)}
                            aria-label={`${item.name} 삭제`}
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>

                {/* Summary footer */}
                <div className={s.panelFooter}>
                  {totalSavings > 0 && (
                    <div className={s.savingsRow}>
                      <span className={s.savingsLabel}>💰 총 절약</span>
                      <span className={s.savingsValue}>-{fmt(totalSavings)}원</span>
                    </div>
                  )}
                  <div className={s.totalRow}>
                    <span className={s.totalLabel}>합계 ({totalCount}개)</span>
                    <span className={s.totalPrice}>{fmt(totalPrice)}원</span>
                  </div>
                  <button className={s.clearBtn} onClick={handleClear}>
                    장바구니 비우기
                  </button>
                </div>
              </>
            )}
          </aside>
        </>,
        document.body,
      )}
    </>
  );
}
