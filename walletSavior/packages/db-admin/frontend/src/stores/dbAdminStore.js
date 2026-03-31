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
    // 백엔드 CategoryCreate 스키마에는 id가 필수 — 이름 기반으로 자동 생성
    const autoId = category.id || `cat-${category.name.replace(/\s+/g, '-')}-${Date.now()}`;
    try {
      await api.createCategory({ ...category, id: autoId, parent_id: parentId });
      await get().fetchCategories();
    } catch {
      set((s) => ({
        categories: addToTree(s.categories, parentId, { ...category, id: autoId, children: [], productCount: 0 }),
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
    // 프론트엔드 필드명 → 백엔드 필드명 변환
    const word = (kw.keyword ?? kw.word ?? '').trim();
    if (!word) return;
    const apiData = {
      word,
      synonyms: kw.synonyms || [],
      category_id: (kw.categoryId || kw.category_id) || null,
    };
    try {
      await api.createKeyword(apiData);
      await get().fetchKeywords();
    } catch {
      set((s) => ({ keywords: [...s.keywords, { ...kw, id: `kw-${Date.now()}` }] }));
    }
  },
  updateKeyword: async (id, data) => {
    // 프론트엔드 필드명 → 백엔드 필드명 변환
    const apiData = {};
    if (data.keyword !== undefined) apiData.word = data.keyword;
    if (data.word !== undefined) apiData.word = data.word;
    if (data.synonyms !== undefined) apiData.synonyms = data.synonyms;
    if (data.categoryId !== undefined) apiData.category_id = data.categoryId;
    if (data.category_id !== undefined) apiData.category_id = data.category_id;
    try {
      await api.updateKeyword(id, apiData);
      await get().fetchKeywords();
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

  fetchKeywords: async () => {
    try {
      const data = await api.getKeywords();
      const list = Array.isArray(data) ? data : data.keywords ?? data.data ?? [];
      // 백엔드 필드명 → 프론트엔드 필드명 변환
      const mapped = list.map((kw) => ({
        ...kw,
        keyword: kw.keyword || kw.word || '',
        searchCount: kw.searchCount ?? kw.search_count ?? 0,
        synonyms: kw.synonyms || [],
        categoryId: kw.categoryId || kw.category_id || '',
      }));
      if (mapped.length > 0) set({ keywords: mapped });
    } catch {
      // mock 유지
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
        const qr = qualityData.value;
        // API 응답 → 프론트엔드 형식 변환
        const counts = qr.counts || {};
        const quality = qr.quality || {};
        const totalRecords = counts.baseline_prices ?? counts.products ?? qr.totalRecords ?? 0;
        set({
          qualityReport: {
            totalRecords,
            outliers: quality.outliers ?? qr.outliers ?? 0,
            duplicates: quality.duplicates ?? qr.duplicates ?? 0,
            missingFields: quality.products_without_prices ?? quality.missingFields ?? qr.missingFields ?? 0,
            completeness: quality.completeness ?? qr.completeness ?? (totalRecords > 0 ? 95 : 0),
            accuracy: quality.accuracy ?? qr.accuracy ?? (totalRecords > 0 ? 90 : 0),
          },
        });
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
        // API 필드명 → 프론트엔드 필드명 변환
        set({
          dashboardStats: {
            ...get().dashboardStats,
            totalProducts: s.totalProducts ?? s.products ?? products.length ?? get().dashboardStats.totalProducts,
            totalPriceRecords: s.totalPriceRecords ?? s.baseline_prices ?? get().dashboardStats.totalPriceRecords,
            totalCategories: s.totalCategories ?? s.categories ?? get().dashboardStats.totalCategories,
            totalKeywords: s.totalKeywords ?? s.keywords ?? get().dashboardStats.totalKeywords,
            lastUpdated: s.lastUpdated ?? s.generated_at ?? new Date().toISOString(),
            qualityScore: s.qualityScore ?? s.quality_score ?? get().dashboardStats.qualityScore,
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
      const list = Array.isArray(data) ? data : data.items ?? data.ingestions ?? data.data ?? [];
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
      if (data) {
        set({
          ingestionStats: {
            pending: data.pending ?? data.total_pending ?? 0,
            approved: data.approved ?? data.total_approved ?? 0,
            rejected: data.rejected ?? data.total_rejected ?? 0,
          },
        });
      }
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
