import { create } from 'zustand';
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
  /* ── 상품 ── */
  products: mockProducts,
  addProduct: (product) =>
    set((s) => ({ products: [...s.products, { ...product, id: `p-${Date.now()}` }] })),
  updateProduct: (id, data) =>
    set((s) => ({ products: s.products.map((p) => (p.id === id ? { ...p, ...data } : p)) })),
  deleteProduct: (id) =>
    set((s) => ({ products: s.products.filter((p) => p.id !== id) })),

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

  /* ── 대시보드 ── */
  dashboardStats: mockDashboardStats,
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
