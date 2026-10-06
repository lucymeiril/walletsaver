/**
 * 장바구니 스토어 — 비로그인은 localStorage, 로그인은 메인 DB를 진실 소스로 사용.
 */
import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { api } from '../services/api';
import useStore from './appStore';
import { asNumericId, normalizeProduct, cartIdentity } from '../utils/productActions';

const CART_API = '/api/cart';
let mergeInFlight = null;
let cartSession = 0;

function normalizeCartItem(item) {
  const product = normalizeProduct(item);
  const isBackendCartItem = item.cart_id || item.item_name !== undefined || item.item_price !== undefined || item.added_at;
  const id = item.local_id || item.stable_id || ((item.variant_id || item.listing_id || item.offer_id)
    ? cartIdentity({ ...item, product_id: product.numericProductId ?? product.catalogProductId }) : product.stableId);
  const priceKnown = item.price_known ?? [item.item_price,item.price,item.sale,item.current_price]
    .some(value => value != null && value !== '' && Number.isFinite(Number(value)));
  return {
    id,
    product_id: product.numericProductId ?? product.catalogProductId,
    product_catalog_id: product.numericProductId ?? product.catalogProductId,
    variant_id: item.variant_id ?? null,
    listing_id: item.listing_id ?? null,
    offer_id: item.offer_id ?? null,
    offer_context: item.offer_context ?? null,
    saved_receipt_valid: item.saved_receipt_valid ?? null,
    saved_receipt_reason: item.saved_receipt_reason ?? null,
    quoted_offer: item.quoted_offer ?? null,
    name: product.name,
    price: priceKnown ? product.price : null,
    price_known: priceKnown,
    original_price: product.originalPrice,
    store_name: product.storeName,
    store_key: product.storeKey,
    category: product.category,
    image: product.image,
    unit: product.unit,
    quantity: item.quantity || 1,
    cart_id: item.cart_id || (isBackendCartItem ? item.id : null) || null,
    source_url: product.sourceUrl,
    source_title: product.sourceTitle || item.offer_context?.source_title || '',
    discount_rate: product.discount,
  };
}

function itemKey(item) {
  return cartIdentity(item);
}

function toCartApiPayload(item) {
  const selection = [item.variant_id, item.listing_id, item.offer_id];
  if (selection.some(Boolean) && !selection.every(Boolean)) throw new Error('선택한 규격·판매처·가격 이력을 확인할 수 없습니다');
  const quote = item.offer_context || item.quoted_offer;
  if (selection.every(Boolean) && quote && !(Number.isFinite(Number(quote.total_price)) && Number(quote.total_price) > 0)) {
    throw new Error('실제 거래 금액이 확인되지 않아 장바구니 금액을 저장할 수 없습니다');
  }
  if (!item.price_known || !Number.isFinite(item.price) || item.price < 0
    || (item.product_catalog_id != null && item.price <= 0)) throw new Error('상품 표시 가격이 확인되지 않아 장바구니 금액을 저장할 수 없습니다');
  const rawId = item.product_catalog_id ?? item.product_id;
  const productId = asNumericId(rawId) ?? rawId;
  return {
    ...(productId ? { product_id: productId } : {}),
    ...(item.variant_id ? { variant_id: item.variant_id } : {}),
    ...(item.listing_id ? { listing_id: item.listing_id } : {}),
    ...(item.offer_id ? { offer_id: item.offer_id } : {}),
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

// Derive totals on every state write, including initial hydration and setState.
// Accessors run while persist spreads its initial state, before get() exists.
function withCartTotals(config) {
  return (set, get, store) => {
    const setWithTotals = (partial, replace) => {
      const update = typeof partial === 'function' ? partial(get()) : partial;
      const next = replace ? update : { ...get(), ...update };
      const items = next.items || [];
      set({ ...update,
        totalPrice: items.reduce((sum, item) => sum + (item.price || 0) * (item.quantity || 1), 0),
        totalSavings: items.reduce((sum, item) => sum + (item.original_price > (item.price || 0) && item.price > 0
          ? (item.original_price - item.price) * (item.quantity || 1) : 0), 0),
        itemCount: items.reduce((sum, item) => sum + (item.quantity || 1), 0),
      }, replace);
    };
    store.setState = setWithTotals;
    return config(setWithTotals, get, store);
  };
}

const useCartStore = create(
  withCartTotals(persist(
    (set, get) => ({
      items: [],
      loading: false,
      synced: false,
      pendingMerge: null,
      totalPrice: 0,
      totalSavings: 0,
      itemCount: 0,

      _getAuth: () => !!useStore.getState().isLoggedIn,

      fetchCart: async () => {
        if (!get()._getAuth()) return [];
        const session = cartSession;
        set({ loading: true });
        try {
          const res = await api.get(CART_API);
          const json = await res.json();
          const rawItems = json.data || json.items || json;
          if (!Array.isArray(rawItems)) throw new Error('장바구니 조회 결과를 확인할 수 없습니다.');
          const items = rawItems.map(normalizeCartItem);
          if (session !== cartSession || !get()._getAuth()) return [];
          set({ items, synced: true, loading: false });
          return items;
        } catch (error) {
          if (session === cartSession) set({ loading: false, synced: false });
          throw error;
        }
      },

      mergeOnLogin: () => {
        if (!get()._getAuth()) return Promise.resolve([]);
        if (mergeInFlight) return mergeInFlight;
        if (get().synced && !get().pendingMerge) return get().fetchCart();
        const session = cartSession;
        const task = (async () => {
          let batch = get().pendingMerge;
          const guestItems = get().items.filter(item => !item.cart_id);
          if (!batch && guestItems.length > 0) {
            batch = {
              merge_id: globalThis.crypto.randomUUID(),
              items: guestItems.map((item) => toCartApiPayload(normalizeCartItem(item))),
            };
            // A retry must use the same identity AND exact payload, even if the
            // server committed before its response was lost.
            set({ pendingMerge: batch });
          }
          if (!batch) return get().fetchCart();
          set({ loading: true });
          try {
            const response = await api.post(`${CART_API}/merge`, batch);
            const json = await response.json();
            const rawItems = json.data || json.items || json;
            if (!Array.isArray(rawItems)) throw new Error('장바구니 병합 결과를 확인할 수 없습니다. 다시 시도해 주세요.');
            if (session !== cartSession || !get()._getAuth()) return [];
            const items = rawItems.map(normalizeCartItem);
            set({ items, pendingMerge: null, synced: true, loading: false });
            return items;
          } catch (error) {
            if (session === cartSession) set({ loading: false, synced: false });
            throw error;
          }
        })();
        const tracked = task.finally(() => { if (mergeInFlight === tracked) mergeInFlight = null; });
        mergeInFlight = tracked;
        return tracked;
      },

      _ensureSynced: async () => {
        if (get()._getAuth() && !get().synced) {
          await get().mergeOnLogin();
        }
      },

      addItem: async (item) => {
        const normalized = normalizeCartItem(item);
        toCartApiPayload(normalized); // Validate the same quoted amount for guest and authenticated carts.
        const isLoggedIn = get()._getAuth();

        if (!isLoggedIn) {
          if (get().pendingMerge) throw new Error('이전 장바구니 병합을 확인한 뒤 상품을 추가해 주세요.');
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
        if (!isLoggedIn && get().pendingMerge) throw new Error('이전 장바구니 병합을 먼저 확인해 주세요.');
        if (isLoggedIn) await get()._ensureSynced();

        const item = get().items.find(
          (row) => row.id === itemId || row.cart_id === itemId || (row.product_id === itemId && !row.variant_id && !row.listing_id && !row.offer_id)
        );
        if (!item) return false;

        if (isLoggedIn) {
          if (!item.cart_id) throw new Error('장바구니 항목이 서버와 동기화되지 않았습니다.');
          await api.put(`${CART_API}/${item.cart_id}`, { quantity });
        }

        set({
          items: get().items.map((row) =>
            (item.cart_id ? row.cart_id === item.cart_id : row.id === item.id)
              ? { ...row, quantity }
              : row
          ),
        });
        return true;
      },

      removeItem: async (itemId) => {
        const isLoggedIn = get()._getAuth();
        if (!isLoggedIn && get().pendingMerge) throw new Error('이전 장바구니 병합을 먼저 확인해 주세요.');
        // An unsubmitted guest row can be removed even when its old price is
        // unavailable. An ambiguous submitted batch must settle first.
        const guestItem = get().items.find(row => row.id === itemId && !row.cart_id);
        if (isLoggedIn && !get().synced && !get().pendingMerge && guestItem) {
          set({ items: get().items.filter(row => row !== guestItem) });
          return true;
        }
        if (isLoggedIn) await get()._ensureSynced();

        const item = get().items.find(
          (row) => row.id === itemId || row.cart_id === itemId || (row.product_id === itemId && !row.variant_id && !row.listing_id && !row.offer_id)
        );
        if (!item) return false;

        if (isLoggedIn) {
          if (!item.cart_id) throw new Error('장바구니 항목이 서버와 동기화되지 않았습니다.');
          await api.delete(`${CART_API}/${item.cart_id}`);
        }

        set({
          items: get().items.filter(
            (row) => item.cart_id ? row.cart_id !== item.cart_id : row.id !== item.id
          ),
        });
        return true;
      },

      clearCart: async () => {
        if (!get()._getAuth() && get().pendingMerge) throw new Error('이전 장바구니 병합을 먼저 확인해 주세요.');
        if (get()._getAuth()) {
          if (get().pendingMerge) await get()._ensureSynced();
          await api.delete(CART_API);
        }
        set({ items: [], synced: get()._getAuth() });
        return true;
      },

      onLogout: () => {
        cartSession += 1;
        mergeInFlight = null;
        set({ items: [], pendingMerge: null, synced: false, loading: false });
      },

    }),
    {
      name: 'wallet-savior-cart',
      // 로그인 계정의 장바구니는 DB가 원본이다. localStorage에는 게스트 장바구니만 남긴다.
      partialize: (state) => ({
        items: (useStore.getState().isLoggedIn ? state.items.filter(item => !item.cart_id) : state.items).map(normalizeCartItem),
        pendingMerge: state.pendingMerge,
      }),
      merge: (persistedState, currentState) => ({
        ...currentState,
        ...(persistedState || {}),
        items: Array.isArray(persistedState?.items)
          ? persistedState.items.map(normalizeCartItem)
          : readLegacyShoppingList().map(normalizeCartItem),
      }),
    }
  ))
);

export default useCartStore;
