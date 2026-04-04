# Website UX Edge Cases — Implementation Spec

**Source Audits:** `website-stability-audit.md`, `website-frontend-audit.md`  
**Scope:** Network Error UI · Auth Token Handling · Image Fallbacks · Index-Based Keys · ARIA Labels · Virtual Scrolling · SSE Reconnection · Stale Data Timestamps  
**Target Directory:** `packages/website/frontend/src/`

---

## Table of Contents

1. [Network Error UI](#1-network-error-ui)
2. [Auth Token Handling](#2-auth-token-handling)
3. [Image Error Fallbacks](#3-image-error-fallbacks)
4. [Index-Based Keys](#4-index-based-keys)
5. [ARIA Labels](#5-aria-labels)
6. [Virtual Scrolling](#6-virtual-scrolling)
7. [SSE Reconnection](#7-sse-reconnection)
8. [Stale Data Timestamps](#8-stale-data-timestamps)
9. [Dependency Changes](#9-dependency-changes)
10. [Verification Checklist](#10-verification-checklist)

---

## 1. Network Error UI

### Audit Findings

| ID | Finding | Source |
|----|---------|--------|
| S-14 | No React Error Boundary in entire app | stability-audit §4.1 |
| S-15 | HomePage references undeclared globals — crashes on render | stability-audit §4.2 |
| S-16 | FavoritesDashboard swallows errors with `catch(console.error)` | stability-audit §4.2 |
| — | `ErrorFallback.jsx` exists but is never used as a boundary | frontend-audit §1 |
| — | Korean error messages exist in `api.js` (`ERROR_MESSAGES` map) | api.js lines 7-16 |

### Current State

- `api.js` already defines Korean error messages and `ApiError` with `.retryable` getter
- `ErrorFallback.jsx` renders an icon + message + retry button but is **never used as an actual React error boundary**
- Pages like HomePage, LocalPage, and FavoritesDashboard have no try/catch around fetches

### 1.1 Create ErrorBoundary class component

**New file:** `components/common/ErrorBoundary.jsx`

```jsx
import { Component } from 'react';
import ErrorFallback from './ErrorFallback';

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error('[ErrorBoundary]', error, info.componentStack);
  }

  handleReset = () => {
    this.setState({ error: null });
    this.props.onReset?.();
  };

  render() {
    if (this.state.error) {
      if (this.props.fallback) {
        return this.props.fallback(this.state.error, this.handleReset);
      }
      return (
        <ErrorFallback
          error={this.state.error}
          onRetry={this.handleReset}
          className={this.props.className}
        />
      );
    }
    return this.props.children;
  }
}
```

### 1.2 Wrap routes in App.jsx

**File:** `App.jsx`

```diff
 import { Routes, Route } from 'react-router-dom';
 import { lazy, Suspense, useEffect } from 'react';
+import ErrorBoundary from './components/common/ErrorBoundary';
 import Header from './components/layout/Header';
 ...

 export default function App() {
   const theme = useStore((s) => s.theme);
   ...
   return (
     <>
       <Header />
       <main style={{ paddingTop: 'var(--hdr-h)' }}>
-        <Suspense fallback={<PageLoader />}>
-          <Routes>
-            ...
-          </Routes>
-        </Suspense>
+        <ErrorBoundary onReset={() => window.location.reload()}>
+          <Suspense fallback={<PageLoader />}>
+            <Routes>
+              ...
+            </Routes>
+          </Suspense>
+        </ErrorBoundary>
       </main>
       ...
     </>
   );
 }
```

### 1.3 Add `role="alert"` to ErrorFallback

**File:** `components/common/ErrorFallback.jsx`

```diff
   return (
-    <div className={`${s.wrapper} ${className}`}>
+    <div className={`${s.wrapper} ${className}`} role="alert">
       <Icon className={s.icon} size={44} />
```

### 1.4 Per-section ErrorBoundary example (data-heavy pages)

Each page that performs multiple independent data fetches should wrap each section. Example for `HomePage.jsx`:

```jsx
import ErrorBoundary from '../../components/common/ErrorBoundary';

// Wrap each independent section
<ErrorBoundary>
  <HotdealSection />
</ErrorBoundary>

<ErrorBoundary>
  <PriceSection />
</ErrorBoundary>
```

### 1.5 useNetworkError hook for per-fetch error UI

**New file:** `hooks/useNetworkError.js`

```js
import { useState, useCallback } from 'react';

/**
 * Manages fetch error state + retry for a single data source.
 * Returns { error, clearError, wrapFetch }.
 */
export default function useNetworkError() {
  const [error, setError] = useState(null);

  const clearError = useCallback(() => setError(null), []);

  const wrapFetch = useCallback(
    async (fetchFn) => {
      try {
        setError(null);
        return await fetchFn();
      } catch (err) {
        setError(err);
        throw err;
      }
    },
    [],
  );

  return { error, clearError, wrapFetch };
}
```

**Usage in any page:**

```jsx
import useNetworkError from '../../hooks/useNetworkError';
import ErrorFallback from '../../components/common/ErrorFallback';

function HotdealSection() {
  const { error, clearError, wrapFetch } = useNetworkError();
  const [data, setData] = useState([]);

  const loadData = useCallback(async () => {
    const result = await wrapFetch(() => api.getJson('/api/hotdeals'));
    setData(result);
  }, [wrapFetch]);

  useEffect(() => { loadData(); }, [loadData]);

  if (error) {
    return <ErrorFallback error={error} onRetry={loadData} />;
  }
  // ...render data
}
```

---

## 2. Auth Token Handling

### Audit Findings

| ID | Finding | Source |
|----|---------|--------|
| S-21 | `decode_token()` returns `None` for ALL JWT errors — no differentiation | stability-audit §6.1 |
| S-25 | `/api/auth/me` returns 501 — not implemented | stability-audit §6.1 |
| — | Token refresh exists but is reactive-only (on 401), not proactive | api.js lines 123-137, 201-221 |
| — | No redirect on auth failure — only opens login modal | api.js line 134 |
| — | No protected routes | stability-audit §7 |
| — | Auth state in Zustand (`isLoggedIn`, `user`) is NOT persisted; lost on refresh | appStore.js |

### Current Flow

1. `authService.login()` → stores `access_token` via `api.setToken()` → `sessionStorage`
2. `api.request()` attaches `Authorization: Bearer` header
3. On 401 → `api.refreshToken()` → retries once → if fails, clears token + `openLoginModal()`
4. On page refresh → `sessionStorage` restores token in `ApiClient` constructor, but `appStore.isLoggedIn` is `false`

### 2.1 Sync auth state on app mount

**File:** `App.jsx` — add token rehydration effect:

```diff
 export default function App() {
   const theme = useStore((s) => s.theme);
+  const login = useStore((s) => s.login);
+  const logout = useStore((s) => s.logout);

   useEffect(() => {
     document.documentElement.setAttribute('data-theme', theme);
   }, [theme]);

+  // Rehydrate auth state from sessionStorage on mount
+  useEffect(() => {
+    const token = sessionStorage.getItem('access_token');
+    if (!token) return;
+    api.getJson('/api/auth/me')
+      .then((user) => login(user))
+      .catch(() => {
+        // Token expired or invalid — clean up silently
+        api.clearToken();
+        sessionStorage.removeItem('refresh_token');
+        logout();
+      });
+  }, [login, logout]);
```

**Imports to add:**

```diff
+import { api } from './services/api';
```

> **Note:** This requires the backend `/api/auth/me` to be implemented (currently returns 501 per S-25). If not yet implemented, guard with a check or skip until backend is ready.

### 2.2 Force logout + redirect on unrecoverable 401

**File:** `services/api.js` — enhance the 401 handler (lines 132-136):

```diff
       } else {
         this.clearToken();
+        sessionStorage.removeItem('refresh_token');
-        useStore.getState().openLoginModal();
+        const store = useStore.getState();
+        store.logout();
+        store.openLoginModal();
         throw new ApiError(ERROR_MESSAGES.unauthorized, 401, 'unauthorized');
       }
```

### 2.3 Prevent stale token state with token expiry check

**New file:** `utils/tokenUtils.js`

```js
/**
 * Decode JWT payload without verification (browser-side convenience).
 * Returns null if token is malformed.
 */
export function decodeTokenPayload(token) {
  try {
    const base64 = token.split('.')[1];
    const json = atob(base64.replace(/-/g, '+').replace(/_/g, '/'));
    return JSON.parse(json);
  } catch {
    return null;
  }
}

/**
 * Returns true if the token expires within `bufferMs` milliseconds.
 * Default buffer: 60 seconds.
 */
export function isTokenExpiringSoon(token, bufferMs = 60_000) {
  const payload = decodeTokenPayload(token);
  if (!payload?.exp) return true;
  return Date.now() >= payload.exp * 1000 - bufferMs;
}
```

### 2.4 Proactive token refresh before expiry

**File:** `services/api.js` — add pre-request expiry check in `request()`:

```diff
   async request(path, options = {}) {
     const { timeout = DEFAULT_TIMEOUT, signal: externalSignal, ...fetchOptions } = options;
+
+    // Proactive token refresh: if token expires within 60 s, refresh before request
+    if (this.token && isTokenExpiringSoon(this.token)) {
+      await this.refreshToken();
+    }
+
     const headers = {
```

**Import to add at top of api.js:**

```diff
+import { isTokenExpiringSoon } from '../utils/tokenUtils';
```

---

## 3. Image Error Fallbacks

### Audit Findings

| ID | Finding | Source |
|----|---------|--------|
| S-30 | No image error fallbacks anywhere — 14 `<img>` tags, 0 `onError` handlers | stability-audit §9 |
| — | Broken images show browser default broken-image icon | frontend-audit §9 |

### Files Affected (all `<img>` tags without `onError`)

| File | Line(s) | Image Type |
|------|---------|-----------|
| `components/modals/DetailModal.jsx` | 26, 48, 73 | hotdeal hero, mart img, community post images |
| `components/modals/MartProductModal.jsx` | 65 | product image |
| `components/modals/ProductQuickView.jsx` | 98 | product image |
| `pages/Community/CommunityPage.jsx` | 388, 785 | image preview, post images |
| `pages/Home/HomePage.jsx` | 688 | fashion/deal card images |
| `pages/Hotdeal/HotdealPage.jsx` | 207, 332 | deal thumbnails, modal hero |
| `pages/Local/components/NaverPlaceDetailContent.jsx` | 19 | place image |
| `pages/Mart/MartPage.jsx` | 390-393, 729 | flyer images, sale detail |
| `pages/Search/SearchPage.jsx` | 170 | search result thumbnails |

### 3.1 Create SafeImage component

**New file:** `components/common/SafeImage.jsx`

```jsx
import { useState, useCallback } from 'react';
import s from './SafeImage.module.css';

const FALLBACK_ICON = (
  <svg width="40" height="40" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
    <circle cx="8.5" cy="8.5" r="1.5"/>
    <polyline points="21,15 16,10 5,21"/>
  </svg>
);

export default function SafeImage({
  src,
  alt = '',
  className = '',
  fallbackClassName = '',
  loading = 'lazy',
  ...props
}) {
  const [hasError, setHasError] = useState(false);
  const [imgSrc, setImgSrc] = useState(src);

  // Reset error state when src prop changes
  const handleError = useCallback(() => setHasError(true), []);

  // If src changes externally, reset error state
  if (src !== imgSrc && !hasError) {
    setImgSrc(src);
  }
  if (src !== imgSrc && hasError) {
    setImgSrc(src);
    setHasError(false);
  }

  if (hasError || !src) {
    return (
      <div
        className={`${s.fallback} ${fallbackClassName || className}`}
        role="img"
        aria-label={alt || '이미지를 불러올 수 없습니다'}
      >
        {FALLBACK_ICON}
      </div>
    );
  }

  return (
    <img
      src={imgSrc}
      alt={alt}
      className={className}
      loading={loading}
      onError={handleError}
      {...props}
    />
  );
}
```

**New file:** `components/common/SafeImage.module.css`

```css
.fallback {
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg2, #f3f4f6);
  color: var(--text3, #9ca3af);
  border-radius: 8px;
  min-height: 80px;
  width: 100%;
  aspect-ratio: 16 / 9;
}
```

### 3.2 Migration: Replace `<img>` with `<SafeImage>` in each file

#### DetailModal.jsx

```diff
+import SafeImage from '../common/SafeImage';

-<img src={item.thumb} alt="" className={s.hero} />
+<SafeImage src={item.thumb} alt={item.title || '상품 이미지'} className={s.hero} />

-<img src={item.img} alt="" className={s.martImg} />
+<SafeImage src={item.img} alt={item.name || '마트 상품'} className={s.martImg} />

-{item.images.map((url, i) => <img key={i} src={url} alt="" className={s.postImg} />)}
+{item.images.map((url) => <SafeImage key={url} src={url} alt="게시물 이미지" className={s.postImg} />)}
```

#### MartProductModal.jsx

```diff
+import SafeImage from '../common/SafeImage';

-<img src={image} alt={name} className={s.img} />
+<SafeImage src={image} alt={name} className={s.img} />
```

#### ProductQuickView.jsx

```diff
+import SafeImage from '../common/SafeImage';

-<img src={image} alt={name} className={s.img} />
+<SafeImage src={image} alt={name} className={s.img} />
```

#### HotdealPage.jsx

```diff
+import SafeImage from '../../components/common/SafeImage';

-<img src={d.thumb} alt={d.title} className={s.thumb} loading="lazy" />
+<SafeImage src={d.thumb} alt={d.title} className={s.thumb} />

-<img src={item.thumb} alt="" className={s.modalHero} />
+<SafeImage src={item.thumb} alt={item.title || '핫딜 이미지'} className={s.modalHero} />
```

#### MartPage.jsx

```diff
+import SafeImage from '../../components/common/SafeImage';

-<img src={flyerPages[flyerIdx]?.image_url} alt={`...전단지...`} className={s.flyerImg} />
+<SafeImage src={flyerPages[flyerIdx]?.image_url} alt={`${currentFlyer?.name || flyerMart} 전단지 ${flyerIdx + 1}페이지`} className={s.flyerImg} />

-<img src={saleDetail.img} alt={saleDetail.name} className={s.detailImg} />
+<SafeImage src={saleDetail.img} alt={saleDetail.name} className={s.detailImg} />
```

#### NaverPlaceDetailContent.jsx

```diff
+import SafeImage from '../../common/SafeImage';

-<img src={place.image_url} alt={place.name} className={s.detailImage} />
+<SafeImage src={place.image_url} alt={place.name} className={s.detailImage} />
```

#### SearchPage.jsx

```diff
+import SafeImage from '../../components/common/SafeImage';

-<img src={item.image} alt="" className={s.thumb} loading="lazy" />
+<SafeImage src={item.image} alt={item.name || '검색 결과'} className={s.thumb} />
```

#### HomePage.jsx

```diff
+import SafeImage from '../../components/common/SafeImage';

-<img src={d.image_url || d.thumb} alt={d.title || d.name} className={s.fashionImg} loading="lazy" />
+<SafeImage src={d.image_url || d.thumb} alt={d.title || d.name} className={s.fashionImg} />
```

#### CommunityPage.jsx

```diff
+import SafeImage from '../../components/common/SafeImage';

-<img src={src} alt="" />
+<SafeImage src={src} alt="업로드 미리보기" />

-<img key={i} src={sanitizeURL(url)} alt="" loading="lazy" />
+<SafeImage key={url} src={sanitizeURL(url)} alt="게시물 이미지" />
```

---

## 4. Index-Based Keys

### Audit Findings

| Source | Finding |
|--------|---------|
| frontend-audit §7 | ~30+ instances of `key={i}` or `key={index}` across 8+ files |
| stability-audit §8 | SearchPage has no virtual scroll for large result sets |

### Files to Fix

Below are **only the dynamic lists** that need stable keys. Static skeleton arrays (`[0,1,2].map(i => ...)`) are acceptable and excluded.

#### 4.1 `components/search/SearchAutocomplete.jsx`

**Lines ~106, ~128** — autocomplete keyword/product items have `id` fields.

```diff
-{keywords.map((kw, i) => (
-  <div key={i} ...>
+{keywords.map((kw) => (
+  <div key={`kw-${kw.id}`} ...>

-{products.map((p, i) => (
-  <div key={i} ...>
+{products.map((p) => (
+  <div key={`p-${p.id}`} ...>
```

#### 4.2 `components/common/SearchBar.jsx`

**Lines ~106, ~118** — suggestions have `id` or `label`; recent searches have `timestamp`.

```diff
-{suggestions.map((item, i) => (
-  <button key={i} ...>
+{suggestions.map((item) => (
+  <button key={item.id || item.label} ...>

-{recentSearches.map((item, i) => (
-  <button key={i} ...>
+{recentSearches.map((item) => (
+  <button key={item.timestamp || item.query} ...>
```

#### 4.3 `components/modals/DetailModal.jsx`

**Line ~73** — community post images: URLs are unique.

```diff
-{item.images.map((url, i) => <img key={i} src={url} .../>)}
+{item.images.map((url) => <SafeImage key={url} src={url} .../>)}
```

#### 4.4 `pages/Price/PricePage.jsx`

**Line ~141** — variant chips. Variants have `name` or `value` fields.

```diff
-{variants.map((v, i) => (
-  <button key={i} className={...} onClick={() => setVariantIdx(i)}>
+{variants.map((v, i) => (
+  <button key={v.name || v.value || `var-${i}`} className={...} onClick={() => setVariantIdx(i)}>
```

**Line ~128** — Recharts `<Cell>` inside chart. Chart entries have category/name fields.

```diff
-<Cell key={index} fill={...} />
+<Cell key={entry.name || entry.category || `cell-${index}`} fill={...} />
```

#### 4.5 `pages/Price/CategoryComparePage.jsx`

**Lines ~85, ~95, ~105** — tags, breadcrumbs, alternatives. These items have `id` or `name` fields.

```diff
 // Tags
-{tags.map((t, i) => <span key={i}>{t}</span>)}
+{tags.map((t) => <span key={t}>{t}</span>)}

 // Breadcrumb items
-{breadcrumbs.map((b, i) => <span key={i}>{b.label}</span>)}
+{breadcrumbs.map((b) => <span key={b.path || b.label}>{b.label}</span>)}

 // Alternatives list
-{alternatives.map((alt, i) => <div key={i}>...</div>)}
+{alternatives.map((alt) => <div key={alt.id || alt.name}>...</div>)}
```

#### 4.6 `pages/Mart/MartPage.jsx`

**Lines ~380, ~410** — mart product/sale cards have `id` or `name`.

```diff
-{activeMartItems.map((item, i) => (
-  <div key={i} className={s.card}>
+{activeMartItems.map((item) => (
+  <div key={item.id || item.name} className={s.card}>

-{saleItems.map((item, i) => (
-  <div key={i} ...>
+{saleItems.map((item) => (
+  <div key={item.id || item.name} ...>
```

#### 4.7 `pages/Local/LocalPage.jsx`

**Lines ~180, ~200, ~250** — category results and breadcrumbs.

```diff
-{categoryResults.map((item, i) => (
-  <div key={i} ...>
+{categoryResults.map((item) => (
+  <div key={item.id || item.place_id || item.name} ...>
```

#### 4.8 `pages/Community/CommunityPage.jsx`

**Line ~160** — post preview images.

```diff
-{wImages.map((src, i) => (
-  <div key={i} className={s.previewWrap}>
+{wImages.map((src) => (
+  <div key={src} className={s.previewWrap}>
```

#### 4.9 `plugins/manager/PluginMarketplace.jsx`

**Line ~126** — demo plugins have `id` field.

```diff
-{DEMO_PLUGINS.map((plugin, i) => (
-  <PluginCard key={i} plugin={plugin} />
+{DEMO_PLUGINS.map((plugin) => (
+  <PluginCard key={plugin.id} plugin={plugin} />
```

#### 4.10 `pages/Local/components/NaverPlaceDetailContent.jsx` and `RestDetailContent.jsx`

Menu rows — use menu item name or generate compound key.

```diff
-{menu.map((item, i) => <div key={i}>...</div>)}
+{menu.map((item) => <div key={`${item.name}-${item.price}`}>...</div>)}
```

### Summary

| File | # Fixes | Stable Key Source |
|------|---------|-------------------|
| SearchAutocomplete.jsx | 2 | `kw.id`, `p.id` |
| SearchBar.jsx | 2 | `item.label`, `item.timestamp` |
| DetailModal.jsx | 1 | `url` (image URL) |
| PricePage.jsx | 2 | `v.name`, `entry.name` |
| CategoryComparePage.jsx | 3 | `t` (tag string), `b.label`, `alt.id` |
| MartPage.jsx | 2 | `item.id` |
| LocalPage.jsx | 3 | `item.place_id`, `item.name` |
| CommunityPage.jsx | 1 | `src` (URL) |
| PluginMarketplace.jsx | 1 | `plugin.id` |
| NaverPlaceDetailContent.jsx | 1 | `item.name-item.price` |
| **Total** | **18** | |

---

## 5. ARIA Labels

### Audit Findings

| Source | Finding |
|--------|---------|
| frontend-audit §10 | ~30% ARIA coverage overall |
| frontend-audit §10 | LoginModal: no tab roles, no form labels, no dialog role, unlabeled close |
| frontend-audit §10 | DetailModal: no dialog role, no heading, inaccessible images |
| frontend-audit §10 | RichTextEditor: toolbar buttons lack ARIA labels + `aria-pressed` |
| frontend-audit §16 | Button.jsx: missing `aria-busy` during loading state |
| frontend-audit §10 | Search inputs across HomePage, PricePage, SearchPage: no `aria-label` |

### 5.1 Button.jsx — add `aria-busy`

**File:** `components/common/Button.jsx`

```diff
     <button
       type={type}
       className={classes}
       disabled={disabled || loading}
       onClick={onClick}
+      aria-busy={loading || undefined}
       {...props}
     >
```

### 5.2 ErrorFallback.jsx — add `role="alert"`

**File:** `components/common/ErrorFallback.jsx`

```diff
-    <div className={`${s.wrapper} ${className}`}>
+    <div className={`${s.wrapper} ${className}`} role="alert">
```

### 5.3 LoginModal.jsx — full ARIA upgrade

**File:** `components/modals/LoginModal.jsx`

```diff
 // Outer overlay → add dialog semantics
-<div className={s.overlay} onClick={onClose}>
-  <div className={s.modal} onClick={e => e.stopPropagation()}>
+<div className={s.overlay} onClick={onClose} role="presentation">
+  <div className={s.modal} onClick={e => e.stopPropagation()}
+       role="dialog" aria-modal="true" aria-label="로그인">

 // Close button
-<button className={s.close} onClick={onClose}>&times;</button>
+<button className={s.close} onClick={onClose} aria-label="닫기">&times;</button>

 // Tab buttons → add tab semantics
-<div className={s.tabs}>
-  <button className={activeTab === 'login' ? s.active : ''} onClick={() => setTab('login')}>로그인</button>
-  <button className={activeTab === 'register' ? s.active : ''} onClick={() => setTab('register')}>회원가입</button>
-</div>
+<div className={s.tabs} role="tablist">
+  <button role="tab" aria-selected={activeTab === 'login'} className={activeTab === 'login' ? s.active : ''} onClick={() => setTab('login')}>로그인</button>
+  <button role="tab" aria-selected={activeTab === 'register'} className={activeTab === 'register' ? s.active : ''} onClick={() => setTab('register')}>회원가입</button>
+</div>

 // Form inputs → add explicit labels
-<input type="email" placeholder="이메일" .../>
+<label className="sr-only" htmlFor="login-email">이메일</label>
+<input id="login-email" type="email" placeholder="이메일" aria-label="이메일" .../>

-<input type="password" placeholder="비밀번호" .../>
+<label className="sr-only" htmlFor="login-password">비밀번호</label>
+<input id="login-password" type="password" placeholder="비밀번호" aria-label="비밀번호" .../>
```

> Add `.sr-only` CSS class (visually hidden, screen-reader visible) to a global stylesheet if not already present:
>
> ```css
> .sr-only {
>   position: absolute;
>   width: 1px;
>   height: 1px;
>   padding: 0;
>   margin: -1px;
>   overflow: hidden;
>   clip: rect(0, 0, 0, 0);
>   white-space: nowrap;
>   border: 0;
> }
> ```

### 5.4 DetailModal.jsx — dialog semantics

**File:** `components/modals/DetailModal.jsx`

```diff
-<div className={s.overlay} onClick={onClose}>
-  <div className={s.modal} onClick={e => e.stopPropagation()}>
+<div className={s.overlay} onClick={onClose} role="presentation">
+  <div className={s.modal} onClick={e => e.stopPropagation()}
+       role="dialog" aria-modal="true" aria-labelledby="detail-modal-title">

 // Close button
-<button className={s.closeBtn} onClick={onClose}><X size={20} /></button>
+<button className={s.closeBtn} onClick={onClose} aria-label="닫기"><X size={20} /></button>

 // Title → add id for aria-labelledby
-<h2 className={s.title}>{item.title}</h2>
+<h2 id="detail-modal-title" className={s.title}>{item.title}</h2>
```

### 5.5 RichTextEditor.jsx — toolbar button labels

**File:** `components/editor/RichTextEditor.jsx` (or wherever the toolbar is)

Add `aria-label` and `aria-pressed` to each formatting button:

```diff
-<button onClick={() => editor.chain().focus().toggleBold().run()}>B</button>
+<button
+  onClick={() => editor.chain().focus().toggleBold().run()}
+  aria-label="굵게"
+  aria-pressed={editor.isActive('bold')}
+>B</button>

-<button onClick={() => editor.chain().focus().toggleItalic().run()}>I</button>
+<button
+  onClick={() => editor.chain().focus().toggleItalic().run()}
+  aria-label="기울임"
+  aria-pressed={editor.isActive('italic')}
+>I</button>

-<button onClick={() => editor.chain().focus().toggleStrike().run()}>S</button>
+<button
+  onClick={() => editor.chain().focus().toggleStrike().run()}
+  aria-label="취소선"
+  aria-pressed={editor.isActive('strike')}
+>S</button>

-<button onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}>H2</button>
+<button
+  onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
+  aria-label="제목 2"
+  aria-pressed={editor.isActive('heading', { level: 2 })}
+>H2</button>
```

Wrap the toolbar in a semantic group:

```diff
-<div className={s.toolbar}>
+<div className={s.toolbar} role="toolbar" aria-label="텍스트 서식">
```

### 5.6 Search input ARIA labels

Add `aria-label` to search `<input>` elements that lack visible `<label>`:

| File | Fix |
|------|-----|
| `pages/Home/HomePage.jsx` | `<input aria-label="상품 검색" .../>` |
| `pages/Price/PricePage.jsx` | `<input aria-label="물가 검색" .../>` |
| `pages/Search/SearchPage.jsx` | `<input aria-label="통합 검색" .../>` |
| `pages/Community/CommunityPage.jsx` | `<input aria-label="게시글 검색" .../>` |

### 5.7 EmptyState.jsx — add `aria-live`

**File:** `components/common/EmptyState.jsx`

```diff
-<div className={`${s.wrapper} ${className}`}>
+<div className={`${s.wrapper} ${className}`} role="status" aria-live="polite">
```

### Summary of ARIA Changes

| Component | Changes |
|-----------|---------|
| Button.jsx | +`aria-busy` |
| ErrorFallback.jsx | +`role="alert"` |
| EmptyState.jsx | +`role="status"`, `aria-live="polite"` |
| LoginModal.jsx | +`role="dialog"`, `aria-modal`, `aria-label`, tab roles, form labels |
| DetailModal.jsx | +`role="dialog"`, `aria-modal`, `aria-labelledby`, close button label |
| RichTextEditor.jsx | +`role="toolbar"`, button `aria-label`s, `aria-pressed` |
| Search inputs (4 pages) | +`aria-label` on `<input>` elements |

---

## 6. Virtual Scrolling

### Audit Findings

| Source | Finding |
|--------|---------|
| stability-audit §8 | SearchPage: no virtual scroll for potentially large result sets |
| frontend-audit §11 | CommunityPage filtered posts: `filteredAndSorted` recalculates O(n log n) |
| frontend-audit §24 | Recommended virtual scrolling for HotdealPage and CommunityPage |

### Current State

- HotdealPage uses `useInfiniteScroll` (IntersectionObserver) — adds items incrementally ✅
- SearchPage renders all results via `.map()` — no limit, no virtualization
- CommunityPage renders all filtered posts via `.map()`
- No `react-window` or `react-virtualized` in dependencies

### 6.1 Install react-window

```bash
cd packages/website/frontend
npm install react-window
```

Add to Vite manual chunks:

**File:** `vite.config.js`

```diff
 manualChunks: {
   'vendor-react': ['react', 'react-dom', 'react-router-dom'],
   'vendor-charts': ['recharts'],
+  'vendor-virtual': ['react-window'],
   ...
 }
```

### 6.2 Create VirtualList wrapper component

**New file:** `components/common/VirtualList.jsx`

```jsx
import { FixedSizeList } from 'react-window';
import { useRef, useEffect, useState, useCallback } from 'react';

/**
 * Auto-sizing virtual list wrapper.
 * Falls back to regular rendering if < threshold items.
 */
export default function VirtualList({
  items,
  itemHeight = 120,
  renderItem,
  threshold = 50,
  overscanCount = 5,
  className = '',
}) {
  const containerRef = useRef(null);
  const [containerHeight, setContainerHeight] = useState(600);

  useEffect(() => {
    if (!containerRef.current) return;
    const observer = new ResizeObserver(([entry]) => {
      setContainerHeight(entry.contentRect.height);
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  // Below threshold → render normally (no overhead)
  if (items.length < threshold) {
    return <div className={className}>{items.map(renderItem)}</div>;
  }

  const Row = useCallback(
    ({ index, style }) => (
      <div style={style}>{renderItem(items[index], index)}</div>
    ),
    [items, renderItem],
  );

  return (
    <div ref={containerRef} className={className} style={{ flex: 1, minHeight: 400 }}>
      <FixedSizeList
        height={containerHeight}
        width="100%"
        itemCount={items.length}
        itemSize={itemHeight}
        overscanCount={overscanCount}
      >
        {Row}
      </FixedSizeList>
    </div>
  );
}
```

### 6.3 Integration: SearchPage

**File:** `pages/Search/SearchPage.jsx`

```diff
+import VirtualList from '../../components/common/VirtualList';

 // Replace plain .map() rendering with VirtualList when results are large:
-<div className={s.resultGrid}>
-  {results.map((item) => (
-    <SearchResultCard key={item.id} item={item} />
-  ))}
-</div>
+<VirtualList
+  items={results}
+  itemHeight={140}
+  className={s.resultGrid}
+  renderItem={(item) => <SearchResultCard key={item.id} item={item} />}
+/>
```

### 6.4 Integration: CommunityPage

**File:** `pages/Community/CommunityPage.jsx`

```diff
+import VirtualList from '../../components/common/VirtualList';

-<div className={s.postList}>
-  {filteredAndSorted.map((post) => (
-    <PostCard key={post.id} post={post} />
-  ))}
-</div>
+<VirtualList
+  items={filteredAndSorted}
+  itemHeight={160}
+  className={s.postList}
+  renderItem={(post) => <PostCard key={post.id} post={post} />}
+/>
```

> **Note:** `VirtualList` automatically falls back to regular `.map()` rendering when the list has fewer than 50 items, so there's no visual regression for short lists.

---

## 7. SSE Reconnection

### Audit Findings

| ID | Finding | Source |
|----|---------|--------|
| S-32 | No SSE reconnection — stream drop is permanent | stability-audit §10, §2.2 |
| — | No auto-reconnect; user gets partial results with no indication | stability-audit §2.2 |

### Current State (`services/localService.js`)

- Single `fetch()` call with `ReadableStream` reader
- On error: calls `onError?.(err)` once, then stops
- On AbortError: silently exits (expected abort from component unmount)
- No retry, no backoff, no reconnection

### 7.1 Rewrite with reconnection + exponential backoff

**File:** `services/localService.js` — full replacement

```js
/**
 * Local 서비스 — SSE 스트리밍 기반 지역 탐색 API
 * 자동 재연결 + 지수 백오프 지원
 */

const MAX_RETRIES = 3;
const BASE_DELAY_MS = 1000;
const MAX_DELAY_MS = 8000;

/**
 * SSE 스트리밍으로 카테고리별 결과를 점진적으로 수신한다.
 * 네트워크 오류 시 지수 백오프로 최대 3회 재연결을 시도한다.
 *
 * @param {Object} params - { locationName, lat, lng, categories, maxItems }
 * @param {Function} onCategory - 카테고리 결과 도착 시 콜백 (categoryData)
 * @param {Function} onDone - 스트리밍 완료 시 콜백
 * @param {Function} onError - 에러 시 콜백 (최종 실패 시)
 * @param {Function} [onRetry] - 재연결 시도 시 콜백 ({ attempt, maxRetries, delayMs })
 * @returns {Function} abort 함수
 */
export function streamAreaExplore(
  { locationName, lat, lng, categories, maxItems = 30 },
  onCategory,
  onDone,
  onError,
  onRetry,
) {
  const params = new URLSearchParams({ max_items: String(maxItems) });
  if (categories) params.set('categories', categories);
  if (locationName) params.set('location_name', locationName);
  if (lat != null) params.set('lat', String(lat));
  if (lng != null) params.set('lng', String(lng));

  const controller = new AbortController();
  const url = `/api/local/area-explore-stream?${params}`;

  // Track which categories we've already received (for dedup on reconnect)
  const receivedCategories = new Set();
  let aborted = false;

  async function readStream() {
    const response = await fetch(url, { signal: controller.signal });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

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
            onDone?.(data);
            return true; // stream completed normally
          }
          // Dedup: skip categories already received (from prior attempt)
          const catKey = data.name || data.category;
          if (catKey && receivedCategories.has(catKey)) continue;
          if (catKey) receivedCategories.add(catKey);
          onCategory?.(data);
        } catch { /* skip malformed JSON */ }
      }
    }
    onDone?.({});
    return true; // stream completed normally
  }

  (async () => {
    let attempt = 0;

    while (attempt <= MAX_RETRIES) {
      try {
        const completed = await readStream();
        if (completed) return; // success — done
      } catch (err) {
        if (aborted || err.name === 'AbortError') return;

        attempt++;
        if (attempt > MAX_RETRIES) {
          onError?.(err);
          return;
        }

        const delay = Math.min(BASE_DELAY_MS * 2 ** (attempt - 1), MAX_DELAY_MS);
        onRetry?.({ attempt, maxRetries: MAX_RETRIES, delayMs: delay });

        // Wait before retrying
        await new Promise((resolve) => {
          const timer = setTimeout(resolve, delay);
          controller.signal.addEventListener('abort', () => {
            clearTimeout(timer);
            resolve();
          }, { once: true });
        });

        if (controller.signal.aborted) return;
      }
    }
  })();

  return () => {
    aborted = true;
    controller.abort();
  };
}
```

### 7.2 Update LocalPage to show reconnection status

**File:** `pages/Local/LocalPage.jsx` — where `streamAreaExplore` is called:

```diff
+const [retryInfo, setRetryInfo] = useState(null);

 const abort = streamAreaExplore(
   params,
   handleCategory,
   handleDone,
-  handleError,
+  handleError,
+  (info) => {
+    setRetryInfo(info);
+    // Auto-clear after delay passes
+    setTimeout(() => setRetryInfo(null), info.delayMs + 500);
+  },
 );

 // In the JSX, show reconnection banner:
+{retryInfo && (
+  <div className={s.retryBanner} role="status" aria-live="polite">
+    <RefreshCw size={14} className={s.spin} />
+    <span>재연결 중... ({retryInfo.attempt}/{retryInfo.maxRetries})</span>
+  </div>
+)}
```

**CSS for retry banner** (add to `LocalPage.module.css`):

```css
.retryBanner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: var(--warning-bg, #fef3c7);
  color: var(--warning-text, #92400e);
  border-radius: 8px;
  font-size: 0.85rem;
  margin-bottom: 12px;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
```

---

## 8. Stale Data Timestamps

### Audit Findings

| Source | Finding |
|--------|---------|
| stability-audit §5.1 | Zustand persistence includes favorites/filters but no refresh timestamps |
| stability-audit §10 | No offline detection — user sees stale data with no indication |
| frontend-audit §11 | Multiple pages re-fetch all data on GPS change; no cache staleness indicator |

### Current State

- `api.js` has a 30-second TTL cache, but the user **never sees when data was last fetched**
- No "last refreshed" display anywhere in the UI

### 8.1 Create LastRefreshed component

**New file:** `components/common/LastRefreshed.jsx`

```jsx
import { useState, useEffect } from 'react';
import { RefreshCw } from 'lucide-react';
import s from './LastRefreshed.module.css';

function formatElapsed(ms) {
  const seconds = Math.floor(ms / 1000);
  if (seconds < 10) return '방금 전';
  if (seconds < 60) return `${seconds}초 전`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}분 전`;
  const hours = Math.floor(minutes / 60);
  return `${hours}시간 전`;
}

/**
 * Displays "마지막 업데이트: N초 전" with optional manual refresh.
 * Updates the relative time every 15 seconds.
 */
export default function LastRefreshed({ timestamp, onRefresh, loading = false, className = '' }) {
  const [, setTick] = useState(0);

  useEffect(() => {
    if (!timestamp) return;
    const id = setInterval(() => setTick((t) => t + 1), 15_000);
    return () => clearInterval(id);
  }, [timestamp]);

  if (!timestamp) return null;

  const elapsed = Date.now() - timestamp;

  return (
    <div className={`${s.wrapper} ${className}`} aria-live="polite">
      <span className={s.text}>마지막 업데이트: {formatElapsed(elapsed)}</span>
      {onRefresh && (
        <button
          className={s.refreshBtn}
          onClick={onRefresh}
          disabled={loading}
          aria-label="새로고침"
          title="새로고침"
        >
          <RefreshCw size={14} className={loading ? s.spin : ''} />
        </button>
      )}
    </div>
  );
}
```

**New file:** `components/common/LastRefreshed.module.css`

```css
.wrapper {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 0.75rem;
  color: var(--text3, #9ca3af);
}

.text {
  white-space: nowrap;
}

.refreshBtn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 2px;
  border: none;
  background: none;
  color: var(--text3, #9ca3af);
  cursor: pointer;
  border-radius: 4px;
  transition: color 0.15s;
}

.refreshBtn:hover:not(:disabled) {
  color: var(--primary, #3b82f6);
}

.refreshBtn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
```

### 8.2 Create useRefreshTimestamp hook

**New file:** `hooks/useRefreshTimestamp.js`

```js
import { useState, useCallback } from 'react';

/**
 * Tracks the last time a data fetch completed successfully.
 * Returns { lastRefreshed, markRefreshed }.
 */
export default function useRefreshTimestamp() {
  const [lastRefreshed, setLastRefreshed] = useState(null);
  const markRefreshed = useCallback(() => setLastRefreshed(Date.now()), []);
  return { lastRefreshed, markRefreshed };
}
```

### 8.3 Integration: data-heavy pages

#### HomePage.jsx

```diff
+import LastRefreshed from '../../components/common/LastRefreshed';
+import useRefreshTimestamp from '../../hooks/useRefreshTimestamp';

 function HomePage() {
+  const { lastRefreshed, markRefreshed } = useRefreshTimestamp();

   useEffect(() => {
     fetchAllData().then(() => {
+      markRefreshed();
     });
   }, [/* deps */]);

   return (
     <div className={s.page}>
+      <LastRefreshed
+        timestamp={lastRefreshed}
+        onRefresh={() => { fetchAllData().then(markRefreshed); }}
+        loading={loading}
+      />
       {/* rest of page */}
```

#### HotdealPage.jsx

```diff
+import LastRefreshed from '../../components/common/LastRefreshed';
+import useRefreshTimestamp from '../../hooks/useRefreshTimestamp';

 function HotdealPage() {
+  const { lastRefreshed, markRefreshed } = useRefreshTimestamp();

   // After successful fetch in polling or initial load:
   const fetchDeals = async () => {
     const data = await api.getJson('/api/hotdeals', ...);
     setDeals(data);
+    markRefreshed();
   };

   return (
     <section className={s.header}>
       <h1>핫딜</h1>
+      <LastRefreshed timestamp={lastRefreshed} onRefresh={fetchDeals} loading={loading} />
     </section>
```

#### PricePage.jsx

```diff
+import LastRefreshed from '../../components/common/LastRefreshed';
+import useRefreshTimestamp from '../../hooks/useRefreshTimestamp';

 function PricePage() {
+  const { lastRefreshed, markRefreshed } = useRefreshTimestamp();

   useEffect(() => {
     fetchProduct().then(() => {
+      markRefreshed();
     });
   }, [productId]);

   // In the chart section header:
+  <LastRefreshed timestamp={lastRefreshed} onRefresh={() => fetchProduct().then(markRefreshed)} />
```

#### LocalPage.jsx

```diff
+import LastRefreshed from '../../components/common/LastRefreshed';
+import useRefreshTimestamp from '../../hooks/useRefreshTimestamp';

 function LocalPage() {
+  const { lastRefreshed, markRefreshed } = useRefreshTimestamp();

   // In the SSE onDone callback:
   const handleDone = (data) => {
     setStreaming(false);
+    markRefreshed();
   };

+  <LastRefreshed timestamp={lastRefreshed} onRefresh={startExplore} loading={streaming} />
```

#### MartPage.jsx

```diff
+import LastRefreshed from '../../components/common/LastRefreshed';
+import useRefreshTimestamp from '../../hooks/useRefreshTimestamp';

 function MartPage() {
+  const { lastRefreshed, markRefreshed } = useRefreshTimestamp();

   // After flyer/mart data loaded:
+  markRefreshed();

+  <LastRefreshed timestamp={lastRefreshed} onRefresh={loadMartData} loading={loading} />
```

### Target Pages for Timestamps

| Page | Placement | Refresh Trigger |
|------|-----------|----------------|
| HomePage | Below header, above content sections | Re-fetch all 8 data sources |
| HotdealPage | Section header, next to "핫딜" title | Re-fetch deals |
| PricePage | Chart section header | Re-fetch product + chart data |
| LocalPage | Above category results | Re-start SSE stream |
| MartPage | Flyer section header | Re-fetch mart/flyer data |
| CommunityPage | Post list header | Re-fetch posts |

---

## 9. Dependency Changes

### New Dependencies to Install

```bash
cd packages/website/frontend
npm install react-window
```

### No Additional Dependencies Needed

| Feature | Library | Notes |
|---------|---------|-------|
| Error Boundary | Built-in (class component) | No `react-error-boundary` needed — custom class is lightweight |
| SafeImage | Built-in (React `useState`) | No external library |
| Virtual Scrolling | `react-window` | Lightweight (~6 KB gzipped) |
| SSE Reconnection | Built-in (native fetch + retry loop) | No external library |
| Token Utils | Built-in (`atob`) | No external library |
| Timestamp Display | Built-in (React component) | No external library |

### Vite Config Update

**File:** `vite.config.js`

```diff
 manualChunks: {
   'vendor-react': ['react', 'react-dom', 'react-router-dom'],
   'vendor-charts': ['recharts'],
+  'vendor-virtual': ['react-window'],
   'vendor-editor': ['@tiptap/react', '@tiptap/starter-kit'],
   'vendor-zustand': ['zustand'],
 }
```

---

## 10. Verification Checklist

### New Files Created

| File | Purpose |
|------|---------|
| `components/common/ErrorBoundary.jsx` | React class error boundary wrapping routes |
| `components/common/SafeImage.jsx` | Image component with onError fallback |
| `components/common/SafeImage.module.css` | SafeImage fallback styles |
| `components/common/LastRefreshed.jsx` | "Last updated: N분 전" display component |
| `components/common/LastRefreshed.module.css` | LastRefreshed styles |
| `components/common/VirtualList.jsx` | react-window wrapper with auto-fallback |
| `hooks/useNetworkError.js` | Per-fetch error state management |
| `hooks/useRefreshTimestamp.js` | Tracks last successful data fetch time |
| `utils/tokenUtils.js` | JWT decode + expiry check utilities |

### Modified Files

| File | Changes |
|------|---------|
| `App.jsx` | +ErrorBoundary wrap, +auth rehydration effect |
| `services/api.js` | +proactive token refresh, +logout cleanup on 401 |
| `services/localService.js` | Full rewrite: +reconnection, +backoff, +dedup |
| `components/common/Button.jsx` | +`aria-busy` |
| `components/common/ErrorFallback.jsx` | +`role="alert"` |
| `components/common/EmptyState.jsx` | +`role="status"`, `aria-live="polite"` |
| `components/modals/LoginModal.jsx` | +dialog ARIA, +tab roles, +form labels |
| `components/modals/DetailModal.jsx` | +dialog ARIA, +SafeImage, +stable keys |
| `components/modals/MartProductModal.jsx` | +SafeImage |
| `components/modals/ProductQuickView.jsx` | +SafeImage |
| `components/common/SearchBar.jsx` | Stable keys for suggestions/recent |
| `components/search/SearchAutocomplete.jsx` | Stable keys for keywords/products |
| `components/editor/RichTextEditor.jsx` | +toolbar ARIA, +button labels, +aria-pressed |
| `pages/Home/HomePage.jsx` | +SafeImage, +LastRefreshed, +search input aria-label |
| `pages/Hotdeal/HotdealPage.jsx` | +SafeImage, +LastRefreshed |
| `pages/Mart/MartPage.jsx` | +SafeImage, +stable keys, +LastRefreshed |
| `pages/Local/LocalPage.jsx` | +retry banner, +stable keys, +LastRefreshed |
| `pages/Local/components/NaverPlaceDetailContent.jsx` | +SafeImage, +stable keys |
| `pages/Price/PricePage.jsx` | +stable keys, +LastRefreshed, +search input aria-label |
| `pages/Price/CategoryComparePage.jsx` | +stable keys |
| `pages/Community/CommunityPage.jsx` | +SafeImage, +stable keys, +VirtualList, +LastRefreshed |
| `pages/Search/SearchPage.jsx` | +SafeImage, +VirtualList, +search input aria-label |
| `plugins/manager/PluginMarketplace.jsx` | +stable keys |
| `vite.config.js` | +`vendor-virtual` chunk |
| `package.json` | +`react-window` dependency |

### Manual Testing Plan

| # | Test | Expected |
|---|------|----------|
| 1 | Disconnect network → reload page | ErrorBoundary catches, shows Korean error + retry button |
| 2 | Let access token expire → make API call | Auto-refresh triggers; if fails, login modal opens, state cleared |
| 3 | Load page with broken image URLs | SafeImage shows placeholder icon (no broken image browser icon) |
| 4 | Open DevTools → filter React warnings for "key" | Zero "Each child should have unique key" warnings |
| 5 | Run axe DevTools on LoginModal | No missing label / dialog-role violations |
| 6 | Load 100+ community posts | VirtualList kicks in (only visible items rendered) |
| 7 | Start local area explore → kill server mid-stream | "재연결 중..." banner appears, retries 3 times |
| 8 | Load HotdealPage → wait 30s → check timestamp | Shows "30초 전", click refresh → updates to "방금 전" |
| 9 | Screen reader navigation through LoginModal | Announces "로그인 dialog", reads tab roles + form labels |
| 10 | RichTextEditor → screen reader announces toolbar | Buttons announced as "굵게 토글 버튼, 눌림" |

---

## Audit Traceability

| Spec Section | Audit IDs Addressed |
|-------------|---------------------|
| §1 Network Error UI | S-14, S-15, S-16 |
| §2 Auth Token Handling | S-21, S-25 |
| §3 Image Error Fallbacks | S-30 |
| §4 Index-Based Keys | frontend-audit §7 (18 fixes across 10 files) |
| §5 ARIA Labels | frontend-audit §10, §16 (7 components) |
| §6 Virtual Scrolling | frontend-audit §11, §24 |
| §7 SSE Reconnection | S-32 |
| §8 Stale Data Timestamps | S-31, frontend-audit §11 |
