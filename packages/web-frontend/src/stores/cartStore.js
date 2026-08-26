/**
 * 장바구니 스토어 — 비로그인은 localStorage, 로그인은 메인 DB를 진실 소스로 사용.
 */
import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { api } from '../services/api';
import useStore from './appStore';
import { asNumericId, normalizeProduct } from '../utils/productActions';

const CART_API = '/api/cart';

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
    store_name: item.store_name,
    source_url: item.source_url,
    original_price: item.original_price,
    discount_rate: item.discount_rate,
    category: item.category,
    quantity: item.quantity || 1,
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

      _getAuth: () => !!useStore.getState().isLoggedIn,

      fetchCart: async () => {
        if (!get()._getAuth()) return [];
        set({ loading: true });
        try {
          const res = await api.get(CART_API);
          const json = await res.json();
          const rawItems = json.data || json.items || json || [];
          const items = Array.isArray(rawItems) ? rawItems.map(normalizeCartItem) : [];
          set({ items, synced: true, loading: false });
          return items;
        } catch (error) {
          set({ loading: false, synced: false });
          throw error;
        }
      },

      mergeOnLogin: async () => {
        if (!get()._getAuth()) return [];
        const localItems = get().items;
        if (localItems.length > 0) {
          await api.post(`${CART_API}/merge`, {
            items: localItems
              .filter((item) => (item.price || item.item_price || 0) >= 0)
              .map((item) => toCartApiPayload(normalizeCartItem(item))),
          });
        }
        return get().fetchCart();
      },

      _ensureSynced: async () => {
        if (get()._getAuth() && !get().synced) {
          await get().mergeOnLogin();
        }
      },

      addItem: async (item) => {
        const normalized = normalizeCartItem(item);
        const isLoggedIn = get()._getAuth();

        if (!isLoggedIn) {
          const key = itemKey(normalized);
          const existing = get().items.find((row) => itemKey(row) === key);
          if (existing) {
            const nextQuantity = existing.quantity + normalized.quantity;
            set({
              items: get().items.map((row) =>
                itemKey(row) === key ? { ...row, quantity: nextQuantity } : row
              ),
            });
          } else {
            set({ items: [...get().items, normalized] });
          }
          return normalized;
        }

        await get()._ensureSynced();
        const key = itemKey(normalized);
        const existing = get().items.find((row) => itemKey(row) === key);

        if (existing?.cart_id) {
          const nextQuantity = existing.quantity + normalized.quantity;
          await api.put(`${CART_API}/${existing.cart_id}`, { quantity: nextQuantity });
          const updated = { ...existing, quantity: nextQuantity };
          set({
            items: get().items.map((row) =>
              row.cart_id === existing.cart_id ? updated : row
            ),
          });
          return updated;
        }

        const res = await api.post(CART_API, toCartApiPayload(normalized));
        const json = await res.json();
        const saved = normalizeCartItem(json.data || json);
        set({ items: [...get().items.filter((row) => itemKey(row) !== key), saved] });
        return saved;
      },

      updateQuantity: async (itemId, quantity) => {
        if (quantity < 1) return get().removeItem(itemId);
        const isLoggedIn = get()._getAuth();
        if (isLoggedIn) await get()._ensureSynced();

        const item = get().items.find(
          (row) => row.id === itemId || row.cart_id === itemId || row.product_id === itemId
        );
        if (!item) return false;

        if (isLoggedIn) {
          if (!item.cart_id) throw new Error('장바구니 항목이 서버와 동기화되지 않았습니다.');
          await api.put(`${CART_API}/${item.cart_id}`, { quantity });
        }

        set({
          items: get().items.map((row) =>
            (row.id === itemId || row.cart_id === itemId || row.product_id === itemId)
              ? { ...row, quantity }
              : row
          ),
        });
        return true;
      },

      removeItem: async (itemId) => {
        const isLoggedIn = get()._getAuth();
        if (isLoggedIn) await get()._ensureSynced();

        const item = get().items.find(
          (row) => row.id === itemId || row.cart_id === itemId || row.product_id === itemId
        );
        if (!item) return false;

        if (isLoggedIn) {
          if (!item.cart_id) throw new Error('장바구니 항목이 서버와 동기화되지 않았습니다.');
          await api.delete(`${CART_API}/${item.cart_id}`);
        }

        set({
          items: get().items.filter(
            (row) => row.id !== itemId && row.cart_id !== itemId && row.product_id !== itemId
          ),
        });
        return true;
      },

      clearCart: async () => {
        if (get()._getAuth()) {
          await get()._ensureSynced();
          await api.delete(CART_API);
        }
        set({ items: [], synced: get()._getAuth() });
        return true;
      },

      onLogout: () => {
        set({ items: [], synced: false });
      },

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
      // 로그인 계정의 장바구니는 DB가 원본이다. localStorage에는 게스트 장바구니만 남긴다.
      partialize: (state) => ({
        items: useStore.getState().isLoggedIn ? [] : state.items.map(normalizeCartItem),
      }),
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
