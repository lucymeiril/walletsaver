import { beforeEach, afterEach, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import Products from './Products';
import { api } from '../../api/client';
vi.mock('../../api/client', () => ({ api: { getNormalizedProducts: vi.fn(), getProducts: vi.fn() } }));
const product = { public_product_id: 'prod-opaque', canonical_name: '선언 구성', is_active: true,
  unified_category_id: 'food.gift', category_name: '선물 구성', aliases: ['원명'], keywords: ['키워드'],
  variants: [{ public_variant_id: 'var-vector', variant_name: '식품과 부속', is_active: true,
    display_unit: '1200g+1200g', package_quantity: 1, package_unit: '세트', bundle_count: 1,
    quantity_components: [{ identity: '김치 A', quantity: 1200, unit: 'g', count: null },
      { identity: '김치 B', quantity: 1200, unit: 'g', count: null }],
    attributes: { scalar_basis: 'one_complete_declared_vector_not_piece_count' },
    source_listings: [{ public_source_listing_id: 'listing-opaque', source_name: 'Costco', source_record_key: 'native-123', source_title: '원 제목', source_unit_text: '1200g+1200g' }] },
    { public_variant_id: 'var-unknown', is_active: false, package_quantity: null, package_unit: null, bundle_count: 1,
      display_unit: '3.6kg내외', source_listings: [] }],
};
const envelope = items => ({ source_scope: 'admin_normalized_catalog', read_only: true, items, total: 21, page: 1, per_page: 20, total_pages: 2 });
beforeEach(() => { vi.clearAllMocks(); api.getNormalizedProducts.mockResolvedValue(envelope([product])); });
afterEach(cleanup);
it('defaults to exact read-only catalog/spec/source facts, with unknown components and no legacy controls/price guesses', async () => {
  render(<Products />);
  await screen.findByText('prod-opaque');
  expect(api.getProducts).not.toHaveBeenCalled();
  expect(screen.queryByText('상품 추가')).toBeNull();
  expect(screen.queryByText('DB 초기화')).toBeNull();
  fireEvent.click(screen.getByText('규격·출처 보기'));
  expect(screen.getByText('var-vector')).toBeTruthy();
  expect(screen.getByText('listing-opaque')).toBeTruthy();
  expect(screen.getByText('native-123')).toBeTruthy();
  expect(screen.getByText('var-unknown')).toBeTruthy();
  expect(screen.getByText('저장된 표시 규격: 3.6kg내외')).toBeTruthy();
  expect(screen.queryByText(/미확인 ×1/)).toBeNull();
  expect(screen.getAllByText(/구성 수 미확인/)).toHaveLength(2);
  expect(screen.queryByText('0원')).toBeNull();
  const href = screen.getByText('이 출처 관측 이력').getAttribute('href');
  const params = new URL(href, 'http://localhost').searchParams;
  expect(Object.fromEntries(params)).toEqual({ public_product_id: 'prod-opaque', public_variant_id: 'var-vector', public_source_listing_id: 'listing-opaque' });
});
it('keeps bounded search/leaf filters and paging, ignoring superseded responses', async () => {
  let late;
  api.getNormalizedProducts.mockImplementationOnce(() => new Promise(resolve => { late = resolve; }));
  render(<Products />);
  fireEvent.change(screen.getByLabelText('상품 검색'), { target: { value: '구성' } });
  fireEvent.change(screen.getByLabelText('통합 분류 ID'), { target: { value: 'food.gift' } });
  fireEvent.click(screen.getByRole('button', { name: '검색' }));
  await screen.findByText('prod-opaque');
  expect(api.getNormalizedProducts).toHaveBeenLastCalledWith({ q: '구성', unified_category_id: 'food.gift', page: 1, per_page: 20 }, expect.any(Object));
  late(envelope([{ ...product, public_product_id: 'late-wrong' }]));
  await waitFor(() => expect(screen.queryByText('late-wrong')).toBeNull());
  fireEvent.click(screen.getByText('다음'));
  await waitFor(() => expect(api.getNormalizedProducts).toHaveBeenLastCalledWith({ q: '구성', unified_category_id: 'food.gift', page: 2, per_page: 20 }, expect.any(Object)));
});
