# DB Admin — Frontend Resilience Implementation Spec

> **Date:** 2025-07-18  
> **Source Audits:** `db-admin-stability-audit.md` (H-5, H-6, M-2, L-2), `db-admin-concurrency-audit.md` (§5)  
> **Scope:** `packages/db-admin/frontend/src/` — React 19 + Zustand 5 + React Router 6  
> **Goal:** Zero unhandled crashes, no infinite spinners, graceful degradation on network failure

---

## Table of Contents

1. [Error Boundaries](#1-error-boundaries)
2. [AbortController + Fetch Timeout](#2-abortcontroller--fetch-timeout)
3. [Loading States](#3-loading-states)
4. [Empty States](#4-empty-states)
5. [Retry on Network Error](#5-retry-on-network-error)
6. [Stale Data Detection](#6-stale-data-detection)
7. [File Change Summary](#7-file-change-summary)
8. [Implementation Order](#8-implementation-order)

---

## Current State Summary

| Feature | Status | Key Gap |
|---------|--------|---------|
| Error Boundary | ❌ None | Component error → full app crash |
| Fetch Timeout | ❌ None | Hung request → infinite spinner |
| AbortController | ❌ None | Navigation → orphaned requests updating unmounted state |
| Loading States | ⚠️ Partial | Global `loading` flag shared across all pages — races possible |
| Empty States | ⚠️ Partial | Products ✅, others show blank space |
| Retry | ❌ None | Single network glitch → permanent failure |
| Stale Data | ❌ None | No `lastUpdated` timestamps, no auto-refresh |

---

## 1. Error Boundaries

### Audit References
- **H-5** (stability audit): "No React ErrorBoundary wraps any page or component"
- **5.4** (concurrency audit): "A rendering error in any component crashes the entire app"
- **L-2** (stability audit): "Lazy-loaded chunk fails → loader shows indefinitely"

### 1.1 Create `ErrorBoundary` Component

**New file:** `src/components/ErrorBoundary.jsx`

```jsx
import { Component } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error('[ErrorBoundary]', error, errorInfo);
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
    this.props.onReset?.();
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback({
          error: this.state.error,
          resetErrorBoundary: this.handleReset,
        });
      }

      return (
        <div style={{
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          justifyContent: 'center', minHeight: '40vh', gap: '1rem',
          padding: '2rem', color: 'var(--text2, #555)',
        }}>
          <AlertTriangle size={48} color="var(--danger, #e74c3c)" />
          <h2 style={{ margin: 0 }}>오류가 발생했습니다</h2>
          <p style={{ margin: 0, color: 'var(--text3, #888)', textAlign: 'center', maxWidth: 400 }}>
            {this.props.message || '페이지를 표시하는 중 문제가 발생했습니다. 다시 시도해 주세요.'}
          </p>
          {import.meta.env.DEV && this.state.error && (
            <pre style={{
              background: 'var(--bg2, #f5f5f5)', padding: '0.75rem 1rem',
              borderRadius: 8, fontSize: '0.8rem', maxWidth: '100%',
              overflow: 'auto', whiteSpace: 'pre-wrap',
            }}>
              {this.state.error.message}
            </pre>
          )}
          <button
            onClick={this.handleReset}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: '0.5rem',
              padding: '0.6rem 1.2rem', borderRadius: 8, border: 'none',
              background: 'var(--primary, #3b82f6)', color: '#fff',
              cursor: 'pointer', fontSize: '0.95rem',
            }}
          >
            <RefreshCw size={16} />
            다시 시도
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
```

### 1.2 Wrap App.jsx — Global + Per-Route Boundaries

**Modify:** `src/App.jsx`

```jsx
import { Routes, Route, Navigate } from 'react-router-dom';
import { lazy, Suspense } from 'react';
import AdminLayout from './layouts/AdminLayout';
import ErrorBoundary from './components/ErrorBoundary';

const Dashboard          = lazy(() => import('./pages/Dashboard/Dashboard'));
const Products           = lazy(() => import('./pages/Products/Products'));
const Prices             = lazy(() => import('./pages/Prices/Prices'));
const ClassificationPage = lazy(() => import('./pages/Classification/ClassificationPage'));
const Analytics          = lazy(() => import('./pages/Analytics/Analytics'));
const InboxPage          = lazy(() => import('./pages/Inbox/InboxPage'));

function Loader() {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      minHeight: '40vh', color: 'var(--text3)',
    }}>
      로딩 중...
    </div>
  );
}

// Per-page boundary wrapper — isolates crashes to a single page
function PageBoundary({ children }) {
  return (
    <ErrorBoundary>
      <Suspense fallback={<Loader />}>
        {children}
      </Suspense>
    </ErrorBoundary>
  );
}

export default function App() {
  return (
    // Global boundary — catches layout-level errors
    <ErrorBoundary message="애플리케이션에 심각한 오류가 발생했습니다.">
      <Suspense fallback={<Loader />}>
        <Routes>
          <Route element={<AdminLayout />}>
            <Route path="/"               element={<PageBoundary><Dashboard /></PageBoundary>} />
            <Route path="/inbox"          element={<PageBoundary><InboxPage /></PageBoundary>} />
            <Route path="/products"       element={<PageBoundary><Products /></PageBoundary>} />
            <Route path="/prices"         element={<PageBoundary><Prices /></PageBoundary>} />
            <Route path="/classification" element={<PageBoundary><ClassificationPage /></PageBoundary>} />
            <Route path="/categories"     element={<Navigate to="/classification" replace />} />
            <Route path="/keywords"       element={<Navigate to="/classification" replace />} />
            <Route path="/analytics"      element={<PageBoundary><Analytics /></PageBoundary>} />
          </Route>
        </Routes>
      </Suspense>
    </ErrorBoundary>
  );
}
```

### Design Decisions
- **Class component** required — React Error Boundaries cannot be function components.
- **Two-tier boundary:** Global (catches AdminLayout/router errors) + per-route (isolates page crashes so sidebar remains functional).
- **Dev-only stack trace** — `import.meta.env.DEV` guard ensures production users see only the Korean message.
- **No `react-error-boundary` dependency** — zero new packages; the project uses React 19 which supports class components.
- **`onReset` prop** — pages can pass a callback to re-fetch data after recovery.

---

## 2. AbortController + Fetch Timeout

### Audit References
- **H-6** (stability audit): "No AbortController timeout — requests hang indefinitely"
- **5.1** (concurrency audit): "fetch() has no AbortController timeout"
- **5.2** (concurrency audit): "No retry logic — transient network errors immediately fail"
- **5.3** (concurrency audit): "No request cancellation on navigation"

### 2.1 Rewrite `api/client.js` — Resilient Fetch Layer

**Modify:** `src/api/client.js`

```javascript
const API_BASE = '/api';

// ─── Timeout defaults (ms) ───
const DEFAULT_TIMEOUT = 15000;   // 15s for normal API calls
const LONG_TIMEOUT    = 45000;   // 45s for analytics / exports / bulk ops

// ─── Core: fetch with AbortController timeout ───
function fetchWithTimeout(url, options = {}, timeoutMs = DEFAULT_TIMEOUT) {
  const controller = new AbortController();
  const existingSignal = options.signal;

  // Merge caller's signal (for navigation cancel) with timeout signal
  if (existingSignal) {
    existingSignal.addEventListener('abort', () => controller.abort(existingSignal.reason));
  }

  const timer = setTimeout(
    () => controller.abort(new DOMException('요청 시간이 초과되었습니다 (15초)', 'TimeoutError')),
    timeoutMs
  );

  return fetch(url, { ...options, signal: controller.signal })
    .finally(() => clearTimeout(timer));
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
const get = (url, { signal, timeout } = {}) =>
  fetchWithTimeout(url, { signal }, timeout).then(json);

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

// ─── API endpoints ───
// All endpoints accept an optional last argument: { signal, timeout }
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

  // Ingestions
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
};
```

### 2.2 Create `useAbortController` Hook

**New file:** `src/hooks/useAbortController.js`

```javascript
import { useEffect, useRef, useCallback } from 'react';

/**
 * 컴포넌트 언마운트 또는 의존성 변경 시 진행 중인 fetch 요청을 자동 취소하는 훅.
 *
 * Usage:
 *   const getSignal = useAbortController([page, filter]);
 *   useEffect(() => {
 *     fetchProducts(params, { signal: getSignal() });
 *   }, [page, filter]);
 */
export function useAbortController(deps = []) {
  const controllerRef = useRef(null);

  const getSignal = useCallback(() => {
    if (controllerRef.current) {
      controllerRef.current.abort();
    }
    controllerRef.current = new AbortController();
    return controllerRef.current.signal;
  }, []);

  useEffect(() => {
    return () => {
      if (controllerRef.current) {
        controllerRef.current.abort();
      }
    };
  }, deps); // eslint-disable-line react-hooks/exhaustive-deps

  return getSignal;
}
```

### 2.3 Integration Pattern: Store Actions Accept `signal`

**Change pattern in `stores/dbAdminStore.js`:**

Every store action that calls `api.*` must forward `{ signal }` as the final argument. Example diff for `fetchProducts`:

```javascript
// BEFORE
fetchProducts: async (params = {}) => {
  set({ loading: true, error: null });
  try {
    const data = await api.getProducts(params);
    // ...
  } catch { /* ... */ }
  finally { set({ loading: false }); }
},

// AFTER
fetchProducts: async (params = {}, { signal } = {}) => {
  set({ loading: true, error: null });
  try {
    const data = await api.getProducts(params, { signal });
    // ...
  } catch (err) {
    if (err.name === 'AbortError') return;   // navigated away — do nothing
    set({ products: [], error: '⚠️ 데이터를 불러올 수 없습니다' });
  } finally {
    set({ loading: false });
  }
},
```

**Apply this pattern to ALL 18 fetch actions:**

| Store Action | signal arg? | AbortError guard? |
|---|---|---|
| `fetchProducts` | ✅ Add | ✅ Add |
| `fetchProductStats` | ✅ Add | ✅ Add |
| `fetchCategories` | ✅ Add | ✅ Add |
| `fetchKeywords` | ✅ Add | ✅ Add |
| `fetchKeywordStats` | ✅ Add | ✅ Add |
| `fetchOutliers` | ✅ Add | ✅ Add |
| `fetchPriceHistory` | ✅ Add | ✅ Add |
| `fetchProductPriceHistory` | ✅ Add | ✅ Add |
| `fetchPriceStats` | ✅ Add | ✅ Add |
| `fetchTierConfig` | ✅ Add | ✅ Add |
| `fetchAnalytics` | ✅ Add | ✅ Add |
| `fetchDashboard` | ✅ Add | ✅ Add |
| `fetchIngestions` | ✅ Add | ✅ Add |
| `fetchIngestion` | ✅ Add | ✅ Add |
| `fetchIngestionStats` | ✅ Add | ✅ Add |
| `addProduct` | ❌ (mutation — must complete) | — |
| `updateProduct` | ❌ | — |
| `deleteProduct` | ❌ | — |
| `bulkDeleteProducts` | ❌ | — |
| `bulkUpdateCategory` | ❌ | — |
| `addCategory` | ❌ | — |
| `updateCategory` | ❌ | — |
| `deleteCategory` | ❌ | — |
| `moveCategory` | ❌ | — |
| `addKeyword` | ❌ | — |
| `updateKeyword` | ❌ | — |
| `deleteKeyword` | ❌ | — |
| `bulkDeleteKeywords` | ❌ | — |
| `saveTierConfig` | ❌ | — |
| `whitelistOutlier` | ❌ | — |
| `reviewIngestion` | ❌ | — |
| `bulkApproveIngestions` | ❌ | — |

> **Rule:** Read operations → accept & respect `signal`. Write/mutation operations → never abort (user expects side-effect to complete).

### 2.4 Integration Pattern: Page Components Use `useAbortController`

**Example for `Products.jsx`:**

```jsx
import { useAbortController } from '../../hooks/useAbortController';

export default function Products() {
  const { fetchProducts, fetchProductStats } = useDbAdminStore();
  const getSignal = useAbortController([/* re-abort on filter change */]);

  useEffect(() => {
    const signal = getSignal();
    fetchProducts(params, { signal });
    fetchProductStats({ signal });
  }, [debouncedSearch, page, sortKey, sortDir]);

  // ...
}
```

**Apply to all 6 page components:**

| Page | `useEffect` calls to wrap |
|---|---|
| `Dashboard.jsx` | `fetchDashboard()`, `fetchIngestionStats()` |
| `Products.jsx` | `fetchProducts()`, `fetchProductStats()` |
| `Prices.jsx` | `fetchTierConfig()`, `fetchOutliers()`, `fetchPriceStats()`, `fetchPriceHistory()` |
| `ClassificationPage.jsx` | `fetchCategories()`, `fetchKeywords()`, `fetchKeywordStats()` |
| `Analytics.jsx` | `fetchAnalytics()`, `fetchProducts()`, `fetchOutliers()`, + 4 inline `api.*` calls |
| `InboxPage.jsx` | `fetchIngestions()`, `fetchIngestionStats()` |

### Design Decisions
- **15 second default timeout** — matches backend uvicorn `timeout_keep_alive=30`, with margin.
- **45 second long timeout** — analytics/bulk/reset operations are known to be slow.
- **Signal merging** — caller's signal (navigation) + timeout signal (deadline) both handled.
- **No new dependencies** — `AbortController` is native in all supported browsers.
- **Mutations never abort** — write operations must complete to prevent inconsistent state.

---

## 3. Loading States

### Audit References
- **5.7** (concurrency audit): "Promise.allSettled() catches failures silently. Dashboard widgets show stale/empty data without indicating an error."
- **M-2** (stability audit): "No optimistic updates — UI shows old data until refetch completes"

### Current Gaps

| Page | Global `loading` | Per-section loading | Per-action loading |
|---|---|---|---|
| Dashboard | ✅ | ❌ missing | ❌ |
| Products | ✅ | ❌ | ❌ bulk ops |
| Prices | ✅ | ⚠️ `previewLoading` only | ❌ |
| Classification | ✅ | ❌ | ❌ |
| Analytics | ✅ | ❌ all sections share one flag | ❌ |
| Inbox | ✅ | ❌ | ❌ review action |

### 3.1 Add Per-Domain Loading Flags to Store

**Add to `stores/dbAdminStore.js` initial state:**

```javascript
// Replace single `loading` with per-domain flags
loadingProducts: false,
loadingCategories: false,
loadingKeywords: false,
loadingPrices: false,
loadingAnalytics: false,
loadingDashboard: false,
loadingIngestions: false,

// Keep global loading as a computed convenience (for sidebar/topbar spinner)
// Derivation: use a Zustand selector in components
// const isAnyLoading = useDbAdminStore(s =>
//   s.loadingProducts || s.loadingCategories || ... );
```

**Update each fetch action** to use its domain-specific flag:

```javascript
// BEFORE
fetchProducts: async (params = {}, { signal } = {}) => {
  set({ loading: true, error: null });
  // ...
  finally { set({ loading: false }); }
},

// AFTER
fetchProducts: async (params = {}, { signal } = {}) => {
  set({ loadingProducts: true, error: null });
  // ...
  finally { set({ loadingProducts: false }); }
},
```

### 3.2 Loading Indicator Component

**New file:** `src/components/LoadingBar.jsx`

```jsx
import { Loader2 } from 'lucide-react';

export function LoadingBar({ message = '불러오는 중...' }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: '0.5rem',
      padding: '0.75rem 1rem', background: 'var(--bg2, #f8f9fa)',
      borderRadius: 8, color: 'var(--text3, #888)', fontSize: '0.9rem',
    }}>
      <Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} />
      {message}
    </div>
  );
}

export function LoadingOverlay({ message = '처리 중...' }) {
  return (
    <div style={{
      position: 'absolute', inset: 0, display: 'flex',
      alignItems: 'center', justifyContent: 'center',
      background: 'rgba(255,255,255,0.8)', zIndex: 10, borderRadius: 8,
    }}>
      <LoadingBar message={message} />
    </div>
  );
}
```

### 3.3 Page-Level Loading Integration

**Pattern for each page:**

```jsx
// Products.jsx
const { loadingProducts, error, products } = useDbAdminStore();

return (
  <div className={s.page}>
    {loadingProducts && <LoadingBar message="상품 목록을 불러오는 중..." />}
    {error && <ErrorBanner message={error} onRetry={handleRetry} />}
    {!loadingProducts && !error && products.length === 0 && <EmptyState ... />}
    {products.length > 0 && <ProductTable ... />}
  </div>
);
```

### 3.4 Mutation Loading (Inline)

For mutations like delete/create, use local component state (not store) to show per-button loading:

```jsx
const [saving, setSaving] = useState(false);

const handleSave = async () => {
  setSaving(true);
  try {
    await addProduct(data);
    onClose();
  } catch {
    // error set in store
  } finally {
    setSaving(false);
  }
};

<button disabled={saving}>
  {saving ? '저장 중...' : '저장'}
</button>
```

### Design Decisions
- **Per-domain flags** prevent the bug where navigating from Dashboard to Products clears Dashboard's loading state mid-fetch.
- **`LoadingBar`** (non-blocking) preferred over full-page overlay for list pages.
- **`LoadingOverlay`** (blocking) used only for destructive mutations (reset, bulk delete).
- **Keep existing `loading` flag** as deprecated alias during transition — avoids breaking all pages at once.

---

## 4. Empty States

### Audit References
- **Current:** Only Products page has a proper empty state. Analytics shows blank. Keywords/Categories show blank. Inbox shows no items message but no visual.

### 4.1 Create `EmptyState` Component

**New file:** `src/components/EmptyState.jsx`

```jsx
import { PackageOpen } from 'lucide-react';

export default function EmptyState({
  icon: Icon = PackageOpen,
  title = '데이터 없음',
  description = '표시할 항목이 없습니다.',
  action,
  actionLabel,
}) {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      justifyContent: 'center', padding: '3rem 1rem', gap: '0.75rem',
      color: 'var(--text3, #999)',
    }}>
      <Icon size={48} strokeWidth={1.5} />
      <h3 style={{ margin: 0, color: 'var(--text2, #666)' }}>{title}</h3>
      <p style={{ margin: 0, textAlign: 'center', maxWidth: 300 }}>{description}</p>
      {action && (
        <button onClick={action} style={{
          marginTop: '0.5rem', padding: '0.5rem 1rem', borderRadius: 8,
          border: '1px solid var(--border, #ddd)', background: 'transparent',
          cursor: 'pointer', color: 'var(--primary, #3b82f6)',
        }}>
          {actionLabel || '새로 만들기'}
        </button>
      )}
    </div>
  );
}
```

### 4.2 Per-Page Empty State Messages (Korean)

| Page | Icon | `title` | `description` | `actionLabel` |
|---|---|---|---|---|
| Dashboard | `LayoutDashboard` | `데이터 없음` | `아직 등록된 데이터가 없습니다. 수신함에서 데이터를 승인해 주세요.` | `수신함으로 이동` |
| Products | `Package` | `등록된 상품 없음` | `등록된 상품이 없습니다. 수신함에서 데이터를 승인하거나 직접 추가하세요.` | `+ 상품 추가` |
| Prices | `DollarSign` | `가격 데이터 없음` | `아직 가격 정보가 수집되지 않았습니다.` | — |
| Classification | `FolderTree` | `카테고리 없음` | `카테고리를 추가하여 상품을 분류하세요.` | `+ 카테고리 추가` |
| Keywords | `Tags` | `키워드 없음` | `키워드를 추가하여 상품을 자동 분류하세요.` | `+ 키워드 추가` |
| Analytics | `BarChart3` | `분석 데이터 없음` | `충분한 가격 데이터가 쌓이면 분석 결과가 표시됩니다.` | — |
| Inbox | `Inbox` | `대기 중인 항목 없음` | `크롤러에서 수집된 새 데이터가 없습니다.` | — |

### 4.3 Integration Example

```jsx
// InboxPage.jsx — currently has no empty state
{!loadingIngestions && !error && ingestions.length === 0 && (
  <EmptyState
    icon={Inbox}
    title="대기 중인 항목 없음"
    description="크롤러에서 수집된 새 데이터가 없습니다."
  />
)}
```

### Design Decisions
- **All messages in Korean** — consistent with existing UI language.
- **Optional action button** — only for pages where the user can create items directly.
- **Conditional rendering guard:** `!loading && !error && items.length === 0` — prevents flash of empty state during load.

---

## 5. Retry on Network Error

### Audit References
- **5.2** (concurrency audit): "Transient network errors immediately fail. No retry with backoff."
- **H-2** (stability audit): "No retry mechanism exists for any database operation."
- **§9.2** (concurrency audit): "During backend restart (~2s), frontend API calls return connection-refused."

### 5.1 Add `fetchWithRetry` to `api/client.js`

Add this function to the client module (above the `api` export):

```javascript
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

      // Never retry on: user abort, client errors (4xx), timeout on mutation
      if (err.name === 'AbortError') throw err;

      const isRetryable =
        !err.status ||                    // network error (no status)
        err.status >= 500 ||              // server error
        err.status === 408 ||             // request timeout
        err.status === 429;               // rate limited

      if (!isRetryable || attempt === maxRetries) throw err;

      // Exponential backoff: 1s, 2s, 4s
      const delay = Math.min(1000 * Math.pow(2, attempt), 4000);
      await new Promise(r => setTimeout(r, delay));
    }
  }

  throw lastError;
}
```

### 5.2 Apply Retry: Only to GET Requests

**Modify the `get` helper** to use `fetchWithRetry`:

```javascript
const get = (url, { signal, timeout, maxRetries = 3 } = {}) =>
  fetchWithRetry(url, { signal }, { timeout, maxRetries, signal }).then(json);
```

**POST/PUT/DELETE remain non-retried** (mutations are not idempotent):

```javascript
const postJson = (url, data, { signal, timeout } = {}) =>
  fetchWithTimeout(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
    signal,
  }, timeout).then(json);
```

### 5.3 Retry-Aware Error Messages

Update store error messages to indicate retry exhaustion:

```javascript
// When an error reaches the store, all retries have already failed.
// Append retry info to the error message:
catch (err) {
  if (err.name === 'AbortError') return;
  const timeoutHint = err.name === 'TimeoutError'
    ? ' (서버 응답 시간 초과)'
    : err.status >= 500
      ? ' (서버 오류 — 잠시 후 다시 시도해 주세요)'
      : '';
  set({ error: `⚠️ 데이터를 불러올 수 없습니다${timeoutHint}` });
}
```

### Design Decisions
- **GET only** — POST/PUT/DELETE are not idempotent; retrying a `createProduct` could create duplicates.
- **Max 3 retries** — total 4 attempts. Backoff: 1s → 2s → 4s (total ~7s worst case).
- **429 included** — rate-limited requests should retry after backoff (server returns `retry_after`; we could parse it, but fixed backoff is simpler and sufficient).
- **No jitter** — admin tool with low concurrency; jitter is overkill.
- **Zero dependencies** — native `setTimeout` + `Promise`.

---

## 6. Stale Data Detection

### Audit References
- **M-2** (stability audit): "No `updatedAt` timestamp. Dashboard data can be minutes stale."
- **4.4** (concurrency audit): "Zustand store fetches fresh data on each page mount. Acceptable but no staleness indication."
- **§9.2** (concurrency audit): "Frontend proxy timeout during backend restart."

### 6.1 Add `lastFetchedAt` Timestamps to Store

**Add to `stores/dbAdminStore.js` initial state:**

```javascript
lastFetchedAt: {
  products: null,      // Date.now() or null
  categories: null,
  keywords: null,
  prices: null,
  analytics: null,
  dashboard: null,
  ingestions: null,
},
```

**Update in each fetch action's success path:**

```javascript
fetchProducts: async (params = {}, { signal } = {}) => {
  set({ loadingProducts: true, error: null });
  try {
    const data = await api.getProducts(params, { signal });
    // ... existing mapping ...
    set({
      products: mapped,
      productPagination: { ... },
      lastFetchedAt: { ...get().lastFetchedAt, products: Date.now() },
    });
  } catch (err) { /* ... */ }
  finally { set({ loadingProducts: false }); }
},
```

### 6.2 Create `LastUpdated` Component

**New file:** `src/components/LastUpdated.jsx`

```jsx
import { useState, useEffect } from 'react';
import { Clock, RefreshCw } from 'lucide-react';

function formatRelativeTime(timestamp) {
  if (!timestamp) return null;
  const diff = Math.floor((Date.now() - timestamp) / 1000);
  if (diff < 10) return '방금 전';
  if (diff < 60) return `${diff}초 전`;
  if (diff < 3600) return `${Math.floor(diff / 60)}분 전`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}시간 전`;
  return `${Math.floor(diff / 86400)}일 전`;
}

export default function LastUpdated({ timestamp, onRefresh, isLoading }) {
  const [, forceUpdate] = useState(0);

  // Re-render every 30s to update relative time
  useEffect(() => {
    const interval = setInterval(() => forceUpdate(n => n + 1), 30000);
    return () => clearInterval(interval);
  }, []);

  const label = formatRelativeTime(timestamp);
  const isStale = timestamp && (Date.now() - timestamp) > 5 * 60 * 1000; // 5 min

  return (
    <div style={{
      display: 'inline-flex', alignItems: 'center', gap: '0.4rem',
      fontSize: '0.8rem', color: isStale ? 'var(--warning, #e67e22)' : 'var(--text3, #999)',
    }}>
      <Clock size={13} />
      <span>{label ? `마지막 업데이트: ${label}` : '아직 로드되지 않음'}</span>
      {isStale && <span style={{ fontWeight: 600 }}>(오래됨)</span>}
      {onRefresh && (
        <button
          onClick={onRefresh}
          disabled={isLoading}
          title="새로고침"
          style={{
            background: 'none', border: 'none', cursor: 'pointer',
            padding: 2, display: 'inline-flex', color: 'inherit',
          }}
        >
          <RefreshCw
            size={13}
            style={isLoading ? { animation: 'spin 1s linear infinite' } : {}}
          />
        </button>
      )}
    </div>
  );
}
```

### 6.3 Per-Page Integration

```jsx
// Dashboard.jsx — header area
<LastUpdated
  timestamp={lastFetchedAt.dashboard}
  onRefresh={() => { fetchDashboard(); fetchIngestionStats(); }}
  isLoading={loadingDashboard}
/>
```

### 6.4 Auto-Refresh for Dashboard

The Dashboard is the most time-sensitive page (alerts, ingestion counts). Add auto-refresh:

**In `Dashboard.jsx`:**

```jsx
const AUTO_REFRESH_MS = 60_000; // 60 seconds

useEffect(() => {
  const signal = getSignal();
  fetchDashboard({ signal });
  fetchIngestionStats({ signal });

  const interval = setInterval(() => {
    const sig = getSignal();
    fetchDashboard({ signal: sig });
    fetchIngestionStats({ signal: sig });
  }, AUTO_REFRESH_MS);

  return () => clearInterval(interval);
}, [fetchDashboard, fetchIngestionStats]);
```

### 6.5 Staleness Thresholds

| Page | Auto-refresh | Stale threshold | Visual indicator |
|---|---|---|---|
| Dashboard | ✅ 60s | 2 min | Yellow "(오래됨)" badge |
| Products | ❌ | 5 min | Yellow "(오래됨)" badge |
| Prices | ❌ | 5 min | Yellow "(오래됨)" badge |
| Classification | ❌ | 5 min | Yellow "(오래됨)" badge |
| Analytics | ❌ | 10 min | Yellow "(오래됨)" badge |
| Inbox | ✅ 30s | 1 min | Yellow "(오래됨)" badge |

> Inbox auto-refreshes at 30s because pending ingestions are time-sensitive (crawler may be actively submitting).

### Design Decisions
- **Client-side timestamps** — the backend doesn't return `Last-Modified` headers consistently, so we track `Date.now()` when fetch succeeds.
- **Relative time format in Korean** — "방금 전", "3분 전", "1시간 전".
- **5-minute stale threshold** — admin tool usage pattern: user opens page, reviews data, takes action. 5 minutes without refresh is a reasonable warning point.
- **Auto-refresh only on Dashboard/Inbox** — other pages are interactive (editing products, managing categories); auto-refresh would disrupt user actions.
- **AbortController integration** — auto-refresh creates a new signal each time, properly cancelling stale requests.

---

## 7. File Change Summary

### New Files (4)

| File | Purpose | Lines (est.) |
|---|---|---|
| `src/components/ErrorBoundary.jsx` | React Error Boundary class component | ~65 |
| `src/components/EmptyState.jsx` | Reusable empty-data visual component | ~35 |
| `src/components/LoadingBar.jsx` | Loading indicator + overlay variants | ~35 |
| `src/components/LastUpdated.jsx` | Relative timestamp + refresh button | ~55 |
| `src/hooks/useAbortController.js` | Auto-cancel hook for page navigation | ~25 |

### Modified Files (8)

| File | Changes | Scope |
|---|---|---|
| `src/api/client.js` | Add `fetchWithTimeout`, `fetchWithRetry`, `signal` param to all 40+ endpoints, timeout tiers | **Full rewrite** |
| `src/App.jsx` | Import `ErrorBoundary`, wrap routes in two-tier boundaries | ~15 lines changed |
| `src/stores/dbAdminStore.js` | Add per-domain loading flags, `lastFetchedAt`, `signal` forwarding, AbortError guards | ~80 lines changed across 18 actions |
| `src/pages/Dashboard/Dashboard.jsx` | Add `useAbortController`, `LastUpdated`, auto-refresh, empty state | ~20 lines added |
| `src/pages/Products/Products.jsx` | Add `useAbortController`, use `loadingProducts`, already has empty state | ~10 lines changed |
| `src/pages/Prices/Prices.jsx` | Add `useAbortController`, empty state per tab, `LastUpdated` | ~25 lines added |
| `src/pages/Classification/ClassificationPage.jsx` | Add `useAbortController`, empty state for both categories + keywords | ~20 lines added |
| `src/pages/Analytics/Analytics.jsx` | Add `useAbortController`, cancel inline `api.*` calls, empty state, fix silent failures | ~30 lines changed |
| `src/pages/Inbox/InboxPage.jsx` | Add `useAbortController`, empty state, auto-refresh 30s | ~20 lines added |

### No New Dependencies

All features use **native browser APIs** (`AbortController`, `setTimeout`, `fetch`) and **existing React APIs** (class components for Error Boundary). The project's `package.json` is unchanged.

---

## 8. Implementation Order

### Phase 1: Critical Path (est. 2–3 hours)

Execute in this order to minimize risk:

| Step | Task | Why First |
|---|---|---|
| 1 | **Rewrite `api/client.js`** — timeout + retry + signal support | Foundation for all other changes; backward compatible (signal is optional) |
| 2 | **Create `ErrorBoundary.jsx`** | Independent component, no deps |
| 3 | **Modify `App.jsx`** — wrap routes | Immediate crash protection |
| 4 | **Create `useAbortController.js`** | Independent hook |
| 5 | **Add signal forwarding to `dbAdminStore.js`** | Must come after client.js change |

### Phase 2: UI Polish (est. 2 hours)

| Step | Task |
|---|---|
| 6 | **Create `LoadingBar.jsx`** + `EmptyState.jsx` + `LastUpdated.jsx` |
| 7 | **Add per-domain loading flags** to store |
| 8 | **Update all 6 page components** — wire up `useAbortController`, empty states, loading, `LastUpdated` |

### Phase 3: Auto-Refresh (est. 30 min)

| Step | Task |
|---|---|
| 9 | **Dashboard auto-refresh** (60s) |
| 10 | **Inbox auto-refresh** (30s) |

### Verification Checklist

After implementation, verify each scenario:

- [ ] **Error Boundary:** Add `throw new Error('test')` in Dashboard render → should show fallback, not crash app
- [ ] **Timeout:** Set `DEFAULT_TIMEOUT = 1` temporarily → all fetches should fail with "요청 시간이 초과되었습니다"
- [ ] **Retry:** Kill backend, wait for 3 retry attempts in Network tab, then start backend → should succeed on retry
- [ ] **AbortController:** Navigate from Products to Dashboard while loading → Products fetch should be cancelled in Network tab
- [ ] **Empty State:** Delete all products via admin reset → Products page should show "등록된 상품 없음"
- [ ] **Loading:** Throttle network to Slow 3G → loading indicators should be visible during fetch
- [ ] **Stale Data:** Wait 5+ minutes on Products page → should show "마지막 업데이트: 5분 전 (오래됨)"
- [ ] **Auto-Refresh:** Open Dashboard, observe Network tab → should see fetch every 60s
