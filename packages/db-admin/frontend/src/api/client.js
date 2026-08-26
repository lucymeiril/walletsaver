import { getAccessToken, logout as authLogout } from '../stores/authStore';

const API_BASE = '/api';

const DEFAULT_TIMEOUT = 15000;
const LONG_TIMEOUT = 45000;

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

async function handleUnauthorized(resp, url, options, timeoutMs, fetcher) {
  if (resp.status !== 401) return resp;

  const refreshToken = sessionStorage.getItem('db_admin_refresh_token');
  if (!refreshToken) {
    authLogout();
    throw new Error('인증이 만료되었습니다.');
  }

  const refreshResp = await fetch(`${API_BASE}/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });

  if (!refreshResp.ok) {
    authLogout();
    throw new Error('인증이 만료되었습니다.');
  }

  const data = await refreshResp.json();
  sessionStorage.setItem('db_admin_access_token', data.access_token);
  if (data.refresh_token) {
    sessionStorage.setItem('db_admin_refresh_token', data.refresh_token);
  }

  return fetcher(url, injectAuth(options), timeoutMs);
}

function fetchWithTimeout(url, options = {}, timeoutMs = DEFAULT_TIMEOUT) {
  const authedOptions = injectAuth(options);
  const controller = new AbortController();
  const existingSignal = authedOptions.signal;

  if (existingSignal) {
    existingSignal.addEventListener('abort', () => controller.abort(existingSignal.reason));
  }

  const timer = setTimeout(
    () => controller.abort(new DOMException('요청 시간이 초과되었습니다 (15초)', 'TimeoutError')),
    timeoutMs,
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

function isRetryableStatus(status) {
  return status >= 500 || status === 408 || status === 429;
}

function retryDelayMs(response, attempt) {
  const retryAfter = response?.headers?.get('Retry-After');
  if (retryAfter) {
    const seconds = Number(retryAfter);
    if (Number.isFinite(seconds) && seconds >= 0) {
      return Math.min(seconds * 1000, 10000);
    }
  }
  return Math.min(1000 * Math.pow(2, attempt), 4000);
}

async function fetchWithRetry(url, options = {}, {
  timeout = DEFAULT_TIMEOUT,
  maxRetries = 3,
  signal,
} = {}) {
  let lastError;

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      const response = await fetchWithTimeout(url, { ...options, signal }, timeout);
      if (!isRetryableStatus(response.status) || attempt === maxRetries) {
        return response;
      }

      await new Promise(resolve => setTimeout(resolve, retryDelayMs(response, attempt)));
    } catch (err) {
      lastError = err;
      if (err.name === 'AbortError' && signal?.aborted) throw err;

      const isRetryable =
        !err.status || err.status >= 500 || err.status === 408 || err.status === 429;
      if (!isRetryable || attempt === maxRetries) throw err;

      const delay = Math.min(1000 * Math.pow(2, attempt), 4000);
      await new Promise(resolve => setTimeout(resolve, delay));
    }
  }

  throw lastError || new Error('요청 재시도에 실패했습니다.');
}

const json = async (response) => {
  if (!response.ok) {
    let data;
    try {
      data = await response.json();
    } catch {
      data = {};
    }
    const message = data.detail || data.message || data.error?.message || `HTTP ${response.status}`;
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  const text = await response.text();
  return text ? JSON.parse(text) : {};
};

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

function postFormData(url, formData, { signal, onProgress } = {}) {
  return new Promise((resolve, reject) => {
    const token = getAccessToken();
    const xhr = new XMLHttpRequest();
    xhr.open('POST', url);
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    if (signal) signal.addEventListener('abort', () => xhr.abort());

    if (onProgress && xhr.upload) {
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) {
          onProgress(Math.round((event.loaded / event.total) * 100));
        }
      };
    }

    xhr.onload = () => {
      if (xhr.status === 401) {
        authLogout();
        reject(Object.assign(new Error('인증이 만료되었습니다.'), { status: 401 }));
        return;
      }
      let data;
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        data = {};
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(data);
      } else {
        const message = data.detail || data.message || `HTTP ${xhr.status}`;
        reject(Object.assign(new Error(message), { status: xhr.status, data }));
      }
    };
    xhr.onerror = () => reject(new Error('네트워크 오류가 발생했습니다.'));
    xhr.onabort = () => reject(Object.assign(
      new DOMException('요청이 취소되었습니다.', 'AbortError'),
      { name: 'AbortError' },
    ));
    xhr.send(formData);
  });
}

export const api = {
  getProducts: (params, opts) => {
    const qs = params ? `?${new URLSearchParams(params)}` : '';
    return get(`${API_BASE}/products/${qs}`, opts);
  },
  getProduct: (id, opts) => get(`${API_BASE}/products/${id}`, opts),
  getProductStats: (opts) => get(`${API_BASE}/products/stats`, opts),
  getProductHistory: (id, days = 30, opts) =>
    get(`${API_BASE}/products/${id}/history?days=${days}`, opts),
  getProductComparison: (id, opts) => get(`${API_BASE}/products/${id}/comparison`, opts),
  getProductSimilar: (id, limit = 10, opts) =>
    get(`${API_BASE}/products/${id}/similar?limit=${limit}`, opts),
  createProduct: (data, opts) => postJson(`${API_BASE}/products/`, data, opts),
  updateProduct: (id, data, opts) => putJson(`${API_BASE}/products/${id}`, data, opts),
  deleteProduct: (id, opts) => del(`${API_BASE}/products/${id}`, opts),
  bulkDeleteProducts: (ids, opts) => postJson(`${API_BASE}/products/bulk-delete`, { ids }, opts),
  bulkUpdateCategory: (ids, categoryId, opts) =>
    postJson(`${API_BASE}/products/bulk-category`, { ids, category_id: categoryId }, opts),

  getMatchingRules: (params = {}, opts) => {
    const qs = new URLSearchParams(params).toString();
    return get(`${API_BASE}/matching-rules${qs ? `?${qs}` : ''}`, opts);
  },
  getMatchingRuleStats: (opts) => get(`${API_BASE}/matching-rules/stats`, opts),
  createMatchingRule: (data, opts) => postJson(`${API_BASE}/matching-rules`, data, opts),
  updateMatchingRule: (id, data, opts) => putJson(`${API_BASE}/matching-rules/${id}`, data, opts),
  deleteMatchingRule: (id, opts) => del(`${API_BASE}/matching-rules/${id}`, opts),

  getCategories: (opts) => get(`${API_BASE}/categories/`, opts),
  createCategory: (data, opts) => postJson(`${API_BASE}/categories/`, data, opts),
  updateCategory: (id, data, opts) => putJson(`${API_BASE}/categories/${id}`, data, opts),
  deleteCategory: (id, opts) => del(`${API_BASE}/categories/${id}`, opts),
  moveCategory: (id, newParentId, opts) =>
    putJson(`${API_BASE}/categories/${id}/move`, { new_parent_id: newParentId }, opts),
  getCategoryProducts: (id, opts) => get(`${API_BASE}/categories/${id}/products`, opts),
  getCategoryProductCount: (id, opts) => get(`${API_BASE}/categories/${id}/product-count`, opts),

  getKeywords: (params, opts) => {
    const qs = params ? `?${new URLSearchParams(params)}` : '';
    return get(`${API_BASE}/keywords/${qs}`, opts);
  },
  getKeywordStats: (opts) => get(`${API_BASE}/keywords/stats`, opts),
  searchKeywords: (q, opts) => get(`${API_BASE}/keywords/search?q=${q}`, opts),
  getPopularKeywords: (opts) => get(`${API_BASE}/keywords/popular`, opts),
  createKeyword: (data, opts) => postJson(`${API_BASE}/keywords/`, data, opts),
  updateKeyword: (id, data, opts) => putJson(`${API_BASE}/keywords/${id}`, data, opts),
  deleteKeyword: (id, opts) => del(`${API_BASE}/keywords/${id}`, opts),
  bulkDeleteKeywords: (ids, opts) =>
    postJson(`${API_BASE}/keywords/bulk-delete`, ids ? { ids } : {}, opts),

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
  getSourceTypes: (opts) => get(`${API_BASE}/analytics/source-types`, opts),

  getDashboardStats: (opts) => get(`${API_BASE}/dashboard/stats`, opts),

  getPriceStats: (opts) => get(`${API_BASE}/prices/stats`, opts),
  getProductPrices: (id, days = 90, opts) =>
    get(`${API_BASE}/prices/product/${id}?days=${days}`, opts),
  getTierConfig: (opts) => get(`${API_BASE}/prices/tier-config`, opts),
  saveTierConfig: (tiers, opts) => postJson(`${API_BASE}/prices/tier-config`, { tiers }, opts),
  getGlobalOutliers: (limit = 20, opts) => get(`${API_BASE}/prices/outliers?limit=${limit}`, opts),
  getPriceHistory: (params = {}, opts) => {
    const qs = new URLSearchParams(params).toString();
    return get(`${API_BASE}/prices/history?${qs}`, opts);
  },
  whitelistOutlier: (id, opts) => postJson(`${API_BASE}/prices/outliers/${id}/whitelist`, {}, opts),
  getTierPreview: (params = {}, opts) => {
    const qs = new URLSearchParams(params).toString();
    return get(`${API_BASE}/prices/tier-preview?${qs}`, { ...opts, timeout: LONG_TIMEOUT });
  },
  getOutlierDistribution: (productId, days = 90, opts) =>
    get(`${API_BASE}/prices/outliers/${productId}/distribution?days=${days}`, opts),

  getIngestions: (params, opts) =>
    get(`${API_BASE}/ingestions?${new URLSearchParams(params)}`, opts),
  getIngestion: (id, opts) => get(`${API_BASE}/ingestions/${id}`, opts),
  reviewIngestion: (id, data, opts) =>
    postJson(`${API_BASE}/ingestions/${id}/db-review`, data, opts),
  bulkApproveIngestions: (ids, reviewer, notes, opts) =>
    postJson(
      `${API_BASE}/ingestions/bulk-approve`,
      { ids, reviewer, notes },
      { ...opts, timeout: LONG_TIMEOUT },
    ),
  getIngestionStats: (opts) => get(`${API_BASE}/ingestions/stats`, opts),

  getDataSummary: (opts) => get(`${API_BASE}/admin/data-summary`, opts),
  resetSource: (source, confirm, opts) =>
    postJson(`${API_BASE}/admin/reset-source`, { source, confirm }, { ...opts, timeout: LONG_TIMEOUT }),
  resetProducts: (confirm, opts) =>
    postJson(`${API_BASE}/admin/reset-products`, { confirm }, { ...opts, timeout: LONG_TIMEOUT }),
  resetAll: (confirm, opts) =>
    postJson(`${API_BASE}/admin/reset-all`, { confirm }, { ...opts, timeout: LONG_TIMEOUT }),

  getIntegritySummary: (opts) =>
    get(`${API_BASE}/admin/integrity/summary`, { ...opts, timeout: LONG_TIMEOUT }),
  recheckIntegrity: (check, opts) =>
    postJson(`${API_BASE}/admin/integrity/recheck`, check ? { check } : {}, { ...opts, timeout: LONG_TIMEOUT }),
  repairIntegrity: (check, confirm, opts) =>
    postJson(`${API_BASE}/admin/integrity/repair`, { check, confirm }, { ...opts, timeout: LONG_TIMEOUT }),

  maintenancePurge: (scope, note, opts) =>
    postJson(
      `${API_BASE}/admin/maintenance/purge`,
      { scope, confirm: true, note: note || null },
      { ...opts, timeout: LONG_TIMEOUT },
    ),
  maintenanceMigrate: (revision, opts) =>
    postJson(
      `${API_BASE}/admin/maintenance/migrate`,
      { revision: revision || 'head' },
      { ...opts, timeout: LONG_TIMEOUT },
    ),
  maintenanceIntegrity: (opts) =>
    get(`${API_BASE}/admin/maintenance/integrity`, { ...opts, timeout: LONG_TIMEOUT }),

  getCommunityPosts: (params = {}, opts) =>
    get(`${API_BASE}/community/posts?${new URLSearchParams(params)}`, opts),
  getCommunityPost: (id, opts) => get(`${API_BASE}/community/posts/${id}`, opts),
  deleteCommunityPost: (id, opts) => del(`${API_BASE}/community/posts/${id}`, opts),
  restoreCommunityPost: (id, opts) => postJson(`${API_BASE}/community/posts/${id}/restore`, {}, opts),
  deleteCommunityComment: (id, opts) => del(`${API_BASE}/community/comments/${id}`, opts),
  restoreCommunityComment: (id, opts) => postJson(`${API_BASE}/community/comments/${id}/restore`, {}, opts),
  banCommunityUser: (id, opts) => postJson(`${API_BASE}/community/users/${id}/ban`, {}, opts),
  unbanCommunityUser: (id, opts) => postJson(`${API_BASE}/community/users/${id}/unban`, {}, opts),

  previewImport: (file, mode, { signal, onProgress } = {}) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('mode', mode);
    return postFormData(`${API_BASE}/import/classified/preview`, formData, { signal, onProgress });
  },
  confirmImport: (file, mode, traceId, { signal, onProgress } = {}) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('mode', mode);
    if (traceId) formData.append('trace_id', traceId);
    return postFormData(`${API_BASE}/import/classified/confirm`, formData, { signal, onProgress });
  },
  getImportFailureCsvUrl: (traceId) =>
    `${API_BASE}/import/classified/failure-csv/${traceId}`,

  downloadAuthed: async (url, filename) => {
    const token = getAccessToken();
    const response = await fetch(url, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!response.ok) throw new Error(`다운로드 실패 (HTTP ${response.status})`);
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = objectUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(objectUrl);
  },
};