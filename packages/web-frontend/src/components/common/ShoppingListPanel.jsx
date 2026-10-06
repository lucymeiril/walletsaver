import { useState, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate } from 'react-router-dom';
import { X, Plus, Minus as MinusIcon, Trash2, Zap, Package } from 'lucide-react';
import useStore from '../../stores/appStore';
import useCartStore from '../../stores/cartStore';
import useModalStore from '../../stores/modalStore';
import SafeImage from './SafeImage';
import { getSavedOfferConditionText, getSavedReceiptHoldText, getCartQuotePresentation, getOfferUnitPrice } from '../../utils/productDecision';
import s from './ShoppingListPanel.module.css';

const fmt = (n) => n?.toLocaleString('ko-KR') ?? '0';

const STORE_ICONS = {
  emart: '🟡', homeplus: '🟠', lotte: '🔴', costco: '🔵',
};

const CATEGORY_ICONS = {
  식품: '🥩', 과일: '🍎', 채소: '🥬', 수산: '🐟', 음료: '🥤',
  간식: '🍪', 생활: '🧴', 가전: '📱', 패션: '👗',
};

function knownPrice(item) {
  return item.price_known !== false && item.price != null && item.price !== ''
    && Number.isFinite(Number(item.price)) && Number(item.price) >= 0
    && (!(item.product_id || item.product_catalog_id) || Number(item.price) > 0);
}

function SelectedQuote({ item }) {
  if (!item.variant_id && !item.listing_id && !item.offer_id) return item.unit ? <div className={s.itemSpec}>규격 {item.unit}</div> : null;
  const quote = item.offer_context || item.quoted_offer || {};
  const presentation = getCartQuotePresentation(item);
  const measuredRate = presentation.canDisplayUnitPrice
    && ['reviewed_homogeneous_contents', 'reviewed_declared_linear_contents'].includes(quote.quantity_basis)
    ? getOfferUnitPrice(quote, quote.quantity_components || []) : null;
  const receiptHold = getSavedReceiptHoldText(item);
  const spec = quote.display_unit || item.unit;
  const sourceTitle = quote.source_title || item.source_title;
  return <div className={s.itemSpec}>
    <div>선택 규격 {quote.variant_name || spec || '미확인'}</div>
    {quote.variant_name && spec && <div>{spec}</div>}
    {sourceTitle && <div>판매 상품 {sourceTitle}</div>}
    <div>{getSavedOfferConditionText(item, quote)}</div>
    {presentation.observedReceipt && <div>{presentation.observedReceipt} · 과거 관측 구성</div>}
    {presentation.statusText && <div>{presentation.statusText}</div>}
    {receiptHold && <div>{receiptHold}</div>}
    {measuredRate && ['100g', '100ml', '100m'].includes(measuredRate.unit)
      && <div>관측 단위가 · {measuredRate.unit}당 {fmt(measuredRate.price)}원</div>}
    {presentation.canDisplayUnitPrice && quote.total_quantity > 0 && quote.quantity_unit === 'g' && quote.per_100g > 0 && <div>100g당 {fmt(quote.per_100g)}원</div>}
    {presentation.canDisplayUnitPrice && quote.total_quantity > 0 && quote.quantity_unit === 'ml' && quote.per_100ml > 0 && <div>100ml당 {fmt(quote.per_100ml)}원</div>}
    {presentation.canDisplayUnitPrice && quote.total_quantity > 0 && quote.quantity_unit === 'ea' && quote.per_item > 0 && <div>개당 {fmt(quote.per_item)}원</div>}
    {quote.comparable_price == null && <div>비교 가격 미확인 · 저장한 관측 금액</div>}
    {quote.crawled_at && <div>가격 관측 {quote.crawled_at}</div>}
  </div>;
}

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

  const totalPrice = items.reduce((sum, i) => sum + (knownPrice(i) ? Number(i.price) * (i.quantity || 1) : 0), 0);
  const unknownPriceCount = items.filter(item => !knownPrice(item)).length;
  const unconfirmedPurchase = items.some(item => {
    const presentation = getCartQuotePresentation(item);
    return presentation.selected && !presentation.confirmedPurchase;
  });
  const totalSavings = items.reduce((sum, i) => {
    const orig = i.original_price || 0;
    const sale = i.price || 0;
    if (!i.offer_id && knownPrice(i) && orig > sale && sale > 0) return sum + (orig - sale) * (i.quantity || 1);
    return sum;
  }, 0);
  const totalCount = items.reduce((sum, i) => sum + (i.quantity || 1), 0);

  const handleClear = async () => {
    try {
      await clearCart();
      addToast('장바구니를 비웠습니다', 'info');
    } catch (err) {
      addToast(err?.message || '장바구니 비우기에 실패했습니다', 'error');
    }
  };

  const handleRemove = async (item) => {
    const id = item.cart_id || item.id || item.product_id;
    try {
      await removeItem(id);
    } catch (err) {
      addToast(err?.message || '장바구니 항목 삭제에 실패했습니다', 'error');
    }
  };

  const handleQuantity = async (item, delta) => {
    const id = item.cart_id || item.id || item.product_id;
    const newQty = (item.quantity || 1) + delta;
    try {
      await updateQuantity(id, newQty);
    } catch (err) {
      addToast(err?.message || '수량 변경에 실패했습니다', 'error');
    }
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
                <span className={s.panelCount}>{totalCount}회 주문</span>
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
                    const hasOrigPrice = !item.offer_id && knownPrice(item) && item.original_price > 0 && item.original_price > item.price;
                    const presentation = getCartQuotePresentation(item);
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
                            <SelectedQuote item={item} />
                            {item.store_name && (
                              <div className={s.itemStore}>
                                <span>{storeIcon}</span> {item.store_name}
                              </div>
                            )}
                            {item.category && (
                              <span className={s.itemCategory}>{catIcon} {item.category}</span>
                            )}
                            <div className={s.itemPrices}>
                              <span className={s.itemSalePrice}>{knownPrice(item) ? `${presentation.amountLabel} ${fmt(item.price)}원` : '금액 미확인'}</span>
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
                          <span className={s.itemSpec}>주문 {item.quantity || 1}회</span>
                          <span className={s.itemTotalPrice}>
                            {knownPrice(item) ? `${fmt(Number(item.price) * (item.quantity || 1))}원` : '금액 미확인'}
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
                    <span className={s.totalLabel}>{unconfirmedPurchase ? '저장 관측 금액 합계' : unknownPriceCount ? '확인된 저장 금액' : '저장 금액 합계'} ({totalCount}회 주문)</span>
                    <span className={s.totalPrice}>{fmt(totalPrice)}원</span>
                  </div>
                  {unknownPriceCount > 0 && <p className={s.itemSpec}>금액 미확인 {unknownPriceCount}항목 · 전체 합계 미확인</p>}
                  {unconfirmedPurchase && <p className={s.itemSpec}>현재 결제 합계 미확인 · 저장 관측 금액을 합산한 값입니다</p>}
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
