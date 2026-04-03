const API_BASE = '/api';

const json = async (r) => {
  const data = await r.json();
  if (!r.ok) {
    const msg = data.detail || data.message || `HTTP ${r.status}`;
    const err = new Error(msg);
    err.status = r.status;
    throw err;
  }
  return data;
};
const postJson = (url, data) =>
  fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }).then(json);
const putJson = (url, data) =>
  fetch(url, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }).then(json);
const del = (url) => fetch(url, { method: 'DELETE' }).then(json);

// 모든 URL에 trailing slash를 사용 — FastAPI의 router.get("/") 패턴과 일치시켜
// 307 리다이렉트로 인한 POST body 손실을 방지한다.
export const api = {
  // Products
  getProducts: (params) => {
    const qs = params ? `?${new URLSearchParams(params)}` : '';
    return fetch(`${API_BASE}/products/${qs}`).then(json);
  },
  getProduct: (id) => fetch(`${API_BASE}/products/${id}`).then(json),
  getProductStats: () => fetch(`${API_BASE}/products/stats`).then(json),
  getProductHistory: (id, days = 30) => fetch(`${API_BASE}/products/${id}/history?days=${days}`).then(json),
  getProductComparison: (id) => fetch(`${API_BASE}/products/${id}/comparison`).then(json),
  getProductSimilar: (id, limit = 10) => fetch(`${API_BASE}/products/${id}/similar?limit=${limit}`).then(json),
  createProduct: (data) => postJson(`${API_BASE}/products/`, data),
  updateProduct: (id, data) => putJson(`${API_BASE}/products/${id}`, data),
  deleteProduct: (id) => del(`${API_BASE}/products/${id}`),
  bulkDeleteProducts: (ids) => postJson(`${API_BASE}/products/bulk-delete`, { ids }),
  bulkUpdateCategory: (ids, categoryId) => postJson(`${API_BASE}/products/bulk-category`, { ids, category_id: categoryId }),
  // Categories
  getCategories: () => fetch(`${API_BASE}/categories/`).then(json),
  createCategory: (data) => postJson(`${API_BASE}/categories/`, data),
  updateCategory: (id, data) => putJson(`${API_BASE}/categories/${id}`, data),
  deleteCategory: (id) => del(`${API_BASE}/categories/${id}`),
  moveCategory: (id, newParentId) => putJson(`${API_BASE}/categories/${id}/move`, { new_parent_id: newParentId }),
  getCategoryProducts: (id) => fetch(`${API_BASE}/categories/${id}/products`).then(json),
  getCategoryProductCount: (id) => fetch(`${API_BASE}/categories/${id}/product-count`).then(json),
  // Keywords
  getKeywords: (params) => {
    const qs = params ? `?${new URLSearchParams(params)}` : '';
    return fetch(`${API_BASE}/keywords/${qs}`).then(json);
  },
  getKeywordStats: () => fetch(`${API_BASE}/keywords/stats`).then(json),
  searchKeywords: (q) => fetch(`${API_BASE}/keywords/search?q=${q}`).then(json),
  getPopularKeywords: () => fetch(`${API_BASE}/keywords/popular`).then(json),
  createKeyword: (data) => postJson(`${API_BASE}/keywords/`, data),
  updateKeyword: (id, data) => putJson(`${API_BASE}/keywords/${id}`, data),
  deleteKeyword: (id) => del(`${API_BASE}/keywords/${id}`),
  bulkDeleteKeywords: (ids) => postJson(`${API_BASE}/keywords/bulk-delete`, ids ? { ids } : {}),
  // Analytics
  getQualityReport: () => fetch(`${API_BASE}/analytics/quality-report`).then(json),
  getSummary: () => fetch(`${API_BASE}/analytics/summary`).then(json),
  getPriceTrends: (productIds, days = 30) => {
    const params = new URLSearchParams();
    productIds.forEach(id => params.append('product_ids', id));
    params.set('days', days);
    return fetch(`${API_BASE}/analytics/price-trends?${params}`).then(json);
  },
  getSourceStatsDetail: () => fetch(`${API_BASE}/analytics/source-stats`).then(json),
  searchProducts: (q) => fetch(`${API_BASE}/analytics/products/search?q=${encodeURIComponent(q)}`).then(json),
  // Dashboard
  getDashboardStats: () => fetch(`${API_BASE}/dashboard/stats`).then(json),
  // Prices
  getPriceStats: () => fetch(`${API_BASE}/prices/stats`).then(json),
  getProductPrices: (id, days = 90) => fetch(`${API_BASE}/prices/product/${id}?days=${days}`).then(json),
  getTierConfig: () => fetch(`${API_BASE}/prices/tier-config`).then(json),
  saveTierConfig: (tiers) => postJson(`${API_BASE}/prices/tier-config`, { tiers }),
  getGlobalOutliers: (limit = 20) => fetch(`${API_BASE}/prices/outliers?limit=${limit}`).then(json),
  getPriceHistory: (params = {}) => {
    const qs = new URLSearchParams(params).toString();
    return fetch(`${API_BASE}/prices/history?${qs}`).then(json);
  },
  whitelistOutlier: (id) => postJson(`${API_BASE}/prices/outliers/${id}/whitelist`, {}),
  getTierPreview: (params = {}) => {
    const qs = new URLSearchParams(params).toString();
    return fetch(`${API_BASE}/prices/tier-preview?${qs}`).then(json);
  },
  getOutlierDistribution: (productId, days = 90) =>
    fetch(`${API_BASE}/prices/outliers/${productId}/distribution?days=${days}`).then(json),
  // Ingestions (pending queue) — ingestion router는 "" 패턴이라 trailing slash 불필요
  getIngestions: (params) => fetch(`${API_BASE}/ingestions?${new URLSearchParams(params)}`).then(json),
  getIngestion: (id) => fetch(`${API_BASE}/ingestions/${id}`).then(json),
  reviewIngestion: (id, data) => postJson(`${API_BASE}/ingestions/${id}/db-review`, data),
  bulkApproveIngestions: (ids, reviewer, notes) => postJson(`${API_BASE}/ingestions/bulk-approve`, { ids, reviewer, notes }),
  getIngestionStats: () => fetch(`${API_BASE}/ingestions/stats`).then(json),
};
