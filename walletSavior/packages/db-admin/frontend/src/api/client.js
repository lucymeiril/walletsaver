const API_BASE = '/api';

const json = (r) => r.json();
const postJson = (url, data) =>
  fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }).then(json);
const putJson = (url, data) =>
  fetch(url, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }).then(json);
const del = (url) => fetch(url, { method: 'DELETE' }).then(json);

export const api = {
  // Products
  getProducts: () => fetch(`${API_BASE}/products`).then(json),
  getProduct: (id) => fetch(`${API_BASE}/products/${id}`).then(json),
  createProduct: (data) => postJson(`${API_BASE}/products`, data),
  updateProduct: (id, data) => putJson(`${API_BASE}/products/${id}`, data),
  deleteProduct: (id) => del(`${API_BASE}/products/${id}`),
  // Categories
  getCategories: () => fetch(`${API_BASE}/categories`).then(json),
  createCategory: (data) => postJson(`${API_BASE}/categories`, data),
  updateCategory: (id, data) => putJson(`${API_BASE}/categories/${id}`, data),
  deleteCategory: (id) => del(`${API_BASE}/categories/${id}`),
  // Keywords
  getKeywords: () => fetch(`${API_BASE}/keywords`).then(json),
  searchKeywords: (q) => fetch(`${API_BASE}/keywords/search?q=${q}`).then(json),
  getPopularKeywords: () => fetch(`${API_BASE}/keywords/popular`).then(json),
  createKeyword: (data) => postJson(`${API_BASE}/keywords`, data),
  updateKeyword: (id, data) => putJson(`${API_BASE}/keywords/${id}`, data),
  deleteKeyword: (id) => del(`${API_BASE}/keywords/${id}`),
  // Analytics
  getQualityReport: () => fetch(`${API_BASE}/analytics/quality-report`).then(json),
  getSummary: () => fetch(`${API_BASE}/analytics/summary`).then(json),
  // Ingestions (pending queue)
  getIngestions: (params) => fetch(`${API_BASE}/ingestions?${new URLSearchParams(params)}`).then(json),
  getIngestion: (id) => fetch(`${API_BASE}/ingestions/${id}`).then(json),
  reviewIngestion: (id, data) => postJson(`${API_BASE}/ingestions/${id}/db-review`, data),
  getIngestionStats: () => fetch(`${API_BASE}/ingestions/stats`).then(json),
};
