import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../api/client', () => ({
  api: {
    getIngestions: vi.fn(),
    getIngestion: vi.fn(),
  },
}));

import { api } from '../../../api/client';
import useAdminStore from '../../../stores/adminStore';
import DataReviewPage from '../DataReviewPage';

const INGESTIONS = Array.from({ length: 501 }, (_, index) => ({
  id: index + 1,
  crawler_name: `crawler-${index + 1}`,
  items_count: 1,
  quality_score: 100,
  schema_type: 'DiscountItem',
  status: 'pending',
}));

beforeEach(() => {
  vi.clearAllMocks();
  useAdminStore.setState({
    ingestions: [],
    ingestionsLoading: false,
    ingestionsError: null,
  });
  api.getIngestions.mockImplementation(async ({ limit, offset }) => ({
    total: INGESTIONS.length,
    items: INGESTIONS.slice(offset, offset + limit),
  }));
});

afterEach(cleanup);

describe('DataReviewPage approved intake source context', () => {
  const batch = { id: 13, crawler_name: 'source-context', schema_type: 'DiscountItem',
    status: 'approved', items_count: 1, quality_score: 100 };

  it('shows nested source terms and explicit review interpretation without inventing missing tuple IDs', async () => {
    const row = { name: 'Declared capsules', sale_price: 40990, source: 'costco', mart_native_code: '649298',
      public_product_id: 'prod-source', public_variant_id: 'var-source', display_unit: '80개입',
      source_url: 'https://www.costco.co.kr/p/649298', attributes: { promotion_conditions: {
        source_quote_currency: 'KRW', payable_price_unconfirmed: true, customer_eligibility_unconfirmed: true,
        source_minimum_purchase_quantity: 1, source_maximum_order_quantity: 500,
        source_native_business_conditions: { membership: false, minOrderQuantity: 1, maxOrderQuantity: 500 },
      } } };
    const detail = { ...batch, items: [row], crawler_reviewer_notes: 'Source identity verified; observed quote only.',
      db_reviewer_notes: 'Customer/payment eligibility remains unknown.' };
    const original = JSON.stringify(detail);
    api.getIngestions.mockResolvedValue({ total: 1, items: [batch] });
    api.getIngestion.mockResolvedValue(detail);
    render(<DataReviewPage />);
    fireEvent.click(await screen.findByText('source-context'));
    const context = await screen.findByRole('region', { name: '원 출처·정규화 연결 1' });
    expect(within(context).getByText('prod-source')).toBeInTheDocument();
    expect(within(context).getByText('var-source')).toBeInTheDocument();
    expect(within(context).getByText('649298')).toBeInTheDocument();
    expect(context).toHaveTextContent('출처 연결 ID: 미확인 · 행사 관측 ID: 미확인');
    expect(within(context).getByText(/원 관측가: 40,990원/)).toBeInTheDocument();
    expect(within(context).getByText('관측가만 확인 · 총지출·실제 결제 금액 미확인')).toBeInTheDocument();
    expect(within(context).getByText('출처 주문 수량 상한 500개 · 재고·할인 한도 아님')).toBeInTheDocument();
    expect(within(context).getByText('고객·회원 이용 자격 미확인')).toBeInTheDocument();
    fireEvent.click(within(context).getByText('원문 구매·행사 조건'));
    expect(context.textContent).toContain('"membership": false');
    expect(screen.getByRole('region', { name: '검토 해석 메모' })).toHaveTextContent(detail.db_reviewer_notes);
    expect(screen.getByRole('region', { name: '검토 해석 메모' })).toHaveTextContent(detail.crawler_reviewer_notes);
    expect(screen.queryByText('[object Object]')).not.toBeInTheDocument();
    expect(within(context).queryByRole('link')).not.toBeInTheDocument();
    expect(within(context).queryByRole('button')).not.toBeInTheDocument();
    expect(JSON.stringify(detail)).toBe(original);
  });

  it('preserves unknown observations, source arrays and bounded nested display without a price or package default', async () => {
    const detail = { ...batch, items: [{ name: 'Unpriced selected group', sale_price: null, price: 0,
      display_unit: '1.8kg내외', attributes: { source_record_key: 'native-unpriced', promotion_conditions: {
        source_quote_currency: null, payable_price_unconfirmed: true, selected_product_scope_unconfirmed: true,
        promotions: [{ description: 'Choose three, one free', requiredProductQuantity: 3 }],
      }, label_notes: 'x'.repeat(6100) } }] };
    const original = JSON.stringify(detail);
    api.getIngestions.mockResolvedValue({ total: 1, items: [batch] });
    api.getIngestion.mockResolvedValue(detail);
    render(<DataReviewPage />);
    fireEvent.click(await screen.findByText('source-context'));
    const context = await screen.findByRole('region', { name: '원 출처·정규화 연결 1' });
    expect(within(context).getByText(/출처 규격 표기: 1.8kg내외 · 원 관측가: 미확인/)).toBeInTheDocument();
    expect(within(context).getByText('native-unpriced')).toBeInTheDocument();
    expect(within(context).getByText('선택 상품 구성·행사 적용 자격 미확인')).toBeInTheDocument();
    fireEvent.click(within(context).getByText('원문 구매·행사 조건'));
    expect(context.textContent).toContain('"requiredProductQuantity": 3');
    expect(context.textContent).toContain('"source_quote_currency": null');
    expect(screen.getAllByText('일부 표시 · 원본 값은 변경되지 않습니다.').length).toBeGreaterThan(0);
    expect(context).not.toHaveTextContent('0원');
    expect(context).not.toHaveTextContent('×1');
    expect(screen.getByRole('region', { name: '검토 해석 메모' })).toHaveTextContent('미기록');
    expect(JSON.stringify(detail)).toBe(original);
  });
});

describe('DataReviewPage pagination', () => {
  it('loads every ingestion batch and exposes pages beyond the API first page', async () => {
    render(<DataReviewPage />);

    expect(await screen.findByText('501건 중 1–10')).toBeInTheDocument();
    expect(api.getIngestions).toHaveBeenNthCalledWith(1, { limit: 500, offset: 0 });
    expect(api.getIngestions).toHaveBeenNthCalledWith(2, { limit: 500, offset: 500 });

    fireEvent.click(screen.getByRole('button', { name: '»' }));

    await waitFor(() => {
      expect(screen.getByText('crawler-501')).toBeInTheDocument();
      expect(screen.getByText('501건 중 501–501')).toBeInTheDocument();
    });
  });
});
