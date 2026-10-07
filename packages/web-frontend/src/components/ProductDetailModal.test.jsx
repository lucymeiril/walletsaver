import { act, fireEvent, render, screen, waitFor, cleanup } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import PricePage from '../pages/Price/PricePage';
import ProfilePage from '../pages/Profile/ProfilePage';
import SearchPage from '../pages/Search/SearchPage';
import SearchAutocomplete from './search/SearchAutocomplete';
import { searchService } from '../services/searchService';
import ProductDetailModal from './ProductDetailModal';
import { api } from '../services/api';
import useStore from '../stores/appStore';
import useCartStore from '../stores/cartStore';
import ShoppingListPanel from './common/ShoppingListPanel';
import useModalStore from '../stores/modalStore';
import { buildProductDecision, getComparableOffers, getVariantBestOffer, getPriceHistorySummary, getOfferUnitPrice, getSavedReceiptHoldText, getOfferConditionText, getOfferReceiptText, getCartQuotePresentation, getObservedOfferPriceText, getCatalogObservationDescription } from '../utils/productDecision';
import { buildCartPayload, buildWishlistPayload, buildProductShareUrl, selectProductOffer, normalizeProduct, getSourceReferencePriceText } from '../utils/productActions';

vi.mock('recharts', () => ({ ResponsiveContainer: ({children}) => children, AreaChart: ({data}) => <div data-testid="selected-history">{JSON.stringify(data)}</div>, BarChart: () => null, Area: () => null, Bar: () => null, XAxis: () => null, YAxis: () => null, Tooltip: () => null, Cell: () => null }));

vi.mock('../services/api', () => ({
  api: {
    getJson: vi.fn(),
    postJson: vi.fn(),
    get: vi.fn(() => Promise.resolve({ json: () => Promise.resolve({ data: [] }) })),
    post: vi.fn((path, payload) => Promise.resolve({
      json: () => Promise.resolve(path === '/api/cart'
        ? { data: { ...payload, id: 9, cart_id: 9 } }
        : { data: { ...payload, id: 7 } }),
    })),
    put: vi.fn(() => Promise.resolve({ json: () => Promise.resolve({}) })),
    delete: vi.fn(() => Promise.resolve({ json: () => Promise.resolve({}) })),
  },
}));

vi.mock('../hooks/useActivityTracker', () => ({
  default: () => ({
    trackView: vi.fn(),
    trackCartAdd: vi.fn(),
    trackWishlistAdd: vi.fn(),
  }),
}));

describe('203 cart merge and selected quote presentation', () => {
  let apiImplementations;
  beforeEach(() => {
    apiImplementations = Object.fromEntries(['post', 'get', 'put', 'delete'].map(key => [key, api[key].getMockImplementation()]));
    useCartStore.getState().onLogout();
    useStore.setState({ isLoggedIn: false, user: null, toasts: [] });
    api.post.mockReset(); api.get.mockReset(); api.put.mockReset(); api.delete.mockReset();
    api.get.mockResolvedValue({ json: async () => ({ data: [] }) });
    api.put.mockResolvedValue({ json: async () => ({}) });
    api.delete.mockResolvedValue({ json: async () => ({}) });
  });
  afterEach(() => {
    cleanup(); useCartStore.getState().onLogout(); vi.clearAllMocks();
    for (const key of Object.keys(apiImplementations)) api[key].mockImplementation(apiImplementations[key]);
  });

  it('cold-hydrates the original selected guest receipt and recomputes totals on every cart mutation', async () => {
    const saved = {
      id: 'product:prod-paper:old-variant:paper-listing:paper-offer',
      product_id: 'prod-paper', variant_id: 'old-variant', listing_id: 'paper-listing', offer_id: 'paper-offer',
      name: '밀크 A4 친환경 복사지 80g 2500매', unit: '80g', price: 27000, price_known: true,
      original_price: 0, quantity: 1, saved_receipt_valid: null,
      offer_context: null, quoted_offer: { id: 'paper-offer', total_price: 27000,
        total_quantity: 80, quantity_unit: 'g', per_100g: 33750, current_eligible: true },
    };
    localStorage.setItem('wallet-savior-cart', JSON.stringify({ state: { items: [saved], pendingMerge: null }, version: 0 }));
    // Seed before module construction: rehydrate() on an existing store misses
    // the initial getState() === undefined / eager accessor failure.
    vi.resetModules();
    const { default: coldCart } = await import('../stores/cartStore');
    try {
      expect(coldCart.persist.hasHydrated()).toBe(true);
      expect(coldCart.getState()).toMatchObject({ itemCount: 1, totalPrice: 27000, totalSavings: 0,
        items: [{ product_id: 'prod-paper', variant_id: 'old-variant', listing_id: 'paper-listing',
          offer_id: 'paper-offer', price: 27000, quantity: 1, quoted_offer: saved.quoted_offer,
          offer_context: null, saved_receipt_valid: null }] });
      expect(getSavedReceiptHoldText(coldCart.getState().items[0])).toContain('규격 확인');
      const id = coldCart.getState().items[0].id;
      await coldCart.getState().updateQuantity(id, 2);
      expect(coldCart.getState()).toMatchObject({ itemCount: 2, totalPrice: 54000, totalSavings: 0 });
      await coldCart.getState().addItem(saved);
      expect(coldCart.getState()).toMatchObject({ itemCount: 3, totalPrice: 81000, totalSavings: 0 });
      expect(coldCart.getState().items).toHaveLength(1);
      expect(coldCart.getState().items[0]).toMatchObject({ variant_id: 'old-variant', offer_id: 'paper-offer', quoted_offer: saved.quoted_offer });
      await coldCart.getState().removeItem(id);
      expect(coldCart.getState()).toMatchObject({ items: [], itemCount: 0, totalPrice: 0, totalSavings: 0 });
      coldCart.setState({ items: [{ ...saved, original_price: 30000 }] });
      coldCart.setState(state => ({ items: state.items.map(item => ({ ...item, quantity: 2 })) }));
      expect(coldCart.getState()).toMatchObject({ itemCount: 2, totalPrice: 54000, totalSavings: 6000 });
      await coldCart.getState().clearCart();
      expect(coldCart.getState()).toMatchObject({ items: [], itemCount: 0, totalPrice: 0, totalSavings: 0 });
      expect(api.get).not.toHaveBeenCalled(); expect(api.post).not.toHaveBeenCalled();
      expect(api.put).not.toHaveBeenCalled(); expect(api.delete).not.toHaveBeenCalled();
    } finally {
      coldCart.getState().onLogout();
    }
  });

  it('retries a frozen guest merge with the same ID after a committed response is lost, without merging canonical rows again', async () => {
    const first = buildCartPayload(selectProductOffer(selectionFixture(), { variantId: 'var-a' }));
    const second = buildCartPayload(selectProductOffer(selectionFixture(), { variantId: 'var-b' }));
    await useCartStore.getState().addItem(first); await useCartStore.getState().addItem(second);
    useStore.setState({ isLoggedIn: true });
    const receipts = new Map(); let applied = 0;
    api.post.mockImplementation(async (path, batch) => {
      if (!receipts.has(batch.merge_id)) {
        applied += 1;
        receipts.set(batch.merge_id, batch.items.map((row, i) => ({ ...row, cart_id: i + 1,
          offer_context: { ...selectionFixture().variants[i].listings[0].offers[0], display_unit: i ? '90g×6' : '90g×3' } })));
        throw new Error('committed response lost');
      }
      return { json: async () => ({ data: receipts.get(batch.merge_id) }) };
    });
    await expect(useCartStore.getState().mergeOnLogin()).rejects.toThrow('committed response lost');
    const batch = useCartStore.getState().pendingMerge;
    expect(JSON.parse(localStorage.getItem('wallet-savior-cart')).state.pendingMerge).toEqual(batch);
    const rows = await useCartStore.getState().mergeOnLogin();
    expect(api.post.mock.calls[0][1]).toEqual(api.post.mock.calls[1][1]);
    expect(applied).toBe(1);
    expect(rows.map(row => [row.variant_id, row.offer_id, row.quantity])).toEqual([['var-a', 'offer-a', 1], ['var-b', 'offer-b', 1]]);
    expect(rows[0].offer_context).toMatchObject({ total_quantity: 270, minimum_quantity: 2, membership_required: true });
    expect(useCartStore.getState().pendingMerge).toBeNull();
    expect(api.get).not.toHaveBeenCalled();
    api.get.mockRejectedValueOnce(new Error('canonical fetch failed'));
    await expect(useCartStore.getState().mergeOnLogin()).rejects.toThrow('canonical fetch failed');
    expect(useCartStore.getState().items).toEqual(rows);
    api.get.mockResolvedValue({ json: async () => ({ data: rows }) });
    await useCartStore.getState().mergeOnLogin();
    expect(api.post).toHaveBeenCalledTimes(2);
    expect(api.get).toHaveBeenCalledTimes(2);
  });

  it('shares concurrent login merge and guards a malformed response without changing its batch', async () => {
    await useCartStore.getState().addItem({ item_name: '수동 무료', item_price: 0 });
    useStore.setState({ isLoggedIn: true });
    let resolve; api.post.mockImplementation(() => new Promise(done => { resolve = done; }));
    const first = useCartStore.getState().mergeOnLogin();
    const second = useCartStore.getState().mergeOnLogin();
    expect(first).toBe(second); expect(api.post).toHaveBeenCalledTimes(1);
    const batch = useCartStore.getState().pendingMerge;
    resolve({ json: async () => ({ data: null }) });
    await expect(first).rejects.toThrow('병합 결과를 확인');
    expect(useCartStore.getState().pendingMerge).toEqual(batch);
    expect(api.post.mock.calls[0][1].items[0]).toMatchObject({ item_price: 0, quantity: 1 });
  });

  it('renders selected spec, source and receipt conditions while keeping unknown money and unit prices unknown', () => {
    const quote = selectionFixture().variants[0].listings[0].offers[0];
    useCartStore.setState({ items: [
      { id: 'selected', product_id: 'prod-spec', variant_id: 'var-a', listing_id: 'listing-a', offer_id: 'offer-a',
        saved_receipt_valid: true, name: '선택 상품', price: 6000, price_known: true, quantity: 2, unit: '90g×3', store_name: 'emart',
        offer_context: { ...quote, comparable_price: null, source_title: '90g×3 실제 판매 상품' } },
      { id: 'held', product_id: 'prod-held', variant_id: 'var-held', listing_id: 'listing-held', offer_id: 'offer-held',
        name: '내용 미확인', price: 0, price_known: false, quantity: 1,
        offer_context: { total_quantity: null, quantity_unit: null, per_item: null, total_price: null } },
    ] });
    render(<MemoryRouter><ShoppingListPanel /></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: '장바구니 열기' }));
    expect(screen.getByText('선택 규격 90g×3')).toBeInTheDocument();
    expect(screen.getByText('판매 상품 90g×3 실제 판매 상품')).toBeInTheDocument();
    expect(screen.getByText(/수령 270g.*수령 패키지 3.*최소 구매 2.*구매 2.*추가 증정 1.*회원 필요.*쿠폰 필요 없음/)).toBeInTheDocument();
    expect(screen.getByText('주문 2회')).toBeInTheDocument();
    expect(screen.getByText('금액 미확인 1항목 · 전체 합계 미확인')).toBeInTheDocument();
    expect(screen.queryByText('0원')).not.toBeInTheDocument();
    expect(screen.queryByText(/개당/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('선택 상품'));
    expect(useModalStore.getState().modalData).toMatchObject({ product_id: 'prod-spec', variant_id: 'var-a', listing_id: 'listing-a', offer_id: 'offer-a' });
  });

  it.each([false, null, undefined])('holds revised or unverified saved cart receipt %s without replacing its tuple or money', async (valid) => {
    const receipt = { display_unit: '보온보냉병 2PK (950ml)', total_quantity: 950, quantity_unit: 'ml',
      per_100ml: 3262, total_price: 30990, comparable_price: 30990, received_package_count: 1,
      minimum_quantity: 2, membership_required: true, coupon_required: null };
    const row = { id: 7, product_id: 'prod-bottle', variant_id: 'old-variant', listing_id: 'listing-bottle', offer_id: 'saved-offer',
      item_name: '보온보냉병', item_price: 30990, quantity: 1, offer_context: receipt,
      saved_receipt_valid: valid, saved_receipt_reason: 'selected_specification_revised' };
    useStore.setState({ isLoggedIn: true });
    api.get.mockResolvedValue({ json: async () => ({ data: [row] }) });
    await useCartStore.getState().mergeOnLogin();
    expect(useCartStore.getState().items[0]).toMatchObject({ variant_id: 'old-variant', listing_id: 'listing-bottle',
      offer_id: 'saved-offer', price: 30990, offer_context: receipt, saved_receipt_reason: 'selected_specification_revised' });
    render(<MemoryRouter><ShoppingListPanel /></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: '장바구니 열기' }));
    expect(screen.getByText(/저장 당시 규격이 변경되었습니다.*규격 확인·다시 선택 필요/)).toBeInTheDocument();
    expect(screen.getByText('선택 규격 보온보냉병 2PK (950ml)')).toBeInTheDocument();
    expect(screen.getByText(/최소 구매 2.*회원 필요.*쿠폰 조건 미확인/)).toBeInTheDocument();
    expect(screen.queryByText(/수령 950ml|수령 패키지 1|100ml당|3,262원/)).not.toBeInTheDocument();
    expect(screen.getAllByText('30,990원').length).toBeGreaterThan(0);
    expect(getSavedReceiptHoldText({ ...row, product_id: 7 })).toBeNull();
    expect(api.post).not.toHaveBeenCalled();
  });

  it.each(['contents_identity_and_allocation_unverified', 'heterogeneous_contents_allocation_unverified'])('labels expired saved %s money as historical and preserves known aggregate observations without a unit rate', (reason) => {
    const quote = { id: 'past-offer', listed_price: 3990, total_price: 3990, comparable_price: 3990,
      total_quantity: 800, quantity_unit: 'ml', received_package_count: 2, minimum_quantity: 1,
      promotion_conditions: { buy_quantity: 1, free_quantity: 1, condition_text: '1+1' },
      quantity_comparison_reason: reason, per_100ml: 499, current_eligible: false,
      availability_reason: 'expired', valid_to: '2026-09-01 15:00:00.000000', crawled_at: '2026-09-02 13:39:13.826400' };
    const item = { id: 'past', product_id: 'prod-pops', variant_id: 'past-variant', listing_id: 'past-listing',
      offer_id: 'past-offer', name: '원래 400ml', unit: '400ml', quantity: 1, price: 3990,
      price_known: true, quoted_offer: quote, saved_receipt_valid: null };
    useCartStore.setState({ items: [item] });
    render(<MemoryRouter><ShoppingListPanel /></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: '장바구니 열기' }));
    expect(screen.getByText('저장된 출처 조건 계산 금액 3,990원')).toBeInTheDocument();
    expect(screen.getByText(/판매 기간 종료.*과거 관측 거래.*현재 결제 금액·구매 가능 여부 미확인/)).toBeInTheDocument();
    expect(screen.getByText('관측 출처 조건 계산: 수령 800ml · 관측 출처 조건 계산: 수령 패키지 2 · 과거 관측 구성')).toBeInTheDocument();
    expect(screen.getByText(/최소 구매 1.*1\+1.*구매 1.*추가 증정 1.*회원 조건 미확인/)).toBeInTheDocument();
    expect(screen.getByText('저장 관측 금액 합계 (1회 주문)')).toBeInTheDocument();
    expect(screen.getByText(/현재 결제 합계 미확인/)).toBeInTheDocument();
    expect(screen.queryByText('거래 금액 3,990원')).not.toBeInTheDocument();
    expect(screen.queryByText(/100ml당|499원|확인된 구매 금액/)).not.toBeInTheDocument();
    expect(screen.queryByText('0원', { exact: true })).not.toBeInTheDocument();
    expect(useCartStore.getState().items[0]).toEqual(item);
    expect(api.get).not.toHaveBeenCalled(); expect(api.post).not.toHaveBeenCalled();
    // A source-spec revision is stronger than a preserved old allocation hold:
    // the saved aggregate must not become current contents again.
    expect(getCartQuotePresentation({ ...item, saved_receipt_reason: 'selected_specification_revised' }).observedReceipt).toBeNull();
    // Old immutable server contexts may predate the comparison-reason field.
    const { quantity_comparison_reason, ...oldQuote } = quote;
    const saved = { ...item, quoted_offer: oldQuote, saved_receipt_valid: false, saved_receipt_reason: reason };
    expect(getCartQuotePresentation(saved)).toMatchObject({
      observedReceipt: '관측 출처 조건 계산: 수령 800ml · 관측 출처 조건 계산: 수령 패키지 2', canDisplayUnitPrice: false,
    });
    for (const mismatch of ['selected_specification_revised', 'receipt_components_unconfirmed', 'receipt_basis_revised']) {
      expect(getCartQuotePresentation({ ...saved, saved_receipt_reason: mismatch }).observedReceipt).toBeNull();
    }
    expect(saved.quoted_offer).not.toHaveProperty('quantity_comparison_reason');
  });

  it('requires actual saved eligibility and verified purchase conditions before labeling current purchase money', () => {
    const item = { product_id: 'prod-selected', variant_id: 'v', listing_id: 'l', offer_id: 'o', price: 3990,
      saved_receipt_valid: true, offer_context: { total_price: 3990, current_eligible: true,
        membership_required: false, coupon_required: false, minimum_quantity: 1 } };
    expect(getCartQuotePresentation(item)).toMatchObject({ confirmedPurchase: true, amountLabel: '확인된 구매 금액' });
    for (const changed of [{ membership_required: null }, { coupon_required: true }, { current_eligible: false }, { minimum_quantity: null },
      { total_price: null }, { total_price: 4990 }, { promotion_conditions: { payable_price_unconfirmed: true } },
      { valid_to: '2000-01-01 00:00:00.000000' }, { is_latest: false }, { availability_reason: 'not_started' },
      { availability_reason: 'not_yet_valid' }, { availability_reason: 'validity_unconfirmed' },
      { validity_eligible: false }, { valid_from: '2999-01-01 00:00:00.000000' }]) {
      expect(getCartQuotePresentation({ ...item, offer_context: { ...item.offer_context, ...changed } }).confirmedPurchase).toBe(false);
    }
    expect(getCartQuotePresentation({ ...item, saved_receipt_valid: null }).confirmedPurchase).toBe(false);
    expect(getCartQuotePresentation({ ...item, offer_context: { ...item.offer_context,
      valid_from: new Date().toISOString().slice(0, 10), valid_to: new Date().toISOString().slice(0, 10) } }).confirmedPurchase).toBe(true);
    expect(getCartQuotePresentation({ ...item, offer_context: { ...item.offer_context, is_latest: false,
      total_quantity: 800, quantity_unit: 'ml', per_100ml: 499 } })).toMatchObject({
      amountLabel: '과거 관측 금액', canDisplayUnitPrice: true, confirmedPurchase: false });
  });

  it('removes and updates the addressed cart row without changing a different legacy product whose ID equals cart_id', async () => {
    useStore.setState({ isLoggedIn: true });
    useCartStore.setState({ synced: true, items: [
      { id: 'product:prod-selected:v:l:o', cart_id: 7, product_id: 'prod-selected', variant_id: 'v', listing_id: 'l', offer_id: 'o', quantity: 1 },
      { id: 'product:7', cart_id: 8, product_id: 7, quantity: 2 },
    ] });
    await useCartStore.getState().updateQuantity(7, 3);
    expect(useCartStore.getState().items.map(row => row.quantity)).toEqual([3, 2]);
    await useCartStore.getState().removeItem(7);
    expect(useCartStore.getState().items).toMatchObject([{ cart_id: 8, product_id: 7, quantity: 2 }]);
  });

  it('holds unknown or unproved selected transaction amounts and preserves an authoritative empty cart across legacy rehydration', async () => {
    await expect(useCartStore.getState().addItem({ product_id: 'prod-missing', item_name: '금액 미확인' })).rejects.toThrow('상품 표시 가격');
    await expect(useCartStore.getState().addItem({ product_id: 'prod-partial', variant_id: 'var-a', item_name: '일부 선택', item_price: 6000 })).rejects.toThrow('선택한 규격');
    await expect(useCartStore.getState().addItem({ product_id: 'prod-held', variant_id: 'var-a', listing_id: 'listing-a', offer_id: 'offer-a',
      item_name: '거래 미확인', item_price: 3000, quoted_offer: { listed_price: 3000, total_price: null } })).rejects.toThrow('실제 거래 금액');
    useStore.setState({ isLoggedIn: true });
    useCartStore.setState({ synced: false, items: [{ id: 'guest-missing', name: '옛 미확인 가격', price: null, price_known: false, quantity: 1 }] });
    await useCartStore.getState().removeItem('guest-missing');
    expect(useCartStore.getState().items).toEqual([]);
    expect(api.post).not.toHaveBeenCalled();
    useStore.setState({ isLoggedIn: false });
    localStorage.setItem('wallet-savior-store', JSON.stringify({ state: { shoppingList: [{ item_name: '옛 게스트', item_price: 100 }] } }));
    localStorage.setItem('wallet-savior-cart', JSON.stringify({ state: { items: [], pendingMerge: null }, version: 0 }));
    await useCartStore.persist.rehydrate();
    expect(useCartStore.getState().items).toEqual([]);
    localStorage.removeItem('wallet-savior-store');
  });
});

const approvedPipelineProduct = {
  id: 2,
  canonical_name: '오리온 오징어땅콩',
  category_id: 'snack.nut',
  keywords: ['오징어땅콩', '과자'],
  brand: '오리온',
  source_name: 'emart',
  source_title: '오리온 오징어땅콩 202g 행사',
  price: 2990,
  original_price: 3990,
  discount_rate: 25,
  has_discount_metadata: true,
  unit: '202g',
  standard_unit_price: 1480.2,
  standard_unit: '100g',
};

describe('ProductDetailModal public catalog rendering', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    useStore.setState({ isLoggedIn: true, favorites: [], toasts: [], _toastSeq: 0 });
    useCartStore.setState({ items: [], synced: false });
    api.getJson.mockImplementation((path) => {
      if (path.endsWith('/price-compare')) {
        return Promise.resolve({
          data: [
            { source_name: 'emart', price: 2990 },
            { source_name: 'homeplus', price: 3190 },
          ],
        });
      }
      if (path.endsWith('/price-history')) {
        return Promise.resolve({
          data: [
            { date: '2026-04-01', price: 3990 },
            { date: '2026-04-30', price: 2990 },
          ],
        });
      }
      if (path.endsWith('/trust')) {
        return Promise.resolve({
          data: {
            hotdeal_score: 95,
            rationale: '최근 이력 기준 최저가 수준입니다.',
            current_price: 2990,
            historical_low_price: 2990,
            historical_average_price: 3490,
            reference_count: 4,
          },
        });
      }
      return Promise.resolve({ data: null });
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('renders approved pipeline product, offer, unit price, history, and trust data', async () => {
    render(<ProductDetailModal product={approvedPipelineProduct} onClose={vi.fn()} mode="product" />);

    expect(screen.getByRole('dialog', { name: '오리온 오징어땅콩' })).toBeInTheDocument();
    expect(screen.getByText('snack.nut', { exact: false })).toBeInTheDocument();
    expect(screen.getByText('오징어땅콩 202g 행사', { exact: false })).toBeInTheDocument();
    expect(screen.getByText('오징어땅콩')).toBeInTheDocument();
    expect(screen.getByText('과자')).toBeInTheDocument();
    expect(screen.getAllByText('1,480원/100g').length).toBeGreaterThan(0);
    expect(screen.getByText('3,990원')).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText('최근 이력 기준 최저가 수준입니다.')).toBeInTheDocument();
      expect(screen.getByText('homeplus')).toBeInTheDocument();
      expect(screen.getByText('04-30')).toBeInTheDocument();
    });
  });

  it('handles missing optional public catalog fields gracefully', async () => {
    render(<ProductDetailModal product={{ id: 3, canonical_name: '승인 상품', price: 1000 }} onClose={vi.fn()} mode="preview" />);

    expect(screen.getByRole('dialog', { name: '승인 상품' })).toBeInTheDocument();
    expect(screen.getAllByText('온라인').length).toBeGreaterThan(0);
    expect(screen.queryByText('키워드')).not.toBeInTheDocument();
  });

  it.each(['prod-reviewed-package', 17])('loads actual detail for search ID %s without changing identity', async (id) => {
    api.getJson.mockImplementation((path) => Promise.resolve(path === `/api/products/${id}`
      ? { data: {
        id, public_product_id: typeof id === 'string' ? id : undefined,
        name: '검증된 상품', brand: '검증 브랜드', price: 9000, unit: '90g×4',
        best_offer: { comparable_price: 9000, per_100g: 2500, per_100ml: null },
        variants: [{ id: 'var-reviewed', name: '90g×4', package_quantity: 90, bundle_count: 4, listings: [] }],
      } } : { data: null }));
    render(<ProductDetailModal product={{ id, type: 'product', title: '검색 요약', price: 9000 }} onClose={vi.fn()} />);
    await waitFor(() => expect(screen.getByRole('dialog', { name: '검증된 상품' })).toBeInTheDocument());
    expect(api.getJson).toHaveBeenCalledWith(`/api/products/${id}`);
    expect(screen.getByText('검증 브랜드')).toBeInTheDocument();
    expect(screen.getAllByText('2,500원/100g').length).toBeGreaterThan(0);
    expect(screen.queryByText('10,000원/100g')).not.toBeInTheDocument();
  });

  it.each(['4L', '450매 + 150매 + 80매 + 파우치', '50–100g', '100g 또는 200g'])(
    'keeps unknown or mixed unit text %s separate from verified unit prices', (unit) => {
      render(<ProductDetailModal product={{
        id: 'prod-unknown-unit', public_product_id: 'prod-unknown-unit', name: '검증 규격',
        price: 8000, unit, unit_price_display: '999원/100g',
        best_offer: { comparable_price: 8000, per_100g: null, per_100ml: null },
        variants: [{ id: 'var-unknown', name: unit, package_quantity: null, listings: [] }],
      }} onClose={vi.fn()} mode="preview" />);
      expect(screen.getByText('정보 없음')).toBeInTheDocument();
      expect(screen.getByText('판매 수량 미확인', { exact: false })).toBeInTheDocument();
      expect(screen.queryByText(/원\/100(?:g|ml)/)).not.toBeInTheDocument();
    }
  );

  it('preserves a held checkout quote without presenting it as free or comparable', () => {
    render(<ProductDetailModal product={{
      id: 'prod-held', public_product_id: 'prod-held', name: '검증 벌크 상품', price: 0, best_offer: null,
      variants: [{ id: 'var-bulk', name: '180개×120', package_quantity: 180, bundle_count: 120,
        listings: [{ id: 'listing-bulk', source: 'costco', title: '검증 벌크 180개×120',
          offers: [{ listed_price: 2899000, total_price: 2899000, comparable_price: null,
            total_quantity: 21600, quantity_unit: '개', per_100g: null, per_100ml: null }] }] }],
    }} onClose={vi.fn()} mode="preview" />);
    expect(screen.getByText('비교 가격 미확인')).toBeInTheDocument();
    expect(screen.getByText('표시 가격 2,899,000원', { exact: false })).toBeInTheDocument();
    expect(screen.getByText('180개×120')).toBeInTheDocument();
    expect(screen.queryByText('0원')).not.toBeInTheDocument();
  });

  it('uses normalized comparable amounts and preserves package basis while excluding held quotes', () => {
    const rows = getComparableOffers({ public_product_id: 'prod-review', price: 9000, best_offer: null }, [
      { source: 'emart', variant_name: '90g×4', comparable_price: 9000, total_price: 9000,
        total_quantity: 360, quantity_unit: 'g', per_100g: 2500, per_100ml: null },
      { source: 'costco', variant_name: '다른 구성', comparable_price: null, total_price: 5000, price: 5000 },
    ]);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ price: 9000, totalPrice: 9000, totalQuantity: 360,
      quantityUnit: 'g', title: '90g×4', unitPrice: 2500, unit: '100g' });
  });

  it('selects the newest comparable offer for the selected variant without reviving older held prices', () => {
    const variant = { id: 'var-reviewed', listings: [
      { source: 'emart', title: '검증 90g×4', offers: [
        { comparable_price: null, total_price: 5000 }, { comparable_price: 1000, total_price: 1000 },
      ] },
      { source: 'homeplus', title: '검증 90g×4', offers: [
        { comparable_price: 9000, total_price: 9000, total_quantity: 360, quantity_unit: 'g' },
      ] },
    ] };
    expect(getVariantBestOffer(variant)).toMatchObject({ price: 9000, sourceName: 'homeplus',
      variantId: 'var-reviewed', totalQuantity: 360, quantityUnit: 'g' });
    expect(getVariantBestOffer({ listings: [variant.listings[0]] })).toBeNull();
  });

  it.each(['prod-linked', 'opaque:reviewed', 17])('keeps catalog ID %s in both account request payloads', (id) => {
    const product = { id, public_product_id: typeof id === 'string' ? id : undefined,
      name: '검증 상품', price: 9000, sale: typeof id === 'string' ? 1234 : undefined, quantity: 2 };
    expect(buildCartPayload(product)).toMatchObject({ product_id: id, item_price: 9000, quantity: 2 });
    expect(buildWishlistPayload(product)).toMatchObject({ product_id: id, current_price: 9000 });
  });

  it('retains the unique listing quote and identity when comparability is held', () => {
    const product = { id: 'prod-held', public_product_id: 'prod-held', name: '벌크 구성',
      price: 0, best_offer: null, variants: [{ id: 'var-bulk', package_quantity: 180, bundle_count: 120,
        listings: [{ id: 'listing-bulk', source: 'costco', url: 'https://example.invalid/quote',
          title: '180개×120', offers: [{ listed_price: 2899000, comparable_price: null }] }] }] };
    expect(() => buildCartPayload(product)).toThrow('실제 거래 금액이 확인되지 않아');
    expect(buildWishlistPayload(product)).toMatchObject({ product_id: 'prod-held', price_at_add: 2899000,
      current_price: null });
    expect(product.variants[0]).toMatchObject({ package_quantity: 180, bundle_count: 120 });
  });

  it('keeps unknown prices nullable in wishlist and rejects an invented zero cart amount', () => {
    const product = { id: 'prod-unknown', public_product_id: 'prod-unknown', name: '가격 미확인',
      price: 0, best_offer: null, variants: [{ id: 'var-physical', package_quantity: null, listings: [] }] };
    expect(() => buildCartPayload(product)).toThrow('상품 표시 가격이 확인되지 않아');
    expect(buildWishlistPayload(product)).toMatchObject({ product_id: 'prod-unknown',
      price_at_add: null, current_price: null });
    const manual = buildCartPayload({ item_name: '수동 무료 상품', item_price: 0 });
    expect(manual.item_price).toBe(0);
    expect(manual.product_id).toBeUndefined();
  });

  it('renders mart products with full image/info and normalized wishlist/cart actions', async () => {
    render(<ProductDetailModal product={{
      id: 'emart-sale-apple',
      type: 'mart',
      name: '행사 사과',
      sale: 9900,
      orig: 12900,
      img: 'https://example.com/apple.png',
      martName: '이마트',
      martKey: 'emart',
      category: '과일',
      unit: '1.5kg',
      keywords: ['사과', '과일'],
    }} onClose={vi.fn()} mode="preview" />);

    expect(screen.getByRole('dialog', { name: '행사 사과' })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: '행사 사과' })).toBeInTheDocument();
    expect(screen.getAllByText('이마트').length).toBeGreaterThan(0);
    expect(screen.getAllByText('1.5kg', { exact: false }).length).toBeGreaterThan(0);
    expect(screen.getByText('사과')).toBeInTheDocument();

    fireEvent.click(screen.getByText('찜하기'));
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/api/wishlist', expect.objectContaining({
        item_name: '행사 사과',
        item_image_url: 'https://example.com/apple.png',
        store_name: '이마트',
      }));
    });
    expect(api.post.mock.calls.at(-1)[1]).not.toHaveProperty('product_id');

    fireEvent.click(screen.getByText('장바구니 담기'));
    await waitFor(() => {
      expect(useCartStore.getState().items[0]).toEqual(expect.objectContaining({
        name: '행사 사과',
        price: 9900,
        store_name: '이마트',
      }));
    });
  });

  it('renders rich decision support for real-shaped hotdeal preview data', () => {
    render(<ProductDetailModal product={{
      id: 'hotdeal-ramen-1',
      type: 'hotdeal',
      title: '농심 신라면 20봉 핫딜',
      price: 12900,
      original_price: 18900,
      discount_rate: 32,
      has_discount_metadata: true,
      source: '뽐뿌',
      source_url: 'https://example.com/deal',
      unit: '20입',
      period: '오늘 23:59까지',
      hotVotes: 42,
      coldVotes: 3,
      comments: 18,
      price_history: [
        { date: '2026-04-01', price: 15900, has_discount_metadata: true },
        { date: '2026-04-12', price: 14500, has_discount_metadata: true },
        { date: '2026-04-30', price: 12900, has_discount_metadata: true },
      ],
      comparable_offers: [
        { source_name: '쿠팡', price: 13900, title: '신라면 20봉' },
        { source_name: '이마트', price: 14900, title: '신라면 멀티팩' },
      ],
    }} onClose={vi.fn()} mode="preview" />);

    expect(screen.getByText('구매 판단', { exact: false })).toBeInTheDocument();
    expect(screen.getByText('역대 최저가')).toBeInTheDocument();
    expect(screen.getByText('가격 이력 요약', { exact: false })).toBeInTheDocument();
    expect(screen.getByText('마지막 할인 04-30')).toBeInTheDocument();
    expect(screen.getByText('판매처별 규격·가격', { exact: false })).toBeInTheDocument();
    expect(screen.getByText('쿠팡')).toBeInTheDocument();
    expect(screen.getByText('커뮤니티 반응 🔥42 / ❄️3')).toBeInTheDocument();
    expect(screen.getByText('댓글 18개')).toBeInTheDocument();
  });

  it('renders price-only observations without fake discount UI', () => {
    render(<ProductDetailModal product={{
      id: 'emart-tofu-observation',
      type: 'mart',
      name: '국산콩 두부 300g',
      sale: 1980,
      orig: null,
      martName: '이마트',
      martKey: 'emart',
      unit: '300g',
      price_observation_only: true,
      has_discount_metadata: false,
      record_label: '관측 가격',
      claim_status_label: '할인 여부 미확인',
      price_history: [
        {
          date: '2026-05-01',
          price: 2200,
          price_observation_only: true,
          has_discount_metadata: false,
        },
        {
          date: '2026-05-05',
          price: 1980,
          price_observation_only: true,
          has_discount_metadata: false,
        },
      ],
    }} onClose={vi.fn()} mode="preview" />);

    expect(screen.getByText('관측 가격')).toBeInTheDocument();
    expect(screen.getByText('할인 여부 미확인')).toBeInTheDocument();
    expect(screen.queryByText(/절약/)).not.toBeInTheDocument();
    expect(screen.queryByText('마지막 할인 05-05')).not.toBeInTheDocument();
    expect(screen.getByText('저가 관측')).toBeInTheDocument();
  });
});

const selectionFixture = () => ({ id:'prod-spec', public_product_id:'prod-spec', name:'선택 거래', price:6000, avg:0,
  best_offer:{id:'offer-a',variant_id:'var-a',listing_id:'listing-a',comparable_price:6000,total_price:6000,per_100g:2222},
  variants:[['a',1,6000,270,2222],['b',6,9000,540,1667]].map(([key,bundle,price,total,per])=>({
    id:`var-${key}`,name:`90g×${bundle}`,display_unit:`90g×${bundle}`,package_quantity:90,package_unit:'g',bundle_count:bundle,
    listings:[{id:`listing-${key}`,source:`판매처-${key}`,title:`구성-${key}`,offers:[{
      id:`offer-${key}`,listed_price:price,total_price:price,comparable_price:price,total_quantity:total,quantity_unit:'g',per_100g:per,
      minimum_quantity:key==='a'?2:1,received_package_count:key==='a'?3:1,bundle_count:bundle,
      promotion_conditions:key==='a'?{buy_quantity:2,free_quantity:1}:{},membership_required:key==='a',coupon_required:false,
      offer_state:'active',current_eligible:true,
    }]}],
  })) });

describe('409 source reference price is not sold contents', () => {
  afterEach(() => { cleanup(); vi.clearAllMocks(); });

  it('keeps the source literal alongside a held quote without supplying contents or comparable pricing', () => {
    const raw = selectionFixture();
    raw.variants = [raw.variants[0]];
    const variant = raw.variants[0], offer = variant.listings[0].offers[0];
    Object.assign(variant, { package_quantity: null, package_unit: null, standard_unit: null,
      display_unit: '', name: '퓨레 원문 상품' });
    Object.assign(offer, { listed_price: 3000, total_price: null, comparable_price: null,
      total_quantity: null, quantity_unit: null, received_package_count: null,
      per_100g: null, current_eligible: false,
      source_reference_price_text: '10g당 375원',
      source_reference_price_role: 'source_reference_not_sold_contents' });
    const before = JSON.stringify(raw);
    const selected = selectProductOffer(raw, { variantId: variant.id });
    expect(normalizeProduct(selected)).toMatchObject({ sourceReferencePriceText: '10g당 375원',
      sourceReferencePriceRole: 'source_reference_not_sold_contents' });
    expect(selected.unit).toBe('');
    expect(selected.best_offer).toBeNull();
    expect(getOfferUnitPrice(selected.selected_offer)).toBeNull();
    expect(() => buildCartPayload(selected)).toThrow('실제 거래 금액이 확인되지 않아');
    render(<ProductDetailModal product={selected} mode="preview" onClose={vi.fn()} />);
    expect(screen.getByText(/출처 단가 기준: 10g당 375원 · 판매 내용량·비교 단위 아님/)).toBeInTheDocument();
    expect(screen.getByText(/표시 가격 3,000원/)).toBeInTheDocument();
    expect(screen.getAllByText(/판매 수량 미확인/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/375원\/100g/)).not.toBeInTheDocument();
    expect(JSON.stringify(raw)).toBe(before);
  });

  it('keeps a declared capsule count separate from a milligram price reference and preserves ordinary measured offers', () => {
    const raw = selectionFixture();
    raw.variants = [raw.variants[0]];
    const variant = raw.variants[0], offer = variant.listings[0].offers[0];
    Object.assign(variant, { package_quantity: 60, package_unit: '개', standard_unit: '개',
      bundle_count: 1, display_unit: '60캡슐' });
    Object.assign(offer, { total_quantity: 60, quantity_unit: '개', per_100g: null, per_item: 100,
      source_reference_price_text: '1000mg당 원문 표시 기준',
      source_reference_price_role: 'source_reference_not_sold_contents' });
    const selected = selectProductOffer(raw, { variantId: variant.id });
    expect(selected.unit).toBe('60캡슐');
    expect(selected.selected_offer.total_quantity).toBe(60);
    expect(selected.selected_offer.quantity_unit).toBe('개');
    expect(selected.selected_offer.per_100g).toBeNull();
    expect(buildCartPayload(selected).quoted_offer.source_reference_price_text).toBe('1000mg당 원문 표시 기준');
    render(<ProductDetailModal product={selected} mode="preview" onClose={vi.fn()} />);
    expect(screen.getAllByText('60캡슐').length).toBeGreaterThan(0);
    expect(screen.getByText(/출처 단가 기준: 1000mg당 원문 표시 기준/)).toBeInTheDocument();
    cleanup();
    Object.assign(variant, { package_quantity: 80, package_unit: 'g', standard_unit: 'g', display_unit: '80g' });
    Object.assign(offer, { total_quantity: 80, quantity_unit: 'g', per_100g: 7500 });
    delete offer.source_reference_price_text; delete offer.source_reference_price_role;
    const ordinary = selectProductOffer(raw, { variantId: variant.id });
    expect(ordinary.unit).toBe('80g');
    expect(getOfferUnitPrice(ordinary.selected_offer)).toEqual({ price: 7500, unit: '100g' });
    expect(normalizeProduct(ordinary).sourceReferencePriceText).toBe('');
  });

  it('requires the explicit source role and a nonempty literal rather than raw numeric or unrelated fields', () => {
    for (const offer of [null, {}, { source_reference_price_text: '10g당 375원' },
      { source_reference_price_role: 'sold_contents', source_reference_price_text: '10g당 375원' },
      ...[null, false, 375, {}, ''].map(text => ({ source_reference_price_role: 'source_reference_not_sold_contents', source_reference_price_text: text })),
      { attributes: { unit_price_display: '10g당 375원' } }]) {
      expect(getSourceReferencePriceText(offer)).toBe('');
    }
  });
});

describe('406 selected measured scalar specification fallback', () => {
  afterEach(() => { cleanup(); vi.clearAllMocks(); });

  it('renders the selected proven measured amount and bundle without changing its quote or tuple', () => {
    const raw = selectionFixture();
    const variant = raw.variants[1];
    Object.assign(variant, { display_unit: '', name: '원문 올리브 규격', package_quantity: 480,
      package_unit: 'g', bundle_count: 3 });
    const before = JSON.stringify(raw);
    const selected = selectProductOffer(raw, { variantId: variant.id });
    expect(selected.unit).toBe('480g×3');
    expect(selected.selected_offer).toEqual(variant.listings[0].offers[0]);
    expect(buildCartPayload(selected)).toMatchObject({ unit: '480g×3', variant_id: variant.id,
      listing_id: 'listing-b', offer_id: 'offer-b', price: 9000 });
    render(<ProductDetailModal product={selected} mode="preview" onClose={vi.fn()} />);
    expect(screen.getAllByText('480g×3').length).toBeGreaterThan(0);
    expect(screen.queryByText('규격 미확인')).not.toBeInTheDocument();
    expect(JSON.stringify(raw)).toBe(before);
  });

  it('preserves literal uncertain descriptions and leaves unknown physical or vector quantities unknown', () => {
    const raw = selectionFixture();
    const variant = raw.variants[1];
    for (const literal of ['3.6kg내외', '26~31입', '호두·아몬드 혼합 구성']) {
      variant.display_unit = literal;
      expect(selectProductOffer(raw, { variantId: variant.id }).unit).toBe(literal);
      expect(buildCartPayload(selectProductOffer(raw, { variantId: variant.id })).unit).toBe(literal);
    }
    variant.display_unit = '';
    for (const specification of [
      { package_quantity: null, package_unit: null, bundle_count: 1 },
      { package_quantity: 1, package_unit: '세트', bundle_count: 1 },
      { package_quantity: 30, package_unit: 'm', bundle_count: 1 },
      { package_quantity: 480, package_unit: '', bundle_count: 3 },
      { package_quantity: false, package_unit: 'g', bundle_count: 3 },
      { package_quantity: 480, package_unit: 'g', bundle_count: null },
      { package_quantity: 480, package_unit: 'g', bundle_count: 3,
        quantity_components: [{ unit: 'g', quantity: 480, count: null }] },
    ]) {
      Object.assign(variant, { quantity_components: null }, specification);
      expect(selectProductOffer(raw, { variantId: variant.id }).unit).toBe('');
      expect(buildCartPayload(selectProductOffer(raw, { variantId: variant.id })).unit).toBeFalsy();
    }
  });
});

describe('273 selected source summary without comparable payment', () => {
  afterEach(() => { cleanup(); vi.clearAllMocks(); });

  it('keeps the selected expired rule and source period without borrowing an eligible sibling or claiming absent history', () => {
    const raw = selectionFixture();
    const quote = raw.variants[0].listings[0].offers[0];
    Object.assign(quote, { total_price: null, comparable_price: null, total_quantity: null,
      per_100g: null, current_eligible: false, availability_reason: 'expired',
      observation_receipt_eligible: false,
      observation_receipt_reason: 'promotion_observation_outside_period',
      valid_to: '2026-09-01T15:00:00Z', crawled_at: '2026-09-02T14:51:14Z' });
    const product = selectProductOffer(raw, { variantId: 'var-a', listingId: 'listing-a', offerId: 'offer-a' });
    const original = JSON.stringify(product);
    const decision = buildProductDecision(product);
    expect(product.best_offer).toBeNull();
    expect(decision.currentOffer.period).toBe('판매 기간 종료 · 출처 행사 기간 시작일 미확인 ~ 2026-09-01T15:00:00Z');
    expect(decision.currentOffer.conditionText).toContain('관측 당시 행사 적용 미확인');
    expect(decision.currentOffer.conditionText).toContain('구매 2');
    expect(decision.currentOffer.conditionText).toContain('추가 증정 1');
    expect(decision.historySummary).toMatchObject({ hasData: false, comparableCount: 0, min: null, avg: null, max: null });
    render(<ProductDetailModal product={product} mode="preview" onClose={vi.fn()} />);
    expect(screen.getByText(decision.currentOffer.period)).toBeInTheDocument();
    expect(screen.getByText(/이 화면에 연결된 조회 기간의 선택 규격 관측 이력 미확인/)).toBeInTheDocument();
    expect(screen.queryByText(/가격 이력이 아직 없습니다/)).not.toBeInTheDocument();
    expect(screen.queryByText('행사 정보 없음')).not.toBeInTheDocument();
    expect(screen.queryByText(/출처 조건 계산 금액 6,000/)).not.toBeInTheDocument();
    expect(JSON.stringify(product)).toBe(original);

    const history = [{ ...quote, variant_id: 'var-a', listing_id: 'listing-a',
      date: quote.crawled_at, price: quote.listed_price }];
    expect(buildProductDecision(product, { priceHistory: history }).historySummary).toMatchObject({
      hasData: true, count: 1, comparableCount: 0, min: null, avg: null, max: null });
  });

  it('keeps an ambiguous source summary unknown rather than adopting another member period', () => {
    const raw = selectionFixture(); raw.best_offer = null;
    raw.variants[1].listings[0].offers[0].valid_to = '2026-12-31T15:00:00Z';
    expect(buildProductDecision(raw).currentOffer).toMatchObject({ period: '', conditionText: '' });
  });
});

describe('selected price alerts', () => {
  beforeEach(() => {
    useStore.setState({ isLoggedIn: true, user: { id: 1, nickname: 'synthetic' }, priceAlerts: [], toasts: [] });
    api.getJson.mockResolvedValue({ data: null });
    api.postJson.mockImplementation(async (path, payload) => {
      const variant = selectionFixture().variants.find(row => row.id === payload.variant_id);
      return { data: { ...payload, id: payload.variant_id === 'var-a' ? 21 : 22,
        offer_context: { ...variant.listings[0].offers[0], display_unit: variant.display_unit },
        current_price: null, is_triggered: false, trigger_reason: 'eligibility_unverified' } };
    });
  });
  afterEach(() => { cleanup(); vi.clearAllMocks(); });

  it('submits the changed selected tuple and retains separate canonical alert identities in the local store', async () => {
    render(<ProductDetailModal product={selectionFixture()} mode="preview" onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: '가격 알림 설정' }));
    fireEvent.change(screen.getByLabelText('목표 가격'), { target: { value: '5000' } });
    fireEvent.click(screen.getByRole('button', { name: '저장' }));
    await waitFor(() => expect(useStore.getState().priceAlerts).toHaveLength(1));
    expect(api.postJson).toHaveBeenLastCalledWith('/api/users/me/alerts', {
      product_id: 'prod-spec', target_price: 5000, variant_id: 'var-a', listing_id: 'listing-a', offer_id: 'offer-a',
    });
    fireEvent.click(screen.getByRole('button', { name: '규격 선택: 90g×6' }));
    fireEvent.click(screen.getByRole('button', { name: '가격 알림 설정' }));
    expect(screen.getByLabelText('목표 가격')).toHaveValue(9000);
    fireEvent.change(screen.getByLabelText('목표 가격'), { target: { value: '8000' } });
    fireEvent.click(screen.getByRole('button', { name: '저장' }));
    await waitFor(() => expect(useStore.getState().priceAlerts).toHaveLength(2));
    expect(api.postJson).toHaveBeenLastCalledWith('/api/users/me/alerts', {
      product_id: 'prod-spec', target_price: 8000, variant_id: 'var-b', listing_id: 'listing-b', offer_id: 'offer-b',
    });
    const [first, second] = useStore.getState().priceAlerts;
    useStore.getState().addPriceAlert({ ...first, target_price: 4500 });
    expect(useStore.getState().priceAlerts).toHaveLength(2);
    useStore.getState().removePriceAlert(first.id);
    expect(useStore.getState().priceAlerts).toEqual([second]);
  });

  it('allows a valid selected unknown quote with an explicit target without submitting invented money', async () => {
    const product = selectionFixture();
    Object.assign(product.variants[0].listings[0].offers[0], { total_price: null, comparable_price: null, total_quantity: null, quantity_unit: null });
    render(<ProductDetailModal product={product} mode="preview" onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: '가격 알림 설정' }));
    expect(screen.getByLabelText('목표 가격')).toHaveValue(null);
    expect(screen.getByText(/선택 거래 금액 미확인/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('목표 가격'), { target: { value: '5000' } });
    fireEvent.click(screen.getByRole('button', { name: '저장' }));
    await waitFor(() => expect(api.postJson).toHaveBeenCalledTimes(1));
    expect(api.postJson.mock.calls[0][1]).toEqual({ product_id: 'prod-spec', target_price: 5000,
      variant_id: 'var-a', listing_id: 'listing-a', offer_id: 'offer-a' });
  });

  it('keeps an ambiguous normalized product unavailable until an actual tuple is selected', () => {
    const product = selectionFixture(); product.best_offer = null;
    render(<ProductDetailModal product={product} mode="preview" onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: '가격 알림 설정' }));
    expect(screen.getByRole('button', { name: '저장' })).toBeDisabled();
    expect(api.postJson).not.toHaveBeenCalled();
  });

  it('renders saved receipt conditions, held eligibility and unknown current money in Profile without a false target reached', async () => {
    const context = { ...selectionFixture().variants[0].listings[0].offers[0], display_unit: '90g×3', source: 'synthetic' };
    api.getJson.mockResolvedValue({ data: [{ id: 21, product_id: 'prod-spec', product_name: '선택 거래',
      variant_id: 'var-a', listing_id: 'listing-a', offer_id: 'offer-a', target_price: 5000,
      saved_receipt_valid: true, current_price: null, quoted_price: 6000, offer_context: context,
      trigger_reason: 'eligibility_unverified', is_triggered: false }] });
    render(<MemoryRouter><ProfilePage /></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: '가격 알림' }));
    await screen.findByText('선택 거래');
    expect(screen.getByText(/현재 비교 가능 거래 금액 미확인/)).toBeInTheDocument();
    expect(screen.getByText(/수령 270g.*최소 구매 2.*회원 필요/)).toBeInTheDocument();
    expect(screen.getByText(/판정 보류.*이용 조건 미확인/)).toBeInTheDocument();
    expect(screen.queryByText('목표 도달')).not.toBeInTheDocument();
    expect(screen.queryByText('0원')).not.toBeInTheDocument();
  });

  it('holds a revised saved alert receipt without deleting the target, quote or original capacity title', async () => {
    api.getJson.mockResolvedValue({ data: [{ id: 21, product_id: 'prod-bottle', product_name: '보온보냉병',
      variant_id: 'old-variant', listing_id: 'listing-bottle', offer_id: 'saved-offer', target_price: 30990,
      current_price: null, quoted_price: 30990, saved_receipt_valid: false, saved_receipt_reason: 'selected_specification_revised',
      offer_context: { display_unit: '2PK (950ml)', total_quantity: 950, quantity_unit: 'ml', received_package_count: 1,
        minimum_quantity: 2, membership_required: true, coupon_required: null },
      trigger_reason: 'selected_specification_revised', is_triggered: false }] });
    render(<MemoryRouter><ProfilePage /></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: '가격 알림' }));
    await screen.findByText('보온보냉병');
    expect(screen.getByText(/2PK \(950ml\)/)).toBeInTheDocument();
    expect(screen.getByText(/목표 30,990원.*미확인/)).toBeInTheDocument();
    expect(screen.getByText(/규격 확인·다시 선택 필요/)).toBeInTheDocument();
    expect(screen.queryByText(/수령 950ml|수령 패키지 1/)).not.toBeInTheDocument();
    expect(screen.queryByText('목표 도달', { exact: true })).not.toBeInTheDocument();
    expect(api.delete).not.toHaveBeenCalled();
  });

  it('shows actual alert-fetch errors and permits retry instead of reporting an empty alert list', async () => {
    api.getJson.mockRejectedValueOnce(new Error('synthetic account unavailable'));
    render(<MemoryRouter><ProfilePage /></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: '가격 알림' }));
    await screen.findByRole('alert');
    expect(screen.getByText('synthetic account unavailable')).toBeInTheDocument();
    api.getJson.mockResolvedValueOnce({ data: [] });
    fireEvent.click(screen.getByRole('button', { name: '다시 불러오기' }));
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
  });
});

describe('selected normalized transaction boundary',()=>{
  beforeEach(()=>{useStore.setState({isLoggedIn:true,selectedProduct:null,favorites:[],toasts:[]});useCartStore.setState({items:[],synced:true});api.getJson.mockResolvedValue({data:null});});
  afterEach(()=>{cleanup();vi.clearAllMocks();vi.unstubAllGlobals();});
  it('shares the actual selected quote and receipt, preserving unknown money and expired availability', async () => {
    const writeText = vi.fn().mockResolvedValue();
    vi.stubGlobal('navigator', { clipboard: { writeText } });
    const product = selectionFixture();
    Object.assign(product.variants[0].listings[0].offers[0], { total_price: null, listed_price: null,
      comparable_price: null, current_eligible: false, availability_reason: 'expired' });
    render(<ProductDetailModal product={product} mode="preview" onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: '공유' }));
    await waitFor(() => expect(writeText).toHaveBeenCalled());
    const text = writeText.mock.calls[0][0];
    expect(text).toContain('관측 표시 가격 미확인');
    expect(text).toContain('90g×1');
    expect(text).toContain('수령 270g');
    expect(text).toContain('최소 구매 2');
    expect(text).toContain('회원 필요');
    expect(text).toContain('판매 기간 종료');
    expect(text).not.toContain('0원');
    const url = new URL(text.split('\n').at(-1));
    expect(url.origin).toBe(window.location.origin);
    expect(url.pathname).toBe('/price/prod-spec');
    expect(Object.fromEntries(url.searchParams)).toEqual({ variant: 'var-a', listing: 'listing-a', offer: 'offer-a' });
  });
  it('restores the exact shared variant, source and quote rather than the product best offer', async () => {
    const product = selectionFixture();
    useModalStore.getState().closeModal();
    const shared = buildProductShareUrl(product, { variantId: 'var-b', listingId: 'listing-b', offerId: 'offer-b' });
    vi.stubGlobal('fetch', vi.fn(async path => ({ ok: true, json: async () => ({
      data: String(path) === '/api/products/prod-spec' ? product : [],
    }) })));
    render(<MemoryRouter initialEntries={[new URL(shared).pathname + new URL(shared).search]}>
      <Routes><Route path="/price/:id" element={<PricePage />} /></Routes></MemoryRouter>);
    await waitFor(() => expect(useModalStore.getState().activeModal).toBe('productDetail'));
    const restored = useModalStore.getState().modalData;
    expect(restored).toMatchObject({ selected_variant_id: 'var-b', selected_listing_id: 'listing-b',
      selected_offer_id: 'offer-b', source: '판매처-b', unit: '90g×6' });
    expect(restored.selected_offer).toEqual(product.variants[1].listings[0].offers[0]);
    useModalStore.getState().closeModal();
  });
  it.each([
    'variant=var-b',
    'variant=var-b&listing=listing-a&offer=offer-b',
    'variant=var-b&listing=listing-b&offer=old-offer',
    'variant=var-a&variant=var-b&listing=listing-b&offer=offer-b',
  ])('holds incomplete or changed shared selection without selecting another quote: %s', async query => {
    useModalStore.getState().closeModal();
    vi.stubGlobal('fetch', vi.fn(async path => ({ ok: true, json: async () => ({
      data: String(path) === '/api/products/prod-spec' ? selectionFixture() : [],
    }) })));
    render(<MemoryRouter initialEntries={['/price/prod-spec?' + query]}>
      <Routes><Route path="/price/:id" element={<PricePage />} /></Routes></MemoryRouter>);
    await screen.findByRole('alert');
    expect(screen.getByRole('button', { name: '상품 다시 선택' })).toBeInTheDocument();
    expect(useModalStore.getState().activeModal).toBeNull();
    expect(screen.queryByRole('button', { name: '🛒 장보기에 추가' })).not.toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });
  it('does not report a copied link when clipboard and native sharing are unavailable', async () => {
    vi.stubGlobal('navigator', {});
    render(<ProductDetailModal product={selectionFixture()} mode="preview" onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: '공유' }));
    await waitFor(() => expect(useStore.getState().toasts.some(t => t.msg === '이 브라우저에서는 링크 복사를 사용할 수 없습니다')).toBe(true));
    expect(useStore.getState().toasts.some(t => t.msg.includes('복사했어요'))).toBe(false);
  });
  it('saves the selected wishlist tuple and watches the same spec/source across price events without selecting legacy rows', async () => {
    const first = selectProductOffer(selectionFixture(), { variantId: 'var-a' });
    const second = selectProductOffer(selectionFixture(), { variantId: 'var-b' });
    expect(buildWishlistPayload(first)).toMatchObject({ product_id: 'prod-spec', variant_id: 'var-a',
      listing_id: 'listing-a', offer_id: 'offer-a', price_at_add: 6000 });
    expect(normalizeProduct(first).favoriteId).not.toBe(normalizeProduct(second).favoriteId);
    const next = selectionFixture(); next.variants[0].listings[0].offers[0].id = 'offer-new';
    expect(normalizeProduct(selectProductOffer(next, { variantId: 'var-a' })).favoriteId).toBe(normalizeProduct(first).favoriteId);
    const legacy = { ...selectionFixture(), comparison_reason: 'selection_context_missing', item_price: 1234 };
    expect(() => buildCartPayload(legacy)).toThrow('상품 표시 가격이 확인되지 않아');
    expect(selectProductOffer(legacy)).toMatchObject({ best_offer: null, price: null, current_price: null, item_price: null });
    expect(buildCartPayload(selectProductOffer(legacy, { variantId: 'var-b' }))).toMatchObject({
      variant_id: 'var-b', listing_id: 'listing-b', offer_id: 'offer-b', item_price: 9000 });
    useStore.getState().hydrateFavorites([{ id: 8, product_id: 'prod-spec', item_name: '선택 거래',
      variant_id: 'var-a', listing_id: 'listing-a', offer_id: 'offer-old', price_at_add: 6000 }]);
    expect(useStore.getState().favorites).toEqual([normalizeProduct(first).favoriteId]);
    useStore.getState().hydrateFavorites([{ id: 7, product_id: 'prod-spec', item_name: '기존 상품 찜' }]);
    expect(useStore.getState().favorites).not.toContain(normalizeProduct(first).favoriteId);
    render(<ProductDetailModal product={selectionFixture()} mode="preview" onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: '규격 선택: 90g×6' }));
    fireEvent.click(screen.getByRole('button', { name: '찜하기' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/wishlist', expect.objectContaining({
      product_id: 'prod-spec', variant_id: 'var-b', listing_id: 'listing-b', offer_id: 'offer-b', price_at_add: 9000,
    })));
    expect(useStore.getState().favorites).toContain(normalizeProduct(second).favoriteId);
    expect(useStore.getState().favorites).not.toContain(normalizeProduct(first).favoriteId);
  });
  it('compares a proven common unit rather than raw spend and renders conditions',()=>{
    const rows=getComparableOffers(selectionFixture());
    expect(rows.map(row=>row.offerId)).toEqual(['offer-b','offer-a']);
    expect(rows[0]).toMatchObject({price:9000,comparisonValue:1667,comparisonBasis:'100g'});
    render(<ProductDetailModal product={selectionFixture()} mode="preview" onClose={vi.fn()}/>);
    expect(screen.getByText('100g 기준 표시 조건에서 더 저렴')).toBeInTheDocument();
    for(const text of [/최소 구매 2/,/수령 패키지 3/,/회원 필요/,/쿠폰 필요 없음/])expect(screen.getAllByText(text).length).toBeGreaterThan(0);
  });
  it('withholds lowest labels for unknown quantities and mixed dimensions',()=>{
    const product=selectionFixture();
    for(const variant of product.variants)Object.assign(variant.listings[0].offers[0],{total_quantity:null,quantity_unit:null,per_100g:null,per_item:null,bundle_count:null});
    product.best_offer={...product.variants[0].listings[0].offers[0],variant_id:'var-a'};
    expect(getComparableOffers(product).every(row=>row.comparisonValue===null)).toBe(true);
    render(<ProductDetailModal product={product} mode="preview" onClose={vi.fn()}/>);
    expect(screen.queryByText(/기준 더 저렴|기준 최저/)).not.toBeInTheDocument();
    const mixed=selectionFixture();Object.assign(mixed.variants[1].listings[0].offers[0],{quantity_unit:'ml',per_100g:null,per_100ml:1667});
    expect(getComparableOffers(mixed).find(row=>row.offerId==='offer-b').comparisonValue).toBeNull();
  });
  it.each(['both', 'reference', 'other'])('preserves heterogeneous scalar quotes while holding %s comparison and history statistics', (held) => {
    const reason = 'heterogeneous_contents_allocation_unverified';
    const product = selectionFixture();
    const variant = product.variants[0];
    product.variants = [variant];
    Object.assign(variant, { package_quantity: 230, package_unit: 'g', bundle_count: 4, display_unit: '230g×4' });
    const selected = variant.listings[0].offers[0];
    Object.assign(selected, { listed_price: 22990, total_price: 22990, comparable_price: 22990,
      total_quantity: 920, quantity_unit: 'g', bundle_count: 4, received_package_count: 1,
      per_100g: null, per_item: null, minimum_quantity: null, membership_required: null,
      coupon_required: null, promotion_condition: null, promotion_conditions: {},
      quantity_comparison_reason: held !== 'other' ? reason : null });
    const other = { ...selected, id: 'offer-other', listed_price: 21990, total_price: 21990, comparable_price: 21990,
      quantity_comparison_reason: held !== 'reference' ? reason : null };
    variant.listings.push({ id: 'listing-other', source: '다른 원견적', offers: [other] });
    product.best_offer = { ...selected, variant_id: variant.id, listing_id: variant.listings[0].id };
    const rows = getComparableOffers(product);
    for (const row of rows.filter(row => row.quantityComparisonReason)) {
      expect(row).toMatchObject({ quantityComparisonReason: reason, unitPrice: null,
        totalQuantity: 920, quantityUnit: 'g', comparisonValue: null, comparisonBasis: null });
    }
    if (held !== 'other') expect(rows.every(row => row.comparisonValue === null)).toBe(true);
    expect(rows.find(row => row.offerId === selected.id)).toMatchObject({ price: 22990, totalPrice: 22990 });
    // A retained old scalar rate must not override a newly explicit hold.
    const heldOffer = selected.quantity_comparison_reason ? selected : other;
    expect(getOfferUnitPrice({ ...heldOffer, per_100g: 2498.913 })).toBeNull();
    const history = [selected, other].map((offer, index) => ({ ...offer, variant_id: variant.id,
      price: offer.listed_price, date: `2026-09-0${index + 1}`, is_latest: false, current_eligible: false }));
    const summary = getPriceHistorySummary(product, history, { variantId: variant.id });
    expect(summary.history).toHaveLength(2);
    expect(summary.history.map(row => row.price)).toEqual([22990, 21990]);
    expect(summary.history.filter(row => row.quantityComparisonReason).every(row => row.quantity_comparison_reason === reason)).toBe(true);
    expect(summary).toMatchObject(held === 'other'
      ? { min: 22990, avg: 22990, max: 22990, comparableCount: 1 }
      : { min: null, avg: null, max: null, comparableCount: 0 });
    expect(variant).toMatchObject({ package_quantity: 230, package_unit: 'g', bundle_count: 4 });
  });
  it.each(['매','인','인분'])('requires the same selected receipt for typed %s quotes', (unit) => {
    const product=selectionFixture();
    for(const variant of product.variants){
      Object.assign(variant,{package_quantity:2,package_unit:unit,bundle_count:1});
      Object.assign(variant.listings[0].offers[0],{quantity_unit:unit,total_quantity:2,per_100g:null,
        per_item:variant.id==='var-a'?3000:1000,bundle_count:1,received_package_count:1,
        minimum_quantity:1,membership_required:null,coupon_required:null,promotion_conditions:{},promotion_condition:null});
    }
    const selected=product.variants[0].listings[0].offers[0];
    product.best_offer={...selected,variant_id:'var-a',listing_id:'listing-a'};
    product.variants[0].listings.push({id:'listing-compatible',source:'동일 규격 판매처',offers:[{
      ...selected,id:'offer-compatible',listed_price:5000,total_price:5000,comparable_price:5000,per_item:2500,
    }]});
    const rows=getComparableOffers(product);
    expect(rows.map(row=>row.offerId)).toEqual(['offer-compatible','offer-a','offer-b']);
    expect(rows.find(row=>row.offerId==='offer-compatible')).toMatchObject({comparisonValue:2500,comparisonBasis:`1${unit}`});
    expect(rows.find(row=>row.offerId==='offer-b')).toMatchObject({unit:`1${unit}`,unitPrice:1000,totalQuantity:2,
      comparisonValue:null,comparisonBasis:null});
    expect(rows.find(row=>row.offerId==='offer-a')).toMatchObject({price:6000,totalPrice:6000,unit:`1${unit}`});
  });
  it.each(['quantity','bundle','received','membership','coupon','structured_conditions'])('holds typed quotes when the same variant has different %s', (boundary) => {
    const product=selectionFixture();
    const variant=product.variants[0];
    product.variants=[variant];
    const selected=variant.listings[0].offers[0];
    Object.assign(selected,{quantity_unit:'매',total_quantity:2,per_100g:null,per_item:3000,bundle_count:1,
      received_package_count:1,minimum_quantity:1,membership_required:null,coupon_required:null,
      promotion_conditions:{required_event:'same'},promotion_condition:null});
    const other={...selected,id:'offer-other',per_item:1000};
    if(boundary==='quantity')other.total_quantity=4;
    if(boundary==='bundle')other.bundle_count=2;
    if(boundary==='received')other.received_package_count=2;
    if(boundary==='membership')other.membership_required=true;
    if(boundary==='coupon')other.coupon_required=true;
    if(boundary==='structured_conditions')other.promotion_conditions={required_event:'different'};
    variant.listings.push({id:'listing-other',source:'다른 조건',offers:[other]});
    product.best_offer={...selected,variant_id:'var-a',listing_id:'listing-a'};
    expect(getComparableOffers(product).find(row=>row.offerId==='offer-other')).toMatchObject({unit:'1매',unitPrice:1000,
      comparisonValue:null,comparisonBasis:null});
  });
  it('submits the selected complete tuple and transaction spend without multiplying minimum purchase',async()=>{
    render(<ProductDetailModal product={selectionFixture()} mode="preview" onClose={vi.fn()}/>);
    fireEvent.click(screen.getByText('장바구니 담기'));
    await waitFor(()=>expect(api.post).toHaveBeenCalledWith('/api/cart',expect.objectContaining({product_id:'prod-spec',variant_id:'var-a',listing_id:'listing-a',offer_id:'offer-a',item_price:6000,quantity:1})));
    fireEvent.click(screen.getByRole('button',{name:'규격 선택: 90g×6'}));fireEvent.click(screen.getByText('장바구니 담기'));
    await waitFor(()=>expect(api.post).toHaveBeenCalledWith('/api/cart',expect.objectContaining({variant_id:'var-b',listing_id:'listing-b',offer_id:'offer-b',item_price:9000,quantity:1})));
    expect(useCartStore.getState().items).toHaveLength(2);
  });
  it('keys separate observed offers, rejects normalized zero and preserves manual free',async()=>{
    useStore.setState({isLoggedIn:false});
    const first=buildCartPayload(selectProductOffer(selectionFixture(),{variantId:'var-a'}));
    expect(buildCartPayload({...selectionFixture(),variant_id:'var-b',listing_id:'listing-b',offer_id:'offer-b'})).toMatchObject({variant_id:'var-b',listing_id:'listing-b',offer_id:'offer-b',item_price:9000});
    await useCartStore.getState().addItem(first);
    const next=selectionFixture();next.variants[0].listings[0].offers[0].id='offer-new';
    await useCartStore.getState().addItem(buildCartPayload(selectProductOffer(next,{variantId:'var-a'})));
    await useCartStore.getState().addItem(first);
    expect(useCartStore.getState().items.map(row=>[row.offer_id,row.quantity])).toEqual([['offer-a',2],['offer-new',1]]);
    const unresolved=selectionFixture();Object.assign(unresolved.variants[0].listings[0].offers[0],{listed_price:3000,total_price:null,comparable_price:null,total_quantity:null});
    expect(()=>buildCartPayload(unresolved)).toThrow('실제 거래 금액이 확인되지 않아');
    expect(buildWishlistPayload(unresolved)).toMatchObject({price_at_add:3000,current_price:null});
    const held=selectionFixture();held.variants[0].listings[0].offers[0].comparable_price=null;
    expect(buildCartPayload(held)).toMatchObject({item_price:6000,quantity:1});
    const zero=selectionFixture();Object.assign(zero.variants[0].listings[0].offers[0],{total_price:0,listed_price:0,comparable_price:0});
    expect(()=>buildCartPayload(zero)).toThrow('상품 표시 가격이 확인되지 않아');
    expect(buildWishlistPayload(zero).current_price).toBeNull();
    await expect(useCartStore.getState().addItem({product_id:'prod-zero',item_name:'미확인',item_price:0})).rejects.toThrow('상품 표시 가격이 확인되지 않아');
    await useCartStore.getState().addItem(buildCartPayload({item_name:'수동 무료',item_price:0}));expect(useCartStore.getState().items.at(-1).price).toBe(0);
    const ambiguous=selectionFixture();ambiguous.best_offer=null;expect(()=>buildCartPayload(ambiguous)).toThrow('상품 표시 가격이 확인되지 않아');
  });
  it('shows selected history with unknown average, unknown statistics and selected cart request',async()=>{
    const product=selectionFixture();product.stats={dataDays:180,records:999};
    const quote=product.variants[0].listings[0].offers[0];
    const history=[
      {...quote,date:'2026-09-29',price:6000,comparable_price:6000,variant_id:'var-a',is_latest:false,current_eligible:false},
      {...quote,id:'historic-compatible',date:'2026-09-30',price:7000,total_price:7000,comparable_price:7000,variant_id:'var-a',is_latest:false,current_eligible:false},
      {...quote,id:'historic-other-condition',date:'2026-10-01',price:1000,total_price:1000,comparable_price:1000,variant_id:'var-a',membership_required:false},
      {...product.variants[1].listings[0].offers[0],date:'2026-10-02',price:9000,variant_id:'var-b'},
    ];
    const summary=getPriceHistorySummary(selectProductOffer(product,{variantId:'var-a'}),history);
    expect(summary).toMatchObject({min:6000,avg:6500,max:7000,comparableCount:2});
    expect(summary.history[0]).toMatchObject({total_quantity:270,quantity_unit:'g',received_package_count:3,minimum_quantity:2,membership_required:true,coupon_required:false,promotion_conditions:{buy_quantity:2,free_quantity:1}});
    render(<ProductDetailModal product={{...product,price_history:history}} mode="preview" onClose={vi.fn()}/>);
    expect(screen.getByText('선택 규격·같은 수령 및 행사 조건의 관측 통계 · 2건')).toBeInTheDocument();
    expect(screen.getByText('6,500원')).toBeInTheDocument();
    expect(screen.getAllByText(/수령 270g.*수령 패키지 3.*최소 구매 2.*구매 2.*추가 증정 1.*회원 필요.*쿠폰 필요 없음/).length).toBeGreaterThan(0);
    cleanup();
    const mismatch=history.map(point=>({...point,received_package_count:99}));
    expect(getPriceHistorySummary(selectProductOffer(product,{variantId:'var-a'}),mismatch)).toMatchObject({min:null,avg:null,max:null});
    history.push({...quote,id:'historic-listed-only',date:'2026-10-01',variant_id:'var-a',price:3000,total_price:null,comparable_price:null,total_quantity:null,received_package_count:null});
    vi.stubGlobal('fetch',vi.fn(async path=>({ok:true,json:async()=>({data:String(path).includes('price-history')?history:String(path)==='/api/products/prod-spec'?product:[]})})));
    render(<MemoryRouter initialEntries={['/price/prod-spec']}><Routes><Route path="/price/:id" element={<PricePage/>}/></Routes></MemoryRouter>);
    await waitFor(()=>expect(screen.getByTestId('selected-history')).toHaveTextContent('6000'));
    expect(screen.getByTestId('selected-history')).not.toHaveTextContent('9000');
    expect(screen.getByText('선택 규격·같은 수령 및 행사 조건의 관측 통계: 최저 6,000원 · 평균 6,500원 · 최고 7,000원 (2건)')).toBeInTheDocument();
    expect(screen.getAllByText(/수령 270g.*수령 패키지 3.*최소 구매 2.*구매 2.*추가 증정 1.*회원 필요.*쿠폰 필요 없음/).length).toBeGreaterThan(0);
    expect(screen.getByText('표시 가격 이력에는 비교 조건이 미확인인 관측도 포함됩니다.')).toBeInTheDocument();
    expect(screen.getByText(/2026-10-01 · 관측 표시 가격 3,000원 · 판매 수량 미확인/)).toBeInTheDocument();
    expect(screen.queryByText(/실제 거래 금액 3,000원/)).not.toBeInTheDocument();
    expect(screen.queryByText('180일')).not.toBeInTheDocument();expect(screen.queryByText('999건')).not.toBeInTheDocument();
    expect(screen.queryByRole('button',{name:/수집 요청/})).not.toBeInTheDocument();
    expect(screen.queryByText(/적정 핫딜가|원 이하면 구매 추천/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button',{name:'90g×6'}));
    await waitFor(()=>expect(screen.getByTestId('selected-history')).toHaveTextContent('9000'));expect(screen.getByTestId('selected-history')).not.toHaveTextContent('6000');
    fireEvent.click(screen.getByRole('button',{name:'🛒 장보기에 추가'}));
    await waitFor(()=>expect(api.post).toHaveBeenCalledWith('/api/cart',expect.objectContaining({product_id:'prod-spec',variant_id:'var-b',listing_id:'listing-b',offer_id:'offer-b',item_price:9000,quantity:1})));
  });
});

describe('217 selected component vector presentation', () => {
  afterEach(() => { cleanup(); vi.clearAllMocks(); vi.unstubAllGlobals(); });
  it('renders only the selected real components in Modal and PricePage without erasing unknown adjuncts or pricing them as a homogeneous amount', async () => {
    const product = selectionFixture();
    const components = [{ identity: '건표고 원물', quantity: 100, unit: 'g', count: 2 },
      { identity: '건표고채', quantity: 60, unit: 'g', count: 1 },
      { identity: '선물 보자기', quantity: null, unit: null, count: null }];
    product.variants[0].quantity_components = components;
    product.variants[1].quantity_components = components.map(c => ({ ...c, count: c.count == null ? null : c.count * 10 }));
    expect(getOfferUnitPrice(product.best_offer, components)).toBeNull();
    api.getJson.mockResolvedValue({ data: null });
    render(<ProductDetailModal product={product} mode="preview" onClose={vi.fn()} />);
    const region = screen.getByLabelText('선택 규격 구성');
    expect(region).toHaveTextContent('건표고 원물 · 100g · 수량 2');
    expect(region).toHaveTextContent('건표고채 · 60g · 수량 1');
    expect(region).toHaveTextContent('선물 보자기 · 측정 내용량 미확인 · 수량 미확인');
    expect(screen.queryByText(/원\/100g/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '규격 선택: 90g×6' }));
    expect(region).toHaveTextContent('건표고 원물 · 100g · 수량 20');
    expect(region).not.toHaveTextContent('수량 2건');
    expect(product.variants[0].quantity_components).toEqual(components);
    cleanup();
    vi.stubGlobal('fetch', vi.fn(async path => ({ ok: true, json: async () => ({ data: String(path) === '/api/products/prod-spec' ? product : [] }) })));
    render(<MemoryRouter initialEntries={['/price/prod-spec']}><Routes><Route path="/price/:id" element={<PricePage />} /></Routes></MemoryRouter>);
    expect(await screen.findByLabelText('선택 규격 구성')).toHaveTextContent('건표고 원물 · 100g · 수량 2');
    fireEvent.click(screen.getByRole('button', { name: '90g×6' }));
    expect(screen.getByLabelText('선택 규격 구성')).toHaveTextContent('건표고채 · 60g · 수량 10');
    expect(screen.getByLabelText('선택 규격 구성')).toHaveTextContent('선물 보자기 · 측정 내용량 미확인 · 수량 미확인');
  });
});

describe('218 conditional selection observations', () => {
  beforeEach(() => {
    useStore.setState({ isLoggedIn: false, user: null, toasts: [] });
    useCartStore.setState({ items: [] });
    api.getJson.mockResolvedValue({ data: null });
  });
  afterEach(() => { cleanup(); vi.clearAllMocks(); });
  it.each([
    ['percentage', 2500, 4, { conditional_discount_percent: 50 }, '4개씩 골라 담으면, 50% 할인', '조건부 50% 할인 · 적용 미확인'],
    ['free item', 3900, 3, { conditional_free_quantity: 1 }, '3개씩 골라 담으면, 그 중 1개는 무료', '선택 상품 중 1개 무료 조건 · 무료 상품·금액 미확인'],
    ['basket total', 6980, 2, { conditional_basket_total_won: 10000 }, '2개씩 골라 담으면, 10,000원', '선택 묶음 총액 10,000원 조건 · 적용 상품 구성 미확인'],
    ['won discount', 15900, 2, { conditional_discount_won: 10000 }, '2개씩 골라 담으면, 10,000원 할인', '조건부 10,000원 할인 · 적용 미확인'],
    ['Homeplus3-selection', 3990, 3, { source_condition_kind: 'selected_basket_total', conditional_basket_total_won: 9990,
      source_event_maximum_quantity: 99, source_order_minimum_quantity: 1,
      source_purchase_limit: { purchaseLimitYn: 'Y', purchaseLimitDuration: 'P', purchaseLimitDay: 1,
        purchaseLimitQty: 10, itemPurchaseLimitMessage: '1일 동안 최대 10개 구매가능' },
      source_event_period: { start_date: '2026-10-01', end_date: '2026-10-14' },
      source_selection_price_intervals: [{ thresholdQty: 3, changeAmount: 9990 }, { thresholdQty: 6, changeAmount: 19980 }],
      eligible_selection_unconfirmed: true, coupon_application_unconfirmed: true },
    '3개 담으면, 9,990원에 구매 (최대 99개까지 행사/할인 적용)', '선택 묶음 총액 9,990원 조건 · 적용 상품 구성 미확인'],
    ['Homeplus4-selection', 2990, 4, { source_condition_kind: 'selected_basket_total', conditional_basket_total_won: 9990,
      source_event_maximum_quantity: 100, source_order_minimum_quantity: 1,
      source_purchase_limit: { purchaseLimitYn: 'Y', purchaseLimitDuration: 'P', purchaseLimitDay: 1,
        purchaseLimitQty: 10, itemPurchaseLimitMessage: '1일 동안 최대 10개 구매가능' },
      source_event_period: { start_date: '2026-10-01', end_date: '2026-10-14' },
      source_selection_price_intervals: [{ thresholdQty: 4, changeAmount: 9990 }, { thresholdQty: 8, changeAmount: 19980 }],
      eligible_selection_unconfirmed: true, coupon_application_unconfirmed: true },
    '4개 담으면, 9,990원에 구매 (최대 100개까지 행사/할인 적용)', '선택 묶음 총액 9,990원 조건 · 적용 상품 구성 미확인'],
  ])('preserves %s quote and history with conditional selection facts without inventing payable amount, same-SKU receipt or cart success', async (kind, listed, required, benefit, condition, expected) => {
    const product = selectionFixture(); product.variants = [product.variants[0]]; product.best_offer = null;
    const offer = product.variants[0].listings[0].offers[0];
    Object.assign(offer, { listed_price: listed, total_price: null, comparable_price: null, total_quantity: null,
      received_package_count: null, per_100g: null, per_item: null, minimum_quantity: null, promotion_type: 'unknown',
      current_eligible: false, membership_required: null, coupon_required: null, promotion_condition: condition,
      promotion_conditions: { ...benefit, condition_text: condition, required_selection_quantity: required,
        basket_selection_required: true, payable_price_unconfirmed: true } });
    product.price_history = [{ ...offer, price: listed, date: '2026-08-31', variant_id: 'var-a', listing_id: 'listing-a' }];
    const selected = selectProductOffer(product, { variantId: 'var-a' });
    expect(selected.cur).toBeNull(); expect(getOfferUnitPrice(offer)).toBeNull();
    expect(getComparableOffers(selected)).toEqual([]);
    expect(() => buildCartPayload(selected)).toThrow('실제 거래 금액');
    const summary = getPriceHistorySummary(selected, product.price_history);
    expect(summary).toMatchObject({ min: null, avg: null, max: null, comparableCount: 0 });
    expect(summary.history[0]).toMatchObject({ price: listed, total_price: null, comparablePrice: null });
    expect(getOfferConditionText(summary.history[0])).toContain(expected);
    if (benefit.source_event_maximum_quantity) {
      const text = getOfferConditionText(summary.history[0]);
      expect(text).toContain(`출처 행사 적용 수량 상한 ${benefit.source_event_maximum_quantity}개 · 재고·판매 묶음 수량 아님`);
      expect(text).toContain('출처 주문 최소 1개 · 행사 선택 수량과 별도');
      expect(text).toContain('출처 구매 한도: 1일 동안 최대 10개 구매가능');
      expect(text).toContain('출처 행사 기간 2026-10-01 ~ 2026-10-14 · 현재 이용 자격 미확인');
      expect(text).toContain(`출처 단계별 조건: ${required}개 조건 9,990원 … ${required * 2}개 조건 19,980원`);
      expect(text).toContain('쿠폰 자격·적용 미확인');
      expect(getCartQuotePresentation({ product_id: 'prod-spec', variant_id: 'var-a', listing_id: 'listing-a',
        offer_id: offer.id, price: listed, saved_receipt_valid: true,
        quoted_offer: { ...offer, total_price: listed, minimum_quantity: 1, current_eligible: true,
          membership_required: false, coupon_required: false } }).confirmedPurchase).toBe(false);
    }
    render(<ProductDetailModal product={product} mode="preview" onClose={vi.fn()} />);
    expect(screen.getByText(`· 표시 가격 ${listed.toLocaleString('ko-KR')}원`)).toBeInTheDocument();
    expect(screen.getAllByText(new RegExp('조건부 행사 관측.*실제 결제 금액 미확인')).length).toBeGreaterThan(0);
    expect(screen.getAllByText(new RegExp(`선택 상품 ${required}개 조건.*같은 상품 수령량 미확인`)).length).toBeGreaterThan(0);
    expect(screen.queryByText(/원\/100g|^0원$|관측 거래 금액|최저가 출처/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '장바구니 담기' }));
    await waitFor(() => expect(useStore.getState().toasts.some(t => t.msg.includes('실제 거래 금액'))).toBe(true));
    expect(useStore.getState().toasts.some(t => t.type === 'success')).toBe(false);
    expect(useCartStore.getState().items).toEqual([]);
    expect(api.post).not.toHaveBeenCalled();
  });
});

describe('219 named program observations', () => {
  beforeEach(() => { useStore.setState({ isLoggedIn: false, toasts: [] }); api.getJson.mockResolvedValue({ data: null }); });
  afterEach(() => { cleanup(); vi.clearAllMocks(); });
  it.each([
    ['농할', 3740, '농할 할인 20%_결제시 자동적용', 'checkout', 'automatic', '결제시 자동적용'],
    ['수산대전', 19900, '수산대전 20% 할인', null, null, null],
  ])('shows %s source rate and application declaration separately from unknown eligibility, cap and payment', (program, listed, condition, stage, method, applicationText) => {
    const product = selectionFixture(); product.variants = [product.variants[0]]; product.best_offer = null;
    const offer = product.variants[0].listings[0].offers[0];
    Object.assign(offer, { listed_price: listed, total_price: null, comparable_price: null, total_quantity: null,
      received_package_count: null, per_100g: null, per_item: null, minimum_quantity: null, promotion_type: 'unknown',
      current_eligible: false, membership_required: null, coupon_required: null, promotion_condition: condition,
      promotion_conditions: { condition_text: condition, source_condition_kind: 'named_program_percentage_discount',
        source_program_name: program, conditional_discount_percent: 20, payable_price_unconfirmed: true,
        discount_application_unconfirmed: true, program_eligibility_unconfirmed: true, benefit_cap: null,
        discount_calculation_basis: null, source_declared_application_stage: stage,
        source_declared_application_method: method, source_application_text: applicationText } });
    product.price_history = [{ ...offer, price: listed, date: '2026-08-31', variant_id: 'var-a', listing_id: 'listing-a' }];
    const selected = selectProductOffer(product, { variantId: 'var-a' });
    expect(selected.cur).toBeNull(); expect(getOfferUnitPrice(offer)).toBeNull();
    expect(() => buildCartPayload(selected)).toThrow('실제 거래 금액');
    const summary = getPriceHistorySummary(selected, product.price_history);
    expect(summary).toMatchObject({ min: null, avg: null, max: null, comparableCount: 0 });
    expect(summary.history[0]).toMatchObject({ price: listed, total_price: null, comparablePrice: null });
    const text = getOfferConditionText(summary.history[0]);
    expect(text).toContain(`${program} 조건부 관측 · 조건부 20% 할인`);
    expect(text).toContain('이용 자격 미확인 · 할인 한도 미확인 · 할인 계산 기준 미확인');
    expect(text).toContain('실제 적용 미확인 · 실제 결제 금액 미확인');
    if (applicationText) expect(text).toContain(`출처 안내: ${applicationText}`);
    else { expect(text).toContain('적용 시점·방법 미확인'); expect(text).not.toContain('자동'); }
    expect(text).not.toContain('선택 상품');
    render(<ProductDetailModal product={product} mode="preview" onClose={vi.fn()} />);
    expect(screen.getByText(`· 표시 가격 ${listed.toLocaleString('ko-KR')}원`)).toBeInTheDocument();
    expect(screen.getAllByText(new RegExp(`${program} 조건부 관측.*실제 결제 금액 미확인`)).length).toBeGreaterThan(0);
    expect(screen.queryByText(/원\/100g|^0원$|관측 거래 금액|최저가 출처/)).not.toBeInTheDocument();
    expect(offer.promotion_conditions.source_declared_application_stage).toBe(stage);
    expect(api.post).not.toHaveBeenCalled();
  });
});


describe('221 basket spend observations', () => {
  beforeEach(() => {
    useStore.setState({ isLoggedIn: false, user: null, toasts: [] });
    useCartStore.setState({ items: [] });
    api.getJson.mockResolvedValue({ data: null });
  });
  afterEach(() => { cleanup(); vi.clearAllMocks(); });
  it.each([
    ['arrow cash', 1350, '[동서식품] 4.5만↑ 5천원 할인', {
      source_condition_kind: 'basket_spend_won_discount', source_spend_threshold_won: 45000,
      source_threshold_amount_text: '4.5만', source_threshold_marker: '↑', source_threshold_operator: null,
      source_threshold_inclusive: null, threshold_equality_unconfirmed: true, source_scope_text: '동서식품',
      conditional_discount_won: 5000,
    }, '출처 구매 금액 조건 4.5만↑', '조건부 5,000원 할인'],
    ['inclusive immediate cash', 4380, '[동원] 4만원 이상 구매시, 5천원 즉시할인', {
      source_condition_kind: 'basket_spend_won_discount', source_spend_threshold_won: 40000,
      source_threshold_amount_text: '4만원', source_threshold_marker: '이상', source_threshold_operator: '>=',
      source_threshold_inclusive: true, threshold_equality_unconfirmed: false, source_scope_text: '동원',
      conditional_discount_won: 5000, source_application_text: '즉시할인',
    }, '출처 구매 금액 조건 4만원 이상', '조건부 5,000원 할인'],
    ['arrow card percentage', 79900, '[행사카드] 명절세트 30만↑ 12% 할인', {
      source_condition_kind: 'basket_spend_percent_discount', source_spend_threshold_won: 300000,
      source_threshold_amount_text: '30만', source_threshold_marker: '↑', source_threshold_operator: null,
      source_threshold_inclusive: null, threshold_equality_unconfirmed: true, source_scope_text: '행사카드 명절세트',
      conditional_discount_percent: 12, source_payment_card_text: '행사카드',
    }, '출처 구매 금액 조건 30만↑', '조건부 12% 할인'],
    ['inclusive program cash', 3900, '제타패스 X 요즘 1만원 이상 3천원 할인', {
      source_condition_kind: 'basket_spend_won_discount', source_spend_threshold_won: 10000,
      source_threshold_amount_text: '1만원', source_threshold_marker: '이상', source_threshold_operator: '>=',
      source_threshold_inclusive: true, threshold_equality_unconfirmed: false, source_scope_text: '제타패스 X 요즘',
      conditional_discount_won: 3000, source_program_name: '제타패스 X 요즘',
    }, '출처 구매 금액 조건 1만원 이상', '조건부 3,000원 할인'],
  ])('renders %s declared threshold and benefit without assigning eligibility or payable price', async (_kind, listed, condition, facts, thresholdText, benefitText) => {
    const product = selectionFixture(); product.variants = [product.variants[0]]; product.best_offer = null;
    const offer = product.variants[0].listings[0].offers[0];
    Object.assign(offer, { listed_price: listed, total_price: null, comparable_price: null, total_quantity: null,
      received_package_count: null, per_100g: null, per_item: null, minimum_quantity: null, promotion_type: 'unknown',
      current_eligible: false, membership_required: null, coupon_required: null, promotion_condition: condition,
      promotion_conditions: { ...facts, condition_text: condition, payable_price_unconfirmed: true,
        discount_application_unconfirmed: true, qualifying_basket_unconfirmed: true, basket_allocation_unconfirmed: true,
        spend_threshold_basis_unconfirmed: true, discount_calculation_basis: null, benefit_cap: null,
        confirmed_user_eligibility: null, source_declared_application_stage: null } });
    product.price_history = [{ ...offer, price: listed, date: '2026-08-31', variant_id: 'var-a', listing_id: 'listing-a' }];
    const selected = selectProductOffer(product, { variantId: 'var-a' });
    expect(selected.cur).toBeNull(); expect(getOfferUnitPrice(offer)).toBeNull();
    expect(getComparableOffers(selected)).toEqual([]);
    expect(() => buildCartPayload(selected)).toThrow('실제 거래 금액');
    const summary = getPriceHistorySummary(selected, product.price_history);
    expect(summary).toMatchObject({ min: null, avg: null, max: null, comparableCount: 0 });
    expect(summary.history[0]).toMatchObject({ price: listed, total_price: null, comparablePrice: null });
    const text = getOfferConditionText(summary.history[0]);
    expect(text).toContain(condition); expect(text).toContain(thresholdText); expect(text).toContain(benefitText);
    expect(text).toContain(`출처 행사 범위: ${facts.source_scope_text}`);
    expect(text).toContain('이용 자격 미확인 · 적용 상품 구성·금액 배분 미확인 · 구매 금액 계산 기준 미확인');
    expect(text).toContain('할인 한도 미확인 · 할인 계산 기준 미확인');
    expect(text).toContain('실제 적용 미확인 · 실제 결제 금액 미확인');
    expect(text).toContain('회원 조건 미확인 · 쿠폰 조건 미확인');
    expect(text).not.toMatch(/회원 제한 없음|쿠폰 필요 없음|선택 상품/);
    if (facts.source_threshold_marker === '↑') {
      expect(text).toContain('기준 금액과 같을 때 적용 여부 미확인');
      expect(text).not.toContain(`${facts.source_threshold_amount_text} 이상`);
    } else {
      expect(text).not.toContain('기준 금액과 같을 때 적용 여부 미확인');
    }
    if (facts.source_payment_card_text) expect(text).toContain('출처 카드 조건: 행사카드 · 카드 이용 자격 미확인');
    if (facts.source_program_name) expect(text).toContain(`출처 프로그램: ${facts.source_program_name}`);
    if (facts.source_application_text) expect(text).toContain('출처 안내: 즉시할인');
    render(<ProductDetailModal product={product} mode="preview" onClose={vi.fn()} />);
    expect(screen.getByText(`· 표시 가격 ${listed.toLocaleString('ko-KR')}원`)).toBeInTheDocument();
    expect(screen.getAllByText(/구매 금액 조건부 관측.*실제 결제 금액 미확인/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/원\/100g|^0원$|관측 거래 금액|최저가 출처/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '장바구니 담기' }));
    await waitFor(() => expect(useStore.getState().toasts.some(t => t.msg.includes('실제 거래 금액'))).toBe(true));
    expect(useCartStore.getState().items).toEqual([]);
    expect(api.post).not.toHaveBeenCalled();
  });
});

describe('222 observed source quote with unknown purchase terms', () => {
  afterEach(() => { cleanup(); vi.clearAllMocks(); });
  it('preserves a source quote in selected history without pricing or saving an unverified purchase', async () => {
    useStore.setState({ isLoggedIn: false, user: null, toasts: [] });
    useCartStore.setState({ items: [] });
    api.getJson.mockResolvedValue({ data: null });
    const product = selectionFixture(); product.variants = [product.variants[0]]; product.best_offer = null;
    const offer = product.variants[0].listings[0].offers[0];
    Object.assign(offer, { listed_price: 2190, total_price: null, comparable_price: null, per_100g: null,
      per_item: null, promotion_type: 'unknown', current_eligible: false, minimum_quantity: null,
      promotion_conditions: { source_condition_kind: 'source_quote_purchase_conditions_unverified',
        payable_price_unconfirmed: true, minimum_purchase_quantity_unconfirmed: true,
        coupon_application_unconfirmed: true } });
    product.price_history = [{ ...offer, price: 2190, date: '2026-10-04', variant_id: 'var-a', listing_id: 'listing-a' }];
    const selected = selectProductOffer(product, { variantId: 'var-a' });
    expect(selected.cur).toBeNull(); expect(getOfferUnitPrice(offer)).toBeNull();
    expect(getComparableOffers(selected)).toEqual([]);
    expect(() => buildCartPayload(selected)).toThrow('실제 거래 금액');
    const history = getPriceHistorySummary(selected, product.price_history);
    expect(history.history[0]).toMatchObject({ price: 2190, total_price: null, comparablePrice: null });
    expect(getOfferConditionText(history.history[0])).toContain('최소구매 수량·총지출 미확인');
    render(<ProductDetailModal product={product} mode="preview" onClose={vi.fn()} />);
    expect(screen.getByText('· 표시 가격 2,190원')).toBeInTheDocument();
    expect(screen.getAllByText(/출처 표시가격 관측.*쿠폰 자격·적용 미확인/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/관측 거래 금액|원\/100g|^0원$/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '장바구니 담기' }));
    await waitFor(() => expect(useStore.getState().toasts.some(t => t.msg.includes('실제 거래 금액'))).toBe(true));
    expect(useCartStore.getState().items).toEqual([]); expect(api.post).not.toHaveBeenCalled();
  });
});

describe('249 native source quote declarations', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.clearAllMocks(); });
  it('keeps the source promotion period literal without asserting receipt validity or UTC endpoints', () => {
    const offer = { listed_price: 3900, total_price: null, comparable_price: null,
      received_package_count: null, total_quantity: null, valid_from: null, valid_to: null,
      current_eligible: false, promotion_conditions: {
        source_condition_kind: 'source_quote_purchase_conditions_unverified', payable_price_unconfirmed: true,
        source_promotion_period_text: ' (2026.10.01 - 2026.10.14) ',
        source_required_product_quantity: 3, source_free_quantity: 1, selected_product_scope_unconfirmed: true,
      } };
    const original = JSON.stringify(offer);
    const text = getOfferConditionText(offer);
    expect(text).toContain('출처 표시 행사기간 (2026.10.01 - 2026.10.14) · 시간대/경계 미확인');
    expect(text).toContain('선택 상품 3개 조건 · 같은 상품 수령량 미확인');
    expect(text).toContain('총지출·실제 결제 금액 미확인');
    expect(getOfferUnitPrice(offer)).toBeNull();
    expect(JSON.stringify(offer)).toBe(original);
  });
  it('omits missing or nontext source promotion periods instead of inventing dates', () => {
    for (const source_promotion_period_text of [undefined, null, '', '  ', false, 20261001, [], {}]) {
      const text = getOfferConditionText({ promotion_conditions: {
        source_condition_kind: 'source_quote_purchase_conditions_unverified', payable_price_unconfirmed: true,
        source_promotion_period_text,
      } });
      expect(text).not.toContain('출처 표시 행사기간');
      expect(text).toContain('총지출·실제 결제 금액 미확인');
    }
  });
  it('formats legacy share money with a null offer without turning malformed amounts into zero', () => {
    expect(getObservedOfferPriceText(null, 2190)).toBe('2,190원');
    expect(getObservedOfferPriceText(null, '2190.5')).toBe('2,190.5원');
    expect(getObservedOfferPriceText(null, 0)).toBe('0원');
    expect(getObservedOfferPriceText(null)).toBe('미확인');
    for (const amount of [null, undefined, '', ' ', false, true, [], {}, 'invalid', '0x10', NaN, Infinity, -1]) {
      expect(getObservedOfferPriceText(null, amount)).toBe('미확인');
    }
    const unknownCurrency = { promotion_conditions: { source_condition_kind: 'source_quote_purchase_conditions_unverified',
      source_quote_currency: null, payable_price_unconfirmed: true } };
    expect(getObservedOfferPriceText(unknownCurrency, 2190)).toBe('2,190 (통화 미명시)');
    expect(getObservedOfferPriceText(unknownCurrency, 0)).toBe('미확인');
  });
  const coupons = [
    { manageCouponNm: '[컨틴] 7만/4천 10.01~07', purchaseMin: 70000, discount: 4000, discountType: '2',
      discountMax: 0, issueStartDt: '2026-10-01 00:00:00', issueEndDt: '2026-10-07 23:59:59' },
    { manageCouponNm: '[컨틴] 5만/2천 10.01~07', purchaseMin: 50000, discount: 2000, discountType: '2' },
  ];
  it('retains optional coupon and purchase limits on a KRW public base quote without claiming checkout payment', () => {
    const offer = { id: 'public-base-quote', listed_price: 2190, total_price: 2190, comparable_price: 2190,
      total_quantity: 12000, quantity_unit: 'ml', received_package_count: 1, per_100ml: 18.25,
      minimum_quantity: 1, membership_required: null, coupon_required: null, current_eligible: true,
      promotion_conditions: { source_condition_kind: 'source_public_base_quote', source_quote_currency: 'KRW',
        source_base_quote_only: true, payable_price_unconfirmed: false,
        source_minimum_purchase_quantity: 1, source_maximum_purchase_quantity: 2,
        source_purchase_limit: { purchaseLimitYn: 'Y', purchaseLimitDuration: 'O', purchaseLimitQty: 2,
          itemPurchaseLimitMessage: '최대 2개 구매가능' },
        source_coupon_declarations: { couponInfo: coupons[0], couponList: coupons },
        coupon_application_unconfirmed: true } };
    const original = JSON.stringify(offer);
    const text = getOfferConditionText(offer);
    for (const fragment of ['출처 기본 표시가격 관측 (쿠폰 할인 전)', '출처 주문 최소 1개 · 판매 묶음 수량 아님',
      '출처 구매 수량 한도 2개 · 판매 묶음 수량 아님', '최대 2개 구매가능',
      '구매금액 기준 표기 70,000', '할인값 표기 4,000', '구매금액 기준 표기 50,000', '할인값 표기 2,000',
      '출처 발급 기간 2026-10-01 00:00:00 ~ 2026-10-07 23:59:59', '쿠폰 자격·실제 적용 미확인',
      '기본 표시가격·내용량 기준 계산 · 쿠폰 할인·배송비 미포함 · 실제 결제 금액 미확인',
      '회원 조건 미확인 · 쿠폰 조건 미확인']) expect(text).toContain(fragment);
    expect(text.match(/7만\/4천/g)).toHaveLength(1);
    expect(text).not.toMatch(/총지출·실제 결제 금액 미확인|쿠폰 필요 없음|회원 제한 없음|할인 한도 0/);
    expect(getObservedOfferPriceText(offer)).toBe('2,190원');
    expect(getOfferUnitPrice(offer)).toEqual({ price: 18.25, unit: '100ml' });
    expect(getCartQuotePresentation({ product_id: 'prod-water', variant_id: 'var-water',
      listing_id: 'listing-water', offer_id: offer.id, saved_receipt_valid: true, price: 2190,
      offer_context: offer })).toMatchObject({ confirmedPurchase: false,
      statusText: expect.stringContaining('현재 결제 금액·구매 가능 여부 미확인') });
    expect(JSON.stringify(offer)).toBe(original);
  });
  it.each([
    ['costco', 40990, { source_quote_currency: 'KRW', source_minimum_purchase_quantity: 1,
      source_maximum_order_quantity: 500, membership_eligibility_unconfirmed: true,
      source_public_flag_values_unrecoverable: true },
      ['출처 주문 최소 1개', '출처 주문 수량 상한 500개 · 재고·할인 한도 아님', '회원 자격 미확인']],
    ['homeplus', 2190, { source_quote_currency: null, currency_unconfirmed: true,
      source_minimum_purchase_quantity: 1, source_maximum_purchase_quantity: 2,
      minimum_purchase_quantity_unconfirmed: false,
      source_purchase_limit: { purchaseLimitYn: 'Y', purchaseLimitDuration: 'O', purchaseLimitQty: 2,
        itemPurchaseLimitMessage: '최대 2개 구매가능' },
      source_coupon_declarations: { couponInfo: coupons[0], couponList: coupons } },
      ['출처 주문 최소 1개', '출처 구매 수량 한도 2개', '최대 2개 구매가능',
        '구매금액 기준 표기 70,000', '할인값 표기 4,000', '구매금액 기준 표기 50,000', '할인값 표기 2,000',
        '출처 발급 기간 2026-10-01 00:00:00 ~ 2026-10-07 23:59:59', '쿠폰 자격·실제 적용 미확인']],
    ['lottemart', 3900, { source_quote_currency: 'KRW', selected_product_scope_unconfirmed: true,
      source_required_product_quantity: 3, source_free_quantity: 1,
      condition_text: '3개씩 골라 담으면, 그 중 1개는 무료' },
      ['3개씩 골라 담으면, 그 중 1개는 무료', '선택 상품 3개 조건 · 같은 상품 수령량 미확인',
        '선택 상품 중 1개 무료 조건 · 무료 상품·금액 미확인', '적용 상품 구성 미확인']],
  ])('shows %s source terms without converting its quote into a paid receipt', async (source, amount, terms, fragments) => {
    useStore.setState({ isLoggedIn: false, user: null, toasts: [] }); useCartStore.setState({ items: [] });
    api.getJson.mockResolvedValue({ data: null });
    const product = selectionFixture(); product.variants = [product.variants[0]]; product.best_offer = null;
    const listing = product.variants[0].listings[0]; listing.source = source;
    const offer = listing.offers[0];
    Object.assign(offer, { listed_price: amount, total_price: null, comparable_price: null,
      total_quantity: null, received_package_count: null, per_100g: null, per_100ml: null, per_item: null,
      minimum_quantity: null, membership_required: null, coupon_required: null, current_eligible: false,
      promotion_type: 'unknown', promotion_conditions: { source_condition_kind: 'source_quote_purchase_conditions_unverified',
        payable_price_unconfirmed: true, coupon_application_unconfirmed: true, ...terms } });
    product.price_history = [{ ...offer, price: amount, date: '2026-10-05', variant_id: 'var-a', listing_id: 'listing-a' }];
    const original = JSON.stringify(product);
    const selected = selectProductOffer(product, { variantId: 'var-a' });
    const text = getOfferConditionText(offer);
    for (const fragment of fragments) expect(text).toContain(fragment);
    if (terms.source_minimum_purchase_quantity) expect(text).not.toContain('최소구매 수량·총지출 미확인');
    expect(text).toContain('총지출·실제 결제 금액 미확인');
    expect(getOfferUnitPrice(offer)).toBeNull(); expect(getComparableOffers(selected)).toEqual([]);
    expect(getPriceHistorySummary(selected, product.price_history)).toMatchObject({ min: null, avg: null, max: null });
    expect(() => buildCartPayload(selected)).toThrow('실제 거래 금액');
    render(<ProductDetailModal product={product} mode="preview" onClose={vi.fn()} />);
    const quoteText = source === 'homeplus' ? '2,190 (통화 미명시)' : `${amount.toLocaleString('ko-KR')}원`;
    expect(screen.getByText(`· 표시 가격 ${quoteText}`)).toBeInTheDocument();
    for (const fragment of fragments) expect(screen.getAllByText(text => text.includes(fragment)).length).toBeGreaterThan(0);
    expect(screen.queryByText(/관측 거래 금액|원\/100g|원\/100ml|^0원$|최저가 출처/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '장바구니 담기' }));
    await waitFor(() => expect(useStore.getState().toasts.some(row => row.msg.includes('실제 거래 금액'))).toBe(true));
    expect(useCartStore.getState().items).toEqual([]); expect(api.post).not.toHaveBeenCalled();
    expect(JSON.stringify(product)).toBe(original);
    if (source === 'homeplus') {
      expect(screen.queryByText(/2,190원/)).not.toBeInTheDocument();
      expect(text.match(/7만\/4천/g)).toHaveLength(1);
      expect(text).not.toContain('할인 한도 0');
      cleanup();
      const prior = { ...offer, id: 'old-observation', date: '2026-09-02', price: 6480,
        variant_id: 'var-a', listing_id: 'listing-a',
        promotion_conditions: { source_condition_kind: 'source_quote_purchase_conditions_unverified',
          payable_price_unconfirmed: true, source_quote_currency: 'KRW' } };
      const history = [prior, ...product.price_history];
      vi.stubGlobal('fetch', vi.fn(async path => ({ ok: true, json: async () => ({ data:
        String(path) === '/api/products/prod-spec' ? product : String(path).includes('price-history') ? history : [] }) })));
      render(<MemoryRouter initialEntries={['/price/prod-spec']}><Routes><Route path="/price/:id" element={<PricePage />} /></Routes></MemoryRouter>);
      await screen.findByText(/2026-10-05 · 관측 표시 가격 2,190 \(통화 미명시\)/);
      expect(await screen.findByText(/2026-09-02 · 관측 표시 가격 6,480원/)).toBeInTheDocument();
      expect(screen.queryByText(/2,190원|실제 거래 금액 2,190|^0원$/)).not.toBeInTheDocument();
      expect(screen.getByText(/최저 미확인 · 평균 미확인 · 최고 미확인/)).toBeInTheDocument();
      expect(getObservedOfferPriceText({}, 2190)).toBe('2,190원');
      expect(getObservedOfferPriceText({ promotion_conditions: { source_condition_kind: 'source_quote_purchase_conditions_unverified',
        source_quote_currency_unconfirmed: true } }, 2190)).toBe('2,190 (통화 미명시)');
      expect(getObservedOfferPriceText(offer, null)).toBe('미확인');
    }
  });
});

describe('400 catalog observed-price description boundary', () => {
  beforeEach(() => {
    useStore.setState({ selectedProduct: null, recentSearches: [], isLoggedIn: false, favorites: [], toasts: [] });
    api.getJson.mockResolvedValue({ data: null });
    vi.spyOn(searchService, 'trending').mockResolvedValue({ data: [] });
  });
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  it('labels generated search amounts as observation-condition comparison, retaining positive and unknown values without inventing a clock', async () => {
    vi.spyOn(searchService, 'search').mockResolvedValue({ data: [
      { type: 'product', id: 'prod-known', title: '선택 스낵', price: 9900, description: '294g / 현재가 9900.0원' },
      { type: 'product', id: 'prod-held', title: '조건 미확인 스낵', price: null, description: '294g / 비교 가능한 관측 조건 비교금액 미확인' },
    ] });
    render(<MemoryRouter initialEntries={['/search?q=스낵']}><SearchPage /></MemoryRouter>);
    expect(await screen.findByText('294g / 관측 조건 비교금액 9900.0원 · 관측 시점 미확인')).toBeInTheDocument();
    expect(screen.getByText('9,900원')).toBeInTheDocument();
    expect(screen.getByText('294g / 비교 가능한 관측 조건 비교금액 미확인 · 관측 시점 미확인')).toBeInTheDocument();
    expect(screen.queryByText(/현재가|^0원$/)).not.toBeInTheDocument();
    expect(getCatalogObservationDescription({ id: 7, description: '현재가 1000원' })).toBe('현재가 1000원');
    expect(getCatalogObservationDescription({ id: 'prod-known', description: '출처가 선언한 상품 설명' })).toBe('출처가 선언한 상품 설명');
  });

  it('replaces stale search summary with the exact selected source quote and clock while preserving valid historical condition arithmetic', () => {
    const raw = selectionFixture();
    raw.description = '90g / 현재가 9000원';
    const offer = raw.variants[0].listings[0].offers[0];
    Object.assign(offer, { listed_price: 8980, total_price: 17960, comparable_price: 17960,
      total_quantity: 1800, per_100g: 997.7778, crawled_at: '2026-08-31T01:45:00Z',
      valid_to: '2026-09-01T15:00:00Z', current_eligible: false, availability_reason: 'expired',
      observation_receipt_eligible: true });
    raw.variants[0].package_quantity = 600;
    raw.variants[0].display_unit = '600g';
    const product = selectProductOffer(raw, { variantId: 'var-a', listingId: 'listing-a', offerId: 'offer-a' });
    const before = JSON.stringify(product);
    render(<ProductDetailModal product={product} mode="preview" onClose={vi.fn()} />);
    expect(screen.getByText('출처 표시 가격 8,980원 · 관측 시점 2026-08-31T01:45:00Z')).toBeInTheDocument();
    expect(screen.getAllByText(/출처 조건 계산 금액 17,960원/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/판매 기간 종료/).length).toBeGreaterThan(0);
    expect(screen.queryByText('90g / 현재가 9000원')).not.toBeInTheDocument();
    expect(JSON.stringify(product)).toBe(before);
  });

  it('keeps explicit unknown currency and missing selected-source clock unknown without reviving stale calculated payment', () => {
    const raw = selectionFixture();
    raw.description = '90g / 관측 조건 비교금액 17960원';
    const offer = raw.variants[0].listings[0].offers[0];
    Object.assign(offer, { listed_price: 2190, total_price: null, comparable_price: null,
      total_quantity: null, per_100g: null, current_eligible: false,
      observation_receipt_eligible: false, observation_receipt_reason: 'promotion_observation_outside_period',
      promotion_conditions: { source_condition_kind: 'source_quote_purchase_conditions_unverified',
        source_quote_currency: null, payable_price_unconfirmed: true } });
    const product = selectProductOffer(raw, { variantId: 'var-a', listingId: 'listing-a', offerId: 'offer-a' });
    render(<ProductDetailModal product={product} mode="preview" onClose={vi.fn()} />);
    expect(screen.getByText('출처 표시 가격 2,190 (통화 미명시) · 관측 시점 미확인')).toBeInTheDocument();
    expect(screen.queryByText(/현재가|관측 조건 비교금액 17960원|2,190원/)).not.toBeInTheDocument();
    expect(getCatalogObservationDescription(product, { offer: null })).toBe('출처 표시 가격 미확인 · 관측 시점 미확인');
  });
});

describe('355 query-owned asynchronous search consumers', () => {
  const deferred = () => {
    let resolve, reject;
    const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    return { promise, resolve, reject };
  };
  const result = word => ({ data: { keywords: [{ id: 1, word }], products: [],
    total_keyword_count: 1, total_product_count: 0 } });
  beforeEach(() => {
    useStore.setState({ selectedProduct: null, recentSearches: [], isLoggedIn: false });
    vi.spyOn(searchService, 'trending').mockResolvedValue({ data: [] });
  });
  afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it.each(['success', 'error'])('keeps current search results loading after superseded %s and finally', async outcome => {
    const old = deferred(), latest = deferred();
    const search = vi.spyOn(searchService, 'search').mockImplementation(query => query === '이전' ? old.promise : latest.promise);
    vi.spyOn(searchService, 'autocomplete').mockResolvedValue(result('unused'));
    render(<MemoryRouter initialEntries={['/search?q=이전']}><SearchPage /></MemoryRouter>);
    await waitFor(() => expect(search).toHaveBeenCalledTimes(1));
    const previousSignal = search.mock.calls[0][2].signal;
    const input = screen.getByPlaceholderText('상품, 핫딜, 커뮤니티 검색...');
    fireEvent.change(input, { target: { value: '현재' } });
    fireEvent.submit(input.closest('form'));
    await waitFor(() => expect(search).toHaveBeenCalledTimes(2));
    await act(async () => outcome === 'success'
      ? old.resolve({ data: [{ id: 'old', type: 'product', title: '늦은 결과' }] })
      : old.reject(new Error('늦은 오류')));
    expect(previousSignal.aborted).toBe(true);
    expect(screen.queryByText('늦은 결과')).not.toBeInTheDocument();
    expect(screen.queryByText('늦은 오류')).not.toBeInTheDocument();
    expect(screen.queryByText('검색 결과가 없습니다')).not.toBeInTheDocument();
    await act(async () => latest.resolve({ data: [{ id: 'latest', type: 'product', title: '최신 검색 결과' }] }));
    expect(await screen.findByText('최신 검색 결과')).toBeInTheDocument();
  });

  it.each(['success', 'error'])('retains shared autocomplete current suggestions after superseded %s', async outcome => {
    const old = deferred(), latest = deferred();
    const autocomplete = vi.spyOn(searchService, 'autocomplete').mockImplementation(query => query === '이전' ? old.promise : latest.promise);
    render(<MemoryRouter><SearchAutocomplete placeholder="공통 자동완성" /></MemoryRouter>);
    const input = screen.getByPlaceholderText('공통 자동완성');
    fireEvent.change(input, { target: { value: '이전' } });
    await waitFor(() => expect(autocomplete).toHaveBeenCalledTimes(1));
    const signal = autocomplete.mock.calls[0][2].signal;
    fireEvent.change(input, { target: { value: '현재' } });
    await waitFor(() => expect(autocomplete).toHaveBeenCalledTimes(2));
    await act(async () => latest.resolve(result('최신 자동완성')));
    expect(await screen.findByText('최신 자동완성')).toBeInTheDocument();
    await act(async () => outcome === 'success' ? old.resolve(result('늦은 자동완성')) : old.reject(new Error('늦은 실패')));
    expect(signal.aborted).toBe(true);
    expect(screen.getByText('최신 자동완성')).toBeInTheDocument();
    expect(screen.queryByText('늦은 자동완성')).not.toBeInTheDocument();
  });

  it('cancels shared autocomplete on submission, external query replacement and unmount', async () => {
    const old = deferred(), next = deferred();
    const autocomplete = vi.spyOn(searchService, 'autocomplete').mockImplementationOnce(() => old.promise).mockImplementationOnce(() => next.promise);
    const onSearch = vi.fn();
    const view = render(<MemoryRouter><SearchAutocomplete variant="page" placeholder="공통 취소" onSearch={onSearch} /></MemoryRouter>);
    const input = screen.getByPlaceholderText('공통 취소');
    fireEvent.change(input, { target: { value: '이전' } });
    await waitFor(() => expect(autocomplete).toHaveBeenCalledTimes(1));
    fireEvent.submit(input.closest('form'));
    expect(onSearch).toHaveBeenCalledWith('이전');
    expect(autocomplete.mock.calls[0][2].signal.aborted).toBe(true);
    await act(async () => old.resolve(result('제출 뒤 이전 제안')));
    expect(screen.queryByText('제출 뒤 이전 제안')).not.toBeInTheDocument();
    fireEvent.change(input, { target: { value: '다음' } });
    await waitFor(() => expect(autocomplete).toHaveBeenCalledTimes(2));
    view.rerender(<MemoryRouter><SearchAutocomplete variant="page" placeholder="공통 취소" onSearch={onSearch} initialValue="URL 검색어" /></MemoryRouter>);
    expect(input).toHaveValue('URL 검색어');
    expect(autocomplete.mock.calls[1][2].signal.aborted).toBe(true);
    view.unmount();
    await act(async () => next.resolve(result('닫힌 제안')));
  });

  it.each(['success', 'error'])('retains PricePage autocomplete current suggestions after superseded %s', async outcome => {
    const old = deferred(), latest = deferred();
    const autocomplete = vi.spyOn(searchService, 'autocomplete').mockImplementation(query => query === '이전' ? old.promise : latest.promise);
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ data: [] }) })));
    render(<MemoryRouter initialEntries={['/price']}><Routes><Route path="/price" element={<PricePage />} /></Routes></MemoryRouter>);
    const input = await screen.findByPlaceholderText('상품명을 검색하세요 (양파, 삼겹살, 계란...)');
    fireEvent.change(input, { target: { value: '이전' } });
    await waitFor(() => expect(autocomplete).toHaveBeenCalledTimes(1));
    const signal = autocomplete.mock.calls[0][2].signal;
    fireEvent.change(input, { target: { value: '현재' } });
    await waitFor(() => expect(autocomplete).toHaveBeenCalledTimes(2));
    await act(async () => latest.resolve(result('최신 자동완성')));
    expect(await screen.findByText('최신 자동완성')).toBeInTheDocument();
    await act(async () => outcome === 'success' ? old.resolve(result('늦은 자동완성')) : old.reject(new Error('늦은 실패')));
    expect(signal.aborted).toBe(true);
    expect(screen.getByText('최신 자동완성')).toBeInTheDocument();
    expect(screen.queryByText('늦은 자동완성')).not.toBeInTheDocument();
  });
});

describe('321 unknown physical quantity and source purchase-rule receipt purpose', () => {
  it('keeps unknown implicit package counts null and labels only explicit source purchase-rule repetitions', () => {
    const quote = { id: 'device-quote', variant_id: 'device-model', listing_id: 'device-source',
      listed_price: 417614, total_price: 417614, comparable_price: 417614, current_eligible: true,
      total_quantity: null, quantity_unit: null, received_package_count: null,
      received_package_count_scope: null, per_item: null, per_100ml: null };
    const product = (offer) => ({ id: 'prod-device', best_offer: offer,
      variants: [{ id: 'device-model', package_quantity: null, package_unit: null,
        listings: [{ id: 'device-source', source: 'original', title: 'DQ205PSVA / 20L', offers: [offer] }] }] });
    const normalized = getComparableOffers(product(quote))[0];
    expect(normalized.receivedPackageCount).toBeNull();
    expect(normalized.comparisonValue).toBeNull();
    expect(getOfferReceiptText(quote)).toBe('판매 수량 미확인 · 수령 패키지 미확인');
    for (const [count, conditions, minimum] of [[3, { buy_quantity: 2, free_quantity: 1 }, 2], [2, {}, 2]]) {
      const conditional = { ...quote, promotion_conditions: conditions, minimum_quantity: minimum,
        received_package_count: count, received_package_count_scope: 'source_purchase_rule_package_repetitions' };
      const text = getOfferConditionText(conditional);
      expect(text).toContain(`구매 조건 수령 단위 ${count}`);
      expect(text).toContain('물리 패키지 수량 미확인');
      expect(text).not.toMatch(/수령 패키지 [23]|수령 [23]개|20L 수령/);
      expect(getOfferUnitPrice(conditional)).toBeNull();
      expect(getComparableOffers(product(conditional))[0]).toMatchObject({ receivedPackageCount: count,
        receivedPackageCountScope: 'source_purchase_rule_package_repetitions', comparisonValue: null });
      expect(getOfferReceiptText(conditional, { receiptValid: false })).toContain('구매 조건 수령 단위 미확인');
    }
    expect(getOfferReceiptText({ ...quote, total_quantity: 200, quantity_unit: 'g', received_package_count: 1 }))
      .toBe('수령 200g · 수령 패키지 1');
  });
});

describe('246 declared vector receipt purpose', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.clearAllMocks(); });
  it('renders declared component totals without turning the complete-vector repetition into physical packages', async () => {
    const components = ['백열무김치', '동치미'].map(identity => ({ identity, presentation: null,
      quantity: 1200, unit: 'g', count: null, amount_scope: 'declared_component_total' }));
    const offer = { id: 'vector-quote', variant_id: 'vector-spec', listing_id: 'vector-source',
      listed_price: 21990, total_price: 21990, comparable_price: 21990, total_quantity: 1,
      quantity_unit: '세트', bundle_count: 1, received_package_count: 1, per_item: 21990,
      per_100g: null, current_eligible: true, minimum_quantity: 1,
      membership_required: false, coupon_required: false, promotion_conditions: {},
      quantity_basis: 'reviewed_source_component_vector_v1',
      scalar_basis: 'one_complete_declared_vector_not_piece_count',
      received_package_count_scope: 'complete_declared_vector' };
    const product = { id: 'prod-spec', public_product_id: 'prod-spec', name: '종가 백열무김치 1.2kg & 동치미 1.2kg',
      best_offer: offer, variants: [{ id: 'vector-spec', name: '원래 선언 구성', display_unit: '원래 선언 구성',
        package_quantity: 1, package_unit: '세트', bundle_count: 1, quantity_components: components,
        listings: [{ id: 'vector-source', source: 'costco', title: '원래 선언 구성', offers: [offer] }] }] };
    useStore.setState({ isLoggedIn: false, toasts: [] }); api.getJson.mockResolvedValue({ data: null });
    render(<ProductDetailModal product={product} mode="preview" onClose={vi.fn()} />);
    expect(screen.getAllByText(/선언된 전체 구성 ×1.*물리 패키지 수량 미확인/).length).toBeGreaterThan(0);
    const facts = screen.getByLabelText('선택 규격 구성');
    expect(facts).toHaveTextContent('백열무김치 · 1200g · 수량 미확인');
    expect(facts).toHaveTextContent('동치미 · 1200g · 수량 미확인');
    expect(screen.queryByText(/수령 패키지 1|2400g|원\/100g|100g당/)).not.toBeInTheDocument();
    const rows = getComparableOffers(product);
    expect(rows[0]).toMatchObject({ receivedPackageCountScope: 'complete_declared_vector',
      quantityBasis: 'reviewed_source_component_vector_v1', quantityComponents: components });
    expect(getOfferUnitPrice(offer, components)).toBeNull();
    const { quantity_basis, scalar_basis, received_package_count_scope, ...legacyOffer } = offer;
    const immutableContext = { ...legacyOffer, quantity_components: components };
    expect(getOfferConditionText(immutableContext)).toContain('물리 패키지 수량 미확인');
    expect(getOfferConditionText(immutableContext)).not.toContain('수령 패키지 1');
    // A plain 세트 unit supplies no independent component/purpose evidence.
    expect(getOfferReceiptText(legacyOffer)).toBe('수령 1세트 · 수령 패키지 1');
    expect(immutableContext).not.toHaveProperty('quantity_basis');
    cleanup();
    vi.stubGlobal('fetch', vi.fn(async path => ({ ok: true, json: async () => ({ data:
      String(path) === '/api/products/prod-spec' ? product : String(path).includes('price-history')
        ? [{ ...offer, price: 21990, date: '2026-10-01' }] : [] }) })));
    render(<MemoryRouter initialEntries={['/price/prod-spec']}><Routes><Route path="/price/:id" element={<PricePage />} /></Routes></MemoryRouter>);
    await screen.findByLabelText('선택 규격 구성');
    expect(screen.getAllByText(/선언된 전체 구성 ×1.*물리 패키지 수량 미확인/).length).toBeGreaterThan(0);
    fireEvent.click(await screen.findByText('관측별 구매 조건'));
    expect(screen.getAllByText(/선언된 전체 구성 ×1.*물리 패키지 수량 미확인/).length).toBeGreaterThan(1);
    expect(screen.queryByText(/수령 패키지 1|2400g|100g당/)).not.toBeInTheDocument();
    expect(product.variants[0].quantity_components).toEqual(components);
    expect(offer).toMatchObject({ id: 'vector-quote', listed_price: 21990, received_package_count: 1 });
  });
});

describe('247 homogeneous measured vector consumers', () => {
  afterEach(() => { cleanup(); vi.clearAllMocks(); });
  const vectorProduct = (unit) => {
    const components = (quantity) => [{ quantity: 50, unit, count: 1, identity: '확인된 동종 내용물', presentation: '' },
      { quantity: quantity - 50, unit, count: 1, identity: '확인된 동종 내용물', presentation: '리필' }];
    const product = { id: 'prod-homogeneous', public_product_id: 'prod-homogeneous', name: '확인된 서로 다른 포장',
      variants: [['a',1850,2,7400,200],['b',4000,1,6000,150]].map(([key,measure,received,spend,rate]) => ({
        id: `homogeneous-${key}`, name: `동종 구성-${key}`, package_quantity: 1, package_unit: '세트', bundle_count: 1,
        quantity_components: components(measure), listings: [{ id: `homogeneous-source-${key}`, source: key, title: `동종 구성-${key}`,
          offers: [{ id: `homogeneous-quote-${key}`, listed_price: spend, total_price: spend, comparable_price: spend,
            total_quantity: received, quantity_unit: '세트', bundle_count: 1, received_package_count: received,
            per_item: spend / received, per_100g: unit === 'g' ? rate : null, per_100ml: unit === 'ml' ? rate : null,
            quantity_basis: 'reviewed_homogeneous_contents', scalar_basis: 'one_complete_declared_vector_not_piece_count',
            received_package_count_scope: 'complete_declared_vector', pricing_measure_quantity: measure * received,
            pricing_measure_unit: unit, pricing_measure_basis: 'reviewed_homogeneous_contents',
            current_eligible: true, offer_state: 'active', minimum_quantity: 1, membership_required: false,
            coupon_required: false, promotion_conditions: {} }] }] })) };
    return selectProductOffer(product, { variantId: 'homogeneous-a' });
  };
  it.each(['g','ml'])('preserves received %s measure once and compares its proven dimensional rate across complete-vector amounts', (unit) => {
    const product = vectorProduct(unit), offer = product.selected_offer;
    expect(getOfferReceiptText(offer)).toContain(`동종 구성 총 내용량 3700${unit}`);
    expect(getOfferReceiptText(offer)).not.toContain(`7400${unit}`);
    expect(getOfferReceiptText(offer)).toContain('선언된 전체 구성 ×2 · 물리 패키지 수량 미확인');
    expect(getOfferReceiptText(offer)).not.toContain('수령 패키지 2');
    const rows = getComparableOffers(product);
    expect(rows.map(row => row.offerId)).toEqual(['homogeneous-quote-b','homogeneous-quote-a']);
    expect(rows[0]).toMatchObject({ comparisonValue: 150, comparisonBasis: `100${unit}`,
      pricingMeasureQuantity: 4000, pricingMeasureUnit: unit, pricingMeasureBasis: 'reviewed_homogeneous_contents' });
    const payload = buildCartPayload(product);
    expect(payload).toMatchObject({ product_id: 'prod-homogeneous', variant_id: 'homogeneous-a',
      listing_id: 'homogeneous-source-a', offer_id: 'homogeneous-quote-a', item_price: 7400,
      quoted_offer: { total_quantity: 2, quantity_unit: '세트', received_package_count: 2,
        pricing_measure_quantity: 3700, pricing_measure_unit: unit, pricing_measure_basis: 'reviewed_homogeneous_contents' } });
    expect(payload.quoted_offer.quantity_components).toEqual(product.variants[0].quantity_components);
    expect(product.variants[0].listings[0].offers[0]).not.toHaveProperty('quantity_components');
    const history = [{ ...offer, price: 7000, comparable_price: 7000, variant_id: 'homogeneous-a', date: '2026-09-01' },
      { ...offer, price: 1000, comparable_price: 1000, pricing_measure_quantity: 3850, variant_id: 'homogeneous-a', date: '2026-09-02' },
      { ...offer, price: 500, comparable_price: 500, pricing_measure_basis: null, variant_id: 'homogeneous-a', date: '2026-09-03' }];
    expect(getPriceHistorySummary(product, history)).toMatchObject({ min: 7000, avg: 7000, max: 7000, comparableCount: 1 });
    expect(getPriceHistorySummary(product, history).history.map(row=>row.price)).toEqual([7000,1000,500]);
    for (const change of [{ current_eligible: false }, { comparable_price: null },
      { quantity_comparison_reason: 'heterogeneous_contents_allocation_unverified' }]) {
      const held = { ...product, variants: product.variants.map(v => ({ ...v, listings: v.listings.map(l => ({ ...l,
        offers: l.offers.map(o => ({ ...o, ...change })) })) })) };
      expect(getComparableOffers(held).every(row => row.comparisonValue == null)).toBe(true);
    }
    const unknown = [{ quantity: 50, unit, count: null, identity: '확인되지 않은 구성', presentation: '' }];
    expect(getOfferUnitPrice(offer, unknown)).toBeNull();
    expect(getOfferUnitPrice({ ...offer, pricing_measure_quantity: null }).unit).toBe('1세트');
    expect(getOfferUnitPrice({ ...offer, pricing_measure_unit: unit === 'g' ? 'ml' : 'g' }).unit).toBe('1세트');
  });
  it('displays750매 as typed contents while retaining whole-vector money and requiring the same sheet receipt', () => {
    const product = vectorProduct('매');
    const variant = product.variants[0], offer = variant.listings[0].offers[0];
    variant.quantity_components = [{ quantity: 15, unit: '매', count: 20, identity: '동종 건티슈', presentation: '' },
      { quantity: 150, unit: '매', count: 3, identity: '동종 건티슈', presentation: '' }];
    Object.assign(offer, { total_quantity: 1, received_package_count: 1, pricing_measure_quantity: 750,
      per_item: 7400, per_100g: null, per_100ml: null });
    variant.listings.push({ id: 'same-sheet-source', source: 'other', title: '동일750매 전체 구성',
      offers: [{ ...offer, id: 'same-sheet-quote', listed_price: 6000, total_price: 6000, comparable_price: 6000, per_item: 6000 }] });
    const selected = selectProductOffer(product, { variantId: variant.id });
    expect(getOfferReceiptText(selected.selected_offer)).toContain('동종 구성 총 내용량 750매');
    expect(getOfferReceiptText(selected.selected_offer)).not.toMatch(/750g|750ml|수령 패키지 1/);
    expect(getOfferUnitPrice(selected.selected_offer, variant.quantity_components)).toEqual({ price: 7400, unit: '1세트' });
    const rows = getComparableOffers(selected);
    expect(rows.find(row=>row.offerId==='same-sheet-quote')).toMatchObject({ comparisonValue: 6000, comparisonBasis: '1세트' });
    expect(rows.find(row=>row.offerId==='homogeneous-quote-b').comparisonValue).toBeNull();
    variant.listings[1].offers[0].minimum_quantity = 2;
    expect(getComparableOffers(selectProductOffer(product,{variantId:variant.id})).find(row=>row.offerId==='same-sheet-quote').comparisonValue).toBeNull();
  });
  it('keeps old guest selections unchanged and does not infer reviewed purpose from a set label or guessed totals', () => {
    const product = vectorProduct('g');
    const old = { product_id: product.id, variant_id: 'old-variant', listing_id: 'old-listing',
      offer_id: 'old-offer', price: 7400, quoted_offer: { total_quantity: 1, quantity_unit: '세트', per_item: 7400 } };
    const bytes = JSON.stringify(old);
    expect(() => buildCartPayload(product, { variantId: old.variant_id,
      listingId: old.listing_id, offerId: old.offer_id })).toThrow();
    expect(JSON.stringify(old)).toBe(bytes);
    const quote = { ...product.selected_offer, quantity_basis: null, scalar_basis: null,
      received_package_count_scope: null, quantity_components: [] };
    expect(getOfferReceiptText(quote)).toContain('수령 패키지 2');
    expect(getOfferReceiptText(quote)).not.toContain('동종 구성 총 내용량');
  });
});

describe('248 validated linear receipt consumers', () => {
  afterEach(() => { cleanup(); vi.clearAllMocks(); });
  const linearProduct = () => {
    const offer = { id: 'linear-observation', variant_id: 'linear-spec', listing_id: 'linear-source',
      listed_price: 6000, total_price: 12000, comparable_price: 12000, total_quantity: 360, quantity_unit: 'm',
      bundle_count: 3, received_package_count: 3, per_100m: 3333, per_item: null,
      per_100g: null, per_100ml: null, current_eligible: true, offer_state: 'active', minimum_quantity: 2,
      membership_required: true, coupon_required: false, promotion_type: 'buy_x_get_y',
      promotion_conditions: { buy_quantity: 2, free_quantity: 1, condition_text: '2+1' },
      quantity_basis: 'reviewed_declared_linear_contents',
      scalar_basis: 'declared_linear_contents_not_physical_dimensions',
      received_package_count_scope: 'declared_linear_package_repetitions',
      pricing_measure_quantity: 360, pricing_measure_unit: 'm', pricing_measure_basis: 'reviewed_declared_linear_contents' };
    const product = { id: 'prod-linear', public_product_id: 'prod-linear', name: '검수된 선형 내용물', best_offer: offer,
      variants: [{ id: 'linear-spec', name: '40m×3 선언 구성', display_unit: '40m×3 선언 구성',
        package_quantity: 40, package_unit: 'm', bundle_count: 3,
        listings: [{ id: 'linear-source', source: 'original', title: '40m×3 선언 구성', offers: [offer] }] }] };
    return selectProductOffer(product, { variantId: 'linear-spec', listingId: 'linear-source', offerId: offer.id });
  };
  it('preserves confirmed received360m once and computes only compatible selected linear historical statistics', () => {
    const product = linearProduct(), offer = product.selected_offer;
    expect(getOfferUnitPrice(offer)).toEqual({ price: 3333, unit: '100m' });
    expect(getOfferReceiptText(offer)).toBe('출처 조건 계산: 선형 내용량 360m · 출처 조건 계산: 선택 선형 구성 ×3 · 물리 패키지 수량 미확인');
    expect(getOfferConditionText(offer)).toContain('최소 구매 2');
    expect(getOfferConditionText(offer)).toContain('구매 2');
    expect(getOfferConditionText(offer)).toContain('추가 증정 1');
    expect(getOfferReceiptText(offer)).not.toMatch(/1080m|수령 패키지 3/);
    const history = [
      { ...offer, id: 'prior-same-receipt', price: 10000, comparable_price: 10000, date: '2026-09-01', is_latest: false, current_eligible: false },
      { ...offer, id: 'prior-other-minimum', price: 2000, comparable_price: 2000, minimum_quantity: 1, date: '2026-09-02' },
      { ...offer, id: 'prior-other-length', price: 3000, comparable_price: 3000, total_quantity: 120, pricing_measure_quantity: 120, date: '2026-09-03' },
      { ...offer, id: 'prior-without-proof', price: 1000, comparable_price: 1000, quantity_basis: null, date: '2026-09-04' },
    ];
    const result = getPriceHistorySummary(product, history);
    expect(result).toMatchObject({ min: 10000, avg: 10000, max: 10000, comparableCount: 1 });
    expect(result.history.map(row => row.price)).toEqual([10000,2000,3000,1000]);
    const payload = buildCartPayload(product);
    expect(payload).toMatchObject({ product_id: 'prod-linear', variant_id: 'linear-spec', listing_id: 'linear-source',
      offer_id: 'linear-observation', item_price: 12000, quoted_offer: { per_100m: 3333,
        pricing_measure_quantity: 360, pricing_measure_unit: 'm', pricing_measure_basis: 'reviewed_declared_linear_contents',
        total_quantity: 360, received_package_count: 3, received_package_count_scope: 'declared_linear_package_repetitions' } });
    expect(product.variants[0].package_quantity).toBe(40);
    expect(getComparableOffers(product)[0]).toMatchObject({ comparisonValue: 3333, comparisonBasis: '100m' });
  });
  it('holds unproved physical-dimension m rates, mismatched proof and obsolete saved context without reviving statistics', () => {
    const product = linearProduct(), original = product.selected_offer;
    for (const change of [{ quantity_basis: null }, { scalar_basis: null }, { received_package_count_scope: null },
      { pricing_measure_basis: null }, { pricing_measure_quantity: null }, { pricing_measure_quantity: 1080 },
      { pricing_measure_unit: 'g' }, { received_package_count: 0 },
      { quantity_comparison_reason: 'quantity_evidence_unverified' }]) {
      const held = { ...original, ...change };
      expect(getOfferUnitPrice(held)).toBeNull();
      expect(getOfferReceiptText(held)).not.toContain('수령 패키지');
      const noProof = { ...product, selected_offer: held, best_offer: held,
        variants: product.variants.map(v=>({ ...v, listings: v.listings.map(l=>({ ...l, offers: [held] })) })) };
      expect(getComparableOffers(noProof).every(row=>row.comparisonValue == null)).toBe(true);
      expect(getPriceHistorySummary(noProof, [{ ...held, price: 12000, date: '2026-09-01' }]))
        .toMatchObject({ min: null, avg: null, max: null, comparableCount: 0 });
    }
    const old = { product_id: product.id, variant_id: 'linear-spec', listing_id: 'linear-source',
      offer_id: original.id, price: 12000, quantity: 1, saved_receipt_valid: false,
      saved_receipt_reason: 'receipt_basis_revised', offer_context: { total_quantity: 360, quantity_unit: 'm', per_100m: 3333 } };
    const bytes = JSON.stringify(old);
    expect(getCartQuotePresentation(old).canDisplayUnitPrice).toBe(false);
    expect(getSavedReceiptHoldText(old)).toContain('다시 선택');
    expect(getOfferReceiptText(old.offer_context, { receiptValid: false })).toContain('검증 미확인');
    expect(JSON.stringify(old)).toBe(bytes);
    const expired = { ...product, variants: product.variants.map(v=>({ ...v, listings: v.listings.map(l=>({ ...l,
      offers: [{ ...original, current_eligible: false, availability_reason: 'expired' }] })) })) };
    expect(getComparableOffers(expired)).toEqual([]);
  });
  it('renders linear source contents and transaction repetitions separately from physical packages in the actual Modal', () => {
    useStore.setState({ isLoggedIn: false, toasts: [] }); api.getJson.mockResolvedValue({ data: null });
    const product = linearProduct();
    product.variants[0].listings.push({ id: 'second-linear-source', source: 'other', title: 'same linear receipt',
      offers: [{ ...product.selected_offer, id: 'second-linear-quote', listing_id: 'second-linear-source',
        total_price: 10800, comparable_price: 10800, per_100m: 3000 }] });
    render(<ProductDetailModal product={product} mode="preview" onClose={vi.fn()} />);
    expect(screen.getAllByText(/선형 내용량 360m.*선택 선형 구성 ×3.*물리 패키지 수량 미확인/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/수령 패키지 3|1080m|원\/100g|원\/100ml/)).not.toBeInTheDocument();
    const comparisonTable = screen.getByRole('heading', { name: '🏬 판매처별 규격·가격' }).parentElement;
    expect(comparisonTable).toHaveTextContent('선형 내용량 360m');
    expect(comparisonTable).not.toHaveTextContent('선형 판매 내용량 검증 미확인');
  });

  it('does not trust an old persisted true receipt flag without explicit linear proof', () => {
    const product = linearProduct(), original = product.selected_offer;
    const old = { product_id: product.id, variant_id: 'linear-spec', listing_id: 'linear-source',
      offer_id: original.id, price: 12000, quantity: 1, saved_receipt_valid: true,
      offer_context: { ...original, quantity_basis: null } };
    const bytes = JSON.stringify(old);
    expect(getCartQuotePresentation(old)).toMatchObject({ canDisplayUnitPrice: false, confirmedPurchase: false });
    expect(getSavedReceiptHoldText(old)).toContain('다시 선택');
    expect(JSON.stringify(old)).toBe(bytes);
  });
});

describe('249 saved measured observation rate presentation', () => {
  afterEach(() => { cleanup(); vi.clearAllMocks(); });
  it.each(['ml','m'])('preserves the known saved %s observation rate through Cart without implying current purchase eligibility', (unit) => {
    const linear = unit === 'm', purpose = linear ? 'reviewed_declared_linear_contents' : 'reviewed_homogeneous_contents';
    const quote = { total_price: linear ? 2380 : 14990, comparable_price: linear ? 2380 : 14990,
      total_quantity: linear ? 120 : 1, quantity_unit: linear ? 'm' : '세트', received_package_count: 1,
      quantity_basis: purpose, scalar_basis: linear ? 'declared_linear_contents_not_physical_dimensions' : 'one_complete_declared_vector_not_piece_count',
      received_package_count_scope: linear ? 'declared_linear_package_repetitions' : 'complete_declared_vector',
      pricing_measure_quantity: linear ? 120 : 4700, pricing_measure_unit: unit, pricing_measure_basis: purpose,
      quantity_components: linear ? [] : [{ quantity: 700, unit: 'ml', count: 1, identity: '선택 주방세제', presentation: '' },
        { quantity: 4000, unit: 'ml', count: 1, identity: '선택 주방세제', presentation: '' }],
      per_100m: linear ? 1983 : null, per_100ml: linear ? null : 319, per_item: linear ? null : 14990,
      current_eligible: true, minimum_quantity: null, membership_required: null, coupon_required: null };
    const item = { id: 'selected-observation', product_id: 'prod-saved-measure', variant_id: 'original-variant',
      listing_id: 'original-source', offer_id: 'original-event', price: quote.total_price, quantity: 1,
      name: '원래 선택', saved_receipt_valid: true, offer_context: quote };
    const bytes = JSON.stringify(item); useCartStore.setState({ items: [item] });
    render(<MemoryRouter><ShoppingListPanel /></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: '장바구니 열기' }));
    expect(screen.getByText(`관측 단위가 · 100${unit}당 ${linear ? '1,983' : '319'}원`)).toBeInTheDocument();
    expect(screen.getByText(/현재 결제 금액·구매 가능 여부 미확인.*회원·쿠폰 이용 조건 미확인/)).toBeInTheDocument();
    expect(screen.getByText(`저장 관측 금액 ${linear ? '2,380' : '14,990'}원`)).toBeInTheDocument();
    expect(screen.queryByText(/확인된 구매 금액|수령 패키지 1/)).not.toBeInTheDocument();
    expect(JSON.stringify(useCartStore.getState().items[0])).toBe(bytes);
    cleanup();
    useCartStore.setState({ items: [{ ...item, saved_receipt_valid: false, saved_receipt_reason: 'selected_specification_revised' }] });
    render(<MemoryRouter><ShoppingListPanel /></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: '장바구니 열기' }));
    expect(screen.queryByText(/관측 단위가/)).not.toBeInTheDocument();
    expect(screen.getByText(/규격 확인·다시 선택 필요/)).toBeInTheDocument();
    cleanup();
    useCartStore.setState({ items: [{ ...item, offer_context: { ...quote, comparable_price: null } }] });
    render(<MemoryRouter><ShoppingListPanel /></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: '장바구니 열기' }));
    expect(screen.queryByText(/관측 단위가/)).not.toBeInTheDocument();
    expect(screen.queryByText('0원', { exact: true })).not.toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });
});

describe('256 observation-time promotion receipt validity', () => {
  afterEach(() => { cleanup(); vi.clearAllMocks(); vi.unstubAllGlobals(); });
  const sourceQuote = (reason) => ({ id: 'original-offer', variant_id: 'var-original', listing_id: 'listing-original',
    listed_price: 8980, total_price: 17960, comparable_price: 17960, total_quantity: 1800, quantity_unit: 'g',
    per_100g: 998, received_package_count: 3, bundle_count: 1, minimum_quantity: 2,
    promotion_condition: '2+1', promotion_conditions: { buy_quantity: 2, free_quantity: 1 },
    membership_required: false, coupon_required: false, current_eligible: true, offer_state: 'active',
    valid_to: '2026-09-01T15:00:00Z', crawled_at: '2026-09-02T13:39:42Z',
    availability_reason: 'expired', observation_receipt_eligible: false, observation_receipt_reason: reason });
  const sourceProduct = (quote) => ({ id: 'prod-temporal', public_product_id: 'prod-temporal', name: '실제 원래 소스',
    best_offer: quote, selected_variant_id: 'var-original', selected_offer: quote,
    variants: [{ id: 'var-original', display_unit: '600g', package_quantity: 600, package_unit: 'g', bundle_count: 1,
      listings: [{ id: 'listing-original', source: 'homeplus', title: '원래 소스600g', offers: [quote] }] }] });

  it.each(['promotion_observation_outside_period', 'promotion_observation_validity_unconfirmed'])
    ('holds stale derived receipt for %s while preserving the source quote, rule, history and saved tuple', async (reason) => {
      const quote = sourceQuote(reason); const product = sourceProduct(quote);
      const original = JSON.stringify(quote);
      const history = [{ ...quote, date: quote.crawled_at, price: 8980 }];
      expect(getOfferUnitPrice(quote)).toBeNull();
      expect(getVariantBestOffer(product.variants[0])).toBeNull();
      expect(getComparableOffers(product)).toEqual([]);
      expect(getPriceHistorySummary(product, history)).toMatchObject({ min: null, avg: null, max: null,
        comparableCount: 0, history: [{ price: 8980, total_quantity: 1800, observationReceiptReason: reason }] });
      const conditions = getOfferConditionText(quote);
      expect(conditions).toContain('관측 당시 행사 적용 미확인');
      expect(conditions).toContain('출처 행사 규칙: 최소 구매 2');
      expect(conditions).toContain('출처 행사 규칙: 구매 2');
      expect(conditions).toContain('출처 행사 규칙: 추가 증정 1');
      expect(conditions).toContain('출처 행사 기간');
      expect(conditions).not.toMatch(/수령 1800g|수령 패키지 3/);
      const item = { id: 'saved-temporal', product_id: 'prod-temporal', variant_id: 'var-original', listing_id: 'listing-original',
        offer_id: 'original-offer', name: '원래 소스600g', unit: '600g', price: 17960, price_known: true, quantity: 1,
        saved_receipt_valid: true, offer_context: quote };
      expect(getCartQuotePresentation(item)).toMatchObject({ confirmedPurchase: false, canDisplayUnitPrice: false,
        observedReceipt: null, amountLabel: '저장된 행사 계산 금액 (적용 미확인)' });
      const { observation_receipt_eligible, observation_receipt_reason, ...oldContext } = quote;
      expect(getCartQuotePresentation({ ...item, offer_context: oldContext, saved_receipt_reason: reason }))
        .toMatchObject({ confirmedPurchase: false, canDisplayUnitPrice: false, observedReceipt: null });
      useStore.setState({ isLoggedIn: false, toasts: [] }); useCartStore.setState({ items: [item] });
      render(<MemoryRouter><ShoppingListPanel /></MemoryRouter>);
      fireEvent.click(screen.getByRole('button', { name: '장바구니 열기' }));
      expect(screen.getByText('저장된 행사 계산 금액 (적용 미확인) 17,960원')).toBeInTheDocument();
      expect(screen.getByText(/출처 표시 가격 8,980원/)).toBeInTheDocument();
      expect(screen.queryByText(/100g당|수령 1800g|수령 패키지 3/)).not.toBeInTheDocument();
      expect(useCartStore.getState().items[0]).toEqual(item);
      cleanup();
      const writeText = vi.fn().mockResolvedValue(); vi.stubGlobal('navigator', { clipboard: { writeText } });
      api.getJson.mockResolvedValue({ data: null });
      render(<ProductDetailModal product={{ ...product, price_history: history }} mode="preview" onClose={vi.fn()} />);
      expect(screen.getAllByText(/관측 당시 행사 적용 미확인/).length).toBeGreaterThan(0);
      expect(screen.queryByText(/관측 거래 금액 17,960|실제 거래 금액 17,960|수령 1800g|수령 패키지 3/)).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: '공유' }));
      await waitFor(() => expect(writeText).toHaveBeenCalled());
      expect(writeText.mock.calls[0][0]).toContain('관측 표시 가격 8,980원');
      expect(writeText.mock.calls[0][0]).not.toContain('17,960');
      cleanup(); vi.unstubAllGlobals();
      vi.stubGlobal('fetch', vi.fn(async path => ({ ok: true, json: async () => ({ data:
        String(path) === '/api/products/prod-temporal' ? product : String(path).includes('price-history') ? history : [] }) })));
      render(<MemoryRouter initialEntries={['/price/prod-temporal']}><Routes><Route path="/price/:id" element={<PricePage />} /></Routes></MemoryRouter>);
      await screen.findByTestId('selected-history');
      expect(screen.getAllByText(/관측 당시 행사 적용 미확인/).length).toBeGreaterThan(0);
      expect(screen.getByTestId('selected-history')).toHaveTextContent('8980');
      fireEvent.click(screen.getByText('관측별 구매 조건'));
      expect(screen.getAllByText(/출처 행사 규칙: 구매 2/).length).toBeGreaterThan(0);
      expect(screen.queryByText(/관측 거래 금액 17,960|실제 거래 금액 17,960|수령 1800g|수령 패키지 3/)).not.toBeInTheDocument();
      expect(api.post).not.toHaveBeenCalled(); expect(JSON.stringify(quote)).toBe(original);
    });

  it('labels an ordinary historical quote as observed rather than actual buyer payment in both history renderers', async () => {
    const quote = { ...sourceQuote(null), listed_price: 11860, total_price: 11860, comparable_price: 11860,
      total_quantity: 1700, quantity_unit: 'ml', per_100g: null, per_100ml: 698,
      received_package_count: 1, minimum_quantity: null, promotion_condition: null, promotion_conditions: {},
      promotion_type: 'final_price', observation_receipt_eligible: null, observation_receipt_reason: null,
      current_eligible: false, membership_required: null, coupon_required: null };
    const original = JSON.stringify(quote); const product = sourceProduct(quote);
    const history = [{ ...quote, date: quote.crawled_at, price: quote.listed_price }];
    useStore.setState({ isLoggedIn: false, toasts: [] }); api.getJson.mockResolvedValue({ data: null });
    render(<ProductDetailModal product={{ ...product, price_history: history }} mode="preview" onClose={vi.fn()} />);
    expect(screen.getAllByText(/관측 거래 금액 11,860원/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/실제 거래 금액/)).not.toBeInTheDocument();
    cleanup();
    vi.stubGlobal('fetch', vi.fn(async path => ({ ok: true, json: async () => ({ data:
      String(path) === '/api/products/prod-temporal' ? product : String(path).includes('price-history') ? history : [] }) })));
    render(<MemoryRouter initialEntries={['/price/prod-temporal']}><Routes><Route path="/price/:id" element={<PricePage />} /></Routes></MemoryRouter>);
    await screen.findByTestId('selected-history'); fireEvent.click(screen.getByText('관측별 구매 조건'));
    expect(screen.getAllByText(/관측 거래 금액 11,860원/).length).toBeGreaterThan(0);
    expect(screen.getByTestId('selected-history')).toHaveTextContent('11860');
    expect(screen.queryByText(/실제 거래 금액/)).not.toBeInTheDocument();
    expect(JSON.stringify(quote)).toBe(original); expect(api.post).not.toHaveBeenCalled();
  });

  it('retains a confirmed within-period historical receipt and compatible statistics after the source period expires today', async () => {
    const quote = { ...sourceQuote(null), observation_receipt_eligible: true, observation_receipt_reason: null,
      crawled_at: '2026-09-01T13:00:00Z', current_eligible: false, is_latest: false };
    const product = sourceProduct(quote);
    const history = [{ ...quote, date: quote.crawled_at, price: 8980 }];
    expect(getOfferReceiptText(quote)).toBe('출처 조건 계산: 수령 1800g · 출처 조건 계산: 수령 패키지 3');
    expect(getOfferConditionText(quote)).not.toContain('관측 당시 행사 적용 미확인');
    expect(getOfferUnitPrice(quote)).toEqual({ price: 998, unit: '100g' });
    expect(getPriceHistorySummary(product, history)).toMatchObject({ comparableCount: 1,
      min: 17960, avg: 17960, max: 17960, history: [{ price: 8980 }] });
    expect(getCartQuotePresentation({ product_id: product.id, variant_id: 'var-original', listing_id: 'listing-original',
      offer_id: quote.id, price: 17960, offer_context: quote, saved_receipt_valid: true })).toMatchObject({
      confirmedPurchase: false, canDisplayUnitPrice: true, amountLabel: '저장된 출처 조건 계산 금액' });
    useStore.setState({ isLoggedIn: false, toasts: [] }); api.getJson.mockResolvedValue({ data: null });
    render(<ProductDetailModal product={{ ...product, price_history: history }} mode="preview" onClose={vi.fn()} />);
    expect(screen.getAllByText(/출처 조건 계산 금액 17,960원/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/출처 조건 계산: 수령 1800g/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/관측 당시 행사 적용 미확인/)).not.toBeInTheDocument();
    expect(screen.queryByText(/실제 거래 금액 17,960|관측 거래 금액 17,960/)).not.toBeInTheDocument();
    cleanup();
    vi.stubGlobal('fetch', vi.fn(async path => ({ ok: true, json: async () => ({ data:
      String(path) === '/api/products/prod-temporal' ? product : String(path).includes('price-history') ? history : [] }) })));
    render(<MemoryRouter initialEntries={['/price/prod-temporal']}><Routes><Route path="/price/:id" element={<PricePage />} /></Routes></MemoryRouter>);
    await screen.findByTestId('selected-history');
    fireEvent.click(screen.getByText('관측별 구매 조건'));
    expect(screen.getAllByText(/출처 조건 계산 금액 17,960원/).length).toBeGreaterThan(0);
    expect(screen.getByTestId('selected-history')).toHaveTextContent('8980');
    expect(screen.queryByText(/관측 당시 행사 적용 미확인/)).not.toBeInTheDocument();
    expect(screen.queryByText(/실제 거래 금액 17,960|관측 거래 금액 17,960/)).not.toBeInTheDocument();
  });
});
