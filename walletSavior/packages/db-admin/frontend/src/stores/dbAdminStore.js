import { create } from 'zustand';
import { api } from '../api/client';
import {
  products as mockProducts,
  categories as mockCategories,
  keywords as mockKeywords,
  priceHistories as mockPriceHistories,
  priceOutliers as mockOutliers,
  dashboardStats as mockDashboardStats,
  categoryAvgPrices as mockCategoryAvgPrices,
  qualityReport as mockQualityReport,
  sourceStats as mockSourceStats,
  priceTiers as mockPriceTiers,
} from '../data/mockData';

const useDbAdminStore = create((set, get) => ({
  // Loading / Error
  loading: false,
  error: null,

  /* ── 상품 ── */
  products: mockProducts,
  addProduct: async (product) => {
    try {
      const result = await api.createProduct(product);
      await get().fetchProducts();
      return result;
    } catch {
      // 오프라인 모드: 로컬 상태만 업데이트
      set((s) => ({ products: [...s.products, { ...product, id: `p-${Date.now()}` }] }));
    }
  },
  updateProduct: async (id, data) => {
    try {
      await api.updateProduct(id, data);
      await get().fetchProducts();
    } catch {
      set((s) => ({ products: s.products.map((p) => (p.id === id ? { ...p, ...data } : p)) }));
    }
  },
  deleteProduct: async (id) => {
    try {
      await api.deleteProduct(id);
      await get().fetchProducts();
    } catch {
      set((s) => ({ products: s.products.filter((p) => p.id !== id) }));
    }
  },

  fetchProducts: async () => {
    set({ loading: true, error: null });
    try {
      const data = await api.getProducts();
      const list = Array.isArray(data) ? data : data.products ?? data.data ?? [];
      // API 상품 → 프론트엔드 형식으로 변환 (basePrice/currentAvg/tier 기본값)
      const mapped = list.map((p) => ({
        ...p,
        category: p.category || p.category_id || '',
        basePrice: p.basePrice ?? p.base_price ?? 0,
        currentAvg: p.currentAvg ?? p.current_avg ?? 0,
        tier: p.tier || 'good',
      }));
      if (mapped.length > 0) set({ products: mapped });
    } catch {
      // mock 유지
    } finally {
      set({ loading: false });
    }
  },

  /* ── 카테고리 (트리 구조) ── */
  categories: mockCategories,
  addCategory: async (parentId, category) => {
    try {
      await api.createCategory({ ...category, parent_id: parentId });
      await get().fetchCategories();
    } catch {
      set((s) => ({
        categories: addToTree(s.categories, parentId, { ...category, id: `cat-${Date.now()}`, children: [], productCount: 0 }),
      }));
    }
  },
  updateCategory: async (id, data) => {
    try {
      await api.updateCategory(id, data);
      await get().fetchCategories();
    } catch {
      set((s) => ({ categories: updateInTree(s.categories, id, data) }));
    }
  },
  deleteCategory: async (id) => {
    try {
      await api.deleteCategory(id);
      await get().fetchCategories();
    } catch {
      set((s) => ({ categories: removeFromTree(s.categories, id) }));
    }
  },

  fetchCategories: async () => {
    set({ loading: true, error: null });
    try {
      const data = await api.getCategories();
      const list = Array.isArray(data) ? data : data.categories ?? data.data ?? [];
      if (list.length > 0) set({ categories: list });
    } catch {
      // mock 유지
    } finally {
      set({ loading: false });
    }
  },

  /* ── 키워드 ── */
  keywords: mockKeywords,
  addKeyword: async (kw) => {
    try {
      await api.createKeyword(kw);
      // 키워드 목록 갱신 (API에 목록 조회가 있으면 사용)
      try {
        const data = await api.getKeywords();
        const list = Array.isArray(data) ? data : data.keywords ?? data.data ?? [];
        if (list.length > 0) set({ keywords: list });
      } catch { /* 갱신 실패 시 로컬 추가 */ }
    } catch {
      set((s) => ({ keywords: [...s.keywords, { ...kw, id: `kw-${Date.now()}` }] }));
    }
  },
  updateKeyword: async (id, data) => {
    try {
      await api.updateKeyword(id, data);
    } catch {
      set((s) => ({ keywords: s.keywords.map((k) => (k.id === id ? { ...k, ...data } : k)) }));
    }
  },
  deleteKeyword: async (id) => {
    try {
      await api.deleteKeyword(id);
      set((s) => ({ keywords: s.keywords.filter((k) => k.id !== id) }));
    } catch {
      set((s) => ({ keywords: s.keywords.filter((k) => k.id !== id) }));
    }
  },

  /* ── 가격 ── */
  priceHistories: mockPriceHistories,
  priceOutliers: mockOutliers,
  priceTiers: mockPriceTiers,
  updatePriceTier: (tier, threshold) =>
    set((s) => ({
      priceTiers: { ...s.priceTiers, [tier]: { ...s.priceTiers[tier], threshold } },
    })),

  /* ── 분석 ── */
  categoryAvgPrices: mockCategoryAvgPrices,
  qualityReport: mockQualityReport,
  sourceStats: mockSourceStats,

  fetchAnalytics: async () => {
    set({ loading: true, error: null });
    try {
      const [qualityData, summaryData] = await Promise.allSettled([
        api.getQualityReport(),
        api.getSummary(),
      ]);
      if (qualityData.status === 'fulfilled' && qualityData.value) {
        set({ qualityReport: qualityData.value });
      }
      if (summaryData.status === 'fulfilled' && summaryData.value) {
        const s = summaryData.value;
        if (s.categoryAvgPrices) set({ categoryAvgPrices: s.categoryAvgPrices });
        if (s.sourceStats) set({ sourceStats: s.sourceStats });
      }
    } catch {
      // mock 유지
    } finally {
      set({ loading: false });
    }
  },

  /* ── 대시보드 ── */
  dashboardStats: mockDashboardStats,

  fetchDashboard: async () => {
    set({ loading: true, error: null });
    try {
      const [productsData, summaryData] = await Promise.allSettled([
        api.getProducts(),
        api.getSummary(),
      ]);
      const products = productsData.status === 'fulfilled'
        ? (Array.isArray(productsData.value) ? productsData.value : productsData.value.products ?? productsData.value.data ?? [])
        : [];
      if (products.length > 0) set({ products });

      if (summaryData.status === 'fulfilled' && summaryData.value) {
        const s = summaryData.value;
        set({
          dashboardStats: {
            ...get().dashboardStats,
            totalProducts: s.totalProducts ?? products.length ?? get().dashboardStats.totalProducts,
            totalPriceRecords: s.totalPriceRecords ?? get().dashboardStats.totalPriceRecords,
            totalCategories: s.totalCategories ?? get().dashboardStats.totalCategories,
            totalKeywords: s.totalKeywords ?? get().dashboardStats.totalKeywords,
            lastUpdated: s.lastUpdated ?? new Date().toISOString(),
            qualityScore: s.qualityScore ?? get().dashboardStats.qualityScore,
            recentIngestions: s.recentIngestions ?? get().dashboardStats.recentIngestions,
          },
        });
      }
    } catch {
      // mock 유지
    } finally {
      set({ loading: false });
    }
  },

  /* ── Ingestions (수신함) ── */
  ingestions: [],
  selectedIngestion: null,
  ingestionFilter: 'all',
  ingestionStats: { pending: 0, approved: 0, rejected: 0 },

  fetchIngestions: async (params = {}) => {
    set({ loading: true, error: null });
    try {
      const data = await api.getIngestions(params);
      const list = Array.isArray(data) ? data : data.ingestions ?? data.data ?? [];
      set({ ingestions: list });
    } catch {
      set({ ingestions: [] });
    } finally {
      set({ loading: false });
    }
  },

  fetchIngestion: async (id) => {
    set({ loading: true, error: null });
    try {
      const data = await api.getIngestion(id);
      set({ selectedIngestion: data });
      return data;
    } catch {
      set({ selectedIngestion: null });
      return null;
    } finally {
      set({ loading: false });
    }
  },

  fetchIngestionStats: async () => {
    try {
      const data = await api.getIngestionStats();
      if (data) set({ ingestionStats: data });
    } catch {
      // mock 유지
    }
  },

  reviewIngestion: async (id, reviewData) => {
    set({ loading: true, error: null });
    try {
      const result = await api.reviewIngestion(id, reviewData);
      await get().fetchIngestions();
      return result;
    } catch (err) {
      set({ error: `리뷰 실패: ${err.message}` });
      return null;
    } finally {
      set({ loading: false });
    }
  },

  setIngestionFilter: (filter) => set({ ingestionFilter: filter }),
}));

/* 트리 유틸리티 */
function addToTree(tree, parentId, node) {
  if (!parentId) return [...tree, node];
  return tree.map((item) => {
    if (item.id === parentId) {
      return { ...item, children: [...(item.children || []), node] };
    }
    if (item.children) {
      return { ...item, children: addToTree(item.children, parentId, node) };
    }
    return item;
  });
}

function updateInTree(tree, id, data) {
  return tree.map((item) => {
    if (item.id === id) return { ...item, ...data };
    if (item.children) return { ...item, children: updateInTree(item.children, id, data) };
    return item;
  });
}

function removeFromTree(tree, id) {
  return tree
    .filter((item) => item.id !== id)
    .map((item) => {
      if (item.children) return { ...item, children: removeFromTree(item.children, id) };
      return item;
    });
}

export default useDbAdminStore;
