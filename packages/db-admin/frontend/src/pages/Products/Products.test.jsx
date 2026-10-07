import { beforeEach, afterEach, it, expect, vi } from 'vitest';
import { act, render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Products from './Products';
import { NormalizedCorrectionForm } from './ProductModal';
import { sourceReviewLink } from './NormalizedProducts';
import InboxPage, { matchesReviewContext } from '../Inbox/InboxPage';
import useDbAdminStore from '../../stores/dbAdminStore';
import { api } from '../../api/client';
vi.mock('../../api/client', () => ({ api: { getNormalizedProducts: vi.fn(), getProducts: vi.fn(), getNormalizedProduct: vi.fn(), updateNormalizedProduct: vi.fn(), getUnifiedCategoryTree: vi.fn(), getKeywords: vi.fn(), getNormalizedPriceHistory: vi.fn(), getNormalizedCorrection: vi.fn(), previewNormalizedCorrection: vi.fn(), applyNormalizedCorrection: vi.fn() } }));
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
  fireEvent.click(screen.getByRole('button', { name: '표시 정보 저장' }));
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
  fireEvent.click(screen.getByRole('button', { name: '표시 정보 저장' }));
  await screen.findByRole('alert');
  expect(screen.getByLabelText('표시 상품명').value).toBe('입력 보존');
  expect(screen.getByRole('alert').textContent).toContain('공식 번들');
  expect(screen.getByRole('button', { name: '표시 정보 저장' }).disabled).toBe(false);
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

const correctionTuple = {public_variant_id:'var-vector',public_source_listing_id:'listing-opaque',public_offer_event_id:'original-event'};
const correctionBinding = {...correctionTuple,binding_sha256:'source-binding',stored_quote:4990,
  stored_specification:{package_quantity:85,package_unit:'g',bundle_count:1,display_unit:'85g'},
  observed_at:'2026-08-31T01:46:57.083473Z',source_name:'Costco',source_record_key:'native-123',
  source_title:'원문 85g×4',source_url:'https://example.invalid/product/native-123',
  source_observations:[{raw_record_id:9,raw_payload_sha256:'immutable-body'}]};
async function openCorrection() {
  api.getNormalizedPriceHistory.mockResolvedValue({items:[{public_offer_event_id:'original-event',observed_quote:4990,crawled_at:correctionBinding.observed_at}],total_pages:1});
  api.getNormalizedCorrection.mockResolvedValue(correctionBinding);
  render(<NormalizedCorrectionForm product={product} initialSelection={{variantId:'var-vector',listingId:'listing-opaque'}} />);
  await screen.findByRole('option',{name:/2026-08-31/});
  fireEvent.change(screen.getByLabelText('교정 관측 기록'), {target:{value:'original-event'}});
  await screen.findByText(/저장 규격: 85g/);
  fireEvent.click(screen.getByLabelText('판매규격 교정'));
  fireEvent.change(screen.getByLabelText('교정 판매개수'),{target:{value:'4'}});
  fireEvent.change(screen.getByLabelText('교정 사유'),{target:{value:'보존 원문 판매개수 교정'}});
}
it('typed correction requires exact source binding and a matching validated preview before applying, without publishing or rewriting the original', async () => {
  await openCorrection();
  expect(api.getNormalizedPriceHistory).toHaveBeenCalledWith({public_product_id:'prod-opaque',public_variant_id:'var-vector',public_source_listing_id:'listing-opaque',page:1,per_page:50},expect.any(Object));
  expect(api.getNormalizedCorrection).toHaveBeenCalledWith('prod-opaque',correctionTuple,expect.any(Object));
  const body={...correctionTuple,binding_sha256:'source-binding',reason:'보존 원문 판매개수 교정',package_quantity:85,package_unit:'g',bundle_count:4};
  api.previewNormalizedCorrection.mockResolvedValue({has_changes:true,applied:false,snapshot_published:false,proposal_sha256:'validated-proposal',source_price:{price:4990,original_price:null,price_state:'sale_price_only',promotion_conditions:{source_base_quote_only:true}},source_specification:{display_unit:'85g×4'},validation:{ok:true}});
  api.applyNormalizedCorrection.mockResolvedValue({applied:true,new_variant_id:'corrected-var',new_event_id:'correction-event',snapshot_published:false});
  fireEvent.click(screen.getByText('가격·규격 교정 미리보기'));
  await screen.findByRole('button',{name:'검증된 교정 정식 적용'});
  expect(api.previewNormalizedCorrection).toHaveBeenCalledWith('prod-opaque',body);
  expect(screen.getByText('저장 표시가 → 원문 검증 가격: 4990 → 4990')).toBeTruthy();
  fireEvent.change(screen.getByLabelText('교정 사유'),{target:{value:'사유 수정'}});
  expect(screen.queryByRole('button',{name:'검증된 교정 정식 적용'})).toBeNull();
  expect(api.applyNormalizedCorrection).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText('가격·규격 교정 미리보기'));
  fireEvent.click(await screen.findByRole('button',{name:'검증된 교정 정식 적용'}));
  await screen.findByText(/교정 정식 적용 완료/);
  expect(api.applyNormalizedCorrection).toHaveBeenCalledWith('prod-opaque',{...body,reason:'사유 수정',expected_proposal_sha256:'validated-proposal'});
  expect(correctionBinding.stored_quote).toBe(4990);
  expect(correctionBinding.observed_at).toBe('2026-08-31T01:46:57.083473Z');
  expect(screen.getByRole('status').textContent).toContain('별도 스냅샷');
});
it('typed correction rejects incomplete quantity locally and retains honest no-change and protected-scope review actions', async () => {
  await openCorrection();
  fireEvent.change(screen.getByLabelText('교정 단위'),{target:{value:''}});
  fireEvent.click(screen.getByText('가격·규격 교정 미리보기'));
  await screen.findByText(/각량·단위·판매개수를 함께 입력하세요/);
  expect(api.previewNormalizedCorrection).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText('교정 단위'),{target:{value:'g'}});
  api.previewNormalizedCorrection.mockResolvedValue({has_changes:false,applied:false,snapshot_published:false,source_price:{price:4990,original_price:null,price_state:'sale_price_only',promotion_conditions:{source_base_quote_only:true}},source_specification:correctionBinding.stored_specification});
  fireEvent.click(screen.getByText('가격·규격 교정 미리보기'));
  expect((await screen.findByRole('button',{name:'검증된 교정 정식 적용'})).disabled).toBe(true);
  expect(screen.getByText('변경 없음 · 적용 불필요')).toBeTruthy();
  expect(screen.queryByText(/원문 검증 실패/)).toBeNull();
  expect(api.applyNormalizedCorrection).not.toHaveBeenCalled();
  api.previewNormalizedCorrection.mockRejectedValue(Object.assign(new Error('공유 규격은 정식 묶음 검토가 필요합니다'),{detail:{mutation_workflow:'/api/catalog-bundles',public_variant_id:'var-vector'}}));
  fireEvent.click(screen.getByText('가격·규격 교정 미리보기'));
  const link=await screen.findByText('선택 출처 정식 검토로 이동');
  expect(new URL(link.getAttribute('href'),'http://localhost').searchParams.get('public_source_listing_id')).toBe('listing-opaque');
  expect(screen.getByLabelText('교정 판매개수').value).toBe('4');
  expect(api.applyNormalizedCorrection).not.toHaveBeenCalled();
});

it('typed correction scope hold is available only from the source binding and mutually excludes numeric edits', async () => {
  await openCorrection();
  expect(screen.queryByLabelText('정확 총수량·단위가 보류')).toBeNull();
  cleanup();
  api.getNormalizedCorrection.mockResolvedValue({...correctionBinding,quantity_scope_actions:['hold_unresolved'],quantity_scope_issues:['measured_inner_scope_unresolved']});
  render(<NormalizedCorrectionForm product={product} initialSelection={{variantId:'var-vector',listingId:'listing-opaque'}} />);
  await screen.findByRole('option',{name:/2026-08-31/});
  fireEvent.change(screen.getByLabelText('교정 관측 기록'),{target:{value:'original-event'}});
  fireEvent.click(await screen.findByLabelText('정확 총수량·단위가 보류'));
  expect(screen.getByLabelText('판매규격 교정').disabled).toBe(true);
  expect(screen.getByLabelText('가격 교정').disabled).toBe(true);
  fireEvent.change(screen.getByLabelText('교정 사유'),{target:{value:'보존 원문 각량·전체 범위 미확인'}});
  api.previewNormalizedCorrection.mockResolvedValue({has_changes:true,source_price:{price:4990},source_specification:correctionBinding.stored_specification,proposal_sha256:'scope-proposal',validation:{ok:true},applied:false});
  fireEvent.click(screen.getByText('가격·규격 교정 미리보기'));
  await screen.findByRole('button',{name:'검증된 교정 정식 적용'});
  expect(api.previewNormalizedCorrection).toHaveBeenLastCalledWith('prod-opaque',{...correctionTuple,binding_sha256:'source-binding',reason:'보존 원문 각량·전체 범위 미확인',quantity_scope_action:'hold_unresolved'});
  expect(api.applyNormalizedCorrection).not.toHaveBeenCalled();
});

it('typed correction timeout preserves only the exact validated proposal for result confirmation and blocks a fresh preview', async () => {
  await openCorrection();
  const body={...correctionTuple,binding_sha256:'source-binding',reason:'보존 원문 판매개수 교정',package_quantity:85,package_unit:'g',bundle_count:4};
  api.previewNormalizedCorrection.mockResolvedValue({has_changes:true,source_price:{price:4990},source_specification:{display_unit:'85g×4'},proposal_sha256:'same-proposal',validation:{ok:true},applied:false});
  api.applyNormalizedCorrection.mockRejectedValueOnce(new DOMException('request timeout','TimeoutError')).mockResolvedValueOnce({applied:true,idempotent:true,new_event_id:'same-correction',snapshot_published:false});
  fireEvent.click(screen.getByText('가격·규격 교정 미리보기'));
  fireEvent.click(await screen.findByRole('button',{name:'검증된 교정 정식 적용'}));
  const confirm=await screen.findByRole('button',{name:'같은 교정 적용 결과 확인'});
  expect(screen.getByRole('alert').textContent).toContain('적용 결과 미확인');
  expect(screen.getByRole('button',{name:'가격·규격 교정 미리보기'}).disabled).toBe(true);
  expect(screen.getByLabelText('교정 사유').disabled).toBe(true);
  expect(api.applyNormalizedCorrection).toHaveBeenCalledTimes(1);
  fireEvent.click(confirm);
  await screen.findByText(/교정 정식 적용 완료/);
  expect(api.previewNormalizedCorrection).toHaveBeenCalledTimes(1);
  expect(api.applyNormalizedCorrection.mock.calls).toEqual([['prod-opaque',{...body,expected_proposal_sha256:'same-proposal'}],['prod-opaque',{...body,expected_proposal_sha256:'same-proposal'}]]);
});

it('typed correction apply uses its own120second timeout and never automatically repeats a mutation', async () => {
  const actual=await vi.importActual('../../api/client');
  vi.useFakeTimers();
  let signal;
  const fetchMock=vi.fn((url,options)=>{signal=options.signal;return new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(signal.reason)));});
  vi.stubGlobal('fetch',fetchMock);
  try {
    const outcome=actual.api.applyNormalizedCorrection('prod-opaque',{...correctionTuple,expected_proposal_sha256:'same-proposal'}).catch(error=>error);
    await vi.advanceTimersByTimeAsync(15001);
    expect(signal.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(104999);
    const error=await outcome;
    expect(error.name).toBe('TimeoutError');
    expect(error.message).toContain('결과 미확인');
    expect(error.message).toContain('120초');
    expect(fetchMock).toHaveBeenCalledTimes(1);
  } finally {vi.useRealTimers();vi.unstubAllGlobals();}
});
