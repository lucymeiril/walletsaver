import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import CategoryComparePage from './CategoryComparePage';
import { LegacyObservationFacts, RelatedHotdealFacts } from './PricePage';
import { searchService } from '../../services/searchService';
import { fmt, fmtUnitPrice } from '../../utils/helpers';

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
  it('guides the old frozen address to current category choices without aliasing its products', async () => {
    searchService.categoryCompare.mockResolvedValue({
      summary: { is_leaf: false, category_path: '식품 > 간편식·면', product_count: 929 },
      subcategories: [{ id: 'food.meals.prepared', name: '조리식품', count: 405 }], products: [],
    });
    render(<MemoryRouter initialEntries={['/price/category/processed_food.frozen_meal']}><Routes>
      <Route path="/price/category/:categoryId" element={<CategoryComparePage />} />
      <Route path="/price" element={<div>전체 분류 선택</div>} />
    </Routes></MemoryRouter>);
    expect(screen.getByRole('heading', { name: '이전 냉동식품 분류 주소입니다' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '전체 분류에서 선택' })).toBeInTheDocument();
    expect(searchService.categoryCompare).not.toHaveBeenCalled();
    expect(screen.queryByText('이 카테고리에 등록된 상품이 없습니다')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '간편식·면 분류에서 선택' }));
    expect(await screen.findByRole('button', { name: /조리식품/ })).toHaveTextContent('405개 상품');
    expect(searchService.categoryCompare).toHaveBeenCalledWith('food.meals', expect.any(Object));
    expect(screen.queryByRole('heading', { name: '이전 냉동식품 분류 주소입니다' })).not.toBeInTheDocument();
  });

  it('marks rounded unit-rate labels approximate without rounding tiny positive rates to zero or changing money', () => {
    expect(fmtUnitPrice(18.25)).toBe('18.25');
    expect(fmtUnitPrice(18.4)).toBe('18.4');
    expect(fmtUnitPrice('18.25')).toBe('18.25');
    expect(fmtUnitPrice(' 18.4 ')).toBe('18.4');
    expect(fmtUnitPrice('1e-9')).toBe('1E-9');
    expect(fmtUnitPrice(1 / 3, '₩')).toBe('≈ ₩0.333333');
    expect(fmtUnitPrice(28140.740740740737)).toBe('≈ 28,140.74');
    expect(fmtUnitPrice(1e-9)).toBe('1E-9');
    expect(fmtUnitPrice(1 / 300000000)).toBe('≈ 3.33333E-9');
    for (const value of [null, undefined, NaN, Infinity, -1, true, false, '', ' ', 'Infinity', 'invalid']) {
      expect(fmtUnitPrice(value)).toBe('');
    }
    expect(fmt(2190)).toBe('2,190');
  });

  it('shows distinct fractional unit rates in category cards and table while preserving transaction amounts', async () => {
    show({ summary: { ...summary, comparison_basis: '100ml', avg_comparison_price: (18.25 + 18.4 + 1 / 3) / 3,
      min_comparison_price: 1 / 3, max_comparison_price: 18.4 }, products: [
      { id: 'water-six', name: '물 2L×6', price: { current: 2190 },
        normalized: { unit_price: 18.25, basis: '100ml' },
        promotion: { total_price: 2190, listed_price: 2190, total_quantity: 12000, quantity_unit: 'ml', display_unit: '2L×6' } },
      { id: 'water-ten', name: '물 1L×10', price: { current: 1840 },
        normalized: { unit_price: 18.4, basis: '100ml' },
        promotion: { total_price: 1840, listed_price: 1840, total_quantity: 10000, quantity_unit: 'ml', display_unit: '1L×10' } },
      { id: 'water-repeating', name: '반복 소수 물', price: { current: 1 },
        normalized: { unit_price: 1 / 3, basis: '100ml' },
        promotion: { total_price: 1, listed_price: 1, total_quantity: 300, quantity_unit: 'ml', display_unit: '300ml' } },
    ] });
    const six = (await screen.findByText('물 2L×6')).closest('.productCard');
    const ten = screen.getByText('물 1L×10').closest('.productCard');
    expect(within(six).getByText('₩18.25/100ml')).toBeInTheDocument();
    expect(within(ten).getByText('₩18.4/100ml')).toBeInTheDocument();
    expect(within(six).getByText('거래 금액 ₩2,190')).toBeInTheDocument();
    expect(within(ten).getByText('거래 금액 ₩1,840')).toBeInTheDocument();
    const repeating = screen.getByText('반복 소수 물').closest('.productCard');
    expect(within(repeating).getByText('≈ ₩0.333333/100ml')).toBeInTheDocument();
    expect(within(repeating).getByText('거래 금액 ₩1')).toBeInTheDocument();
    expect(screen.getByText('평균 단위가 · 표시 조건 기준').parentElement).toHaveTextContent('≈ ₩12.33/100ml');
    fireEvent.click(screen.getByText('테이블'));
    const table = screen.getByRole('table');
    expect(within(table).getByText('₩18.25/100ml')).toBeInTheDocument();
    expect(within(table).getByText('₩18.4/100ml')).toBeInTheDocument();
    expect(within(table).getByText('≈ ₩0.333333/100ml')).toBeInTheDocument();
    expect(within(table).queryByText('₩18/100ml')).not.toBeInTheDocument();
  });

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


describe('category and legacy display regression466', () => {
  it('omits singleton controls without dropping products or compatible whole-category choices', async () => {
    const groups = Array.from({ length: 1000 }, (_, index) => ({ basis: `variant:single-${index}`, product_count: 1 }));
    groups.push({ basis: 'variant:unknown' }, { basis: '100g', product_count: 25 },
      { basis: 'variant:reviewed', product_count: 2 });
    show({ summary: { ...summary, comparison_basis: null, comparison_groups: groups }, products });
    await screen.findByText('동일 중량 기준');
    const controls = screen.getByRole('group', { name: '비교 단위 선택' });
    expect(within(controls).getAllByRole('button')).toHaveLength(3);
    expect(within(controls).getByRole('button', { name: '100g · 25개 상품' })).toBeInTheDocument();
    expect(within(controls).getByRole('button', { name: '같은 규격 상품 · 2개 상품' })).toBeInTheDocument();
    expect(screen.queryByText(/동일 규격 그룹|single-|variant:unknown/)).not.toBeInTheDocument();
    expect(screen.getAllByText('비교 미확인')).toHaveLength(3);
    expect(screen.getByText('내용량 미확인')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '단위가↑' })).toBeDisabled();
  });

  it('keeps an explicitly selected singleton URL and permits returning to all products', async () => {
    const basis = 'variant:own-one';
    searchService.categoryCompare.mockImplementation(async (_category, params) => ({
      summary: { ...summary, comparison_basis: params.comparisonBasis,
        comparison_groups: [{ basis, product_count: 1 }, { basis: 'variant:other', product_count: 1 }] },
      products: [{ ...products[0], normalized: { unit_price: 200, basis } }],
    }));
    render(<MemoryRouter initialEntries={[`/price/category/food?comparison_basis=${encodeURIComponent(basis)}`]}>
      <Routes><Route path="/price/category/:categoryId" element={<CategoryComparePage />} /></Routes>
    </MemoryRouter>);
    const selected = await screen.findByRole('button', { name: '선택한 상품 규격 · 1개 상품' });
    expect(selected).toHaveAttribute('aria-pressed', 'true');
    expect(screen.queryByText(/own-one|variant:other|동일 규격 그룹/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '전체 상품' }));
    await waitFor(() => expect(searchService.categoryCompare).toHaveBeenLastCalledWith('food',
      expect.objectContaining({ comparisonBasis: null })));
    await waitFor(() => expect(screen.queryByRole('group', { name: '비교 단위 선택' })).not.toBeInTheDocument());
    expect(screen.getByText('동일 중량 기준')).toBeInTheDocument();
  });

  it('keeps legacy specification literal and external source dates without inventing quantity or recency', () => {
    render(<><LegacyObservationFacts unit="120g" /><RelatedHotdealFacts deal={{
      source: 'algumon', time: '35일 전', posted_at: '2025-08-31T00:00:00Z',
      fetched_at: '2025-09-01T00:00:00Z', source_period: '8월 행사', expired: true,
      source_conditions: ['회원 전용', '쿠폰 별도'],
    }} /></>);
    expect(screen.getByText('저장 규격 · 120g')).toBeInTheDocument();
    expect(screen.getByText('관측 시각 · 미확인')).toBeInTheDocument();
    expect(screen.getByText(/수령량·묶음 수량·구매 조건 검증 미확인/)).toBeInTheDocument();
    expect(screen.getByText('출처 게시 시각 · 2025-08-31T00:00:00Z')).toBeInTheDocument();
    expect(screen.getByText('수집 시각 · 2025-09-01T00:00:00Z')).toBeInTheDocument();
    expect(screen.getByText('출처 게시 후 경과 · 35일 전')).toBeInTheDocument();
    expect(screen.getByText('판매 기간 종료 · 과거 출처 관측')).toBeInTheDocument();
    expect(screen.getByText('출처 조건 · 쿠폰 별도')).toBeInTheDocument();
    expect(screen.queryByText(/600g|현재 최저|구매 추천/)).not.toBeInTheDocument();
    cleanup();
    render(<RelatedHotdealFacts deal={{ source: 'algumon', time: '35일 전' }} />);
    expect(screen.getByText('출처 게시 시각 · 미확인')).toBeInTheDocument();
    expect(screen.getByText('표시 상대 시각 · 35일 전 · 기준 시각 미확인')).toBeInTheDocument();
    expect(screen.getByText('현재 판매 가능 여부 미확인')).toBeInTheDocument();
    cleanup();
    render(<RelatedHotdealFacts deal={{ source: 'algumon', time: '1일 전', fetched_at: '2026-10-06T10:13:03Z' }} />);
    expect(screen.getByText('수집 후 경과 · 1일 전')).toBeInTheDocument();
    expect(screen.getByText('출처 게시 시각 · 미확인')).toBeInTheDocument();
  });
});
