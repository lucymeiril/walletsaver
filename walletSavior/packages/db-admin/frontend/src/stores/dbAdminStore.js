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
  addProduct: (product) =>
    set((s) => ({ products: [...s.products, { ...product, id: `p-${Date.now()}` }] })),
  updateProduct: (id, data) =>
    set((s) => ({ products: s.products.map((p) => (p.id === id ? { ...p, ...data } : p)) })),
  deleteProduct: (id) =>
    set((s) => ({ products: s.products.filter((p) => p.id !== id) })),

  fetchProducts: async () => {
    set({ loading: true, error: null });
    try {
      const data = await api.getProducts();
      const list = Array.isArray(data) ? data : data.products ?? data.data ?? [];
      if (list.length > 0) set({ products: list });
    } catch {
      // mock 유지
    } finally {
      set({ loading: false });
    }
  },

  /* ── 카테고리 (트리 구조) ── */
  categories: mockCategories,
  addCategory: (parentId, category) =>
    set((s) => ({
      categories: addToTree(s.categories, parentId, { ...category, id: `cat-${Date.now()}`, children: [], productCount: 0 }),
    })),
  updateCategory: (id, data) =>
    set((s) => ({ categories: updateInTree(s.categories, id, data) })),
  deleteCategory: (id) =>
    set((s) => ({ categories: removeFromTree(s.categories, id) })),

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
  addKeyword: (kw) =>
    set((s) => ({ keywords: [...s.keywords, { ...kw, id: `kw-${Date.now()}` }] })),
  updateKeyword: (id, data) =>
    set((s) => ({ keywords: s.keywords.map((k) => (k.id === id ? { ...k, ...data } : k)) })),
  deleteKeyword: (id) =>
    set((s) => ({ keywords: s.keywords.filter((k) => k.id !== id) })),

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
