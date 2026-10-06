import { useEffect, useState } from 'react';
import { api } from '../../api/client';
import { StoredSpecification, CatalogPagination } from './NormalizedCatalogFacts';
import s from './Products.module.css';

function historyLink(product, variant, listing) {
  const params = new URLSearchParams({ public_product_id: product.public_product_id });
  if (variant) params.set('public_variant_id', variant.public_variant_id);
  if (listing) params.set('public_source_listing_id', listing.public_source_listing_id);
  return `/prices?${params}`;
}

export default function NormalizedProducts() {
  const [query, setQuery] = useState('');
  const [search, setSearch] = useState('');
  const [categoryDraft, setCategoryDraft] = useState('');
  const [category, setCategory] = useState('');
  const [active, setActive] = useState('');
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState(null);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(''); setExpanded(null);
    api.getNormalizedProducts({ page, per_page: 20, ...(search ? { q: search } : {}), ...(active ? { is_active: active } : {}), ...(category ? { unified_category_id: category } : {}) }, { signal: controller.signal })
      .then(result => {
        if (controller.signal.aborted) return;
        if (result.source_scope !== 'admin_normalized_catalog' || result.read_only !== true || !Array.isArray(result.items) || typeof result.total !== 'number') throw new Error('정규화 카탈로그 응답 형식 미확인');
        setData(result);
      }).catch(err => { if (!controller.signal.aborted) setError(err.message || '정규화 카탈로그 조회 실패'); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [page, search, active, category, refresh]);
  return <div className={s.page}>
    <h2 className={s.title}>정규화 상품 카탈로그</h2>
    <p>저장된 상품·규격·출처 연결을 조회합니다. 관측가는 가격 이력에서 확인하며 현재 구매 가격이나 최저가를 뜻하지 않습니다.</p>
    <p>상품·분류·규격 변경은 공식 출처 검토 카탈로그 번들을 사용합니다.</p>
    <form className={s.filters} onSubmit={e => { e.preventDefault(); setPage(1); setSearch(query.trim()); setCategory(categoryDraft.trim()); }}>
      <label>상품 검색 <input value={query} onChange={e => setQuery(e.target.value)} placeholder="상품명·별칭·키워드 검색" /></label>
      <label>통합 분류 ID <input value={categoryDraft} onChange={e => setCategoryDraft(e.target.value)} /></label>
      <label>상품 상태 <select value={active} onChange={e => { setActive(e.target.value); setPage(1); }}>
        <option value="">보존된 전체 상품</option><option value="true">활성 상품</option><option value="false">비활성 상품</option>
      </select></label>
      <button type="submit">검색</button><button type="button" onClick={() => setRefresh(v => v + 1)}>새로고침</button>
    </form>
    {error && <p role="alert">{error}</p>}
    {loading ? <p>불러오는 중...</p> : !error && data && <>
      {data.items.length === 0 ? <p>조회 조건에 맞는 보존 상품이 없습니다.</p> : <table className={s.table}>
        <thead><tr><th>상품 / 공개 ID</th><th>통합 분류</th><th>상태</th><th>규격·출처 검토</th></tr></thead>
        <tbody>{data.items.map(product => <ProductRow key={product.public_product_id} product={product}
          expanded={expanded === product.public_product_id} toggle={() => setExpanded(expanded === product.public_product_id ? null : product.public_product_id)} />)}</tbody>
      </table>}
      <CatalogPagination data={data} page={page} setPage={setPage} />
    </>}
  </div>;
}

function ProductRow({ product, expanded, toggle }) {
  return <>
    <tr>
      <td>{product.canonical_name}<br /><code>{product.public_product_id}</code></td>
      <td>{product.category_name || '분류명 미확인'}<br /><code>{product.unified_category_id || '분류 ID 미확인'}</code></td>
      <td>{product.is_active === true ? '활성' : product.is_active === false ? '비활성' : '미확인'}</td>
      <td><button onClick={toggle}>{expanded ? '규격 접기' : '규격·출처 보기'}</button> <a href={historyLink(product)}>전체 관측 이력</a></td>
    </tr>
    {expanded && <tr><td colSpan="4">
      <p>브랜드: {product.brand || '미확인'}</p>
      <p>별칭: {(product.aliases || []).join(' · ') || '미등록'}</p>
      <p>키워드: {(product.keywords || []).map(k => typeof k === 'string' ? k : k.word).join(' · ') || '미등록'}</p>
      {product.attributes && <details><summary>저장된 상품 검토 메타데이터</summary><pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(product.attributes, null, 2)}</pre></details>}
      {(product.variants || []).length === 0 && <p>저장된 규격 없음 · 구성·개수 미확인</p>}
      {(product.variants || []).map(variant => <section key={variant.public_variant_id} style={{ padding: 16, border: '1px solid var(--border)', marginBottom: 12 }}>
        <h3>{variant.variant_name || '규격명 미확인'}</h3><code>{variant.public_variant_id}</code>
        <p>규격 상태: {variant.is_active === true ? '활성' : variant.is_active === false ? '비활성 · 보존 이력' : '미확인'}</p>
        <StoredSpecification variant={variant} />
        <a href={historyLink(product, variant)}>이 규격 관측 이력</a>
        <ul>{(variant.source_listings || []).map(listing => <li key={listing.public_source_listing_id}>
          {listing.source_name} · {listing.source_title || '출처 제목 미확인'}<br />
          원 출처 키 <code>{listing.source_record_key || '미확인'}</code> · listing <code>{listing.public_source_listing_id}</code><br />
          <span>출처 규격 원문: {listing.source_unit_text || '미확인'}</span> · <a href={historyLink(product, variant, listing)}>이 출처 관측 이력</a>
        </li>)}</ul>
      </section>)}
    </td></tr>}
  </>;
}
