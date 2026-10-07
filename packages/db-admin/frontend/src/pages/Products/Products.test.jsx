import { beforeEach, afterEach, it, expect, vi } from 'vitest';
import { act, render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Products from './Products';
import { sourceReviewLink } from './NormalizedProducts';
import InboxPage, { matchesReviewContext } from '../Inbox/InboxPage';
import useDbAdminStore from '../../stores/dbAdminStore';
import { api } from '../../api/client';
vi.mock('../../api/client', () => ({ api: { getNormalizedProducts: vi.fn(), getProducts: vi.fn(), getNormalizedProduct: vi.fn(), updateNormalizedProduct: vi.fn(), getUnifiedCategoryTree: vi.fn(), getKeywords: vi.fn() } }));
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


it('467 metadata editor saves only changed display fields on the original opaque ID and reloads preserved specifications', async () => {
  const detail = { ...product, display_name: '선언 구성', display_brand: '', brand: null,
    metadata_editable: true, keyword_ids: [7], keywords: ['원래 키워드'], keyword_associations: [{ id: 7, word: '원래 키워드', unified_category_id: 'food', is_active: true }] };
  api.getNormalizedProduct.mockResolvedValue(detail);
  api.getUnifiedCategoryTree.mockResolvedValue([{ id: 'food', name_ko: '식품', children: [{ id: 'food.gift', name_ko: '선물 구성' }] }]);
  api.getKeywords.mockImplementation(async params => params.page === 2
    ? { items: [{ id: 9, word: '둘째 페이지 키워드' }], total_pages: 2 }
    : { items: [{ id: 8, word: '현재 분류 키워드' }], total_pages: 2 });
  api.updateNormalizedProduct.mockResolvedValue({ ...detail, display_name: '수정 표시명', snapshot_required: true });
  api.getNormalizedProducts.mockImplementation(async () => envelope([{ ...product,
    display_name: api.updateNormalizedProduct.mock.calls.length ? '수정 표시명' : '선언 구성' }]));
  render(<Products />);
  fireEvent.click(await screen.findByRole('button', { name: '표시 정보 수정' }));
  const name = await screen.findByLabelText('표시 상품명');
  expect(api.getNormalizedProduct).toHaveBeenCalledWith('prod-opaque');
  expect(screen.getByText('식품 > 선물 구성')).toBeTruthy();
  await screen.findByRole('option', { name: '둘째 페이지 키워드' });
  expect(screen.getByRole('option', { name: '원래 키워드' }).selected).toBe(true);
  expect(screen.queryByText('행사 raw_data(JSON)')).toBeNull();
  expect(screen.queryByLabelText('현재/행사가')).toBeNull();
  fireEvent.change(name, { target: { value: '수정 표시명' } });
  fireEvent.click(screen.getByRole('button', { name: '저장' }));
  await waitFor(() => expect(api.updateNormalizedProduct).toHaveBeenCalledWith('prod-opaque', { display_name: '수정 표시명' }));
  await screen.findByText('수정 표시명');
  expect(screen.getByRole('status').textContent).toContain('공식 스냅샷');
  fireEvent.click(screen.getByText('규격·출처 보기'));
  expect(screen.getByText('var-vector')).toBeTruthy();
  expect(screen.getByText('listing-opaque')).toBeTruthy();
  expect(api.getProducts).not.toHaveBeenCalled();
});

it('467 metadata editor retains entered fields and the actual save error without closing on rejection', async () => {
  api.getNormalizedProduct.mockResolvedValue({ ...product, display_name: '선언 구성', display_brand: '',
    metadata_editable: true, keyword_ids: [] });
  api.getUnifiedCategoryTree.mockResolvedValue([{ id: 'food.gift', name: '선물 구성' }]);
  api.getKeywords.mockResolvedValue({ items: [] });
  api.updateNormalizedProduct.mockRejectedValue(new Error('검토군 분류 변경은 공식 번들이 필요합니다'));
  render(<Products />);
  fireEvent.click(await screen.findByRole('button', { name: '표시 정보 수정' }));
  fireEvent.change(await screen.findByLabelText('표시 상품명'), { target: { value: '입력 보존' } });
  fireEvent.click(screen.getByRole('button', { name: '저장' }));
  await screen.findByRole('alert');
  expect(screen.getByLabelText('표시 상품명').value).toBe('입력 보존');
  expect(screen.getByRole('alert').textContent).toContain('공식 번들');
  expect(screen.getByRole('button', { name: '저장' }).disabled).toBe(false);
});

it('467 carries the exact selected source tuple into the existing formal review route', () => {
  const listing = {...product.variants[0].source_listings[0],source_url:'https://example.invalid/product/native-123'};
  const url = new URL(sourceReviewLink(product,product.variants[0],listing),'http://localhost');
  expect(url.pathname).toBe('/inbox');
  expect(Object.fromEntries(url.searchParams)).toEqual({public_product_id:'prod-opaque',public_variant_id:'var-vector',public_source_listing_id:'listing-opaque',source:'Costco',native_key:'native-123',source_url:listing.source_url});
  expect(sourceReviewLink(product)).not.toContain('undefined');
});

it('467 finds an existing reviewed source receipt without substituting another specification or listing', () => {
  const context = {public_product_id:'prod-opaque',public_variant_id:'var-vector',public_source_listing_id:'listing-opaque',source:'costco',source_url:'https://example.invalid/product/native-123'};
  const row = {public_product_id:'prod-opaque',public_variant_id:'var-vector',source:'Costco',detail_url:context.source_url,package_quantity:null};
  expect(matchesReviewContext(row,context)).toBe(true);
  expect(matchesReviewContext({...row,public_variant_id:'wrong'},context)).toBe(false);
  expect(matchesReviewContext({...row,detail_url:'https://example.invalid/wrong'},context)).toBe(false);
  expect(matchesReviewContext({...row,public_source_listing_id:'wrong-listing'},context)).toBe(false);
  expect(row.package_quantity).toBeNull();
});

it('467 preserves zero pending receipts and distinguishes an unknown count from the all-status total', () => {
  const previous = useDbAdminStore.getState();
  useDbAdminStore.setState({ ingestionStats:{pending:0,approved:17,rejected:0},
    ingestionPagination:{total:17,total_pages:1},ingestions:[],loadingIngestions:false,error:null,
    fetchIngestions:vi.fn(),fetchIngestionStats:vi.fn() });
  try {
    const {unmount} = render(<MemoryRouter initialEntries={['/inbox?public_product_id=prod-opaque']}><InboxPage /></MemoryRouter>);
    expect(screen.getByText('건 대기').previousElementSibling.textContent).toBe('0');
    expect(screen.getByText('건 승인 완료').previousElementSibling.textContent).toBe('17');
    act(() => useDbAdminStore.setState({ingestionStats:{pending:null,approved:17,rejected:0}}));
    expect(screen.getByText('건 대기').previousElementSibling.textContent).toBe('미확인');
    unmount();
  } finally {
    useDbAdminStore.setState(previous,true);
  }
});
