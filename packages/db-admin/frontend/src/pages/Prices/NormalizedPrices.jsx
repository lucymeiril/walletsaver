import { useEffect, useState } from 'react';
import { api } from '../../api/client';
import { StoredSpecification, CatalogPagination } from '../Products/NormalizedCatalogFacts';
import s from './Prices.module.css';

const emptyFilters = { q: '', source_name: '', unified_category_id: '', public_product_id: '', public_variant_id: '', public_source_listing_id: '', date_from: '', date_to: '', offer_state: '' };
function initialFilters() {
  const params = new URLSearchParams(window.location.search);
  return Object.fromEntries(Object.keys(emptyFilters).map(key => [key, params.get(key) || '']));
}

export default function NormalizedPrices() {
  const [draft, setDraft] = useState(initialFilters);
  const [filters, setFilters] = useState(initialFilters);
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    const params = Object.fromEntries(Object.entries(filters).filter(([, value]) => value !== ''));
    api.getNormalizedPriceHistory({ ...params, page, per_page: 25 }, { signal: controller.signal })
      .then(result => {
        if (controller.signal.aborted) return;
        if (result.source_scope !== 'admin_normalized_catalog' || result.read_only !== true || !Array.isArray(result.items) || typeof result.total !== 'number') throw new Error('정규화 관측 이력 응답 형식 미확인');
        setData(result);
      }).catch(err => { if (!controller.signal.aborted) setError(err.message || '관측 이력 조회 실패'); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [filters, page, refresh]);
  return <div className={s.page}>
    <h2 className={s.title}>정규화 관측 이력</h2>
    <p>원 관측가·행사 선언·출처 시각을 보존한 관리 이력입니다. 현재 판매 가격, 실제 고객 결제액이나 최저가를 계산하지 않습니다.</p>
    <p>날짜는 관측 시각 기준이며 종료일을 포함합니다. 페이지를 넘겨 선택한 기간의 모든 보존 이력을 확인할 수 있습니다.</p>
    <form className={s.dataFilters} onSubmit={e => { e.preventDefault(); setPage(1); setFilters({ ...draft }); }}>
      {Object.entries({ q: '상품·출처 검색', source_name: '출처', unified_category_id: '통합 분류 ID', public_product_id: '공개 상품 ID', public_variant_id: '공개 규격 ID', public_source_listing_id: '공개 출처 연결 ID' }).map(([key, label]) => <label key={key}>
        {label}<input value={draft[key]} onChange={e => setDraft({ ...draft, [key]: e.target.value })} />
      </label>)}
      <label>관측 시작일<input type="date" value={draft.date_from} onChange={e => setDraft({ ...draft, date_from: e.target.value })} /></label>
      <label>관측 종료일<input type="date" value={draft.date_to} onChange={e => setDraft({ ...draft, date_to: e.target.value })} /></label>
      <label>저장 행사 상태<input value={draft.offer_state} onChange={e => setDraft({ ...draft, offer_state: e.target.value })} placeholder="비우면 전체 상태" /></label>
      <button type="submit">이력 조회</button><button type="button" onClick={() => setRefresh(v => v + 1)}>새로고침</button>
    </form>
    {error && <p role="alert">{error}</p>}
    {loading ? <p>불러오는 중...</p> : !error && data && <>
      {data.items.length === 0 ? <p>선택한 조건·기간의 보존 관측 이력이 없습니다.</p> : <div className={s.tableWrap}><table className={s.table}>
        <thead><tr><th>상품·선택 규격</th><th>원 관측가 / 시각</th><th>원 행사 조건 / 평가 범위</th><th>정확한 출처·행사 ID</th></tr></thead>
        <tbody>{data.items.map(row => <ObservationRow key={row.public_offer_event_id} row={row} />)}</tbody>
      </table></div>}
      <CatalogPagination data={data} page={page} setPage={setPage} />
    </>}
  </div>;
}

function observedQuote(row) {
  const amount = Object.hasOwn(row, 'observed_quote') ? row.observed_quote : row.price;
  if (typeof amount !== 'number' || !Number.isFinite(amount) || amount <= 0) return '관측가 미확인';
  const conditions = row.promotion_conditions || {};
  const unknownCurrency = row.quote_currency_status === 'source_unconfirmed' || conditions.currency_unconfirmed === true || conditions.source_quote_currency_unconfirmed === true ||
    (Object.hasOwn(conditions, 'source_quote_currency') && conditions.source_quote_currency == null);
  const currency = row.source_quote_currency ?? conditions.source_quote_currency;
  return `${amount.toLocaleString('ko-KR')}${unknownCurrency ? ' (통화 미명시)' : currency === 'KRW' ? '원' : currency ? ` ${currency}` : ' (통화 미확인)'}`;
}

function ObservationRow({ row }) {
  const storedRates = Object.entries(row).filter(([key, value]) => key.startsWith('recorded_') && value != null);
  return <tr>
    <td>{row.canonical_name}<br /><code>{row.public_product_id}</code><br />
      {row.variant_name || '규격명 미확인'}<br /><code>{row.public_variant_id}</code>
      <p>현재 출처 연결 규격 · 과거 관측별 규격·거래 수령량 아님</p>
      <StoredSpecification variant={{ ...row, attributes: row.variant_attributes }} />
    </td>
    <td><strong>{observedQuote(row)}</strong><br />
      관측 시각: <time dateTime={row.crawled_at}>{row.crawled_at || '미확인'}</time><br />
      저장 가격 상태: {row.price_state || '미확인'}<br />
      원 정상가: {observedQuote({ ...row, observed_quote: row.original_price })}
    </td>
    <td>원 행사: {row.event_name || '미확인'} · 종류 {row.promotion_type || '미확인'}<br />
      선언 기간: {row.valid_from || '시작 미확인'} ~ {row.valid_to || '종료 미확인'}<br />
      저장 상태: {row.offer_state || '미확인'}<br />
      <strong>현재 결제·적용 자격 미확인</strong><br />
      관측 시점 거래 평가: {row.observation_receipt_eligible === false ? `보류 · ${row.observation_receipt_reason || '원 조건 미확인'}` : row.observation_receipt_eligible === true ? '저장된 평가 있음 · 실제 고객 결제 미확인' : '미평가 · 관리 이력'}
      {row.promotion_conditions && <details><summary>원문 구매·행사 조건</summary><pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(row.promotion_conditions, null, 2)}</pre></details>}
      {storedRates.length > 0 && <details><summary>과거 저장 계산값 · 현재 구매·비교 단가 아님</summary><pre>{JSON.stringify(Object.fromEntries(storedRates), null, 2)}</pre></details>}
    </td>
    <td>{row.source_name || '출처 미확인'}<br />출처 제목: {row.source_title || '미확인'}<br />원 출처 키 <code>{row.source_record_key || '미확인'}</code><br />
      listing <code>{row.public_source_listing_id}</code><br />event <code>{row.public_offer_event_id}</code><br />
      원 기록 <code>{row.raw_record_id || '미확인'}</code>
    </td>
  </tr>;
}
