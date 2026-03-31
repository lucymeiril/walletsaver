/**
 * Zustand 전역 상태 스토어.
 * 최소한의 전역 상태만 관리. 나머지는 컴포넌트 로컬 상태.
 */
import { create } from 'zustand';
import { persist } from 'zustand/middleware';

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

      // 토스트 메시지
      toasts: [],
      addToast: (msg, type = 'info') => set((state) => ({
        toasts: [...state.toasts, { id: Date.now(), msg, type }]
      })),
      removeToast: (id) => set((state) => ({
        toasts: state.toasts.filter(t => t.id !== id)
      })),

      // 관심 품목 (Favorites/Watchlist)
      favorites: [],
      addFavorite: (productId) => set((state) => ({
        favorites: state.favorites.includes(productId)
          ? state.favorites
          : [...state.favorites, productId]
      })),
      removeFavorite: (productId) => set((state) => ({
        favorites: state.favorites.filter(id => id !== productId)
      })),
      isFavorite: (productId) => get().favorites.includes(productId),

      // 최근 검색
      recentSearches: [],
      addRecentSearch: (query) => set((state) => {
        const filtered = state.recentSearches.filter(s => s.query !== query);
        return {
          recentSearches: [{ query, timestamp: Date.now() }, ...filtered].slice(0, 10)
        };
      }),
      clearRecentSearches: () => set({ recentSearches: [] }),

      // 장보기 리스트 (Shopping List)
      shoppingList: [],
      addToShoppingList: (productId, quantity = 1) => set((state) => {
        const existing = state.shoppingList.find(item => item.productId === productId);
        if (existing) {
          return {
            shoppingList: state.shoppingList.map(item =>
              item.productId === productId
                ? { ...item, quantity: item.quantity + quantity }
                : item
            )
          };
        }
        return { shoppingList: [...state.shoppingList, { productId, quantity }] };
      }),
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
      nearbyGasStations: [],
      setNearbyGasStations: (stations) => set({ nearbyGasStations: stations }),
      nearbyRestaurants: [],
      setNearbyRestaurants: (restaurants) => set({ nearbyRestaurants: restaurants }),

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
        favorites: state.favorites,
        recentSearches: state.recentSearches,
        shoppingList: state.shoppingList,
        priceAlerts: state.priceAlerts,
        filterPreferences: state.filterPreferences,
      }),
    }
  )
);

export default useStore;
