import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import CategoryComparePage from './CategoryComparePage';
import { searchService } from '../../services/searchService';

vi.mock('../../services/searchService', () => ({ searchService: { categoryCompare: vi.fn() } }));

const summary = { is_leaf: true, product_count: 3, comparison_basis: '100g', avg_comparison_price: 500,
  min_comparison_price: 200, max_comparison_price: 900, ultra_threshold: 350, hotdeal_threshold: 425 };
const condition = { total_price: 6000, listed_price: 3000, total_quantity: 270, quantity_unit: 'g',
  received_package_count: 3, minimum_quantity: 2, membership_required: true, coupon_required: false,
  promotion_conditions: { buy_quantity: 2, free_quantity: 1 }, display_unit: '90g×3' };
const products = [
  { id: 'prod-a', name: '동일 중량 기준', price: { current: 6000 }, normalized: { unit_price: 200, basis: '100g' }, promotion: condition },
  { id: 'prod-b', name: '내용량 미확인', percentile: 0, price: { current: 1 }, normalized: { unit_price: null, basis: null }, promotion: { ...condition, total_quantity: null, quantity_unit: null } },
  { id: 'prod-c', name: '다른 부피 기준', price: { current: 100 }, normalized: { unit_price: 100, basis: '100ml' } },
];
function show(data) {
  searchService.categoryCompare.mockResolvedValue(data);
  render(<MemoryRouter initialEntries={['/price/category/food']}><Routes>
    <Route path="/price/category/:categoryId" element={<CategoryComparePage />} />
    <Route path="/price/:id" element={<div>선택 상품 페이지</div>} />
  </Routes></MemoryRouter>);
}
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe('CategoryCompare actual unit and receipt boundary', () => {
  it('selects authoritative whole-category unit groups before paging and keeps other units out of rankings', async () => {
    const groups = [
      { basis: '100g', product_count: 25, comparable_count: 25 },
      { basis: '100ml', product_count: 5, comparable_count: 5 },
    ];
    searchService.categoryCompare.mockImplementation(async (_category, params) => params.comparisonBasis
      ? { summary: { ...summary, comparison_basis: '100ml', comparison_groups: groups, product_count: 5,
        avg_comparison_price: 100, min_comparison_price: 100, max_comparison_price: 100,
        ultra_threshold: 70, hotdeal_threshold: 85 }, products: [products[2]],
        pagination: { total_pages: 1 } }
      : { summary: { ...summary, comparison_basis: null, comparison_groups: groups, product_count: 30 },
        products, pagination: { total_pages: 2 } });
    render(<MemoryRouter initialEntries={['/price/category/food']}><Routes>
      <Route path="/price/category/:categoryId" element={<CategoryComparePage />} />
    </Routes></MemoryRouter>);
    await screen.findByRole('button', { name: '100ml · 5개 상품' });
    expect(screen.getByRole('button', { name: '100g · 25개 상품' })).toBeInTheDocument();
    expect(screen.getAllByText('비교 미확인')).toHaveLength(3);
    fireEvent.click(screen.getByRole('button', { name: '다음 →' }));
    await waitFor(() => expect(searchService.categoryCompare).toHaveBeenLastCalledWith('food',
      expect.objectContaining({ page: 2, comparisonBasis: null })));
    await screen.findByRole('button', { name: '100ml · 5개 상품' });
    fireEvent.click(screen.getByRole('button', { name: '100ml · 5개 상품' }));
    await waitFor(() => expect(searchService.categoryCompare).toHaveBeenLastCalledWith('food',
      expect.objectContaining({ page: 1, comparisonBasis: '100ml' })));
    const selected = await screen.findByRole('button', { name: '100ml · 5개 상품' });
    expect(selected).toHaveAttribute('aria-pressed', 'true');
    expect(screen.queryByText('동일 중량 기준')).not.toBeInTheDocument();
    expect(screen.getByText('평균 단위가 · 표시 조건 기준').parentElement).toHaveTextContent('₩100/100ml');
    expect(screen.getByRole('button', { name: '단위가↑' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: '전체 상품' }));
    await waitFor(() => expect(searchService.categoryCompare).toHaveBeenLastCalledWith('food',
      expect.objectContaining({ page: 1, comparisonBasis: null })));
    await screen.findByText('동일 중량 기준');
    expect(screen.getByText('공통 비교 단위가 없어 가격 순위를 표시하지 않습니다.')).toBeInTheDocument();
  });

  it('keeps a new category loading and its real error when the cancelled prior query completes', async () => {
    let rejectOld;
    let rejectNew;
    searchService.categoryCompare
      .mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectOld = reject; }))
      .mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectNew = reject; }));
    function CategorySwitch() {
      const navigate = useNavigate();
      return <button onClick={() => navigate('/price/category/other')}>다른 카테고리</button>;
    }
    render(<MemoryRouter initialEntries={['/price/category/food']}>
      <CategorySwitch />
      <Routes><Route path="/price/category/:categoryId" element={<CategoryComparePage />} /></Routes>
    </MemoryRouter>);
    await waitFor(() => expect(searchService.categoryCompare).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole('button', { name: '다른 카테고리' }));
    await waitFor(() => expect(searchService.categoryCompare).toHaveBeenCalledTimes(2));
    await act(async () => rejectOld(new Error('이전 요청 오류')));
    expect(screen.getByText('카테고리 비교 데이터를 불러오는 중입니다')).toBeInTheDocument();
    expect(screen.queryByText('이전 요청 오류')).not.toBeInTheDocument();
    await act(async () => rejectNew(new Error('선택한 비교 단위를 사용할 수 없습니다')));
    expect(await screen.findByText('선택한 비교 단위를 사용할 수 없습니다')).toBeInTheDocument();
    expect(screen.queryByText('카테고리 비교 데이터를 불러오는 중입니다')).not.toBeInTheDocument();
  });

  it('ranks only the common unit and exposes transaction quantity and purchase conditions in card and table', async () => {
    show({ summary, products });
    const title = await screen.findByText('동일 중량 기준');
    const first = title.closest('.productCard');
    expect(within(first).getAllByText(/초특가 · 표시 조건 기준/).length).toBeGreaterThan(0);
    expect(within(first).getByText('거래 금액 ₩6,000')).toBeInTheDocument();
    expect(within(first).getByText(/수령 270g.*수령 패키지 3.*최소 구매 2.*구매 2.*추가 증정 1.*회원 필요.*쿠폰 필요 없음/)).toBeInTheDocument();
    for (const name of ['내용량 미확인', '다른 부피 기준']) {
      const card = screen.getByText(name).closest('.productCard');
      expect(within(card).getByText('비교 미확인')).toBeInTheDocument();
      expect(within(card).queryByText(/단위가 범위 위치|초특가|핫딜/)).not.toBeInTheDocument();
    }
    expect(within(screen.getByText('내용량 미확인').closest('.productCard')).queryByText('₩0')).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('테이블'));
    expect(screen.getByRole('table')).toHaveTextContent('거래 금액 ₩6,000');
    expect(screen.getByRole('table')).toHaveTextContent('판매 수량 미확인');
    fireEvent.click(screen.getByText('동일 중량 기준'));
    expect(await screen.findByText('선택 상품 페이지')).toBeInTheDocument();
  });

  it('holds mixed-basis summaries, zero quotes and different-basis alternative cheap claims', async () => {
    show({ summary: { ...summary, comparison_basis: null },
      products: [...products, { id: 'prod-zero', name: '미확인 가격', price: { current: null }, normalized: { unit_price: 0, basis: '100g' } }],
      alternatives: [{ category_id: 'volume', name: '부피 상품', comparison_basis: '100ml', avg_comparison_price: 1, saving_pct: 99 }] });
    await screen.findByText('동일 중량 기준');
    expect(screen.getByText('공통 비교 단위가 없어 가격 순위를 표시하지 않습니다.')).toBeInTheDocument();
    expect(screen.getByText('단위가↑')).toBeDisabled();
    expect(screen.getAllByText('비교 미확인')).toHaveLength(4);
    expect(screen.queryByText(/초특가 ·|핫딜 ·|저렴|비쌈|₩0/)).not.toBeInTheDocument();
    const average = screen.getByText('평균 단위가 · 표시 조건 기준').parentElement;
    expect(average).toHaveTextContent('미확인');
    expect(average).not.toHaveTextContent('500');
    await waitFor(() => expect(searchService.categoryCompare).toHaveBeenCalledWith('food', expect.any(Object)));
  });

  it('compares an explicit same-variant unit without exposing its internal identity as a unit label', async () => {
    const basis = 'variant:var-proven';
    show({ summary: { ...summary, comparison_basis: basis }, products: [
      { ...products[0], normalized: { unit_price: 200, basis } },
      { ...products[1], normalized: { unit_price: 1, basis: 'variant:var-different' } },
    ] });
    await screen.findByText('동일 중량 기준');
    expect(screen.getAllByText(/동일 규격의 판매 단위/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/var-proven|var-different/)).not.toBeInTheDocument();
    expect(within(screen.getByText('내용량 미확인').closest('.productCard')).getByText('비교 미확인')).toBeInTheDocument();
  });
});

it('preserves declared length quotes and conditions without comparing to mass', async () => {
  const { getOfferUnitPrice, getComparableOffers } = await import('../../utils/productDecision');
  const offer = { id:'offer-m', source:'emart', variant_id:'variant-m', listing_id:'listing-m',
    comparable_price:12000, total_price:12000, total_quantity:360, quantity_unit:'m',
    per_100m:3333, per_100g:null, per_100ml:null, received_package_count:3,
    minimum_quantity:2, membership_required:true, current_eligible:true };
  expect(getOfferUnitPrice(offer)).toEqual({price:3333, unit:'100m'});
  expect(getOfferUnitPrice({...offer, comparable_price:null})).toBeNull();
  const normalized = getComparableOffers({variants:[{id:'variant-m', listings:[{id:'listing-m',source:'emart',offers:[offer]}]}]});
  expect(normalized[0]).toMatchObject({unit:'100m',unitPrice:3333,totalPrice:12000,
    totalQuantity:360,quantityUnit:'m',variantId:'variant-m',listingId:'listing-m',membershipRequired:true});
  show({ summary:{...summary,comparison_basis:'100m'},products:[
    {id:'linear',name:'표시된 길이',price:{current:12000},normalized:{unit_price:3333,basis:'100m'},
      promotion:{total_spend:12000,total_quantity:360,quantity_unit:'m',membership_required:true}},
    {id:'mass',name:'질량 기준',price:{current:100},normalized:{unit_price:1,basis:'100g'}}] });
  const card = (await screen.findByText('표시된 길이')).closest('.productCard');
  expect(within(card).getAllByText(/100m/).length).toBeGreaterThan(0);
  expect(within(card).getByText(/360m.*회원 필요/)).toBeInTheDocument();
  expect(within(screen.getByText('질량 기준').closest('.productCard')).getByText('비교 미확인')).toBeInTheDocument();
});
