import { create } from 'zustand';
import { api } from '../api/client';

const useDbAdminStore = create((set, get) => ({
  // Loading / Error
  loading: false,
  error: null,

  /* ── 상품 ── */
  products: [],
  productStats: null,
  productPagination: { total: 0, page: 1, per_page: 20, total_pages: 1 },

  addProduct: async (product) => {
    try {
      const result = await api.createProduct(product);
      await get().fetchProducts();
      return result;
    } catch (err) {
      set({ error: `상품 추가 실패: ${err.message}` });
      throw err;
    }
  },
  updateProduct: async (id, data) => {
    try {
      await api.updateProduct(id, data);
      await get().fetchProducts();
    } catch (err) {
      set({ error: `상품 수정 실패: ${err.message}` });
      throw err;
    }
  },
  deleteProduct: async (id) => {
    try {
      await api.deleteProduct(id);
      await get().fetchProducts();
    } catch (err) {
      set({ error: `상품 삭제 실패: ${err.message}` });
      throw err;
    }
  },
  bulkDeleteProducts: async (ids) => {
    try {
      await api.bulkDeleteProducts(ids);
      await get().fetchProducts();
    } catch (err) {
      set({ error: `일괄 삭제 실패: ${err.message}` });
      throw err;
    }
  },
  bulkUpdateCategory: async (ids, categoryId) => {
    try {
      await api.bulkUpdateCategory(ids, categoryId);
      await get().fetchProducts();
    } catch (err) {
      set({ error: `일괄 카테고리 변경 실패: ${err.message}` });
      throw err;
    }
  },

  fetchProducts: async (params = {}) => {
    set({ loading: true, error: null });
    try {
      const data = await api.getProducts(params);
      const items = data.items ?? (Array.isArray(data) ? data : []);
      const mapped = items.map((p) => ({
        ...p,
        category: p.category_name || p.category || p.category_id || '',
        basePrice: p.basePrice ?? p.base_price ?? p.original_price ?? 0,
        currentAvg: p.currentAvg ?? p.current_avg ?? p.current_price ?? 0,
        currentPrice: p.current_price ?? 0,
        originalPrice: p.original_price ?? 0,
        discountRate: p.discount_rate ?? 0,
        tier: p.tier || 'good',
      }));
      set({
        products: mapped,
        productPagination: {
          total: data.total ?? mapped.length,
          page: data.page ?? 1,
          per_page: data.per_page ?? 20,
          total_pages: data.total_pages ?? 1,
        },
      });
    } catch {
      set({ products: [], error: '⚠️ 데이터를 불러올 수 없습니다' });
    } finally {
      set({ loading: false });
    }
  },

  fetchProductStats: async () => {
    try {
      const data = await api.getProductStats();
      set({ productStats: data });
    } catch {
      // stats are optional, don't show error
    }
  },

  /* ── 카테고리 (트리 구조) ── */
  categories: [],
  addCategory: async (parentId, category) => {
    const autoId = category.id || `cat-${category.name.replace(/\s+/g, '-')}-${Date.now()}`;
    try {
      await api.createCategory({ ...category, id: autoId, parent_id: parentId });
      await get().fetchCategories();
    } catch (err) {
      set({ error: `카테고리 추가 실패: ${err.message}` });
    }
  },
  updateCategory: async (id, data) => {
    try {
      await api.updateCategory(id, data);
      await get().fetchCategories();
    } catch (err) {
      set({ error: `카테고리 수정 실패: ${err.message}` });
    }
  },
  deleteCategory: async (id) => {
    try {
      await api.deleteCategory(id);
      await get().fetchCategories();
    } catch (err) {
      set({ error: `카테고리 삭제 실패: ${err.message}` });
    }
  },
  moveCategory: async (id, newParentId) => {
    try {
      await api.moveCategory(id, newParentId);
      await get().fetchCategories();
    } catch (err) {
      set({ error: `카테고리 이동 실패: ${err.message}` });
    }
  },

  fetchCategories: async () => {
    set({ loading: true, error: null });
    try {
      const data = await api.getCategories();
      const list = Array.isArray(data) ? data : data.categories ?? data.data ?? [];
      set({ categories: list });
    } catch (err) {
      set({ error: `카테고리 로드 실패: ${err.message}` });
    } finally {
      set({ loading: false });
    }
  },

  /* ── 키워드 ── */
  keywords: [],
  keywordPagination: { total: 0, page: 1, per_page: 20, total_pages: 1 },
  keywordStats: { total: 0, unused_count: 0 },

  addKeyword: async (kw) => {
    const word = (kw.keyword ?? kw.word ?? '').trim();
    if (!word) return { ok: false };
    const apiData = {
      word,
      synonyms: kw.synonyms || [],
      category_id: (kw.categoryId || kw.category_id) || null,
    };
    try {
      await api.createKeyword(apiData);
      await get().fetchKeywords();
      await get().fetchKeywordStats();
      return { ok: true };
    } catch (err) {
      const msg = err.status === 409
        ? err.message
        : `키워드 추가 실패: ${err.message}`;
      set({ error: msg });
      return { ok: false, status: err.status, message: msg };
    }
  },
  updateKeyword: async (id, data) => {
    const apiData = {};
    if (data.keyword !== undefined) apiData.word = data.keyword;
    if (data.word !== undefined) apiData.word = data.word;
    if (data.synonyms !== undefined) apiData.synonyms = data.synonyms;
    if (data.categoryId !== undefined) apiData.category_id = data.categoryId;
    if (data.category_id !== undefined) apiData.category_id = data.category_id;
    try {
      await api.updateKeyword(id, apiData);
      await get().fetchKeywords();
    } catch (err) {
      set({ error: `키워드 수정 실패: ${err.message}` });
    }
  },
  deleteKeyword: async (id) => {
    try {
      await api.deleteKeyword(id);
      set((s) => ({ keywords: s.keywords.filter((k) => k.id !== id) }));
      await get().fetchKeywordStats();
    } catch (err) {
      set({ error: `키워드 삭제 실패: ${err.message}` });
    }
  },
  bulkDeleteKeywords: async (ids) => {
    try {
      const result = await api.bulkDeleteKeywords(ids);
      await get().fetchKeywords();
      await get().fetchKeywordStats();
      return result;
    } catch (err) {
      set({ error: `벌크 삭제 실패: ${err.message}` });
      return null;
    }
  },

  fetchKeywords: async (params = {}) => {
    set({ loading: true, error: null });
    try {
      const data = await api.getKeywords(params);
      const list = data.items ?? (Array.isArray(data) ? data : data.keywords ?? data.data ?? []);
      const mapped = list.map((kw) => ({
        ...kw,
        keyword: kw.keyword || kw.word || '',
        searchCount: kw.searchCount ?? kw.search_count ?? 0,
        synonyms: kw.synonyms || [],
        categoryId: kw.categoryId || kw.category_id || '',
        productCount: kw.productCount ?? kw.product_count ?? 0,
      }));
      set({
        keywords: mapped,
        keywordPagination: {
          total: data.total ?? mapped.length,
          page: data.page ?? 1,
          per_page: data.per_page ?? 20,
          total_pages: data.total_pages ?? 1,
        },
      });
    } catch (err) {
      set({ error: `키워드 로드 실패: ${err.message}` });
    } finally {
      set({ loading: false });
    }
  },

  fetchKeywordStats: async () => {
    try {
      const data = await api.getKeywordStats();
      set({ keywordStats: data });
    } catch {
      // stats are optional
    }
  },

  /* ── 가격 ── */
  priceHistories: {},
  priceOutliers: [],
  priceTiers: {
    ultra: { label: '초특가', threshold: 70, color: 'var(--tier-ultra)' },
    great: { label: '특가',   threshold: 85, color: 'var(--tier-great)' },
    good:  { label: '적정',   threshold: 105, color: 'var(--tier-good)' },
    wait:  { label: '관망',   threshold: 120, color: 'var(--tier-wait)' },
    bad:   { label: '비쌈',   threshold: Infinity, color: 'var(--tier-bad)' },
  },
  priceStats: null,
  priceHistoryPage: { items: [], total: 0, page: 1, per_page: 50, total_pages: 0 },
  tierSaving: false,

  updatePriceTier: (tier, threshold) =>
    set((s) => ({
      priceTiers: { ...s.priceTiers, [tier]: { ...s.priceTiers[tier], threshold } },
    })),

  fetchTierConfig: async () => {
    try {
      const data = await api.getTierConfig();
      if (data && typeof data === 'object') {
        const tiers = {};
        for (const [k, v] of Object.entries(data)) {
          tiers[k] = { ...v, threshold: v.threshold === null ? Infinity : v.threshold };
        }
        set({ priceTiers: tiers });
      }
    } catch {
      // 기본값 유지
    }
  },

  saveTierConfig: async () => {
    set({ tierSaving: true });
    try {
      const tiers = { ...get().priceTiers };
      const payload = {};
      for (const [k, v] of Object.entries(tiers)) {
        payload[k] = { ...v, threshold: v.threshold === Infinity ? null : v.threshold };
      }
      await api.saveTierConfig(payload);
      return true;
    } catch (err) {
      set({ error: `티어 저장 실패: ${err.message}` });
      return false;
    } finally {
      set({ tierSaving: false });
    }
  },

  whitelistOutlier: async (id) => {
    try {
      await api.whitelistOutlier(id);
      await get().fetchOutliers();
    } catch (err) {
      set({ error: `화이트리스트 추가 실패: ${err.message}` });
      throw err;
    }
  },

  fetchOutliers: async (limit = 20) => {
    try {
      const data = await api.getGlobalOutliers(limit);
      const list = Array.isArray(data) ? data : [];
      set({ priceOutliers: list });
    } catch {
      set({ priceOutliers: [] });
    }
  },

  fetchPriceHistory: async (params = {}) => {
    try {
      const data = await api.getPriceHistory(params);
      set({ priceHistoryPage: data || { items: [], total: 0, page: 1, per_page: 50, total_pages: 0 } });
    } catch {
      set({ priceHistoryPage: { items: [], total: 0, page: 1, per_page: 50, total_pages: 0 } });
    }
  },

  fetchProductPriceHistory: async (productId, days = 90) => {
    if (!productId) return;
    try {
      const data = await api.getPriceHistory({ product_id: productId, days, per_page: 200 });
      const items = data?.items || [];
      set((s) => ({
        priceHistories: {
          ...s.priceHistories,
          [productId]: items.map((i) => ({ date: i.date, price: i.price, source: i.source })),
        },
      }));
    } catch {
      // 이력 없음
    }
  },

  fetchPriceStats: async () => {
    try {
      const data = await api.getPriceStats();
      set({ priceStats: data });
    } catch {
      set({ priceStats: null });
    }
  },

  /* ── 분석 ── */
  categoryAvgPrices: [],
  qualityReport: { outliers: 0, duplicates: 0, missingFields: 0, totalRecords: 0, completeness: 0, accuracy: 0, fieldCompleteness: 0, priceCoverage: 0, categoryRate: 0 },
  sourceStats: [],

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
            fieldCompleteness: quality.field_completeness ?? 0,
            priceCoverage: quality.price_coverage ?? 0,
            categoryRate: quality.category_rate ?? 0,
          },
        });
      }
      if (summaryData.status === 'fulfilled' && summaryData.value) {
        const s = summaryData.value;
        if (s.categoryAvgPrices) set({ categoryAvgPrices: s.categoryAvgPrices });
        if (s.sourceStats) set({ sourceStats: s.sourceStats });
      }
    } catch (err) {
      set({ error: `분석 데이터 로드 실패: ${err.message}` });
    } finally {
      set({ loading: false });
    }
  },

  /* ── 대시보드 ── */
  dashboardStats: {
    totalProducts: 0,
    totalPriceRecords: 0,
    totalCategories: 0,
    totalKeywords: 0,
    lastUpdated: null,
    qualityScore: 0,
    qualityDetails: { fillRate: 0, dupRate: 0, noCategoryRate: 0 },
    recentIngestions: [],
    alerts: [],
    freshness: [],
    changes: { products: 0, priceRecords: 0, categories: 0, keywords: 0 },
  },

  fetchDashboard: async () => {
    set({ loading: true, error: null });
    try {
      const data = await api.getDashboardStats();
      if (data) {
        set({
          dashboardStats: {
            totalProducts: data.totalProducts ?? 0,
            totalPriceRecords: data.totalPriceRecords ?? 0,
            totalCategories: data.totalCategories ?? 0,
            totalKeywords: data.totalKeywords ?? 0,
            lastUpdated: data.lastUpdated ?? null,
            qualityScore: data.qualityScore ?? 0,
            qualityDetails: data.qualityDetails ?? { fillRate: 0, dupRate: 0, noCategoryRate: 0 },
            recentIngestions: data.recentIngestions ?? [],
            alerts: data.alerts ?? [],
            freshness: data.freshness ?? [],
            changes: data.changes ?? { products: 0, priceRecords: 0, categories: 0, keywords: 0 },
          },
        });
      }
    } catch (err) {
      set({ error: `대시보드 로드 실패: ${err.message}` });
    } finally {
      set({ loading: false });
    }
  },

  /* ── Ingestions (수신함) ── */
  ingestions: [],
  selectedIngestion: null,
  ingestionFilter: 'all',
  ingestionStats: { pending: 0, approved: 0, rejected: 0 },
  ingestionPagination: { total: 0, page: 1, per_page: 20, total_pages: 1 },

  fetchIngestions: async (params = {}) => {
    set({ loading: true, error: null });
    try {
      const data = await api.getIngestions(params);
      const list = Array.isArray(data) ? data : data.items ?? data.ingestions ?? data.data ?? [];
      set({
        ingestions: list,
        ingestionPagination: {
          total: data.total ?? list.length,
          page: data.page ?? 1,
          per_page: data.per_page ?? 20,
          total_pages: data.total_pages ?? 1,
        },
      });
    } catch {
      set({ ingestions: [], ingestionPagination: { total: 0, page: 1, per_page: 20, total_pages: 1 } });
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
      // 통계 없음
    }
  },

  reviewIngestion: async (id, reviewData) => {
    set({ loading: true, error: null });
    try {
      const apiData = {
        action: reviewData.action,
        notes: reviewData.notes || reviewData.memo || undefined,
        approved_item_indices: reviewData.approved_item_indices || reviewData.selectedItems || undefined,
        rejected_reason: reviewData.rejected_reason || reviewData.reason || undefined,
      };
      const result = await api.reviewIngestion(id, apiData);
      await get().fetchIngestions();
      return result;
    } catch (err) {
      set({ error: `리뷰 실패: ${err.message}` });
      return null;
    } finally {
      set({ loading: false });
    }
  },

  bulkApproveIngestions: async (ids, reviewer, notes) => {
    set({ loading: true, error: null });
    try {
      const result = await api.bulkApproveIngestions(ids, reviewer, notes);
      await get().fetchIngestions();
      await get().fetchIngestionStats();
      return result;
    } catch (err) {
      set({ error: `벌크 승인 실패: ${err.message}` });
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
