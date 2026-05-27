/**
 * 장바구니 스토어 — localStorage (비로그인) + API (로그인) 이중 모드
 */
import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { api } from '../services/api';
import useStore from './appStore';
import { asNumericId, normalizeProduct } from '../utils/productActions';

const CART_API = '/api/cart';

/** 백엔드 → 프론트 필드 정규화 */
function normalizeCartItem(item) {
  const product = normalizeProduct(item);
  const isBackendCartItem = item.cart_id || item.item_name !== undefined || item.item_price !== undefined || item.added_at;
  const id = item.local_id || item.stable_id || product.stableId;
  return {
    id,
    product_id: product.numericProductId || null,
    product_catalog_id: product.numericProductId || null,
    name: product.name,
    price: product.price,
    original_price: product.originalPrice,
    store_name: product.storeName,
    store_key: product.storeKey,
    category: product.category,
    image: product.image,
    unit: product.unit,
    quantity: item.quantity || 1,
    cart_id: item.cart_id || (isBackendCartItem ? item.id : null) || null,
    source_url: product.sourceUrl,
    discount_rate: product.discount,
  };
}

function itemKey(item) {
  return item?.product_catalog_id ? `product:${item.product_catalog_id}` : item?.id;
}

function toCartApiPayload(item) {
  const productId = asNumericId(item.product_catalog_id ?? item.product_id);
  return {
    ...(productId ? { product_id: productId } : {}),
    item_name: item.name,
    item_price: item.price,
    item_image_url: item.image,
    local_id: item.id,
    store_name: item.store_name,
    source_url: item.source_url,
    original_price: item.original_price,
    discount_rate: item.discount_rate,
    category: item.category,
    quantity: item.quantity || 1,
    unit: item.unit,
  };
}

function readLegacyShoppingList() {
  if (typeof localStorage === 'undefined') return [];
  try {
    const raw = localStorage.getItem('wallet-savior-store');
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    const shoppingList = parsed?.state?.shoppingList;
    return Array.isArray(shoppingList) ? shoppingList : [];
  } catch {
    return [];
  }
}

const useCartStore = create(
  persist(
    (set, get) => ({
      items: [],
      loading: false,
      synced: false,

      /** 로그인 상태 확인 (appStore runtime state) */
      _getAuth: () => {
        return !!useStore.getState().isLoggedIn;
      },

      /** API에서 장바구니 로드 */
      fetchCart: async () => {
        if (!get()._getAuth()) return;
        set({ loading: true });
        try {
          const res = await api.get(CART_API);
          const json = await res.json();
          const rawItems = json.data || json.items || json || [];
          const items = Array.isArray(rawItems) ? rawItems.map(normalizeCartItem) : [];
          set({ items, synced: true, loading: false });
        } catch {
          set({ loading: false });
        }
      },

      /** 아이템 추가 */
      addItem: async (item) => {
        const normalized = normalizeCartItem(item);

        const isLoggedIn = get()._getAuth();
        const normalizedKey = itemKey(normalized);
        const existing = get().items.find((i) => itemKey(i) === normalizedKey);

        if (existing) {
          const updated = get().items.map((i) =>
            itemKey(i) === normalizedKey
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
          if (isLoggedIn && normalized.price > 0) {
            try {
              const res = await api.post(CART_API, toCartApiPayload(normalized));
              const json = await res.json();
              const data = json.data || json;
              if (data.id || data.cart_id) {
                set({
                  items: get().items.map((i) =>
                    itemKey(i) === normalizedKey
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
            await api.post(`${CART_API}/merge`, {
              items: localItems
                .filter((item) => (item.price || item.item_price || 0) > 0)
                .map((item) => toCartApiPayload(normalizeCartItem(item))),
            });
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
      partialize: (state) => ({ items: state.items.map(normalizeCartItem) }),
      merge: (persistedState, currentState) => ({
        ...currentState,
        ...(persistedState || {}),
        items: Array.isArray(persistedState?.items) && persistedState.items.length > 0
          ? persistedState.items.map(normalizeCartItem)
          : readLegacyShoppingList().map(normalizeCartItem),
      }),
    }
  )
);

export default useCartStore;
