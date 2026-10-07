import { useEffect, useState } from 'react';
import { api } from '../../api/client';
import { StoredSpecification, CatalogPagination } from './NormalizedCatalogFacts';
import s from './Products.module.css';
import ProductModal from './ProductModal';

function historyLink(product, variant, listing) {
  const params = new URLSearchParams({ public_product_id: product.public_product_id });
  if (variant) params.set('public_variant_id', variant.public_variant_id);
  if (listing) params.set('public_source_listing_id', listing.public_source_listing_id);
  return `/prices?${params}`;
}

export function sourceReviewLink(product, variant, listing) {
  const params = new URLSearchParams({public_product_id:product.public_product_id});
  if (variant) params.set('public_variant_id', variant.public_variant_id);
  if (listing) {
    params.set('public_source_listing_id', listing.public_source_listing_id);
    if (listing.source_name) params.set('source', listing.source_name);
    if (listing.source_record_key) params.set('native_key', listing.source_record_key);
    if (listing.source_url) params.set('source_url', listing.source_url);
  }
  return `/inbox?${params}`;
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
  const [editor, setEditor] = useState(null);
  const [form, setForm] = useState({});
  const [editCategories, setEditCategories] = useState([]);
  const [editKeywords, setEditKeywords] = useState([]);
  const [editError, setEditError] = useState('');
  const [editLoading, setEditLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savedNotice, setSavedNotice] = useState('');
  function leafChoices(nodes, path = []) {
    return nodes.flatMap(node => {
      const names = [...path, node.name_ko || node.name || node.id];
      return node.children?.length
        ? leafChoices(node.children, names)
        : [{ id: node.id, name: names.join(' > ') }];
    });
  }
  const openEditor = async product => {
    setEditLoading(true); setEditError(''); setSavedNotice('');
    try {
      const [detail, tree] = await Promise.all([
        api.getNormalizedProduct(product.public_product_id), api.getUnifiedCategoryTree(),
      ]);
      if (detail.public_product_id !== product.public_product_id || detail.metadata_editable !== true) throw new Error('이 상품의 표시 정보 편집을 사용할 수 없습니다.');
      setForm({ display_name: detail.display_name ?? detail.canonical_name,
        display_brand: detail.display_brand ?? detail.brand ?? '',
        unified_category_id: detail.unified_category_id || '', aliases: (detail.aliases || []).join('\n'),
        keyword_ids: detail.keyword_ids || [], primary_image_url: detail.primary_image_url || '',
        is_active: detail.is_active === true });
      setEditCategories(leafChoices(tree));
      setEditKeywords(detail.keyword_associations || []);
      setEditor(detail);
    } catch (err) { setEditError(err.message || '편집 정보를 불러오지 못했습니다.'); }
    finally { setEditLoading(false); }
  };
  useEffect(() => {
    if (!editor || !form.unified_category_id) return;
    const controller = new AbortController();
    api.getKeywords({ unified_category_id: form.unified_category_id, per_page: 200 }, { signal: controller.signal })
      .then(async result => {
        const rows = Array.isArray(result) ? [...result] : [...(result.items || result.keywords || [])];
        for (let keywordPage = 2; keywordPage <= (result.total_pages || 1); keywordPage += 1) {
          if (controller.signal.aborted) return;
          const next = await api.getKeywords({ unified_category_id: form.unified_category_id, per_page: 200, page: keywordPage }, { signal: controller.signal });
          rows.push(...(next.items || next.keywords || []));
        }
        if (controller.signal.aborted) return;
        const selected = editor.keyword_associations || [];
        setEditKeywords([...new Map([...selected, ...rows].map(k => [k.id, k])).values()]);
      }).catch(err => { if (!controller.signal.aborted) setEditError(err.message || '키워드를 불러오지 못했습니다.'); });
    return () => controller.abort();
  }, [editor, form.unified_category_id]);
  const saveEditor = async () => {
    const candidate = { display_name: form.display_name.trim(), display_brand: form.display_brand.trim() || null,
      unified_category_id: form.unified_category_id, aliases: form.aliases.split('\n').map(v => v.trim()).filter(Boolean),
      keyword_ids: form.keyword_ids, primary_image_url: form.primary_image_url.trim() || null, is_active: form.is_active };
    const original = { ...editor, display_name: editor.display_name ?? editor.canonical_name,
      display_brand: (editor.display_brand ?? editor.brand ?? '').trim() || null, aliases: editor.aliases || [],
      keyword_ids: editor.keyword_ids || [], primary_image_url: editor.primary_image_url || null };
    const changes = Object.fromEntries(Object.entries(candidate).filter(([key, value]) => JSON.stringify(value) !== JSON.stringify(original[key])));
    if (!candidate.display_name) { setEditError('표시 상품명을 입력하세요.'); return; }
    if (!Object.keys(changes).length) { setEditError('변경한 표시 정보가 없습니다.'); return; }
    setSaving(true); setEditError('');
    try {
      const saved = await api.updateNormalizedProduct(editor.public_product_id, changes);
      if (saved.public_product_id !== editor.public_product_id) throw new Error('저장 응답의 상품 연결이 일치하지 않습니다.');
      setSavedNotice('표시 정보를 저장했습니다. 공개 웹 반영은 공식 스냅샷 갱신 후 적용됩니다.');
      setEditor(null); setRefresh(v => v + 1);
    } catch (err) { setEditError(err.message || '표시 정보를 저장하지 못했습니다.'); }
    finally { setSaving(false); }
  };
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
    <p>표시명·브랜드·별칭·키워드·이미지·상태를 편집할 수 있습니다. 수량·출처·가격·검토군 변경은 공식 출처 검토 카탈로그 번들을 사용합니다.</p>
    {editError && !editor && <p role="alert">{editError}</p>}
    {savedNotice && <p role="status">{savedNotice}</p>}
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
          onEdit={() => openEditor(product)} editLoading={editLoading} expanded={expanded === product.public_product_id} toggle={() => setExpanded(expanded === product.public_product_id ? null : product.public_product_id)} />)}</tbody>
      </table>}
      <CatalogPagination data={data} page={page} setPage={setPage} />
    </>}
    {editor && <ProductModal modal={{ mode: 'normalized', product: editor }} form={form} setForm={setForm}
      categories={editCategories} keywords={editKeywords} onSave={saveEditor}
      onClose={() => { if (!saving) { setEditor(null); setEditError(''); } }} saving={saving} error={editError} />}
  </div>;
}

function ProductRow({ product, expanded, toggle, onEdit, editLoading }) {
  return <>
    <tr>
      <td>{product.display_name || product.canonical_name}<br /><code>{product.public_product_id}</code></td>
      <td>{product.category_name || '분류명 미확인'}<br /><code>{product.unified_category_id || '분류 ID 미확인'}</code></td>
      <td>{product.is_active === true ? '활성' : product.is_active === false ? '비활성' : '미확인'}</td>
      <td><button onClick={onEdit} disabled={editLoading}>표시 정보 수정</button> <button onClick={toggle}>{expanded ? '규격 접기' : '규격·출처 보기'}</button> <a href={historyLink(product)}>전체 관측 이력</a></td>
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
          <span>출처 규격 원문: {listing.source_unit_text || '미확인'}</span> · <a href={historyLink(product, variant, listing)}>이 출처 관측 이력</a> · <a href={sourceReviewLink(product, variant, listing)}>정식 출처·규격 검토</a>
        </li>)}</ul>
      </section>)}
    </td></tr>}
  </>;
}
