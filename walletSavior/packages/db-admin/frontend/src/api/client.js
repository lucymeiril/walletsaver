const API_BASE = 'http://localhost:8002/api';

export const api = {
  // Products
  getProducts: () => fetch(`${API_BASE}/products`).then(r => r.json()),
  getProduct: (id) => fetch(`${API_BASE}/products/${id}`).then(r => r.json()),
  createProduct: (data) => fetch(`${API_BASE}/products`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }).then(r => r.json()),
  // Categories
  getCategories: () => fetch(`${API_BASE}/categories`).then(r => r.json()),
  // Keywords
  searchKeywords: (q) => fetch(`${API_BASE}/keywords/search?q=${q}`).then(r => r.json()),
  getPopularKeywords: () => fetch(`${API_BASE}/keywords/popular`).then(r => r.json()),
  // Analytics
  getQualityReport: () => fetch(`${API_BASE}/analytics/quality-report`).then(r => r.json()),
  getSummary: () => fetch(`${API_BASE}/analytics/summary`).then(r => r.json()),
  // Ingestions (pending queue)
  getIngestions: (params) => fetch(`${API_BASE}/ingestions?${new URLSearchParams(params)}`).then(r => r.json()),
  getIngestion: (id) => fetch(`${API_BASE}/ingestions/${id}`).then(r => r.json()),
  reviewIngestion: (id, data) => fetch(`${API_BASE}/ingestions/${id}/db-review`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }).then(r => r.json()),
  getIngestionStats: () => fetch(`${API_BASE}/ingestions/stats`).then(r => r.json()),
};
