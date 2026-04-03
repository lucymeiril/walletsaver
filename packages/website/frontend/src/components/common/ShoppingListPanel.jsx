import { useState, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import useStore from '../../stores/appStore';
import s from './ShoppingListPanel.module.css';

const fmt = (n) => n?.toLocaleString('ko-KR') ?? '0';

export default function ShoppingListPanel() {
  const [open, setOpen] = useState(false);
  const { shoppingList, removeFromShoppingList, clearShoppingList, addToast } = useStore();

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

  const total = shoppingList.reduce((sum, i) => sum + (i.price || 0) * i.quantity, 0);

  const handleClear = () => {
    clearShoppingList();
    addToast('장보기 리스트를 비웠습니다', 'info');
  };

  const handleRemove = (productId) => {
    removeFromShoppingList(productId);
  };

  return (
    <>
      {/* FAB */}
      <button className={s.fab} onClick={toggle} aria-label="장보기 리스트 열기">
        🛒
        {shoppingList.length > 0 && (
          <span className={s.badge}>{shoppingList.length}</span>
        )}
      </button>

      {/* Panel */}
      {open && createPortal(
        <>
          <div className={s.overlay} onClick={() => setOpen(false)} />
          <aside className={s.panel} role="dialog" aria-label="장보기 리스트">
            <div className={s.panelHeader}>
              <div className={s.panelTitle}>
                🛒 장보기 리스트
                <span className={s.panelCount}>{shoppingList.length}개</span>
              </div>
              <button className={s.closeBtn} onClick={() => setOpen(false)} aria-label="닫기">
                <X size={20} />
              </button>
            </div>

            {shoppingList.length === 0 ? (
              <div className={s.empty}>
                <span className={s.emptyIcon}>🛒</span>
                <span className={s.emptyText}>장보기 리스트가 비어있어요</span>
              </div>
            ) : (
              <>
                <div className={s.itemList}>
                  {shoppingList.map((item) => (
                    <div key={item.productId} className={s.item}>
                      <span className={s.itemIcon}>{item.icon}</span>
                      <div className={s.itemInfo}>
                        <div className={s.itemName}>{item.name}</div>
                        <div className={s.itemMeta}>
                          {item.unit && `${item.unit} · `}수량 {item.quantity}개
                        </div>
                      </div>
                      <span className={s.itemPrice}>
                        {item.price ? `${fmt(item.price * item.quantity)}원` : '-'}
                      </span>
                      <button
                        className={s.removeBtn}
                        onClick={() => handleRemove(item.productId)}
                        aria-label={`${item.name} 삭제`}
                      >
                        ❌
                      </button>
                    </div>
                  ))}
                </div>
                <div className={s.panelFooter}>
                  <div className={s.totalRow}>
                    <span className={s.totalLabel}>예상 합계</span>
                    <span className={s.totalPrice}>{fmt(total)}원</span>
                  </div>
                  <button className={s.clearBtn} onClick={handleClear}>
                    목록 비우기
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
