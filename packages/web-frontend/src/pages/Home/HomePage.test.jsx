import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import HomePage from './HomePage';

const state = vi.hoisted(() => ({
  addToast: vi.fn(), addItem: vi.fn(), openProductDetailModal: vi.fn(),
  getJson: vi.fn(), signal: () => undefined,
  setLocation: vi.fn(), setSavedLocation: vi.fn(), addRecentSearch: vi.fn(),
  setSelectedProduct: vi.fn(), addFavorite: vi.fn(), removeFavorite: vi.fn(),
  isFavorite: () => false, clearRecentSearches: vi.fn(), favorites: [], recentSearches: [],
}));
vi.mock('../../stores/appStore', () => ({ default: () => state }));
vi.mock('../../stores/cartStore', () => ({ default: selector => selector({ addItem: state.addItem }) }));
vi.mock('../../stores/modalStore', () => ({ default: () => ({ openProductDetailModal: state.openProductDetailModal }) }));
vi.mock('../../hooks/useAbortController', () => ({ default: () => state.signal }));
vi.mock('../../services/api', () => ({ api: { getJson: state.getJson } }));

const offer = { id: 'offer-selected', listed_price: 8200, total_price: 8200, comparable_price: 8200,
  current_eligible: true, is_latest: true, offer_state: 'active', promotion_type: 'final_price',
  promotion_conditions: {}, membership_required: null, coupon_required: null };
const detail = { id: 'prod-selected', public_product_id: 'prod-selected', name: '선택 색연필',
  best_offer: { ...offer, variant_id: 'var-selected', listing_id: 'listing-selected' },
  variants: [{ id: 'var-selected', display_unit: '판매 규격 미확인', listings: [{ id: 'listing-selected',
    source: 'emart', title: '선택 색연필', url: 'https://example.test/native-selected', offers: [offer] }] }] };
let item;

function mount() { return render(<MemoryRouter><HomePage /></MemoryRouter>); }
function cartButton() { return within(screen.getByText('선택 색연필').closest('[class*=martSaleCard]')).getByTitle('장보기에 추가'); }

beforeEach(() => {
  vi.clearAllMocks();
  item = { id: detail.id, product_id: detail.id, public_product_id: detail.id, name: detail.name,
    variant_id: 'var-selected', listing_id: 'listing-selected', offer_id: offer.id,
    sale: 8200, best_offer: { ...offer }, display_unit: '판매 규격 미확인' };
  state.getJson.mockResolvedValue({ data: detail });
  state.addItem.mockResolvedValue({});
  vi.stubGlobal('fetch', vi.fn(async url => ({ ok: true, json: async () => ({ data:
    String(url).includes('/marts/') ? [item] : String(url) === '/api/dashboard'
      ? { category_summary: [{ name: '식품', count: 5022 }], recent_products: [{ id: 'prod-unpriced', name: '가격 미확인 생수', cur: null }] }
      : [] }) })));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('Home source selection and truthful save outcome', () => {
  it('keeps loaded unknown-priced products visible without invented collection or aggregate statistics', async () => {
    mount();
    await screen.findByText('가격 미확인 생수');
    expect(screen.getByText('현재 가격 미확인')).toBeInTheDocument();
    expect(screen.getByText(/카테고리별 비교 통계 미확인/)).toBeInTheDocument();
    expect(screen.queryByText(/첫 가격 데이터를 수집/)).not.toBeInTheDocument();
    expect(screen.queryByText('0원')).not.toBeInTheDocument();
    fireEvent.click(screen.getByTitle('규격을 선택해 찜하기'));
    expect(state.openProductDetailModal).toHaveBeenCalledWith(expect.objectContaining({id:'prod-unpriced'}));
    expect(state.addFavorite).not.toHaveBeenCalled();
  });

  it('resolves the actual selected tuple and reports success only after acknowledged cart saving', async () => {
    let acknowledge;
    state.addItem.mockImplementation(() => new Promise(resolve => { acknowledge = resolve; }));
    mount(); await screen.findByText('선택 색연필');
    fireEvent.click(screen.getByText('선택 색연필'));
    await waitFor(() => expect(state.openProductDetailModal).toHaveBeenCalledWith(expect.objectContaining({
      selected_variant_id: 'var-selected', selected_listing_id: 'listing-selected', selected_offer_id: 'offer-selected',
    })));
    fireEvent.click(cartButton());
    await waitFor(() => expect(state.addItem).toHaveBeenCalledWith(expect.objectContaining({
      product_id: 'prod-selected', variant_id: 'var-selected', listing_id: 'listing-selected',
      offer_id: 'offer-selected', item_price: 8200, quantity: 1,
    })));
    expect(state.addToast).not.toHaveBeenCalled();
    acknowledge({});
    await waitFor(() => expect(state.addToast).toHaveBeenCalledWith(expect.any(String), 'success'));
  });

  it('rejects unconfirmed actual payment or changed source selection without a cart write or success toast', async () => {
    const held = { ...offer, total_price: null, comparable_price: null, current_eligible: false };
    state.getJson.mockResolvedValue({ data: { ...detail, best_offer: null,
      variants: [{ ...detail.variants[0], listings: [{ ...detail.variants[0].listings[0], offers: [held] }] }] } });
    mount(); await screen.findByText('선택 색연필'); fireEvent.click(cartButton());
    await waitFor(() => expect(state.addToast).toHaveBeenCalledWith(expect.stringContaining('실제 거래 금액'), 'error'));
    expect(state.addItem).not.toHaveBeenCalled();
    state.getJson.mockResolvedValue({ data: { ...detail, variants: [] } });
    fireEvent.click(cartButton());
    await waitFor(() => expect(state.addToast).toHaveBeenCalledWith(expect.stringContaining('거래가 변경'), 'error'));
    expect(state.addItem).not.toHaveBeenCalled();
    expect(state.addToast.mock.calls.some(([, kind]) => kind === 'success')).toBe(false);
  });
});
