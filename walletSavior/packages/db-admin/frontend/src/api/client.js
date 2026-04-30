import { getAccessToken, logout as authLogout } from '../stores/authStore';

const API_BASE = '/api';

// ─── Timeout defaults (ms) ───
const DEFAULT_TIMEOUT = 15000;
const LONG_TIMEOUT    = 45000;

// ─── 인증 헤더 주입 ───
function injectAuth(options = {}) {
  const token = getAccessToken();
  if (!token) return options;
  return {
    ...options,
    headers: {
      ...options.headers,
      Authorization: `Bearer ${token}`,
    },
  };
}

// ─── 401 응답 시 토큰 갱신 시도, 실패하면 로그아웃 ───
async function handleUnauthorized(resp, url, options, timeoutMs, fetcher) {
  if (resp.status !== 401) return resp;

  // 토큰 갱신 시도
  const refreshToken = sessionStorage.getItem('db_admin_refresh_token');
  if (!refreshToken) { authLogout(); throw new Error('인증이 만료되었습니다.'); }

  const refreshResp = await fetch(`${API_BASE}/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });

  if (!refreshResp.ok) { authLogout(); throw new Error('인증이 만료되었습니다.'); }

  const data = await refreshResp.json();
  sessionStorage.setItem('db_admin_access_token', data.access_token);
  if (data.refresh_token) sessionStorage.setItem('db_admin_refresh_token', data.refresh_token);

  // 갱신된 토큰으로 재시도
  return fetcher(url, injectAuth(options), timeoutMs);
}

// ─── Core: fetch with AbortController timeout ───
function fetchWithTimeout(url, options = {}, timeoutMs = DEFAULT_TIMEOUT) {
  const authedOptions = injectAuth(options);
  const controller = new AbortController();
  const existingSignal = authedOptions.signal;

  if (existingSignal) {
    existingSignal.addEventListener('abort', () => controller.abort(existingSignal.reason));
  }

  const timer = setTimeout(
    () => controller.abort(new DOMException('요청 시간이 초과되었습니다 (15초)', 'TimeoutError')),
    timeoutMs
  );

  const rawFetch = (u, o, t) => {
    const c = new AbortController();
    const tm = setTimeout(() => c.abort(), t);
    return fetch(u, { ...o, signal: c.signal }).finally(() => clearTimeout(tm));
  };

  return fetch(url, { ...authedOptions, signal: controller.signal })
    .finally(() => clearTimeout(timer))
    .then(resp => handleUnauthorized(resp, url, options, timeoutMs, rawFetch));
}

// ─── Retry with exponential backoff (network errors + 5xx only) ───
async function fetchWithRetry(url, options = {}, {
  timeout = DEFAULT_TIMEOUT,
  maxRetries = 3,
  signal,
} = {}) {
  let lastError;

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      return await fetchWithTimeout(url, { ...options, signal }, timeout);
    } catch (err) {
      lastError = err;

      if (err.name === 'AbortError') throw err;

      const isRetryable =
        !err.status ||
        err.status >= 500 ||
        err.status === 408 ||
        err.status === 429;

      if (!isRetryable || attempt === maxRetries) throw err;

      const delay = Math.min(1000 * Math.pow(2, attempt), 4000);
      await new Promise(r => setTimeout(r, delay));
    }
  }

  throw lastError;
}

// ─── Response parser ───
const json = async (r) => {
  if (!r.ok) {
    let data;
    try { data = await r.json(); } catch { data = {}; }
    const msg = data.detail || data.message || data.error?.message || `HTTP ${r.status}`;
    const err = new Error(msg);
    err.status = r.status;
    throw err;
  }
  const text = await r.text();
  return text ? JSON.parse(text) : {};
};

// ─── Method helpers (accept signal + timeout) ───
const get = (url, { signal, timeout, maxRetries = 3 } = {}) =>
  fetchWithRetry(url, { signal }, { timeout, maxRetries, signal }).then(json);

const postJson = (url, data, { signal, timeout } = {}) =>
  fetchWithTimeout(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
    signal,
  }, timeout).then(json);

const putJson = (url, data, { signal, timeout } = {}) =>
  fetchWithTimeout(url, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
    signal,
  }, timeout).then(json);

const del = (url, { signal, timeout } = {}) =>
  fetchWithTimeout(url, { method: 'DELETE', signal }, timeout).then(json);

// 모든 URL에 trailing slash를 사용 — FastAPI의 router.get("/") 패턴과 일치시켜
// 307 리다이렉트로 인한 POST body 손실을 방지한다.
export const api = {
  // Products
  getProducts: (params, opts) => {
    const qs = params ? `?${new URLSearchParams(params)}` : '';
    return get(`${API_BASE}/products/${qs}`, opts);
  },
  getProduct: (id, opts) => get(`${API_BASE}/products/${id}`, opts),
  getProductStats: (opts) => get(`${API_BASE}/products/stats`, opts),
  getProductHistory: (id, days = 30, opts) =>
    get(`${API_BASE}/products/${id}/history?days=${days}`, opts),
  getProductComparison: (id, opts) =>
    get(`${API_BASE}/products/${id}/comparison`, opts),
  getProductSimilar: (id, limit = 10, opts) =>
    get(`${API_BASE}/products/${id}/similar?limit=${limit}`, opts),
  createProduct: (data, opts) => postJson(`${API_BASE}/products/`, data, opts),
  updateProduct: (id, data, opts) => putJson(`${API_BASE}/products/${id}`, data, opts),
  deleteProduct: (id, opts) => del(`${API_BASE}/products/${id}`, opts),
  bulkDeleteProducts: (ids, opts) =>
    postJson(`${API_BASE}/products/bulk-delete`, { ids }, opts),
  bulkUpdateCategory: (ids, categoryId, opts) =>
    postJson(`${API_BASE}/products/bulk-category`, { ids, category_id: categoryId }, opts),
  // Categories
  getCategories: (opts) => get(`${API_BASE}/categories/`, opts),
  createCategory: (data, opts) => postJson(`${API_BASE}/categories/`, data, opts),
  updateCategory: (id, data, opts) => putJson(`${API_BASE}/categories/${id}`, data, opts),
  deleteCategory: (id, opts) => del(`${API_BASE}/categories/${id}`, opts),
  moveCategory: (id, newParentId, opts) =>
    putJson(`${API_BASE}/categories/${id}/move`, { new_parent_id: newParentId }, opts),
  getCategoryProducts: (id, opts) =>
    get(`${API_BASE}/categories/${id}/products`, opts),
  getCategoryProductCount: (id, opts) =>
    get(`${API_BASE}/categories/${id}/product-count`, opts),
  // Keywords
  getKeywords: (params, opts) => {
    const qs = params ? `?${new URLSearchParams(params)}` : '';
    return get(`${API_BASE}/keywords/${qs}`, opts);
  },
  getKeywordStats: (opts) => get(`${API_BASE}/keywords/stats`, opts),
  searchKeywords: (q, opts) =>
    get(`${API_BASE}/keywords/search?q=${q}`, opts),
  getPopularKeywords: (opts) => get(`${API_BASE}/keywords/popular`, opts),
  createKeyword: (data, opts) => postJson(`${API_BASE}/keywords/`, data, opts),
  updateKeyword: (id, data, opts) => putJson(`${API_BASE}/keywords/${id}`, data, opts),
  deleteKeyword: (id, opts) => del(`${API_BASE}/keywords/${id}`, opts),
  bulkDeleteKeywords: (ids, opts) =>
    postJson(`${API_BASE}/keywords/bulk-delete`, ids ? { ids } : {}, opts),
  // Analytics — use LONG_TIMEOUT
  getQualityReport: (opts) =>
    get(`${API_BASE}/analytics/quality-report`, { ...opts, timeout: LONG_TIMEOUT }),
  getSummary: (opts) =>
    get(`${API_BASE}/analytics/summary`, { ...opts, timeout: LONG_TIMEOUT }),
  getPriceTrends: (productIds, days = 30, opts) => {
    const params = new URLSearchParams();
    productIds.forEach(id => params.append('product_ids', id));
    params.set('days', days);
    return get(`${API_BASE}/analytics/price-trends?${params}`, { ...opts, timeout: LONG_TIMEOUT });
  },
  getSourceStatsDetail: (opts) =>
    get(`${API_BASE}/analytics/source-stats`, { ...opts, timeout: LONG_TIMEOUT }),
  searchProducts: (q, opts) =>
    get(`${API_BASE}/analytics/products/search?q=${encodeURIComponent(q)}`, opts),
  getSourceDistribution: (opts) =>
    get(`${API_BASE}/analytics/source-distribution`, { ...opts, timeout: LONG_TIMEOUT }),
  getCategoryDistribution: (opts) =>
    get(`${API_BASE}/analytics/category-distribution`, { ...opts, timeout: LONG_TIMEOUT }),
  getDailyTrend: (days = 30, opts) =>
    get(`${API_BASE}/analytics/daily-trend?days=${days}`, { ...opts, timeout: LONG_TIMEOUT }),
  getDataQualitySummary: (opts) =>
    get(`${API_BASE}/analytics/data-quality-summary`, { ...opts, timeout: LONG_TIMEOUT }),
  outlierAction: (id, action, newPrice, opts) =>
    postJson(`${API_BASE}/analytics/outliers/${id}/action`, { action, new_price: newPrice }, opts),
  getSourceTypes: (opts) =>
    get(`${API_BASE}/analytics/source-types`, opts),
  // Dashboard
  getDashboardStats: (opts) => get(`${API_BASE}/dashboard/stats`, opts),
  // Prices
  getPriceStats: (opts) => get(`${API_BASE}/prices/stats`, opts),
  getProductPrices: (id, days = 90, opts) =>
    get(`${API_BASE}/prices/product/${id}?days=${days}`, opts),
  getTierConfig: (opts) => get(`${API_BASE}/prices/tier-config`, opts),
  saveTierConfig: (tiers, opts) => postJson(`${API_BASE}/prices/tier-config`, { tiers }, opts),
  getGlobalOutliers: (limit = 20, opts) =>
    get(`${API_BASE}/prices/outliers?limit=${limit}`, opts),
  getPriceHistory: (params = {}, opts) => {
    const qs = new URLSearchParams(params).toString();
    return get(`${API_BASE}/prices/history?${qs}`, opts);
  },
  whitelistOutlier: (id, opts) =>
    postJson(`${API_BASE}/prices/outliers/${id}/whitelist`, {}, opts),
  getTierPreview: (params = {}, opts) => {
    const qs = new URLSearchParams(params).toString();
    return get(`${API_BASE}/prices/tier-preview?${qs}`, { ...opts, timeout: LONG_TIMEOUT });
  },
  getOutlierDistribution: (productId, days = 90, opts) =>
    get(`${API_BASE}/prices/outliers/${productId}/distribution?days=${days}`, opts),
  // Ingestions (pending queue) — ingestion router는 "" 패턴이라 trailing slash 불필요
  getIngestions: (params, opts) =>
    get(`${API_BASE}/ingestions?${new URLSearchParams(params)}`, opts),
  getIngestion: (id, opts) => get(`${API_BASE}/ingestions/${id}`, opts),
  reviewIngestion: (id, data, opts) =>
    postJson(`${API_BASE}/ingestions/${id}/db-review`, data, opts),
  bulkApproveIngestions: (ids, reviewer, notes, opts) =>
    postJson(`${API_BASE}/ingestions/bulk-approve`, { ids, reviewer, notes }, { ...opts, timeout: LONG_TIMEOUT }),
  getIngestionStats: (opts) => get(`${API_BASE}/ingestions/stats`, opts),
  // Admin
  getDataSummary: (opts) => get(`${API_BASE}/admin/data-summary`, opts),
  resetSource: (source, confirm, opts) =>
    postJson(`${API_BASE}/admin/reset-source`, { source, confirm }, { ...opts, timeout: LONG_TIMEOUT }),
  resetProducts: (confirm, opts) =>
    postJson(`${API_BASE}/admin/reset-products`, { confirm }, { ...opts, timeout: LONG_TIMEOUT }),
  resetAll: (confirm, opts) =>
    postJson(`${API_BASE}/admin/reset-all`, { confirm }, { ...opts, timeout: LONG_TIMEOUT }),
  // Integrity dashboard
  getIntegritySummary: (opts) =>
    get(`${API_BASE}/admin/integrity/summary`, { ...opts, timeout: LONG_TIMEOUT }),
  recheckIntegrity: (check, opts) =>
    postJson(`${API_BASE}/admin/integrity/recheck`, check ? { check } : {}, { ...opts, timeout: LONG_TIMEOUT }),
  repairIntegrity: (check, confirm, opts) =>
    postJson(`${API_BASE}/admin/integrity/repair`, { check, confirm }, { ...opts, timeout: LONG_TIMEOUT }),
};
