import { beforeEach, afterEach, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import Prices from './Prices';
import { api } from '../../api/client';
vi.mock('../../api/client', () => ({ api: { getNormalizedPriceHistory: vi.fn(), getPriceHistory: vi.fn(), getTierConfig: vi.fn() } }));
const row = { public_product_id: 'prod-opaque', public_variant_id: 'var-opaque', public_source_listing_id: 'listing-opaque',
  public_offer_event_id: 'event-later', canonical_name: '원 식품', variant_name: '600g', source_name: 'Homeplus', source_record_key: 'native-123', source_title: '원 제목',
  display_unit: '600g', package_quantity: 600, package_unit: 'g', bundle_count: 1,
  observed_quote: 8980, price: 8980, original_price: null, source_quote_currency: null, quote_currency_status: 'source_unconfirmed',
  crawled_at: '2026-09-02T13:39:00+00:00', valid_to: '2026-09-01T15:00:00+00:00', offer_state: 'active', price_state: 'priced',
  promotion_type: 'buy_x_get_y', event_name: '2+1', promotion_conditions: { buy_quantity: 2, free_quantity: 1, source_quote_currency: null, source_minimum_purchase_quantity: 2 },
  observation_receipt_eligible: false, observation_receipt_reason: 'promotion_observation_outside_period', receipt_evaluation: 'not_evaluated_admin_history',
  recorded_price_per_100g: 998, variant_attributes: { source_fixed_contents: '600g' },
};
const envelope = items => ({ source_scope: 'admin_normalized_catalog', read_only: true, items, total: 26, total_pages: 2, page: 1, per_page: 25 });
beforeEach(() => {
  vi.clearAllMocks(); window.history.replaceState({}, '', '/prices?public_product_id=prod-opaque&public_variant_id=var-opaque&public_source_listing_id=listing-opaque');
  api.getNormalizedPriceHistory.mockResolvedValue(envelope([row]));
});
afterEach(cleanup);
it('separates source quote/currency/rule/observation from held receipt and recorded historical calculations', async () => {
  render(<Prices />);
  await screen.findByText('event-later');
  expect(api.getPriceHistory).not.toHaveBeenCalled(); expect(api.getTierConfig).not.toHaveBeenCalled();
  expect(screen.queryByText('티어 설정')).toBeNull();
  expect(screen.getByText('8,980 (통화 미명시)')).toBeTruthy();
  expect(screen.queryByText('8,980원')).toBeNull();
  expect(screen.queryByText('17,960원')).toBeNull();
  expect(screen.queryByText('0원')).toBeNull();
  expect(screen.getByText('2026-09-02T13:39:00+00:00')).toBeTruthy();
  expect(screen.getByText(/promotion_observation_outside_period/)).toBeTruthy();
  expect(screen.getByText('과거 저장 계산값 · 현재 구매·비교 단가 아님')).toBeTruthy();
  expect(screen.getByText('현재 출처 연결 규격 · 과거 관측별 규격·거래 수령량 아님')).toBeTruthy();
  expect(screen.getByText('현재 결제·적용 자격 미확인')).toBeTruthy();
  expect(screen.getByText('listing-opaque')).toBeTruthy();
  expect(screen.getByText('prod-opaque')).toBeTruthy();
  expect(api.getNormalizedPriceHistory).toHaveBeenCalledWith({ public_product_id: 'prod-opaque', public_variant_id: 'var-opaque', public_source_listing_id: 'listing-opaque', page: 1, per_page: 25 }, expect.any(Object));
});
it('preserves all selected-period pages and unknown quotes without substituting missing values or changing opaque filters', async () => {
  api.getNormalizedPriceHistory.mockResolvedValueOnce(envelope([{ ...row, observed_quote: null, price: 0, recorded_price_per_100g: null, observation_receipt_eligible: null }]));
  render(<Prices />);
  await screen.findByText('event-later');
  expect(screen.getByText('관측가 미확인')).toBeTruthy();
  expect(screen.getByText(/미평가 · 관리 이력/)).toBeTruthy();
  fireEvent.change(screen.getByLabelText('관측 시작일'), { target: { value: '2026-08-01' } });
  fireEvent.change(screen.getByLabelText('관측 종료일'), { target: { value: '2026-09-02' } });
  fireEvent.click(screen.getByText('이력 조회'));
  await waitFor(() => expect(api.getNormalizedPriceHistory).toHaveBeenLastCalledWith(expect.objectContaining({ date_from: '2026-08-01', date_to: '2026-09-02', public_variant_id: 'var-opaque', page: 1 }), expect.any(Object)));
  fireEvent.click(screen.getByText('다음'));
  await waitFor(() => expect(api.getNormalizedPriceHistory).toHaveBeenLastCalledWith(expect.objectContaining({ date_from: '2026-08-01', date_to: '2026-09-02', public_source_listing_id: 'listing-opaque', page: 2 }), expect.any(Object)));
});
