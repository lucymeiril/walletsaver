import { render, screen, waitFor, cleanup, fireEvent, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import MartPage from './MartPage';
import { api } from '../../services/api';

const session = vi.hoisted(() => ({ addToShoppingList: vi.fn(), addToast: vi.fn(),
  isLoggedIn: true, favorites: [], favoriteItems: {}, addFavorite: vi.fn(), removeFavorite: vi.fn(), setFavoriteRemoteId: vi.fn() }));

vi.mock('../../stores/appStore', () => ({
  default: () => session,
}));
vi.mock('../../stores/cartStore', () => ({ default: selector => selector({ addItem: session.addToShoppingList }) }));
vi.mock('../../services/api', () => ({ api: { getJson: vi.fn(), post: vi.fn(), delete: vi.fn() } }));
vi.mock('../../components/ProductDetailModal', () => ({ default: ({ product, mode }) =>
  <div data-testid="mart-detail-selection" data-mode={mode}>{JSON.stringify({ product_id: product.product_id,
    variant_id: product.selected_variant_id, listing_id: product.selected_listing_id, offer_id: product.selected_offer_id })}</div> }));

function fetchJson(data) {
  return Promise.resolve({
    ok: true,
    json: () => Promise.resolve(data),
  });
}

describe('MartPage rendering', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    session.addToShoppingList.mockResolvedValue(true);
    session.favorites = []; session.favoriteItems = {};
    api.getJson.mockResolvedValue({ data: null });
    global.fetch = vi.fn((url) => {
      const href = String(url);
      if (href.includes('/api/marts/emart/promotions')) {
        return fetchJson({
          data: [
            {
              name: '테스트우유 1L',
              price: 1980,
              original_price: 2980,
              event_name: '신선식품 행사',
              unit: '1L',
            },
          ],
        });
      }
      if (href.includes('/api/marts/')) {
        return fetchJson({ data: [] });
      }
      if (href.includes('/api/products/search')) {
        return fetchJson({ data: [] });
      }
      return fetchJson({ data: null });
    });
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('does not crash when auto-opening a product from URL params', async () => {
    render(
      <MemoryRouter initialEntries={['/mart?mart=emart&product=테스트우유%201L']}>
        <MartPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText('테스트우유 1L')).toBeInTheDocument();
    });
    expect(screen.getByText('총 1개 상품')).toBeInTheDocument();
  });

  it('shows price observations without original-price or discount badges', async () => {
    global.fetch = vi.fn((url) => {
      const href = String(url);
      if (href.includes('/api/marts/emart/promotions')) {
        return fetchJson({
          data: [
            {
              name: '국산콩 두부 300g',
              price: 1980,
              original_price: null,
              discount_rate: null,
              record_label: '관측 가격',
              claim_status_label: '할인 여부 미확인',
              price_observation_only: true,
              has_discount_metadata: false,
              unit: '300g',
            },
          ],
        });
      }
      if (href.includes('/api/marts/')) return fetchJson({ data: [] });
      if (href.includes('/api/products/search')) return fetchJson({ data: [] });
      return fetchJson({ data: null });
    });

    render(
      <MemoryRouter initialEntries={['/mart?mart=emart']}>
        <MartPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText('국산콩 두부 300g')).toBeInTheDocument();
    });
    expect(screen.getAllByText('관측 가격').length).toBeGreaterThan(0);
    expect(screen.getByText('1,980', { exact: false })).toBeInTheDocument();
    expect(screen.queryByText(/-\d+%/)).not.toBeInTheDocument();
  });

  function sourceRow(source, price, grams, variant = source) {
    return { id: 'prod-source', product_id: 'prod-source', public_product_id: 'prod-source', name: '동일 상품',
      variant_id: `var-${variant}`, listing_id: `listing-${source}`, offer_id: `offer-${source}`, display_unit: `${grams}g`,
      event_name: '미확인 할인', best_offer: { id: `offer-${source}`, total_price: price, listed_price: price,
        comparable_price: price, total_quantity: grams, quantity_unit: 'g', per_100g: price * 100 / grams,
        received_package_count: 1, minimum_quantity: 2, membership_required: true, coupon_required: null,
        offer_state: 'active', current_eligible: true } };
  }
  function sources(emart, homeplus = []) {
    global.fetch = vi.fn(url => fetchJson({ data: String(url).includes('/emart/promotions') ? emart
      : String(url).includes('/homeplus/promotions') ? homeplus : [] }));
  }
  it('keeps the published selected tuple when opening actual linked detail and never creates an unknown zero display', async () => {
    const item = sourceRow('emart', 6000, 1000);
    sources([item, { ...sourceRow('emart', 0, 1000, 'unknown'), name: '가격 미확인', best_offer: { total_price: null, listed_price: null } }]);
    render(<MemoryRouter><MartPage /></MemoryRouter>);
    fireEvent.click(await screen.findByText('동일 상품', { exact: true }));
    expect(screen.getByTestId('mart-detail-selection')).toHaveAttribute('data-mode', 'product');
    expect(JSON.parse(screen.getByTestId('mart-detail-selection').textContent)).toEqual({ product_id: 'prod-source',
      variant_id: 'var-emart', listing_id: 'listing-emart', offer_id: 'offer-emart' });
    expect(screen.getByText('관측 가격 미확인')).toBeInTheDocument();
    expect(screen.queryByText('0원')).not.toBeInTheDocument();
    expect(screen.queryByText('미확인 할인')).not.toBeInTheDocument();
  });
  it('resolves the exact selected source for cart and wishlist and reports success only after storage acknowledgement', async () => {
    const row = sourceRow('emart', 6000, 1000); sources([row]);
    api.getJson.mockResolvedValue({ data: { id: row.product_id, public_product_id: row.product_id, name: row.name,
      best_offer: { comparable_price: 9999, variant_id: 'var-other' }, variants: [{ id: row.variant_id, display_unit: '1000g',
        listings: [{ id: row.listing_id, source: 'emart', offers: [row.best_offer] }] }] } });
    let cartAck; session.addToShoppingList.mockImplementation(() => new Promise(resolve => { cartAck = resolve; }));
    render(<MemoryRouter><MartPage /></MemoryRouter>);
    await screen.findByText('동일 상품', { exact: true });
    fireEvent.click(screen.getByTitle('장보기에 추가'));
    await waitFor(() => expect(session.addToShoppingList).toHaveBeenCalledWith(expect.objectContaining({
      product_id: row.product_id, variant_id: row.variant_id, listing_id: row.listing_id, offer_id: row.offer_id, item_price: 6000 })));
    expect(session.addToast).not.toHaveBeenCalled(); cartAck(false);
    await waitFor(() => expect(session.addToShoppingList).toHaveBeenCalledTimes(1));
    expect(session.addToast.mock.calls.some(call => call[1] === 'success')).toBe(false);
    let wishAck; api.post.mockImplementation(() => new Promise(resolve => { wishAck = resolve; }));
    fireEvent.click(screen.getByTitle('찜하기'));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/wishlist', expect.objectContaining({
      product_id: row.product_id, variant_id: row.variant_id, listing_id: row.listing_id, offer_id: row.offer_id, price_at_add: 6000 })));
    expect(session.addFavorite).not.toHaveBeenCalled();
    wishAck({ json: async () => ({ data: { id: 31 } }) });
    await waitFor(() => expect(session.setFavoriteRemoteId).toHaveBeenCalledWith('product:prod-source:var-emart:listing-emart', 31));
    expect(session.addToast.mock.calls.filter(call => call[1] === 'success')).toHaveLength(1);
  });
  it('compares the same explicit mass unit with visible conditions instead of ranking transaction totals', async () => {
    sources([sourceRow('emart', 6000, 1000)], [sourceRow('homeplus', 3000, 400)]);
    render(<MemoryRouter><MartPage /></MemoryRouter>); await screen.findByText('동일 상품', { exact: true });
    fireEvent.click(screen.getByText('⚖️ 마트별 비교'));
    const table = screen.getByRole('table');
    expect(within(table).getByText('600원/100g', { exact: false })).toBeInTheDocument();
    expect(within(table).getByText('750원/100g', { exact: false })).toBeInTheDocument();
    const badge = within(table).getByText('표시 조건 단위 최저');
    expect(badge.closest('td').textContent).toContain('6,000원');
    expect(badge.closest('td').textContent).toContain('회원 필요');
    expect(badge.closest('td').textContent).toContain('최소 구매 2');
  });
  it.each(['unknown', 'mixed'])('does not rank %s comparison bases by cheaper total money', async kind => {
    const a = sourceRow('emart', 6000, 1000), b = sourceRow('homeplus', 3000, 400);
    if (kind === 'unknown') for (const row of [a,b]) Object.assign(row.best_offer, { total_quantity: null, quantity_unit: null, per_100g: null });
    else Object.assign(b.best_offer, { quantity_unit: 'ml', per_100g: null, per_100ml: 750 });
    sources([a], [b]); render(<MemoryRouter><MartPage /></MemoryRouter>);
    await screen.findByText('동일 상품', { exact: true }); fireEvent.click(screen.getByText('⚖️ 마트별 비교'));
    expect(screen.queryByText('표시 조건 단위 최저')).not.toBeInTheDocument();
    expect(screen.queryByText('🏆')).not.toBeInTheDocument();
  });
});
