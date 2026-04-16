/**
 * 장바구니 스토어 — localStorage (비로그인) + API (로그인) 이중 모드
 */
import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { api } from '../services/api';

const CART_API = '/api/cart';

const useCartStore = create(
  persist(
    (set, get) => ({
      items: [],
      loading: false,
      synced: false, // DB와 동기화 여부

      /** 로그인 상태 확인 (appStore에서 가져옴) */
      _getAuth: () => {
        try {
          const raw = localStorage.getItem('wallet-savior-store');
          if (!raw) return false;
          const parsed = JSON.parse(raw);
          return !!parsed?.state?.isLoggedIn;
        } catch { return false; }
      },

      /** API에서 장바구니 로드 */
      fetchCart: async () => {
        if (!get()._getAuth()) return;
        set({ loading: true });
        try {
          const res = await api.get(CART_API);
          const data = await res.json();
          set({ items: data.items || data || [], synced: true, loading: false });
        } catch {
          set({ loading: false });
        }
      },

      /** 아이템 추가 */
      addItem: async (item) => {
        const normalized = {
          id: item.id || item.productId || item.product_id || Date.now().toString(),
          product_id: item.product_id || item.productId || item.id,
          name: item.name || item.item_name || item.product_name || '상품',
          price: item.price || item.item_price || item.sale || 0,
          original_price: item.original_price || item.orig || item.origPrice || 0,
          store_name: item.store_name || item.store || item.martName || '',
          store_key: item.store_key || item.martKey || '',
          category: item.category || item.category_name || '',
          image: item.image || item.img || item.image_url || '',
          unit: item.unit || item.spec || '',
          quantity: item.quantity || 1,
        };

        const isLoggedIn = get()._getAuth();
        const existing = get().items.find(
          (i) => (i.product_id || i.id) === (normalized.product_id || normalized.id)
        );

        if (existing) {
          const updated = get().items.map((i) =>
            (i.product_id || i.id) === (normalized.product_id || normalized.id)
              ? { ...i, quantity: i.quantity + normalized.quantity }
              : i
          );
          set({ items: updated });
          if (isLoggedIn && existing.cart_id) {
            try {
              await api.put(`${CART_API}/${existing.cart_id}`, { quantity: existing.quantity + normalized.quantity });
            } catch { /* silently fail */ }
          }
        } else {
          set({ items: [...get().items, normalized] });
          if (isLoggedIn) {
            try {
              const res = await api.post(CART_API, normalized);
              const data = await res.json();
              if (data.id || data.cart_id) {
                set({
                  items: get().items.map((i) =>
                    (i.product_id || i.id) === (normalized.product_id || normalized.id)
                      ? { ...i, cart_id: data.id || data.cart_id }
                      : i
                  ),
                });
              }
            } catch { /* silently fail */ }
          }
        }
        return normalized;
      },

      /** 수량 변경 */
      updateQuantity: async (itemId, quantity) => {
        if (quantity < 1) return get().removeItem(itemId);
        const isLoggedIn = get()._getAuth();
        const item = get().items.find(
          (i) => i.id === itemId || i.cart_id === itemId || i.product_id === itemId
        );
        set({
          items: get().items.map((i) =>
            (i.id === itemId || i.cart_id === itemId || i.product_id === itemId)
              ? { ...i, quantity }
              : i
          ),
        });
        if (isLoggedIn && item?.cart_id) {
          try {
            await api.put(`${CART_API}/${item.cart_id}`, { quantity });
          } catch { /* silently fail */ }
        }
      },

      /** 아이템 삭제 */
      removeItem: async (itemId) => {
        const isLoggedIn = get()._getAuth();
        const item = get().items.find(
          (i) => i.id === itemId || i.cart_id === itemId || i.product_id === itemId
        );
        set({
          items: get().items.filter(
            (i) => i.id !== itemId && i.cart_id !== itemId && i.product_id !== itemId
          ),
        });
        if (isLoggedIn && item?.cart_id) {
          try {
            await api.delete(`${CART_API}/${item.cart_id}`);
          } catch { /* silently fail */ }
        }
      },

      /** 전체 비우기 */
      clearCart: async () => {
        const isLoggedIn = get()._getAuth();
        set({ items: [] });
        if (isLoggedIn) {
          try {
            await api.delete(CART_API);
          } catch { /* silently fail */ }
        }
      },

      /** 로그인 시 localStorage → DB 병합 */
      mergeOnLogin: async () => {
        const localItems = get().items;
        if (localItems.length > 0) {
          try {
            await api.post(`${CART_API}/merge`, { items: localItems });
          } catch { /* silently fail */ }
        }
        await get().fetchCart();
      },

      /** 로그아웃 시 로컬 장바구니 초기화 */
      onLogout: () => {
        set({ items: [], synced: false });
      },

      /** 합계 계산 */
      get totalPrice() {
        return get().items.reduce((sum, i) => sum + (i.price || 0) * (i.quantity || 1), 0);
      },
      get totalSavings() {
        return get().items.reduce((sum, i) => {
          const orig = i.original_price || 0;
          const sale = i.price || 0;
          if (orig > sale && sale > 0) return sum + (orig - sale) * (i.quantity || 1);
          return sum;
        }, 0);
      },
      get itemCount() {
        return get().items.reduce((sum, i) => sum + (i.quantity || 1), 0);
      },
    }),
    {
      name: 'wallet-savior-cart',
      partialize: (state) => ({ items: state.items }),
    }
  )
);

export default useCartStore;
