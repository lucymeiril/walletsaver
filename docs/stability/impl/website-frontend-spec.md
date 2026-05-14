# Website Frontend Stability — Implementation Spec

**Source audits:** `website-stability-audit.md`, `website-frontend-audit.md`  
**Scope:** Frontend Resilience & Error Handling (8 items)  
**Base path:** `packages/website/frontend/src/`

---

## Table of Contents

1. [Error Boundaries](#1-error-boundaries)
2. [AbortController Cleanup](#2-abortcontroller-cleanup)
3. [Loading States](#3-loading-states)
4. [Empty States](#4-empty-states)
5. [Toast Bug](#5-toast-bug)
6. [Modal Fixes](#6-modal-fixes)
7. [useEffect Deps](#7-useeffect-deps)
8. [Debounce](#8-debounce)
9. [Test Recommendations](#9-test-recommendations)
10. [Implementation Order](#10-implementation-order)

---

## 1. Error Boundaries

**Audit refs:** S-14, Frontend Audit §1  
**Severity:** 🔴 CRITICAL  
**Current state:** 0 % coverage. `<Suspense>` wraps routes but no `<ErrorBoundary>`. Any render error → blank white screen.

### 1.1 New file: `components/common/ErrorBoundary.jsx`

`ErrorFallback.jsx` exists with retry button, icons, Korean messages — but it is a presentational component, not a class component with `componentDidCatch`. Create a proper React error boundary that wraps it.

```jsx
// FILE: components/common/ErrorBoundary.jsx  (NEW)
import { Component } from 'react';
import ErrorFallback from './ErrorFallback';

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
    // Future: send to error tracking service
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
    this.props.onReset?.();
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }
      return (
        <ErrorFallback
          error={this.state.error}
          message={this.props.fallbackMessage || '오류가 발생했습니다. 다시 시도해 주세요.'}
          onRetry={this.handleReset}
        />
      );
    }
    return this.props.children;
  }
}
```

### 1.2 Update: `App.jsx` — Global + Per-route boundaries

**File:** `App.jsx`

**BEFORE (lines 38-56):**
```jsx
return (
  <>
    <Header />
    <main style={{ paddingTop: 'var(--hdr-h)' }}>
      <Suspense fallback={<PageLoader />}>
        <Routes>
          <Route path="/"          element={<HomePage />} />
          <Route path="/search"    element={<SearchPage />} />
          <Route path="/price"     element={<PricePage />} />
          <Route path="/price/category/:categoryId" element={<CategoryComparePage />} />
          <Route path="/price/:id" element={<PricePage />} />
          <Route path="/hotdeal"   element={<HotdealPage />} />
          <Route path="/mart"      element={<MartPage />} />
          <Route path="/local"     element={<LocalPage />} />
          <Route path="/community" element={<CommunityPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </Suspense>
    </main>
    <Footer />
    <BottomNav />
    <ToastContainer />
    <LoginModal />
    <ShoppingListPanel />
    <ModalManager />
  </>
);
```

**AFTER:**
```jsx
import ErrorBoundary from './components/common/ErrorBoundary';

// helper — wrap each route element with a per-route boundary
function Guarded({ children, name }) {
  return (
    <ErrorBoundary
      key={name}
      fallbackMessage={`${name} 페이지에서 오류가 발생했습니다.`}
      onReset={() => window.location.reload()}
    >
      {children}
    </ErrorBoundary>
  );
}

return (
  <>
    <Header />
    <main style={{ paddingTop: 'var(--hdr-h)' }}>
      {/* Global boundary catches fatal errors across all routes */}
      <ErrorBoundary fallbackMessage="앱에서 오류가 발생했습니다. 페이지를 새로고침 해주세요.">
        <Suspense fallback={<PageLoader />}>
          <Routes>
            <Route path="/"          element={<Guarded name="홈"><HomePage /></Guarded>} />
            <Route path="/search"    element={<Guarded name="검색"><SearchPage /></Guarded>} />
            <Route path="/price"     element={<Guarded name="물가비교"><PricePage /></Guarded>} />
            <Route path="/price/category/:categoryId" element={<Guarded name="카테고리"><CategoryComparePage /></Guarded>} />
            <Route path="/price/:id" element={<Guarded name="물가비교"><PricePage /></Guarded>} />
            <Route path="/hotdeal"   element={<Guarded name="핫딜"><HotdealPage /></Guarded>} />
            <Route path="/mart"      element={<Guarded name="마트"><MartPage /></Guarded>} />
            <Route path="/local"     element={<Guarded name="내주변"><LocalPage /></Guarded>} />
            <Route path="/community" element={<Guarded name="커뮤니티"><CommunityPage /></Guarded>} />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </Suspense>
      </ErrorBoundary>
    </main>
    <Footer />
    <BottomNav />
    <ToastContainer />
    <LoginModal />
    <ShoppingListPanel />
    <ModalManager />
  </>
);
```

### 1.3 Update: `ErrorFallback.jsx` — Add `role="alert"`

**File:** `components/common/ErrorFallback.jsx`

**BEFORE (line 22-23):**
```jsx
  return (
    <div className={`${s.wrapper} ${className}`}>
```

**AFTER:**
```jsx
  return (
    <div className={`${s.wrapper} ${className}`} role="alert">
```

---

## 2. AbortController Cleanup

**Audit refs:** S-34, Frontend Audit §6  
**Severity:** 🔴 CRITICAL  
**Current state:** `useAbortController` hook exists and works correctly — but **no page uses it**. All page-level fetches (HomePage, HotdealPage, MartPage, PricePage, CommunityPage, CategoryComparePage, LocalPage) fire `fetch()` without a signal and never abort on unmount.

### 2.1 Pattern: How to apply `useAbortController` to every page

The existing `useAbortController` hook (file: `hooks/useAbortController.js`) is well implemented. It:
- Creates a new `AbortController` on each call to `getSignal()`
- Automatically aborts the previous controller
- Aborts on component unmount

**Usage pattern for all pages:**
```jsx
import useAbortController from '../../hooks/useAbortController';

export default function SomePage() {
  const getSignal = useAbortController();

  useEffect(() => {
    const signal = getSignal();
    fetch('/api/endpoint', { signal })
      .then(r => r.json())
      .then(data => setState(data))
      .catch(err => {
        if (err.name !== 'AbortError') handleError(err);
      });
  }, [deps]);
  // No cleanup return needed — useAbortController handles it
}
```

### 2.2 HomePage.jsx

**File:** `pages/Home/HomePage.jsx`

#### 2.2.1 Import `useAbortController`

**BEFORE (line 1):**
```jsx
import { useState, useRef, useCallback, useEffect, useMemo } from 'react';
```

**AFTER:**
```jsx
import { useState, useRef, useCallback, useEffect, useMemo } from 'react';
import useAbortController from '../../hooks/useAbortController';
```

#### 2.2.2 Add `getSignal` in component body (after line 68)

```jsx
const getSignal = useAbortController();
```

#### 2.2.3 Fix `fetchAllData` — pass signal to all 8 fetches

**BEFORE (lines 124-198):**
```jsx
const fetchAllData = useCallback((loc) => {
  const gasQuery = loc ? `lat=${loc.lat}&lng=${loc.lng}&sort=price_asc` : 'sort=price_asc';
  setSectionLoading({ products: true, hotdeals: true, community: true, gas: true, trending: true, fashion: true });
  setSectionError({ products: false, hotdeals: false, community: false, gas: false, trending: false, fashion: false });

  Promise.allSettled([
    fetch('/api/hotdeals?per_page=10').then(r => r.json()),
    fetch('/api/products/category-summary?per_page=8').then(r => r.json()),
    fetch('/api/products/search?per_page=50').then(r => r.json()),
    fetch('/api/posts?board=hotdeal&per_page=5').then(r => r.json()),
    fetch(`/api/gas/nearby?${gasQuery}`).then(r => r.json()),
    fetch('/api/products/trending').then(r => r.json()),
    searchService.trending(8),
    fetch('/api/hotdeals?category=fashion&per_page=6').then(r => r.json()),
  ]).then(([dealRes, catSumRes, prodRes, postRes, gasRes, trendRes, trendApiRes, fashionRes]) => {
    // ... processing ...
  });
}, []);
```

**AFTER:**
```jsx
const fetchAllData = useCallback((loc, signal) => {
  const gasQuery = loc ? `lat=${loc.lat}&lng=${loc.lng}&sort=price_asc` : 'sort=price_asc';
  setSectionLoading({ products: true, hotdeals: true, community: true, gas: true, trending: true, fashion: true });
  setSectionError({ products: false, hotdeals: false, community: false, gas: false, trending: false, fashion: false });

  Promise.allSettled([
    fetch('/api/hotdeals?per_page=10', { signal }).then(r => r.json()),
    fetch('/api/products/category-summary?per_page=8', { signal }).then(r => r.json()),
    fetch('/api/products/search?per_page=50', { signal }).then(r => r.json()),
    fetch('/api/posts?board=hotdeal&per_page=5', { signal }).then(r => r.json()),
    fetch(`/api/gas/nearby?${gasQuery}`, { signal }).then(r => r.json()),
    fetch('/api/products/trending', { signal }).then(r => r.json()),
    searchService.trending(8),
    fetch('/api/hotdeals?category=fashion&per_page=6', { signal }).then(r => r.json()),
  ]).then(([dealRes, catSumRes, prodRes, postRes, gasRes, trendRes, trendApiRes, fashionRes]) => {
    // ... rest identical ...
  });
}, []);
```

**Caller (lines 200-202):**

**BEFORE:**
```jsx
useEffect(() => {
  if (coords) fetchAllData(coords);
}, [coords, fetchAllData]);
```

**AFTER:**
```jsx
useEffect(() => {
  if (coords) {
    const signal = getSignal();
    fetchAllData(coords, signal);
  }
}, [coords, fetchAllData, getSignal]);
```

#### 2.2.4 Fix `fetchMart` — pass signal

**BEFORE (lines 205-215):**
```jsx
const fetchMart = useCallback((tab) => {
  setMartLoading(true);
  setMartError(false);
  fetch(`/api/marts/${tab}/promotions`).then(r => r.json())
    .then(res => {
      const items = normalizeMartItems(res.data ?? res);
      setMartDeals(prev => ({ ...prev, [tab]: items }));
    })
    .catch(() => setMartError(true))
    .finally(() => setMartLoading(false));
}, []);
```

**AFTER:**
```jsx
const fetchMart = useCallback((tab, signal) => {
  setMartLoading(true);
  setMartError(false);
  fetch(`/api/marts/${tab}/promotions`, { signal }).then(r => r.json())
    .then(res => {
      const items = normalizeMartItems(res.data ?? res);
      setMartDeals(prev => ({ ...prev, [tab]: items }));
    })
    .catch(err => {
      if (err.name !== 'AbortError') setMartError(true);
    })
    .finally(() => setMartLoading(false));
}, []);
```

**Caller (line 217):**

**BEFORE:**
```jsx
useEffect(() => { fetchMart(martTab); }, [martTab, fetchMart]);
```

**AFTER:**
```jsx
useEffect(() => {
  const signal = getSignal();
  fetchMart(martTab, signal);
}, [martTab, fetchMart, getSignal]);
```

> **Note:** HomePage uses two `useAbortController` instances — one for main data, one for mart data. Alternatively, use a single hook with separate `AbortController` creations for independent fetch groups. A simpler approach: use two hooks.

```jsx
const getMainSignal = useAbortController();
const getMartSignal = useAbortController();
```

### 2.3 HotdealPage.jsx

**File:** `pages/Hotdeal/HotdealPage.jsx`

#### 2.3.1 Import and initialize

Add after line 10:
```jsx
import useAbortController from '../../hooks/useAbortController';
```

Add inside component body after line 39:
```jsx
const getSignal = useAbortController();
```

#### 2.3.2 Sources fetch (lines 42-46)

**BEFORE:**
```jsx
useEffect(() => {
  fetch('/api/hotdeals/sources').then(r => r.json())
    .then(res => setSources(res.data || ['전체']))
    .catch(() => setSources(['전체']));
}, []);
```

**AFTER:**
```jsx
useEffect(() => {
  const signal = getSignal();
  fetch('/api/hotdeals/sources', { signal }).then(r => r.json())
    .then(res => setSources(res.data || ['전체']))
    .catch(err => {
      if (err.name !== 'AbortError') setSources(['전체']);
    });
}, [getSignal]);
```

#### 2.3.3 Products fetch (lines 48-52)

**BEFORE:**
```jsx
useEffect(() => {
  fetch('/api/products/search?per_page=50').then(r => r.json())
    .then(res => setProducts(res.data || []))
    .catch(console.error);
}, []);
```

**AFTER:**
```jsx
useEffect(() => {
  const signal = getSignal();
  fetch('/api/products/search?per_page=50', { signal }).then(r => r.json())
    .then(res => setProducts(res.data || []))
    .catch(err => {
      if (err.name !== 'AbortError') console.error(err);
    });
}, [getSignal]);
```

#### 2.3.4 Main deals fetch (lines 54-68)

**BEFORE:**
```jsx
useEffect(() => {
  setLoading(true);
  setVisibleCount(PAGE_SIZE);
  const params = new URLSearchParams({ per_page: '50' });
  if (filter !== 'all') params.set('category', filter);
  if (sort) params.set('sort', sort);

  fetch(`/api/hotdeals?${params}`).then(r => r.json())
    .then(res => setAllDeals(res.data || []))
    .catch(err => {
      console.error(err);
      addToast('핫딜 데이터를 불러오는데 실패했습니다', 'error');
    })
    .finally(() => setLoading(false));
}, [filter, sort]);
```

**AFTER:**
```jsx
useEffect(() => {
  setLoading(true);
  setVisibleCount(PAGE_SIZE);
  const controller = new AbortController();
  const params = new URLSearchParams({ per_page: '50' });
  if (filter !== 'all') params.set('category', filter);
  if (sort) params.set('sort', sort);

  fetch(`/api/hotdeals?${params}`, { signal: controller.signal }).then(r => r.json())
    .then(res => setAllDeals(res.data || []))
    .catch(err => {
      if (err.name === 'AbortError') return;
      console.error(err);
      addToast('핫딜 데이터를 불러오는데 실패했습니다', 'error');
    })
    .finally(() => setLoading(false));

  return () => controller.abort();
}, [filter, sort, addToast]);
```

#### 2.3.5 Polling interval (lines 90-101) — abort in-flight fetches

**BEFORE:**
```jsx
useEffect(() => {
  const interval = setInterval(() => {
    const params = new URLSearchParams({ per_page: '50' });
    if (filter !== 'all') params.set('category', filter);
    if (sort) params.set('sort', sort);
    fetch(`/api/hotdeals?${params}`).then(r => r.json())
      .then(res => { if (res.data?.length) setAllDeals(res.data); })
      .catch(() => {});
  }, 60000);
  return () => clearInterval(interval);
}, [filter, sort]);
```

**AFTER:**
```jsx
useEffect(() => {
  let currentController = null;
  const interval = setInterval(() => {
    if (currentController) currentController.abort();
    currentController = new AbortController();
    const params = new URLSearchParams({ per_page: '50' });
    if (filter !== 'all') params.set('category', filter);
    if (sort) params.set('sort', sort);
    fetch(`/api/hotdeals?${params}`, { signal: currentController.signal })
      .then(r => r.json())
      .then(res => { if (res.data?.length) setAllDeals(res.data); })
      .catch(() => {});
  }, 60000);
  return () => {
    clearInterval(interval);
    if (currentController) currentController.abort();
  };
}, [filter, sort]);
```

### 2.4 MartPage.jsx

**File:** `pages/Mart/MartPage.jsx`

#### 2.4.1 Import

Add after line 7:
```jsx
import useAbortController from '../../hooks/useAbortController';
```

Inside component after line 123:
```jsx
const getSignal = useAbortController();
```

#### 2.4.2 Initial mart data load (lines 125-159)

**BEFORE:**
```jsx
useEffect(() => {
  const martKeys = MARTS.map(m => m.key);
  Promise.allSettled(
    martKeys.map(key =>
      fetch(`/api/marts/${key}/promotions`).then(r => r.json())
        // ...
    )
  ).then(results => {
    // ...
  }).catch(err => {
    console.error(err);
    addToast('마트 데이터를 불러오는데 실패했습니다', 'error');
  }).finally(() => setLoading(false));

  fetch('/api/products/search?per_page=50')
    .then(r => r.json())
    .then(res => setProducts(Array.isArray(res?.data) ? res.data : []))
    .catch(console.error);
}, []);
```

**AFTER:**
```jsx
useEffect(() => {
  const controller = new AbortController();
  const { signal } = controller;
  const martKeys = MARTS.map(m => m.key);
  Promise.allSettled(
    martKeys.map(key =>
      fetch(`/api/marts/${key}/promotions`, { signal }).then(r => r.json())
        .then(res => {
          const rawItems = Array.isArray(res?.data) ? res.data : (res?.data?.items || []);
          return {
            key,
            lastCrawledAt: res?.data?.last_crawled_at || '',
            items: rawItems.map(normalizeItem).filter(Boolean),
          };
        })
    )
  ).then(results => {
    const deals = {};
    const meta = {};
    results.forEach(r => {
      if (r.status === 'fulfilled' && r.value) {
        deals[r.value.key] = r.value.items;
        meta[r.value.key] = { lastCrawledAt: r.value.lastCrawledAt };
      }
    });
    setMartDeals(deals);
    setMartMeta(meta);
  }).catch(err => {
    if (err.name === 'AbortError') return;
    console.error(err);
    addToast('마트 데이터를 불러오는데 실패했습니다', 'error');
  }).finally(() => setLoading(false));

  fetch('/api/products/search?per_page=50', { signal })
    .then(r => r.json())
    .then(res => setProducts(Array.isArray(res?.data) ? res.data : []))
    .catch(err => { if (err.name !== 'AbortError') console.error(err); });

  return () => controller.abort();
}, [addToast]);
```

#### 2.4.3 `fetchFlyerData` (lines 161-173)

**BEFORE:**
```jsx
const fetchFlyerData = useCallback((store) => {
  if (flyerData[store]) return;
  setFlyerLoading(true);
  setFlyerError(null);
  fetch(`/api/marts/${store}/flyers`)
    .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
    .then(res => { if (res?.data) setFlyerData(prev => ({ ...prev, [store]: res.data })); })
    .catch(err => {
      console.error('Flyer fetch error:', err);
      setFlyerError(`${store} 전단지를 불러올 수 없습니다`);
    })
    .finally(() => setFlyerLoading(false));
}, [flyerData]);
```

**AFTER:**
```jsx
const fetchFlyerData = useCallback((store, signal) => {
  if (flyerData[store]) return;
  setFlyerLoading(true);
  setFlyerError(null);
  fetch(`/api/marts/${store}/flyers`, { signal })
    .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
    .then(res => { if (res?.data) setFlyerData(prev => ({ ...prev, [store]: res.data })); })
    .catch(err => {
      if (err.name === 'AbortError') return;
      console.error('Flyer fetch error:', err);
      setFlyerError(`${store} 전단지를 불러올 수 없습니다`);
    })
    .finally(() => setFlyerLoading(false));
}, [flyerData]);
```

#### 2.4.4 Flyer mode effect (lines 175-187)

**BEFORE:**
```jsx
useEffect(() => {
  if (mode === 'flyer') {
    fetchFlyerData(flyerMart);
    MARTS.forEach(m => {
      if (m.key !== flyerMart && !flyerData[m.key]) {
        fetch(`/api/marts/${m.key}/flyers`)
          .then(r => r.ok ? r.json() : null)
          .then(res => { if (res?.data) setFlyerData(prev => ({ ...prev, [m.key]: res.data })); })
          .catch(() => {});
      }
    });
  }
}, [mode, flyerMart, fetchFlyerData]);
```

**AFTER:**
```jsx
useEffect(() => {
  if (mode !== 'flyer') return;
  const controller = new AbortController();
  const { signal } = controller;

  fetchFlyerData(flyerMart, signal);
  MARTS.forEach(m => {
    if (m.key !== flyerMart && !flyerData[m.key]) {
      fetch(`/api/marts/${m.key}/flyers`, { signal })
        .then(r => r.ok ? r.json() : null)
        .then(res => { if (res?.data) setFlyerData(prev => ({ ...prev, [m.key]: res.data })); })
        .catch(() => {});
    }
  });

  return () => controller.abort();
}, [mode, flyerMart, fetchFlyerData]);
```

### 2.5 LocalPage.jsx — Fix streaming reader never cancelled

**File:** `pages/Local/LocalPage.jsx`

This is the most critical fix. `runAreaExplore` (lines 103-161) opens a `fetch()` stream **without** an `AbortController` signal, so `reader.read()` loops indefinitely after unmount.

#### 2.5.1 Add abort ref

Add inside component after line 67:
```jsx
const streamAbortRef = useRef(null);
```

#### 2.5.2 Rewrite `runAreaExplore`

**BEFORE (lines 103-161):**
```jsx
const runAreaExplore = useCallback(async (locName, latVal, lngVal) => {
  setPhase('exploring');
  setExploreData({ categories: [] });
  setStreamingCats(new Set(EXPLORE_CATEGORIES.split(',')));

  const params = new URLSearchParams({ max_items: '30' });
  params.set('categories', EXPLORE_CATEGORIES);
  if (locName) params.set('location_name', locName);
  if (latVal != null) params.set('lat', String(latVal));
  if (lngVal != null) params.set('lng', String(lngVal));
  const url = `/api/local/area-explore-stream?${params}`;

  try {
    const response = await fetch(url);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      // ... SSE parsing ...
    }
    setPhase('categories');
    setStreamingCats(new Set());
  } catch {
    addToast('주변 탐색에 실패했습니다. 직접 검색해 주세요.', 'warning');
    setPhase('categories');
    setExploreData({ categories: [] });
    setStreamingCats(new Set());
  }
}, [addToast]);
```

**AFTER:**
```jsx
const runAreaExplore = useCallback(async (locName, latVal, lngVal) => {
  // Abort any previous stream
  if (streamAbortRef.current) streamAbortRef.current.abort();
  const controller = new AbortController();
  streamAbortRef.current = controller;

  setPhase('exploring');
  setExploreData({ categories: [] });
  setStreamingCats(new Set(EXPLORE_CATEGORIES.split(',')));

  const params = new URLSearchParams({ max_items: '30' });
  params.set('categories', EXPLORE_CATEGORIES);
  if (locName) params.set('location_name', locName);
  if (latVal != null) params.set('lat', String(latVal));
  if (lngVal != null) params.set('lng', String(lngVal));
  const url = `/api/local/area-explore-stream?${params}`;

  try {
    const response = await fetch(url, { signal: controller.signal });
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const jsonStr = line.slice(6).trim();
          if (!jsonStr) continue;
          try {
            const data = JSON.parse(jsonStr);
            if (data.done) {
              setPhase('categories');
              setStreamingCats(new Set());
              return;
            }
            if (data.error && !data.name) continue;
            setExploreData(prev => ({
              ...prev,
              categories: [...(prev?.categories || []), data],
            }));
            setStreamingCats(prev => {
              const next = new Set(prev);
              next.delete(data.name);
              return next;
            });
          } catch { /* skip malformed */ }
        }
      }
    } finally {
      reader.releaseLock();
    }
    setPhase('categories');
    setStreamingCats(new Set());
  } catch (err) {
    if (err.name === 'AbortError') return; // Clean abort — do nothing
    addToast('주변 탐색에 실패했습니다. 직접 검색해 주세요.', 'warning');
    setPhase('categories');
    setExploreData({ categories: [] });
    setStreamingCats(new Set());
  }
}, [addToast]);
```

#### 2.5.3 Add cleanup on unmount

Add a `useEffect` for stream cleanup (after `streamAbortRef` declaration):

```jsx
useEffect(() => {
  return () => {
    if (streamAbortRef.current) streamAbortRef.current.abort();
  };
}, []);
```

### 2.6 PricePage.jsx

**File:** `pages/Price/PricePage.jsx`

#### 2.6.1 Import and init

Add import after line 10:
```jsx
import useAbortController from '../../hooks/useAbortController';
```

Inside component after line 38:
```jsx
const getSignal = useAbortController();
```

#### 2.6.2 Products list fetch (lines 41-45)

**BEFORE:**
```jsx
useEffect(() => {
  fetch('/api/products/search?per_page=50').then(r => r.json())
    .then(res => setProducts(res.data || []))
    .catch(console.error);
}, []);
```

**AFTER:**
```jsx
useEffect(() => {
  const signal = getSignal();
  fetch('/api/products/search?per_page=50', { signal }).then(r => r.json())
    .then(res => setProducts(res.data || []))
    .catch(err => { if (err.name !== 'AbortError') console.error(err); });
}, [getSignal]);
```

#### 2.6.3 Product detail fetch (lines 48-58)

**BEFORE:**
```jsx
useEffect(() => {
  if (!id) { setProductData(null); return; }
  setLoading(true);
  fetch(`/api/products/${id}`).then(r => r.json())
    .then(res => setProductData(res.data))
    .catch(err => {
      console.error(err);
      addToast('상품 정보를 불러오는데 실패했습니다', 'error');
    })
    .finally(() => setLoading(false));
}, [id]);
```

**AFTER:**
```jsx
useEffect(() => {
  if (!id) { setProductData(null); return; }
  const controller = new AbortController();
  setLoading(true);
  fetch(`/api/products/${id}`, { signal: controller.signal }).then(r => r.json())
    .then(res => setProductData(res.data))
    .catch(err => {
      if (err.name === 'AbortError') return;
      console.error(err);
      addToast('상품 정보를 불러오는데 실패했습니다', 'error');
    })
    .finally(() => setLoading(false));
  return () => controller.abort();
}, [id, addToast]);
```

#### 2.6.4 Price history fetch (lines 122-128)

**BEFORE:**
```jsx
useEffect(() => {
  if (!product) return;
  fetch(`/api/products/${product.id}/price-history?days=${range}`)
    .then(r => r.json())
    .then(res => setChartData(res.data || []))
    .catch(console.error);
}, [product?.id, range]);
```

**AFTER:**
```jsx
useEffect(() => {
  if (!product) return;
  const controller = new AbortController();
  fetch(`/api/products/${product.id}/price-history?days=${range}`, { signal: controller.signal })
    .then(r => r.json())
    .then(res => setChartData(res.data || []))
    .catch(err => { if (err.name !== 'AbortError') console.error(err); });
  return () => controller.abort();
}, [product?.id, range]);
```

#### 2.6.5 Related hotdeals fetch (lines 131-139)

**BEFORE:**
```jsx
useEffect(() => {
  if (!product) return;
  const CAT_MAP = { ... };
  const hotdealCat = CAT_MAP[product.cat] || '';
  const catParam = hotdealCat ? `category=${hotdealCat}&` : '';
  fetch(`/api/hotdeals?${catParam}per_page=3`).then(r => r.json())
    .then(res => setRelatedHotdeals(res.data || []))
    .catch(console.error);
}, [product?.id, product?.cat]);
```

**AFTER:**
```jsx
useEffect(() => {
  if (!product) return;
  const controller = new AbortController();
  const CAT_MAP = { '농산물': 'food', '축산물': 'food', '수산물': 'food', '가공식품': 'food', '생활용품': 'living', '전자제품': 'electronics', '패션': 'fashion' };
  const hotdealCat = CAT_MAP[product.cat] || '';
  const catParam = hotdealCat ? `category=${hotdealCat}&` : '';
  fetch(`/api/hotdeals?${catParam}per_page=3`, { signal: controller.signal }).then(r => r.json())
    .then(res => setRelatedHotdeals(res.data || []))
    .catch(err => { if (err.name !== 'AbortError') console.error(err); });
  return () => controller.abort();
}, [product?.id, product?.cat]);
```

### 2.7 CommunityPage.jsx

**File:** `pages/Community/CommunityPage.jsx`

#### 2.7.1 Import

Add after line 7:
```jsx
import useAbortController from '../../hooks/useAbortController';
```

Inside component after line 85:
```jsx
const getSignal = useAbortController();
```

#### 2.7.2 Products fetch (lines 88-92)

**BEFORE:**
```jsx
useEffect(() => {
  fetch('/api/products/search?per_page=50').then(r => r.json())
    .then(res => setProducts(res.data || []))
    .catch(console.error);
}, []);
```

**AFTER:**
```jsx
useEffect(() => {
  const signal = getSignal();
  fetch('/api/products/search?per_page=50', { signal }).then(r => r.json())
    .then(res => setProducts(res.data || []))
    .catch(err => { if (err.name !== 'AbortError') console.error(err); });
}, [getSignal]);
```

#### 2.7.3 `refreshPosts` with abort (lines 95-109)

**BEFORE:**
```jsx
const refreshPosts = () => {
  setLoading(true);
  const params = new URLSearchParams({ post_type: board, per_page: '50' });
  fetch(`/api/posts?${params}`).then(r => r.json())
    .then(res => setPosts((res.data || []).map(p => mapApiPost(p, products))))
    .catch(err => {
      console.error(err);
      addToast('게시글을 불러오는데 실패했습니다', 'error');
    })
    .finally(() => setLoading(false));
};

useEffect(() => {
  refreshPosts();
}, [board, products]);
```

**AFTER:**
```jsx
useEffect(() => {
  const controller = new AbortController();
  setLoading(true);
  const params = new URLSearchParams({ post_type: board, per_page: '50' });
  fetch(`/api/posts?${params}`, { signal: controller.signal }).then(r => r.json())
    .then(res => setPosts((res.data || []).map(p => mapApiPost(p, products))))
    .catch(err => {
      if (err.name === 'AbortError') return;
      console.error(err);
      addToast('게시글을 불러오는데 실패했습니다', 'error');
    })
    .finally(() => setLoading(false));
  return () => controller.abort();
}, [board, products, addToast]);
```

If `refreshPosts` is called manually elsewhere (e.g., after post creation), keep it as a separate function but have it use a ref-based controller:

```jsx
const postsControllerRef = useRef(null);

const refreshPosts = useCallback(() => {
  if (postsControllerRef.current) postsControllerRef.current.abort();
  postsControllerRef.current = new AbortController();
  setLoading(true);
  const params = new URLSearchParams({ post_type: board, per_page: '50' });
  fetch(`/api/posts?${params}`, { signal: postsControllerRef.current.signal }).then(r => r.json())
    .then(res => setPosts((res.data || []).map(p => mapApiPost(p, products))))
    .catch(err => {
      if (err.name === 'AbortError') return;
      console.error(err);
      addToast('게시글을 불러오는데 실패했습니다', 'error');
    })
    .finally(() => setLoading(false));
}, [board, products, addToast]);

useEffect(() => {
  refreshPosts();
  return () => { if (postsControllerRef.current) postsControllerRef.current.abort(); };
}, [refreshPosts]);
```

### 2.8 CategoryComparePage.jsx

**File:** `pages/Price/CategoryComparePage.jsx`

Apply the same pattern. Locate the `useEffect` that fetches category data (search for `fetch` or `searchService`), add a local `AbortController`, pass `{ signal }`, and return `controller.abort()`.

---

## 3. Loading States

**Audit ref:** Frontend Audit §2  
**Severity:** 🟠 HIGH  
**Current state:** ~70 % coverage. Gaps on mutation buttons.

### 3.1 New hook: `hooks/useAsyncAction.js`

Creates a reusable "loading + action" wrapper for mutation buttons (vote, submit, install).

```jsx
// FILE: hooks/useAsyncAction.js  (NEW)
import { useState, useCallback } from 'react';

export default function useAsyncAction(asyncFn) {
  const [loading, setLoading] = useState(false);

  const execute = useCallback(async (...args) => {
    if (loading) return;
    setLoading(true);
    try {
      return await asyncFn(...args);
    } finally {
      setLoading(false);
    }
  }, [asyncFn, loading]);

  return [execute, loading];
}
```

### 3.2 HotdealPage — vote button loading

**File:** `pages/Hotdeal/HotdealPage.jsx`

Wrap the `handleVote` function with loading state. In the JSX, pass `disabled={voteLoading}` and show a small spinner icon.

```jsx
const [voteLoading, setVoteLoading] = useState({});

const handleVote = useCallback(async (id, type) => {
  if (voteLoading[id]) return; // prevent double-click
  setVoteLoading(prev => ({ ...prev, [id]: true }));
  const prev = votes[id];
  const newType = prev === type ? null : type;
  setVotes(p => ({ ...p, [id]: newType }));
  try {
    const res = await fetch(`/api/hotdeals/${id}/vote`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ vote_type: newType || 'cancel' }),
    });
    const data = await res.json();
    if (data.data) {
      setAllDeals(ds => ds.map(d =>
        d.id === id ? { ...d, hotVotes: data.data.votes_hot, coldVotes: data.data.votes_not } : d
      ));
    }
  } catch {
    addToast('투표 처리에 실패했습니다', 'error');
    setVotes(p => ({ ...p, [id]: prev }));
  } finally {
    setVoteLoading(prev => ({ ...prev, [id]: false }));
  }
}, [votes, addToast, voteLoading]);
```

In the vote button JSX:
```jsx
<button
  onClick={() => handleVote(deal.id, 'hot')}
  disabled={voteLoading[deal.id]}
  aria-busy={voteLoading[deal.id]}
>
  {voteLoading[deal.id] ? <Spinner size="sm" /> : '🔥'}
</button>
```

### 3.3 CommunityPage — submit button loading

**File:** `pages/Community/CommunityPage.jsx`

Add `submitting` state:
```jsx
const [submitting, setSubmitting] = useState(false);
```

Wrap the submit handler:
```jsx
const handleSubmit = async (e) => {
  e.preventDefault();
  if (submitting) return;
  setSubmitting(true);
  try {
    // ... existing submit logic ...
  } finally {
    setSubmitting(false);
  }
};
```

In JSX:
```jsx
<button type="submit" disabled={submitting} aria-busy={submitting}>
  {submitting ? '게시 중...' : '게시하기'}
</button>
```

### 3.4 PricePage — chart loading skeleton

When `chartData` is being fetched, show a skeleton placeholder:

```jsx
const [chartLoading, setChartLoading] = useState(false);

// In the price history useEffect:
useEffect(() => {
  if (!product) return;
  setChartLoading(true);
  const controller = new AbortController();
  fetch(`/api/products/${product.id}/price-history?days=${range}`, { signal: controller.signal })
    .then(r => r.json())
    .then(res => setChartData(res.data || []))
    .catch(err => { if (err.name !== 'AbortError') console.error(err); })
    .finally(() => setChartLoading(false));
  return () => controller.abort();
}, [product?.id, range]);

// In JSX:
{chartLoading ? (
  <div className={s.chartSkeleton}>
    <Spinner />
    <p>차트 데이터 로딩 중...</p>
  </div>
) : (
  <ResponsiveContainer>...</ResponsiveContainer>
)}
```

### 3.5 MartPage — flyer skeleton

When `flyerLoading` is true and flyer pages array is empty:
```jsx
{flyerLoading && !flyerData[flyerMart] && (
  <div className={s.flyerSkeleton}>
    <Spinner />
    <p>전단지 로딩 중...</p>
  </div>
)}
```

---

## 4. Empty States

**Audit ref:** Frontend Audit §3  
**Severity:** 🟠 HIGH  
**Current state:** ~60 % coverage. `EmptyState.jsx` exists but is inconsistently used.

### 4.1 Empty state messages table

All messages in Korean. Use the existing `EmptyState` component:

| Page | Section | Condition | `title` | `description` |
|------|---------|-----------|---------|---------------|
| HomePage | Gas stations | `gasStations.length === 0 && !sectionLoading.gas` | `'주변 주유소 정보가 없습니다'` | `'위치 권한을 허용하면 주변 주유소를 찾을 수 있습니다.'` |
| HomePage | Price grid | `products.length === 0 && !sectionLoading.products` | `'물가 정보가 없습니다'` | `'잠시 후 다시 확인해 주세요.'` |
| MartPage | Deals list | `filteredItems.length === 0 && !loading` | `'할인 상품이 없습니다'` | `'다른 마트나 카테고리를 선택해 보세요.'` |
| MartPage | Flyer | `flyerPages.length === 0 && !flyerLoading` | `'전단지가 없습니다'` | `'이번 주 전단지가 아직 등록되지 않았습니다.'` |
| HotdealPage | Filtered items | `items.length === 0 && !loading` | `'핫딜이 없습니다'` | `'다른 카테고리나 필터를 선택해 보세요.'` |
| LocalPage | Category results | `displayItems.length === 0 && phase === 'items'` | `'검색 결과가 없습니다'` | `'다른 카테고리를 선택하거나 검색 범위를 넓혀보세요.'` |
| PricePage | Chart data | `chartData.length === 0 && !chartLoading && product` | `'가격 이력이 없습니다'` | `'아직 수집된 가격 데이터가 없습니다.'` |
| PricePage | Related hotdeals | `relatedHotdeals.length === 0 && product` | `'관련 핫딜이 없습니다'` | `'현재 이 상품의 핫딜 정보가 없습니다.'` |
| CommunityPage | Filtered posts | `filteredPosts.length === 0 && !loading` | `'게시글이 없습니다'` | `'첫 번째 게시글을 작성해 보세요!'` |

### 4.2 Implementation pattern

Each page: after the loading guard, before the data `.map()`, add:

```jsx
import EmptyState from '../../components/common/EmptyState';

// Example for HotdealPage:
{!loading && items.length === 0 && (
  <EmptyState
    title="핫딜이 없습니다"
    description="다른 카테고리나 필터를 선택해 보세요."
  />
)}
```

### 4.3 HomePage gas stations section

Locate the section rendering `gasStations.map(...)` and add before it:

```jsx
{!sectionLoading.gas && gasStations.length === 0 && !sectionError.gas && (
  <EmptyState
    title="주변 주유소 정보가 없습니다"
    description="위치 권한을 허용하면 주변 주유소를 찾을 수 있습니다."
  />
)}
```

---

## 5. Toast Bug

**Audit refs:** S-35, Frontend Audit §16  
**Severity:** 🟡 MEDIUM  
**Current state:** `ToastContainer.jsx` hardcodes 3000 ms and always removes `toasts[0].id` (FIFO). This means:
1. **Wrong toast removed** — if toast B is added before toast A auto-dismisses, toasts[0] changes, and the timer targets the wrong toast.
2. **Duration ignored** — `addToast` in `appStore.js` doesn't accept `duration`; `useToast.js` accepts it but the value is never read by `ToastContainer`.

### 5.1 Fix `appStore.js` toast actions

**File:** `stores/appStore.js`

**BEFORE (lines 37-43):**
```jsx
// 토스트 메시지
toasts: [],
addToast: (msg, type = 'info') => set((state) => ({
  toasts: [...state.toasts, { id: Date.now(), msg, type }]
})),
removeToast: (id) => set((state) => ({
  toasts: state.toasts.filter(t => t.id !== id)
})),
```

**AFTER:**
```jsx
// 토스트 메시지
toasts: [],
_toastSeq: 0,
addToast: (msg, type = 'info', duration = 4000) => set((state) => ({
  _toastSeq: state._toastSeq + 1,
  toasts: [...state.toasts, {
    id: state._toastSeq + 1,
    msg,
    type,
    duration,
    createdAt: Date.now(),
  }]
})),
removeToast: (id) => set((state) => ({
  toasts: state.toasts.filter(t => t.id !== id)
})),
```

### 5.2 Rewrite `ToastContainer.jsx`

**File:** `components/common/ToastContainer.jsx`

**BEFORE (entire file):**
```jsx
import { useEffect } from 'react';
import useStore from '../../stores/appStore';

export default function ToastContainer() {
  const { toasts, removeToast } = useStore();

  useEffect(() => {
    if (toasts.length > 0) {
      const timer = setTimeout(() => removeToast(toasts[0].id), 3000);
      return () => clearTimeout(timer);
    }
  }, [toasts, removeToast]);

  return (
    <div style={{ position:'fixed', bottom:20, right:20, zIndex:400, display:'flex', flexDirection:'column', gap:8 }}>
      {toasts.map(t => (
        <div key={t.id} style={{
          background:'var(--surface)', border:'1px solid var(--border2)', borderRadius:10,
          padding:'14px 20px', fontSize:'.88rem', boxShadow:'0 8px 24px rgba(0,0,0,.3)',
          borderLeft: `3px solid ${
            t.type === 'success' ? 'var(--green)' :
            t.type === 'error' ? 'var(--red, #ef4444)' :
            t.type === 'warning' ? 'var(--orange, #f59e0b)' :
            'var(--accent)'
          }`,
          animation: 'slideInRight .3s var(--ease)',
        }}>
          {t.msg}
        </div>
      ))}
    </div>
  );
}
```

**AFTER:**
```jsx
import { useEffect, useRef } from 'react';
import useStore from '../../stores/appStore';

const MAX_VISIBLE = 5;

export default function ToastContainer() {
  const { toasts, removeToast } = useStore();
  const timersRef = useRef(new Map());

  // Per-toast timer: each toast gets its own independent timeout
  useEffect(() => {
    const currentIds = new Set(toasts.map(t => t.id));

    // Clean up timers for removed toasts
    for (const [id, timer] of timersRef.current) {
      if (!currentIds.has(id)) {
        clearTimeout(timer);
        timersRef.current.delete(id);
      }
    }

    // Start timers for new toasts
    for (const toast of toasts) {
      if (!timersRef.current.has(toast.id)) {
        const duration = toast.duration || 4000;
        const timer = setTimeout(() => {
          timersRef.current.delete(toast.id);
          removeToast(toast.id);
        }, duration);
        timersRef.current.set(toast.id, timer);
      }
    }
  }, [toasts, removeToast]);

  // Cleanup all timers on unmount
  useEffect(() => {
    return () => {
      for (const timer of timersRef.current.values()) clearTimeout(timer);
      timersRef.current.clear();
    };
  }, []);

  const visible = toasts.slice(-MAX_VISIBLE);

  const colorMap = {
    success: 'var(--green)',
    error: 'var(--red, #ef4444)',
    warning: 'var(--orange, #f59e0b)',
    info: 'var(--accent)',
  };

  return (
    <div
      role="region"
      aria-live="polite"
      aria-label="알림"
      style={{
        position: 'fixed', bottom: 20, right: 20, zIndex: 400,
        display: 'flex', flexDirection: 'column', gap: 8,
      }}
    >
      {visible.map(t => (
        <div
          key={t.id}
          role="status"
          style={{
            background: 'var(--surface)', border: '1px solid var(--border2)', borderRadius: 10,
            padding: '14px 20px', fontSize: '.88rem', boxShadow: '0 8px 24px rgba(0,0,0,.3)',
            borderLeft: `3px solid ${colorMap[t.type] || colorMap.info}`,
            animation: 'slideInRight .3s var(--ease)',
            cursor: 'pointer',
          }}
          onClick={() => removeToast(t.id)}
          title="클릭하여 닫기"
        >
          {t.msg}
        </div>
      ))}
    </div>
  );
}
```

**Key fixes:**
1. Each toast gets its own independent timer via `timersRef` Map — no more FIFO bug
2. Toast `duration` is respected (default 4000 ms)
3. Max 5 visible toasts — oldest hidden (prevents overflow)
4. Click to dismiss added
5. `aria-live="polite"` and `role="status"` for accessibility
6. Timer cleanup on unmount
7. Uses sequential `_toastSeq` instead of `Date.now()` to avoid collision

---

## 6. Modal Fixes

**Audit ref:** Frontend Audit §8  
**Severity:** 🟡 MEDIUM  
**Current state:** `Modal.jsx` (common) has full focus trap, ESC key, scroll lock, ARIA. But `LoginModal.jsx` and `DetailModal.jsx` use custom overlay patterns and lack all of these.

### 6.1 Strategy

Migrate both `LoginModal` and `DetailModal` to use the common `<Modal>` component rather than reimplementing modal behavior. This gives them ESC key, focus trap, scroll lock, and ARIA for free.

### 6.2 LoginModal.jsx — Migrate to `<Modal>`

**File:** `components/modals/LoginModal.jsx`

**BEFORE (entire file):**
```jsx
import { useState } from 'react';
import useStore from '../../stores/appStore';
import s from './LoginModal.module.css';

export default function LoginModal() {
  const [tab, setTab] = useState('login');
  const { login, addToast, isLoginModalOpen, closeLoginModal } = useStore();

  const handleLogin = (e) => { /* ... */ };
  const handleSignup = (e) => { /* ... */ };

  return (
    <div className={`${s.modal} ${isLoginModalOpen ? 'open' : ''}`}>
      <div className={s.overlay} onClick={closeLoginModal} />
      <div className={s.box}>
        <button className={s.close} onClick={closeLoginModal}>&times;</button>
        {/* ... form content ... */}
      </div>
    </div>
  );
}
```

**AFTER:**
```jsx
import { useState } from 'react';
import useStore from '../../stores/appStore';
import Modal from '../common/Modal';
import s from './LoginModal.module.css';

export default function LoginModal() {
  const [tab, setTab] = useState('login');
  const { login, addToast, isLoginModalOpen, closeLoginModal } = useStore();

  const handleLogin = (e) => {
    e.preventDefault();
    login({ name: '테스트유저', email: 'test@test.com' });
    addToast('로그인 되었습니다! (데모)', 'success');
    closeLoginModal();
  };

  const handleSignup = (e) => {
    e.preventDefault();
    addToast('회원가입이 완료되었습니다! (데모)', 'success');
    closeLoginModal();
  };

  return (
    <Modal isOpen={isLoginModalOpen} onClose={closeLoginModal} title="로그인" size="sm">
      <div className={s.tabs}>
        <button className={`${s.tab} ${tab === 'login' ? s.tabActive : ''}`} onClick={() => setTab('login')}>로그인</button>
        <button className={`${s.tab} ${tab === 'signup' ? s.tabActive : ''}`} onClick={() => setTab('signup')}>회원가입</button>
      </div>

      {tab === 'login' ? (
        <form className={s.form} onSubmit={handleLogin}>
          <div className={s.group}><label>이메일</label><input type="email" placeholder="example@email.com" required /></div>
          <div className={s.group}><label>비밀번호</label><input type="password" placeholder="비밀번호" required /></div>
          <button type="submit" className={s.submitBtn}>로그인</button>
          <div className={s.divider}><span>또는</span></div>
          <button type="button" className={s.kakao}>카카오로 시작하기</button>
          <button type="button" className={s.naver}>네이버로 시작하기</button>
        </form>
      ) : (
        <form className={s.form} onSubmit={handleSignup}>
          <div className={s.group}><label>이메일</label><input type="email" placeholder="example@email.com" required /></div>
          <div className={s.group}><label>닉네임</label><input type="text" placeholder="닉네임" required /></div>
          <div className={s.group}><label>비밀번호</label><input type="password" placeholder="8자 이상" required /></div>
          <div className={s.group}><label>비밀번호 확인</label><input type="password" placeholder="비밀번호 확인" required /></div>
          <button type="submit" className={s.submitBtn}>회원가입</button>
        </form>
      )}
    </Modal>
  );
}
```

**CSS note:** Remove `.modal`, `.overlay`, `.box`, `.close` rules from `LoginModal.module.css` that conflict with `Modal.jsx`'s own styling. Keep `.tabs`, `.tab`, `.tabActive`, `.form`, `.group`, `.submitBtn`, `.divider`, `.kakao`, `.naver`.

### 6.3 DetailModal.jsx — Migrate to `<Modal>`

**File:** `components/modals/DetailModal.jsx`

**BEFORE (lines 18-21):**
```jsx
return (
  <div className={s.overlay} onClick={onClose}>
    <div className={s.modal} onClick={e => e.stopPropagation()}>
      <button className={s.close} onClick={onClose}><X size={20} /></button>
```

**AFTER:**
```jsx
import Modal from '../common/Modal';

// ...

const modalTitle = type === 'hotdeal' ? '핫딜 상세'
  : type === 'mart' ? '마트 상품 상세'
  : type === 'community' ? '게시글 상세'
  : '상세 보기';

return (
  <Modal isOpen={!!item} onClose={onClose} title={modalTitle} size="lg">
    {/* Remove the close button — Modal provides one */}

    {/* 핫딜 상세 */}
    {type === 'hotdeal' && (
      <>
        {item.thumb && <img src={item.thumb} alt="" className={s.hero} />}
        <div className={s.body}>
          {/* ... rest of hotdeal content unchanged ... */}
        </div>
      </>
    )}

    {/* 마트 상세 — unchanged content */}
    {type === 'mart' && ( /* ... */ )}

    {/* 커뮤니티 상세 — unchanged content */}
    {type === 'community' && ( /* ... */ )}

    {/* 댓글 섹션 — unchanged */}
    <div className={s.commentSec}>
      {/* ... */}
    </div>
  </Modal>
);
```

**CSS note:** Remove `.overlay`, `.modal`, `.close` from `DetailModal.module.css`. Keep `.hero`, `.body`, `.meta`, `.title`, `.priceRow`, `.commentSec`, etc.

### 6.4 What this gives us

| Feature | Before | After |
|---------|--------|-------|
| ESC key close | ❌ | ✅ (from Modal.jsx) |
| Focus trap | ❌ | ✅ (from Modal.jsx) |
| Scroll lock | ❌ | ✅ (`body.overflow = 'hidden'`) |
| Previous focus restore | ❌ | ✅ (from Modal.jsx) |
| `aria-modal="true"` | ❌ | ✅ (from Modal.jsx) |
| `role="dialog"` | ❌ | ✅ (from Modal.jsx) |
| Backdrop click close | ✅ | ✅ (from Modal.jsx) |

---

## 7. useEffect Deps

**Audit ref:** Frontend Audit §6  
**Severity:** 🟠 HIGH

### 7.1 CommunityPage — `refreshPosts` in deps

**File:** `pages/Community/CommunityPage.jsx`

**Issue (lines 107-109):**
```jsx
useEffect(() => {
  refreshPosts();
}, [board, products]);
```

`refreshPosts` is **not** in the dependency array, but it captures `board` and `products` from closure. If `products` changes rapidly (initial fetch), multiple fetches fire. Also, `refreshPosts` is not wrapped in `useCallback`, so every render creates a new reference.

**Fix:** Addressed in §2.7.3 — convert to `useCallback` + include in deps. The abort-aware version from §2.7.3 also fixes this stale closure.

### 7.2 PricePage — missing `addToast` in deps

**File:** `pages/Price/PricePage.jsx` (line 58):

**BEFORE:**
```jsx
}, [id]);
```

**AFTER:**
```jsx
}, [id, addToast]);
```

### 7.3 HotdealPage — `addToast` missing from main fetch deps

**File:** `pages/Hotdeal/HotdealPage.jsx` (line 68):

**BEFORE:**
```jsx
}, [filter, sort]);
```

**AFTER:**
```jsx
}, [filter, sort, addToast]);
```

### 7.4 MartPage — `fetchFlyerData` has stale `flyerData` closure

**File:** `pages/Mart/MartPage.jsx` (line 173):

**Issue:** `fetchFlyerData` has `[flyerData]` as dependency, meaning it recreates on every `flyerData` change, and the early-return `if (flyerData[store]) return` always sees latest. However, when passed as dep to the mode-change `useEffect` (line 187), it causes re-runs.

**Fix:** Use `useRef` for the cache check instead:

```jsx
const flyerDataRef = useRef(flyerData);
flyerDataRef.current = flyerData;

const fetchFlyerData = useCallback((store, signal) => {
  if (flyerDataRef.current[store]) return;
  // ... rest unchanged
}, []); // stable reference — no deps needed
```

### 7.5 PricePage — `location.state` effect missing cleanup

**File:** `pages/Price/PricePage.jsx` (lines 61-71):

**Issue:** Effect deps include `[location.state, products]` but uses `navigate` and `setSelectedProduct` without listing them. ESLint would warn.

**Fix:**
```jsx
}, [location.state, products, navigate, setSelectedProduct, addRecentSearch]);
```

### 7.6 MartPage — flyer mode effect has `flyerData` in deps

**File:** `pages/Mart/MartPage.jsx` (line 187):

**BEFORE:**
```jsx
}, [mode, flyerMart, fetchFlyerData]);
```

`fetchFlyerData` depends on `flyerData`, so this effect re-runs every time a flyer is fetched (infinite loop risk). The fix in §7.4 (removing `flyerData` from `fetchFlyerData` deps) resolves this.

---

## 8. Debounce

**Audit ref:** Frontend Audit §5  
**Severity:** 🟠 HIGH  
**Current state:** `useDebounce` hook exists and works. Only used in PricePage.

### 8.1 New hook: `hooks/useThrottledCallback.js`

For mutation buttons (vote, like) we need throttle, not debounce. Debounce is for text input; throttle limits frequency of discrete actions.

```jsx
// FILE: hooks/useThrottledCallback.js  (NEW)
import { useRef, useCallback } from 'react';

export default function useThrottledCallback(callback, delay = 1000) {
  const lastCallRef = useRef(0);
  const pendingRef = useRef(false);

  return useCallback((...args) => {
    const now = Date.now();
    if (now - lastCallRef.current >= delay && !pendingRef.current) {
      lastCallRef.current = now;
      pendingRef.current = true;
      const result = callback(...args);
      if (result instanceof Promise) {
        result.finally(() => { pendingRef.current = false; });
      } else {
        pendingRef.current = false;
      }
      return result;
    }
  }, [callback, delay]);
}
```

### 8.2 HotdealPage — throttle vote button

**File:** `pages/Hotdeal/HotdealPage.jsx`

```jsx
import useThrottledCallback from '../../hooks/useThrottledCallback';

// Wrap handleVote:
const throttledVote = useThrottledCallback(handleVote, 1000);

// In JSX — replace onClick={handleVote(id, 'hot')} with:
onClick={() => throttledVote(deal.id, 'hot')}
```

### 8.3 CommunityPage — debounce search filter

**File:** `pages/Community/CommunityPage.jsx`

The community search is currently client-side filtering (line 150-154), so debounce isn't strictly needed for network calls, but it prevents excessive re-renders on rapid typing.

```jsx
import useDebounce from '../../hooks/useDebounce';

// Replace direct use of searchQuery in filtering:
const debouncedSearch = useDebounce(searchQuery, 200);

// In useMemo for filtering:
const filteredPosts = useMemo(() => {
  let items = [...posts];
  if (debouncedSearch.trim()) {
    const q = debouncedSearch.trim().toLowerCase();
    items = items.filter(p => p.title?.toLowerCase().includes(q) || p.body?.toLowerCase().includes(q));
  }
  // ... rest of filtering ...
}, [posts, debouncedSearch, /* other deps */]);
```

### 8.4 CommunityPage — throttle like/vote buttons

Apply `useThrottledCallback` to any like/vote handlers.

### 8.5 MartPage — category filter

**File:** `pages/Mart/MartPage.jsx`

Category filter triggers immediate re-render. Since this is local state filtering (no API call), the impact is low. However, if there are many items:

```jsx
const debouncedCatFilter = useDebounce(catFilter, 150);

const filteredItems = useMemo(
  () => debouncedCatFilter === '전체' ? martItems : martItems.filter(i => i.event === debouncedCatFilter),
  [martItems, debouncedCatFilter]
);
```

### 8.6 LocalPage — radius slider

**File:** `pages/Local/LocalPage.jsx`

The radius slider (`setRadius`) triggers `sortItems` recalculation. Use debounce:

```jsx
import useDebounce from '../../hooks/useDebounce';

const debouncedRadius = useDebounce(radius, 300);
// Use debouncedRadius instead of radius in sortItems/display logic
```

### 8.7 Summary of debounce/throttle additions

| Component | Handler | Type | Delay |
|-----------|---------|------|-------|
| HotdealPage | `handleVote` | throttle | 1000 ms |
| CommunityPage | search filter | debounce | 200 ms |
| CommunityPage | like/vote buttons | throttle | 1000 ms |
| MartPage | category filter | debounce | 150 ms |
| LocalPage | radius slider | debounce | 300 ms |
| CategoryComparePage | sort dropdown | debounce | 200 ms |

---

## 9. Test Recommendations

### 9.1 Unit Tests

| Test | File | What to verify |
|------|------|----------------|
| ErrorBoundary renders fallback | `ErrorBoundary.test.jsx` | Child that throws → shows `ErrorFallback`; retry resets |
| ErrorBoundary resets on key change | `ErrorBoundary.test.jsx` | Changing `key` prop resets boundary |
| ToastContainer per-toast timers | `ToastContainer.test.jsx` | 3 toasts with different durations; each dismissed independently |
| ToastContainer max visible | `ToastContainer.test.jsx` | Add 10 toasts; only 5 visible |
| ToastContainer click dismiss | `ToastContainer.test.jsx` | Click toast → removed immediately |
| useThrottledCallback | `useThrottledCallback.test.js` | Rapid calls within delay → only first fires |
| useAbortController | `useAbortController.test.js` | Previous signal aborted when `getSignal()` called again |

### 9.2 Integration Tests

| Test | What to verify |
|------|----------------|
| Navigate away during fetch | Mount HomePage → navigate before fetches complete → no "setState on unmounted" warning |
| Navigate away during SSE stream | Mount LocalPage → start area explore → navigate → stream aborted, no memory leak |
| Rapid filter changes | HotdealPage: change filter 10x rapidly → only last filter's results shown |
| Rapid product navigation | PricePage: click products rapidly → no stale data displayed |
| Error boundary per route | Throw error in HotdealPage → only HotdealPage shows error; header/nav still work |
| Modal ESC key | Open LoginModal → press ESC → modal closes |
| Modal focus trap | Open LoginModal → Tab through fields → focus wraps within modal |
| Toast ordering | Add 3 toasts → verify each auto-dismisses after its own `duration` |

### 9.3 Manual Smoke Tests

1. **Memory leak test:** DevTools → Performance → record while navigating rapidly between all pages for 2 minutes → verify heap doesn't grow continuously
2. **Offline test:** DevTools → Network → Offline → navigate pages → verify error states (not blank screens)
3. **Rapid vote test:** Click vote button 10x rapidly → verify single vote request (throttled)
4. **Streaming abort test:** Start area explore on LocalPage → navigate to HomePage during streaming → verify no console errors

---

## 10. Implementation Order

| Phase | Task | Priority | Effort | Files |
|-------|------|----------|--------|-------|
| 1 | Error Boundary (§1) | 🔴 P0 | 1 h | `ErrorBoundary.jsx` (new), `App.jsx`, `ErrorFallback.jsx` |
| 2 | AbortController — LocalPage streaming (§2.5) | 🔴 P0 | 1 h | `LocalPage.jsx` |
| 3 | AbortController — all pages (§2.2–2.8) | 🔴 P0 | 3 h | 6 page files |
| 4 | Toast bug (§5) | 🟠 P1 | 1 h | `ToastContainer.jsx`, `appStore.js` |
| 5 | Modal fixes (§6) | 🟠 P1 | 2 h | `LoginModal.jsx`, `DetailModal.jsx`, CSS modules |
| 6 | Loading states (§3) | 🟠 P1 | 2 h | `HotdealPage`, `CommunityPage`, `PricePage`, `MartPage` |
| 7 | Empty states (§4) | 🟠 P1 | 1.5 h | 6 page files |
| 8 | Debounce/throttle (§8) | 🟠 P1 | 1.5 h | `useThrottledCallback.js` (new), 5 page files |
| 9 | useEffect deps (§7) | 🟡 P2 | 1 h | 4 page files |
| **Total** | | | **~14 h** | |

### New files created

| File | Purpose |
|------|---------|
| `components/common/ErrorBoundary.jsx` | React class component error boundary |
| `hooks/useThrottledCallback.js` | Throttle wrapper for mutation handlers |
| `hooks/useAsyncAction.js` | Loading state wrapper for async mutations |

### Existing files modified

| File | Changes |
|------|---------|
| `App.jsx` | Import ErrorBoundary; wrap routes with global + per-route boundaries |
| `components/common/ErrorFallback.jsx` | Add `role="alert"` |
| `components/common/ToastContainer.jsx` | Full rewrite: per-toast timers, max visible, a11y |
| `stores/appStore.js` | Toast: add `_toastSeq`, `duration`, `createdAt` |
| `components/modals/LoginModal.jsx` | Migrate to `<Modal>` component |
| `components/modals/DetailModal.jsx` | Migrate to `<Modal>` component |
| `pages/Home/HomePage.jsx` | Add AbortController to all fetches |
| `pages/Hotdeal/HotdealPage.jsx` | AbortController, vote throttle, vote loading, missing deps |
| `pages/Mart/MartPage.jsx` | AbortController, fix stale flyerData closure |
| `pages/Local/LocalPage.jsx` | AbortController for stream, cleanup on unmount |
| `pages/Price/PricePage.jsx` | AbortController on 4 fetches, chart loading, missing deps |
| `pages/Community/CommunityPage.jsx` | AbortController, search debounce, submit loading |
| `pages/Price/CategoryComparePage.jsx` | AbortController |

---

*Generated by Stability Detail Planner — Frontend Resilience & Error Handling*
