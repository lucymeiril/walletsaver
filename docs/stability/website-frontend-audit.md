# Website Frontend Stability Audit

> **Audited:** packages/website/frontend/src/  
> **Stack:** React 18 · Zustand · React Router 6 · Vite 5 · Recharts · Tiptap  
> **Files Reviewed:** 80+ (JSX, JS, CSS Modules)  
> **Overall Stability Score: 5 / 10** 🔴

---

## Executive Summary

The WalletSavior website frontend is a feature-rich SPA with ~80 source files covering product price comparison, hotdeal aggregation, mart flyer viewing, local area exploration (streaming API), community boards, and a plugin system. While the project uses solid foundational patterns (Zustand stores, CSS Modules, lazy loading, manual chunk splitting), **critical stability gaps** exist that would cause crashes, memory leaks, and degraded UX in production.

### Top 5 Critical Issues

| # | Issue | Impact | Affected Files |
|---|-------|--------|----------------|
| 1 | **No Error Boundaries** — zero pages wrapped | Any API/render error crashes the entire app | All pages |
| 2 | **No AbortController on page fetches** | Memory leaks & state-after-unmount on navigation | HomePage, MartPage, LocalPage, PricePage, CommunityPage, HotdealPage |
| 3 | **Token storage in sessionStorage** | XSS can steal auth tokens | api.js, authService.js |
| 4 | **Toast system FIFO bug** | Wrong toast removed; hardcoded 3 s overrides duration | ToastContainer.jsx |
| 5 | **Streaming reader never cancelled** | Reader continues after unmount → memory leak | localService.js, LocalPage.jsx |

---

## 1. Error Boundaries

### Current State: ❌ 0 % Coverage

`App.jsx` wraps routes in `<Suspense>` for lazy loading but has **no `<ErrorBoundary>`**. An unhandled error in any page component crashes the entire React tree with a blank white screen.

| File | Has Error Boundary? | Notes |
|------|---------------------|-------|
| App.jsx | ❌ No | Routes not wrapped |
| HomePage.jsx | ❌ No | 8 API calls; any failure unguarded |
| MartPage.jsx | ❌ No | Flyer fetch can crash |
| HotdealPage.jsx | ❌ No | Polling + voting + comments |
| LocalPage.jsx | ❌ No | Streaming API failures |
| PricePage.jsx | ❌ No | Chart + product fetch |
| CommunityPage.jsx | ❌ No | Post creation, image upload |
| SearchPage.jsx | ❌ No | Search fetch |
| CategoryComparePage.jsx | ❌ No | Category data fetch |

**`ErrorFallback.jsx` exists** as a presentational component with dynamic icons and retry button, but it is never used as an actual React error boundary (class component with `componentDidCatch`).

### Recommendation

```jsx
// Wrap in App.jsx
<ErrorBoundary fallback={<ErrorFallback onRetry={() => window.location.reload()} />}>
  <Routes>…</Routes>
</ErrorBoundary>

// Per-section boundaries in data-heavy pages
<ErrorBoundary fallback={<ErrorFallback code={500} />}>
  <HotdealSection />
</ErrorBoundary>
```

---

## 2. Loading States

### Current State: ⚠️ ~70 % Coverage

Most pages show a `<Spinner>` during initial data fetch. Gaps exist for:

| Gap | Location | Impact |
|-----|----------|--------|
| No loading indicator for vote requests | HotdealPage | Optimistic UI with no spinner; user unaware of pending request |
| No loading state on submit button | CommunityPage write form | User can spam-submit posts |
| No skeleton for flyer pages | MartPage flyer viewer | Blank area while flyer images load |
| Chart loading blank | PricePage chart section | Empty white space while chart data fetches |
| No loading for autocomplete | PricePage search | Typing shows nothing until results arrive |
| No loading for install button | PluginMarketplace | Install appears to do nothing |

**Good:** `Spinner.jsx` has proper `role="status"`, `aria-label`, and screen-reader text.  
**Good:** `SkeletonLoader.jsx` exists for Local page.

### Recommendation

Add `loading` state to all mutation buttons (vote, submit, install). Use skeleton loaders instead of spinners for content areas.

---

## 3. Empty States

### Current State: ⚠️ ~60 % Coverage

`EmptyState.jsx` component exists but is **not consistently used**.

| Page | Empty State Handled? | Gap |
|------|----------------------|-----|
| HomePage — favorites | ✅ Hidden when empty | — |
| HomePage — gas stations | ❌ No | Shows nothing if array empty |
| HomePage — price grid | ❌ No | Uses `PRODUCTS.slice(0,8)` — no fallback |
| MartPage — deals list | ❌ No | No message after load if `martDeals` empty |
| MartPage — flyer pages | ❌ No | Blank if `flyerPages.length === 0` |
| HotdealPage — filtered items | ❌ No | Filter can result in 0 items with no message |
| LocalPage — category results | ❌ No | Category with 0 results shows blank |
| PricePage — chart data | ❌ No | Blank chart if `chartData.length === 0` |
| PricePage — related hotdeals | ❌ No | Empty section if array empty |
| CommunityPage — filtered posts | ❌ No | Filtered list can be empty with no message |
| SearchPage — no results | ✅ Yes | — |
| SearchPage — no query | ✅ Yes | — |
| CategoryComparePage — no products | ✅ Yes | — |

### Recommendation

Audit every `.map()` / `.filter()` and add `{items.length === 0 && <EmptyState />}` fallback.

---

## 4. Form Validation

### Current State: ⚠️ ~40 % Coverage

| Form / Input | Client Validation? | Issues |
|-------------|-------------------|--------|
| Login form (LoginModal) | ❌ None | No email format check, no password rules, demo login hardcoded |
| Community post title | ⚠️ Empty check only | No max length validation |
| Community post price | ⚠️ `type="number"` | Relies on browser; no explicit validation |
| Community image upload | ❌ None | No file size limit — user can upload 100 MB images |
| Comment input (HotdealPage) | ✅ Trim check | But no user feedback on empty submit |
| Search inputs (all pages) | ⚠️ Partial | Accepts single-character queries, no max length |
| Location search (LocalPage) | ✅ Trim check | — |
| Product picker (CommunityPage) | ❌ None | Accepts non-existent product IDs |

**Service-level validation:** All service files (`authService`, `productService`, `hotdealService`, `searchService`) perform **zero input validation** before sending to API — no email format checks, no ID sanitization, no parameter type validation.

### Recommendation

Add validation layer in services:

```js
async login(email, password) {
  if (!email?.includes('@')) throw new Error('유효한 이메일을 입력하세요');
  if (!password || password.length < 6) throw new Error('비밀번호는 6자 이상이어야 합니다');
  // …
}
```

---

## 5. Debounce / Throttle

### Current State: ⚠️ Inconsistent

| Handler | Debounced? | Details |
|---------|-----------|---------|
| Search autocomplete (HomePage) | ✅ 200 ms | `debounceRef` with proper cleanup |
| Search autocomplete (SearchAutocomplete) | ✅ Yes | AbortController + debounce |
| PricePage search | ✅ `useDebounce` hook | 200 ms via custom hook |
| Vote button (HotdealPage) | ❌ No | User can spam vote API |
| Community search | ❌ No | No debounce on filter input |
| Category filter (MartPage) | ❌ No | Immediate re-render on change |
| Category filter (CategoryComparePage) | ❌ No | Immediate fetch on change |
| Flyer drag handler (MartPage) | ❌ No | Fires on every pixel; needs `requestAnimationFrame` |
| Radius slider (LocalPage) | ❌ No | Each change triggers full sort |
| Like/vote buttons (CommunityPage) | ❌ No | No rate limiting |
| Sort dropdown (SearchPage) | ❌ No | Each selection triggers fetch |

**`useDebounce` hook** exists and works correctly with proper cleanup. Not used universally.

### Recommendation

- Apply `useDebounce` to all search/filter inputs
- Add click-throttle wrapper for mutation buttons (vote, like, submit)
- Use `requestAnimationFrame` for drag/mouse-move handlers

---

## 6. useEffect Cleanup

### Current State: ❌ Major Gaps

#### AbortController Usage

| File | Uses AbortController? | Consequence |
|------|----------------------|-------------|
| `useAbortController.js` hook | ✅ Yes | Properly aborts previous controllers |
| `SearchAutocomplete.jsx` | ✅ Yes | Full AbortController + debounce cleanup |
| `ProductQuickView.jsx` | ⚠️ Uses `cancelled` flag | Functional but non-standard |
| `HomePage.jsx` (8 API calls) | ❌ No | All fetches complete even after unmount |
| `MartPage.jsx` (mart + flyer) | ❌ No | Fetches leak on navigation |
| `HotdealPage.jsx` (polls + fetch) | ❌ No | Old polls continue after unmount |
| `LocalPage.jsx` (streaming) | ❌ No | Reader continues reading after unmount |
| `PricePage.jsx` (product + chart) | ❌ No | Dual fetch leak |
| `CommunityPage.jsx` (posts) | ❌ No | Post fetch completes after unmount |
| `CategoryComparePage.jsx` | ❌ No | Category fetch completes after unmount |

#### Interval / Timer Cleanup

| Issue | File | Details |
|-------|------|---------|
| Polling interval recreated on filter change | HotdealPage | `[filter, sort]` deps create new interval per change; rapid filter changes leak intervals |
| Geolocation never aborted | HomePage, LocalPage | `navigator.geolocation` callback fires after unmount |
| FileReader not aborted | RichTextEditor, CommunityPage | Reader completes after component unmount |

#### Event Listener Cleanup

| Component | Cleanup? | Notes |
|-----------|----------|-------|
| Modal.jsx | ✅ Yes | Focus trap + ESC key properly cleaned |
| Header.jsx | ✅ Yes | Scroll listener with passive option |
| ShoppingListPanel.jsx | ✅ Yes | ESC key + body overflow |
| SearchBar.jsx | ⚠️ Partial | Document click listener cleaned but has dependency issues |

### Recommendation

```js
// Pattern for ALL page-level fetches
useEffect(() => {
  const controller = new AbortController();
  fetchData({ signal: controller.signal })
    .catch(err => { if (err.name !== 'AbortError') setError(err); });
  return () => controller.abort();
}, [deps]);
```

---

## 7. React Key Stability

### Current State: ⚠️ Mixed

#### Index-Based Keys (Problematic)

| File | Line | Context | Risk |
|------|------|---------|------|
| SearchBar.jsx | ~106, ~117 | Suggestion list items | Reorder causes wrong item updates |
| DetailModal.jsx | ~73, ~89 | Comment list + content blocks | Index shifts on add/delete |
| MartPage.jsx | — | Common products comparison | Unstable if list changes |
| PricePage.jsx | ~178 | Product tags | Tags may reorder |
| PricePage.jsx | ~75 | Variant chips `key={i}` | Variants could reorder |
| CategoryComparePage.jsx | ~239 | Alternatives list | Index-based |
| CommunityPage.jsx | — | Image preview list | Removing images shifts keys |
| SkeletonLoader.jsx | — | Skeleton items | Acceptable (static count) |

#### Stable Keys (Good)

| File | Key Source | Notes |
|------|-----------|-------|
| SearchAutocomplete.jsx | `kw-${kw.id}`, `p-${p.id}` | ✅ Stable |
| HotdealPage.jsx | `d.id`, `c.id`, `f.key` | ✅ All stable |
| Header.jsx / BottomNav.jsx | `n.to` / route path | ✅ Stable (URLs don't change) |
| PluginMarketplace.jsx | `plugin.id` | ✅ Stable |
| ShoppingListPanel.jsx | `productId` | ✅ Stable |

### Recommendation

Replace all `key={i}` with `key={item.id}` or `key={item.uniqueField}`. For items without IDs, generate a stable key on creation (e.g., `crypto.randomUUID()`).

---

## 8. Modal Management

### Current State: ⚠️ Inconsistent

#### Architecture

- `ModalManager.jsx` — Switch-based router using `useModalStore`
- `Modal.jsx` (common) — **Excellent** implementation: focus trap, ESC key, `aria-modal`, portal rendering, body scroll lock
- Individual modals — **Not all use the common Modal component**

#### Per-Modal Audit

| Modal | Uses `<Modal>`? | ESC Key | Focus Trap | Scroll Lock | Backdrop Close | aria-modal |
|-------|----------------|---------|------------|-------------|----------------|------------|
| LoginModal | ❌ Custom overlay | ❌ No | ❌ No | ❌ No | ✅ Overlay click | ❌ No |
| HotdealModal | ✅ Via Modal | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes |
| MartProductModal | ✅ Via Modal | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes |
| DetailModal | ❌ Custom overlay | ❌ No | ❌ No | ❌ No | ✅ Overlay click | ❌ No |
| ProductQuickView | ✅ Via Modal | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes |

#### Issues

- **LoginModal & DetailModal** do not use the common `Modal.jsx` → missing ESC key, focus trap, scroll lock, ARIA attributes
- **Multiple modal stacking** not handled — no z-index management, no modal stack
- `Modal.jsx` uses `setTimeout(50ms)` for focus — unreliable on slow devices; should use `requestAnimationFrame`
- Body `overflow: hidden` can conflict when multiple modals open simultaneously
- `DetailModal` comment IDs use `Date.now()` — collision risk on rapid comment addition

### Recommendation

Migrate LoginModal and DetailModal to use the common `<Modal>` component. Add modal stack management to ModalManager.

---

## 9. Responsive Design

### Current State: ⚠️ ~70 % Coverage

| Component | Mobile Ready? | Issues |
|-----------|--------------|--------|
| Header.jsx | ✅ Yes | Mobile menu with hamburger, scroll lock |
| BottomNav.jsx | ✅ Yes | Mobile-only bottom nav |
| SearchAutocomplete | ⚠️ Partial | Dropdown may overflow viewport |
| HomePage grid | ⚠️ CSS-dependent | Verify column count on mobile |
| MartPage flyer viewer | ❌ No | Fixed size, no pinch-to-zoom, no touch swipe |
| HotdealPage modal | ⚠️ Partial | No max-width on mobile; chart height fixed 180px |
| LocalPage map | ⚠️ Partial | iframe 100% width but fixed height |
| PricePage sidebar | ⚠️ Partial | Right sidebar hidden on mobile (verify) |
| CommunityPage write form | ⚠️ Partial | Input fields may overflow on mobile |
| CategoryComparePage table | ❌ No | Table overflows on mobile, no horizontal scroll |
| PricePage variant chips | ⚠️ Partial | May overflow without scroll |

**Touch Events:** MartPage flyer drag uses mouse events only — no `touchstart`/`touchmove`/`touchend` for mobile zoom/pan.

### Recommendation

- Add touch event handlers for MartPage flyer
- Wrap tables in `overflow-x: auto` containers
- Test all pages at 320px, 375px, 768px viewports
- Add `@media` queries for chart heights

---

## 10. Accessibility

### Current State: ❌ ~30 % Coverage

#### Good Practices Found

| Component | A11y Feature | Notes |
|-----------|-------------|-------|
| Modal.jsx | Focus trap, ESC key, aria-modal, role="dialog" | ✅ Excellent |
| Spinner.jsx | role="status", aria-label, sr-only text | ✅ Excellent |
| Input.jsx | aria-invalid, aria-describedby, role="alert", htmlFor | ✅ Excellent |
| Header.jsx | aria-labels on icon buttons | ✅ Good |
| BottomNav.jsx | aria-label="하단 네비게이션" | ✅ Good |
| SearchAutocomplete.jsx | Full keyboard nav (Arrow/Enter/ESC) | ✅ Good |
| PluginMarketplace StarRating | aria-label | ✅ Good |

#### Missing Accessibility

| Issue | Affected Components |
|-------|-------------------|
| **No aria-label on search inputs** | HomePage, PricePage, SearchPage |
| **No aria-pressed on toggle buttons** | Favorite heart (all pages), vote buttons (HotdealPage) |
| **No aria-expanded on dropdowns** | SearchBar, ShareButton, ProductPicker |
| **No role="tablist" / aria-selected** | CommunityPage tabs, MartPage mart tabs |
| **No aria-live regions** | EmptyState, price updates, verification results |
| **No keyboard navigation** | MartPage zoom/pan, mart tab selection |
| **No role="alert"** | ErrorFallback wrapper |
| **Missing alt text** | MartPage product images |
| **No aria-controls** on tabs | Tabs.jsx — tab → tabpanel association missing |
| **No tabindex on tabpanel** | Tabs.jsx — panel not keyboard-focusable |
| **Toolbar buttons lack aria-labels** | RichTextEditor — uses `title` only |
| **No role="listbox"** | ProductPicker dropdown |
| **No focus management** | After search submit, after location change |

#### Button.jsx Loading State

`Button.jsx` hides text when loading via CSS class `hiddenText` — screen readers may not know the button is loading. Should add `aria-busy="true"` instead.

### Recommendation

1. Add `aria-label` to all search inputs and icon-only buttons
2. Add `aria-pressed` to all toggle buttons
3. Add `role="tablist"`, `role="tab"`, `role="tabpanel"`, `aria-selected` to Tabs.jsx
4. Add `aria-live="polite"` to EmptyState and dynamic update regions
5. Add `role="alert"` to ErrorFallback

---

## 11. Performance

### Current State: ⚠️ Several Concerns

#### Re-render Issues

| Issue | File | Impact |
|-------|------|--------|
| `handleProductClick` not memoized | HomePage | New function ref every render |
| Data normalization inline every render | MartProductModal | Should use `useMemo` |
| Drag handler causes re-render per pixel | MartPage | Should use `useRef` for drag state |
| `sourceLabel` ternary recalculated | HotdealModal | Should use `useMemo` |
| `filteredAndSorted` recalculates on sort | CommunityPage | O(n log n) on each change |
| `enrichedProducts` recalculates | CategoryComparePage | Expensive for large lists |
| `sortItems()` called in render | LocalPage | No memoization |
| Gas price averaging in render | LocalPage | Should memoize |
| Tab count recalculated every render | SearchPage | Should memoize |

#### Unnecessary API Calls

| Issue | File | Impact |
|-------|------|--------|
| All 8 sections re-fetch on GPS change | HomePage | Full reload on coordinate update |
| All marts fetched on mount | MartPage | Even if user views only 1 mart |
| Polling creates new interval per filter | HotdealPage | Multiple concurrent polls |
| Category results not cached | LocalPage | Re-fetches on every click |
| Chart re-fetches on every URL change | PricePage | Could cache previous results |

#### Good Practices Found

| Pattern | Files |
|---------|-------|
| `React.memo()` on components | ProductQuickView, Header, SearchAutocomplete, PluginMarketplace PluginCard |
| `useCallback` for handlers | ProductQuickView, Header, SearchAutocomplete |
| `useMemo` for derived data | HomePage (activeMartInfo, topGas), HotdealPage (allItems), CategoryComparePage (enrichedProducts) |
| Request deduplication | api.js `_inflight` Map |
| Response caching with TTL | api.js `_cache` Map |

#### Memory Concerns

| Issue | File | Details |
|-------|------|---------|
| Base64 images stored in state | CommunityPage | 10+ images can exhaust memory |
| `_inflight` and `_cache` Maps grow indefinitely | api.js | No cache size limit or periodic purge |
| Global `toastId` counter | useToast.js | Increments forever |
| `flyerData` object grows unbounded | MartPage | Old flyer data never purged |
| `pendingRequests` Map in PluginSDKLoader | PluginSDKLoader.js | Relies on 5 s timeout only |

### Recommendation

- Use `URL.createObjectURL()` instead of Base64 for image previews
- Add LRU eviction to api.js cache (max 100 entries)
- Add `useCallback` to all click handlers passed as props
- Use `useRef` for drag state instead of `useState`
- Cache category results in LocalPage

---

## 12. Bundle Size & Code Splitting

### Current State: ✅ Good Foundation

**Vite config** (`vite.config.js`) has manual chunks:

```js
manualChunks: {
  'vendor-react': ['react', 'react-dom', 'react-router-dom'],
  'vendor-charts': ['recharts'],
  'vendor-editor': ['@tiptap/react', '@tiptap/starter-kit'],
  'vendor-zustand': ['zustand'],
}
```

**Route-level code splitting** via `React.lazy()` in `App.jsx` — all pages are lazy-loaded.

#### Issues

| Issue | Impact |
|-------|--------|
| `lucide-react` not in manual chunks | Imported across many files; could be its own chunk |
| `dompurify` not chunked | Used only in community/sanitize contexts |
| Tiptap extensions (`@tiptap/extension-*`) not in editor chunk | Only `@tiptap/react` and `@tiptap/starter-kit` chunked |
| Plugin system not lazy-loaded | `plugins/` directory loaded eagerly |
| `recharts` loaded even if user never visits PricePage | Chart chunk loaded but component is lazy — acceptable |
| `chunkSizeWarningLimit: 500` | 500 KB limit is generous; consider 300 KB |

#### Recommendations

```js
manualChunks: {
  'vendor-react': ['react', 'react-dom', 'react-router-dom'],
  'vendor-charts': ['recharts'],
  'vendor-editor': ['@tiptap/react', '@tiptap/starter-kit',
    '@tiptap/extension-image', '@tiptap/extension-link', '@tiptap/extension-placeholder'],
  'vendor-zustand': ['zustand'],
  'vendor-icons': ['lucide-react'],
  'vendor-sanitize': ['dompurify'],
}
```

---

## 13. Security Findings

| Severity | Issue | File | Details |
|----------|-------|------|---------|
| 🔴 CRITICAL | Auth tokens in sessionStorage | api.js, authService.js | XSS can steal tokens; use httpOnly cookies |
| 🔴 CRITICAL | No input validation in services | All service files | `productId`, `dealId`, `reason`, `dealData` sent unsanitized |
| 🟠 HIGH | Social login provider not whitelisted | authService.js | `provider` param in URL not validated |
| 🟠 HIGH | `submitDeal(dealData)` has no schema validation | hotdealService.js | Arbitrary data sent to API |
| 🟡 MEDIUM | `style` attribute allowed in sanitizer | sanitize.js | CSS injection possible via `style="display:none"` |
| 🟡 MEDIUM | `targetOrigin: '*'` default in MessageBridge | MessageBridge.js | Dangerous for postMessage; should require explicit origin |
| 🟡 MEDIUM | Token refresh race condition | api.js | Multiple 401s trigger simultaneous refresh calls |
| 🟡 MEDIUM | User object stored in localStorage | appStore.js | Sensitive user data persisted client-side |
| 🟢 LOW | PluginSDKLoader origin fallback | PluginSDKLoader.js | Falls back to `window.location.origin` if no referrer |

### Good Security Practices

- ✅ `encodeURIComponent()` used in SearchAutocomplete, MartProductModal
- ✅ DOMPurify for HTML sanitization in community content
- ✅ `rel="noopener noreferrer"` on external links
- ✅ Plugin sandbox: never combines `allow-scripts` + `allow-same-origin`
- ✅ Plugin manifest schema validation with permission whitelist
- ✅ Plugin entry URL restricted to relative/http (no `javascript:`)

---

## 14. Plugin System Audit

### Current State: ✅ Well-Architected

The plugin system (`plugins/`) demonstrates strong security practices:

| Component | Status | Notes |
|-----------|--------|-------|
| PluginSandbox.jsx | ✅ Excellent | CSP sandbox attrs, `referrerPolicy: "no-referrer"`, 3-state UI (loading/ready/error), retry |
| PluginInstaller.js | ✅ Good | Manifest validation, permission flow, URL safety checks |
| PermissionManager.js | ✅ Good | Permission whitelist, localStorage persistence with error handling |
| MessageBridge.js | ✅ Good | Origin allowlist, timeout on pending requests, proper disconnect/cleanup |
| PluginAPI.js | ✅ Good | External URL rejection, CORS origin config, destroy cleanup |
| manifest.schema.js | ✅ Good | Comprehensive schema validation, clear error messages |

#### Issues

| Issue | Severity | Details |
|-------|----------|---------|
| `targetOrigin: '*'` default | MEDIUM | MessageBridge should require explicit origin |
| Default mock data providers in PluginAPI | LOW | Could confuse production if not overridden |
| `themeChangeCallbacks` is a shared global Set | LOW | All PluginAPI instances share it |
| `requestPermissions` doesn't validate against whitelist | LOW | Requested permissions not pre-validated |
| No encryption of stored plugin data | LOW | localStorage data in plain text |

---

## 15. Custom Hooks Audit

| Hook | Status | Issues |
|------|--------|--------|
| `useAbortController` | ✅ Stable | Proper cleanup; used too rarely in pages |
| `useDebounce` | ✅ Stable | Correct timeout cleanup; should be used more widely |
| `useInfiniteScroll` | ⚠️ Needs improvement | No IntersectionObserver fallback; callback should be memoized by consumer |
| `useLocalStorage` | ❌ Bug | `storedValue` in dependency array causes unnecessary re-renders and stale closures; no QuotaExceededError handling; no cross-tab sync |
| `useMediaQuery` | ✅ Minor issue | Redundant initial `setMatches` call; SSR-safe |
| `useToast` | ❌ Bug | Global `toastId` counter increments indefinitely; no auto-dismiss; no max queue limit |

---

## 16. Common Components Audit

| Component | Status | Key Issues |
|-----------|--------|------------|
| Badge.jsx | ✅ Stable | Pure component |
| Button.jsx | ⚠️ Minor | `aria-busy` missing during loading state |
| Card.jsx | ⚠️ A11y | Interactive cards missing `aria-label`, focus styling |
| EmptyState.jsx | ⚠️ Minor | No `role="status"` or `aria-live`; hardcoded Korean text |
| ErrorFallback.jsx | ⚠️ Minor | Missing `role="alert"`; not used as actual error boundary |
| Input.jsx | ⚠️ Minor | `Math.random()` ID generated on every render — unstable `aria-describedby` |
| Modal.jsx | ✅ Excellent | Full focus trap, ESC key, ARIA, portal, scroll lock |
| SearchBar.jsx | ❌ Keys | Index-based keys on suggestions; debounce dependency issues |
| ShareButton.jsx | ⚠️ Error handling | No try/catch on `window.open`; useEffect dependency gap |
| ShoppingListPanel.jsx | ⚠️ Minor | `fmt()` doesn't handle negative/NaN; otherwise good |
| Spinner.jsx | ✅ Excellent | Proper `role="status"`, `aria-label`, sr-only text |
| Tabs.jsx | ❌ A11y/Perf | Ref callback recreated every render; missing `aria-controls`, `aria-labelledby`, tabindex on panel; crashes on empty tabs |
| Toast.jsx | ⚠️ Minor | Potential stale closure in `handleDismiss` |
| ToastContainer.jsx | ❌ Critical | Hardcoded 3000 ms overrides toast duration; FIFO removes wrong toast; missing `aria-live` |

---

## 17. Layout Components Audit

| Component | Status | Notes |
|-----------|--------|-------|
| Header.jsx | ✅ Good | `memo()`, `useCallback`, passive scroll listener, scroll lock, aria-labels |
| Footer.jsx | ⚠️ Minor | Placeholder `/` links; otherwise static |
| BottomNav.jsx | ✅ Good | Proper aria-label, stable keys |

---

## Scorecard

| Metric | Current | Target | Priority |
|--------|---------|--------|----------|
| Error Boundary Coverage | 0 % | 100 % | 🔴 P0 |
| AbortController Usage | ~15 % | 100 % | 🔴 P0 |
| Loading State Coverage | ~70 % | 100 % | 🟠 P1 |
| Empty State Coverage | ~60 % | 100 % | 🟠 P1 |
| Form Validation | ~40 % | 95 % | 🟠 P1 |
| useEffect Cleanup | ~30 % | 100 % | 🔴 P0 |
| React Key Stability | ~75 % | 100 % | 🟡 P2 |
| Modal Consistency | ~60 % | 100 % | 🟡 P2 |
| Keyboard Accessibility | ~40 % | 90 % | 🟡 P2 |
| ARIA Labels | ~20 % | 90 % | 🟡 P2 |
| Debounce Coverage | ~40 % | 90 % | 🟠 P1 |
| Memory Leak Prevention | ~30 % | 95 % | 🔴 P0 |
| Mobile Responsiveness | ~70 % | 95 % | 🟡 P2 |
| Bundle Splitting | ~80 % | 95 % | 🟢 P3 |

---

## Recommended Fix Order

### Phase 1 — Critical (Production Blockers)

1. **Add ErrorBoundary** class component wrapping `<Routes>` in App.jsx and per-section in heavy pages
2. **Add AbortController** to all `useEffect` fetch calls in pages (HomePage, MartPage, HotdealPage, LocalPage, PricePage, CommunityPage)
3. **Fix streaming cleanup** in LocalPage — abort reader on unmount
4. **Fix ToastContainer** — respect individual toast durations, remove correct toast (not FIFO)
5. **Fix useLocalStorage** — remove `storedValue` from dependency array, add QuotaExceededError handling
6. **Fix token storage** — migrate from sessionStorage to httpOnly cookies (requires backend changes)

### Phase 2 — High Priority (UX / Data Integrity)

7. **Add loading states to mutation buttons** (vote, submit, install)
8. **Add empty states** to all data sections (gas stations, flyer, filtered results, chart)
9. **Add input validation** to all service methods (email, productId, dealData)
10. **Add debounce** to vote buttons, filter inputs, category selections
11. **Fix HotdealPage polling** — use `useRef` for current filter/sort to avoid interval recreation
12. **Use blob URLs** instead of Base64 for image previews in CommunityPage

### Phase 3 — Medium Priority (A11y / Polish)

13. **Migrate LoginModal & DetailModal** to use common `<Modal>` component
14. **Add ARIA attributes** — `aria-pressed`, `aria-expanded`, `aria-label`, `role="tablist"`
15. **Replace index-based keys** with stable IDs in SearchBar, DetailModal, PricePage, CommunityPage
16. **Fix Tabs.jsx** — add `aria-controls`, handle empty tabs, stabilize ref callbacks
17. **Add keyboard navigation** to MartPage flyer (arrow keys, +/- zoom)
18. **Stabilize Input.jsx ID** — use `useId()` (React 18) or `useMemo` instead of `Math.random()`

### Phase 4 — Low Priority (Optimization)

19. **Add `React.memo` / `useCallback`** to un-memoized handlers in HomePage, MartPage
20. **Add LRU cache eviction** to api.js
21. **Lazy-load plugin system** — only load when user visits plugin marketplace
22. **Add `lucide-react` and `dompurify`** to manual chunks in vite config
23. **Add touch events** for MartPage flyer (pinch-to-zoom, swipe-to-pan)
24. **Add virtual scrolling** for long lists in HotdealPage and CommunityPage

---

## Testing Recommendations

1. **Memory Leak Testing** — Navigate rapidly between pages; check DevTools Memory tab for growing heap
2. **Network Error Testing** — Disable network in DevTools; verify all pages show error states gracefully
3. **Accessibility Testing** — Run axe DevTools on every page; test keyboard-only navigation through all modals
4. **Mobile Testing** — Chrome DevTools device emulation at 320px, 375px, 768px
5. **Stress Testing** — Load 1000+ items in lists; measure render performance with React Profiler
6. **Concurrent Request Testing** — Rapidly change filters/sorts; ensure old requests are aborted
7. **Token Refresh Testing** — Trigger multiple simultaneous 401 responses; verify no race condition

---

*Generated by Stability Planner — Frontend & UX Resilience Focus*
