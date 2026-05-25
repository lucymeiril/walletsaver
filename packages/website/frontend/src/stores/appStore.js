/**
 * Zustand 전역 상태 스토어.
 * 최소한의 전역 상태만 관리. 나머지는 컴포넌트 로컬 상태.
 */
import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import useCartStore from './cartStore';
import { buildCartPayload, buildWishlistPayload, normalizeProduct } from '../utils/productActions';

const useStore = create(
  persist(
    (set, get) => ({
      // 현재 선택된 상품 (물가비교 페이지용)
      selectedProduct: null,
      setSelectedProduct: (product) => set({ selectedProduct: product }),

      // 검색 상태
      searchQuery: '',
      setSearchQuery: (q) => set({ searchQuery: q }),
      searchResults: [],
      setSearchResults: (results) => set({ searchResults: results }),
      searchFilters: { category: 'all', sort: 'relevance' },
      setSearchFilters: (filters) => set((state) => ({
        searchFilters: { ...state.searchFilters, ...filters }
      })),

      // 로그인 상태
      isLoggedIn: false,
      user: null,
      login: (user) => set({ isLoggedIn: true, user }),
      logout: () => set({ isLoggedIn: false, user: null }),

      // 로그인 모달
      isLoginModalOpen: false,
      openLoginModal: () => set({ isLoginModalOpen: true }),
      closeLoginModal: () => set({ isLoginModalOpen: false }),

      // 토스트 메시지
      toasts: [],
      _toastSeq: 0,
      addToast: (msg, type = 'info', duration = 4000) => set((state) => ({
        _toastSeq: state._toastSeq + 1,
        toasts: [...state.toasts, {
          id: state._toastSeq + 1,
          msg,
          type,
          duration,
          createdAt: Date.now(),
        }]
      })),
      removeToast: (id) => set((state) => ({
        toasts: state.toasts.filter(t => t.id !== id)
      })),

      // 관심 품목 (Favorites/Watchlist)
      favorites: [],
      favoriteItems: {},
      addFavorite: (productOrId, details = {}) => set((state) => {
        const normalized = typeof productOrId === 'object'
          ? normalizeProduct(productOrId)
          : null;
        const productId = normalized?.favoriteId || productOrId;
        const payload = normalized
          ? buildWishlistPayload(productOrId)
          : { local_id: productId, ...details };
        const favorites = Array.isArray(state.favorites) ? state.favorites : [];
        const favoriteItems = state.favoriteItems || {};
        return {
          favorites: favorites.includes(productId)
            ? favorites
            : [...favorites, productId],
          favoriteItems: {
            ...favoriteItems,
            [productId]: {
              ...(favoriteItems[productId] || {}),
              ...payload,
              local_id: productId,
            },
          },
        };
      }),
      removeFavorite: (productId) => set((state) => ({
        favorites: state.favorites.filter(id => id !== productId),
        favoriteItems: Object.fromEntries(
          Object.entries(state.favoriteItems || {}).filter(([id]) => id !== productId)
        ),
      })),
      setFavoriteRemoteId: (productId, remoteId) => set((state) => ({
        favoriteItems: {
          ...(state.favoriteItems || {}),
          [productId]: {
            ...(state.favoriteItems?.[productId] || { local_id: productId }),
            remote_id: remoteId,
          },
        },
      })),
      isFavorite: (productId) => (get().favorites || []).includes(productId),

      // 최근 검색
      recentSearches: [],
      addRecentSearch: (query) => set((state) => {
        const filtered = state.recentSearches.filter(s => s.query !== query);
        return {
          recentSearches: [{ query, timestamp: Date.now() }, ...filtered].slice(0, 10)
        };
      }),
      clearRecentSearches: () => set({ recentSearches: [] }),

      // 장보기 리스트 (Shopping List) — cartStore와 동기화
      shoppingList: [],
      addToShoppingList: (item, quantityArg) => {
        const cartItem = (item && typeof item === 'object')
          ? item
          : { productId: item, id: item, name: String(item || '상품'), quantity: quantityArg || 1 };
        // cartStore에도 동기화 (ShoppingListPanel이 cartStore를 읽음)
        try {
          useCartStore.getState().addItem(buildCartPayload(cartItem));
        } catch { /* cartStore 미초기화 시 무시 */ }

        return set((state) => {
          const normalized = normalizeProduct(cartItem);
          const id = normalized.favoriteId;
          const existing = state.shoppingList.find(i => (i.productId ?? i.id ?? i.name) === id);
          if (existing) {
            return {
              shoppingList: state.shoppingList.map(i =>
                (i.productId ?? i.id ?? i.name) === id
                  ? { ...i, quantity: i.quantity + (normalized.quantity ?? 1) }
                  : i
              )
            };
          }
          return {
            shoppingList: [
              ...state.shoppingList,
              { productId: id, name: normalized.name, price: normalized.price, unit: normalized.unit || '', icon: cartItem.icon || '🛒', quantity: normalized.quantity ?? 1 },
            ],
          };
        });
      },
      removeFromShoppingList: (productId) => set((state) => ({
        shoppingList: state.shoppingList.filter(item => item.productId !== productId)
      })),
      clearShoppingList: () => set({ shoppingList: [] }),

      // 가격 알림 설정
      priceAlerts: [],
      addPriceAlert: (productId, targetPrice) => set((state) => ({
        priceAlerts: [
          ...state.priceAlerts.filter(a => a.productId !== productId),
          { productId, targetPrice }
        ]
      })),
      removePriceAlert: (productId) => set((state) => ({
        priceAlerts: state.priceAlerts.filter(a => a.productId !== productId)
      })),

      // 커뮤니티 상태
      communityPosts: [],
      setCommunityPosts: (posts) => set({ communityPosts: posts }),
      selectedPost: null,
      setSelectedPost: (post) => set({ selectedPost: post }),
      communityComments: [],
      setCommunityComments: (comments) => set({ communityComments: comments }),

      // 위치 상태
      location: { lat: null, lng: null },
      setLocation: (lat, lng) => set({ location: { lat, lng } }),
      savedLocation: null, // { lat, lng, locationName } — persisted across refresh
      setSavedLocation: (loc) => set({ savedLocation: loc }),
      nearbyGasStations: [],
      setNearbyGasStations: (stations) => set({ nearbyGasStations: stations }),
      nearbyRestaurants: [],
      setNearbyRestaurants: (restaurants) => set({ nearbyRestaurants: restaurants }),

      // 테마
      theme: 'light',
      toggleTheme: () => set((state) => ({
        theme: state.theme === 'light' ? 'dark' : 'light',
      })),

      // 핫딜러 모드 — ON 시 상세 가격 정보·할인율 레이어 추가 노출
      hotdealerMode: false,
      toggleHotdealerMode: () => set((state) => ({ hotdealerMode: !state.hotdealerMode })),

      // 필터/정렬 환경설정
      filterPreferences: {
        hotdealCategory: 'all',
        hotdealSource: '전체',
        hotdealSort: 'time',
        martActive: 'emart',
        localFuel: 'gasoline',
        communityBoard: 'hotdeal',
      },
      setFilterPreference: (key, value) => set((state) => ({
        filterPreferences: { ...state.filterPreferences, [key]: value }
      })),
    }),
    {
      name: 'wallet-savior-store',
      partialize: (state) => ({
        theme: state.theme,
        hotdealerMode: state.hotdealerMode,
        favorites: state.favorites,
        favoriteItems: state.favoriteItems,
        recentSearches: state.recentSearches,
        shoppingList: state.shoppingList,
        priceAlerts: state.priceAlerts,
        filterPreferences: state.filterPreferences,
        savedLocation: state.savedLocation,
      }),
    }
  )
);

export default useStore;
