/**
 * Zustand 전역 상태 스토어.
 * 최소한의 전역 상태만 관리. 나머지는 컴포넌트 로컬 상태.
 */
import { create } from 'zustand';

const useStore = create((set) => ({
  // 현재 선택된 상품 (물가비교 페이지용)
  selectedProduct: null,
  setSelectedProduct: (product) => set({ selectedProduct: product }),

  // 검색어
  searchQuery: '',
  setSearchQuery: (q) => set({ searchQuery: q }),

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
}));

export default useStore;
