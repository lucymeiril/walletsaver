import { useState, useEffect, useCallback } from 'react';
import { X } from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';
import SearchableSelect from '../../components/SearchableSelect';
import TagInput from '../../components/TagInput';
import { api } from '../../api/client';
import s from './Products.module.css';

export function NormalizedCorrectionForm({product,initialSelection,onBusyChange,onApplied,disabled=false}) {
  const [variantId,setVariantId] = useState(initialSelection?.variantId || '');
  const [listingId,setListingId] = useState(initialSelection?.listingId || '');
  const [eventId,setEventId] = useState('');
  const [history,setHistory] = useState(null);
  const [page,setPage] = useState(1);
  const [binding,setBinding] = useState(null);
  const [draft,setDraft] = useState({reason:'',quantity:'',unit:'',count:'',price:'',specEnabled:false,priceEnabled:false,holdEnabled:false});
  const [preview,setPreview] = useState(null);
  const [previewPayload,setPreviewPayload] = useState(null);
  const [result,setResult] = useState(null);
  const [uncertainApply,setUncertainApply] = useState(false);
  const [busy,setBusy] = useState(false);
  const [loading,setLoading] = useState(false);
  const [error,setError] = useState(null);
  const variant = (product.variants || []).find(row => row.public_variant_id === variantId);
  const listing = variant?.source_listings?.find(row => row.public_source_listing_id === listingId);
  const tuple = {public_variant_id:variantId,public_source_listing_id:listingId,public_offer_event_id:eventId};
  const reviewParams = new URLSearchParams({public_product_id:product.public_product_id,public_variant_id:variantId,public_source_listing_id:listingId,
    source:binding?.source_name || listing?.source_name || '',native_key:binding?.source_record_key || listing?.source_record_key || '',source_url:binding?.source_url || listing?.source_url || ''});
  const setField = (key,value) => {setDraft(previous=>({...previous,[key]:value,...(key==='holdEnabled'&&value?{specEnabled:false,priceEnabled:false}:{})}));setPreview(null);setPreviewPayload(null);setResult(null);};
  const fail = err => setError({message:Array.isArray(err.detail) ? err.detail.map(row=>row.msg || row.message || '입력 검증 실패').join(' · ') : err.message || '출처 교정 요청 실패',detail:err.detail});
  useEffect(() => {
    setHistory(null);setBinding(null);setPreview(null);setPreviewPayload(null);setResult(null);setUncertainApply(false);setEventId('');setError(null);
    if (!variantId || !listingId) return;
    const controller = new AbortController();setLoading(true);
    api.getNormalizedPriceHistory({public_product_id:product.public_product_id,public_variant_id:variantId,public_source_listing_id:listingId,page,per_page:50},{signal:controller.signal})
      .then(data=>{if(!controller.signal.aborted){if(!Array.isArray(data.items))throw new Error('출처 관측 이력 형식 미확인');setHistory(data);}})
      .catch(err=>{if(!controller.signal.aborted)fail(err);}).finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return ()=>controller.abort();
  },[product.public_product_id,variantId,listingId,page]);
  useEffect(() => {
    setBinding(null);setPreview(null);setPreviewPayload(null);setResult(null);setUncertainApply(false);setError(null);
    if (!eventId || !variantId || !listingId) return;
    const controller = new AbortController();setLoading(true);
    api.getNormalizedCorrection(product.public_product_id,tuple,{signal:controller.signal})
      .then(data=>{
        if(controller.signal.aborted)return;
        if(!data.binding_sha256 || !data.stored_specification || Object.entries(tuple).some(([key,value])=>data[key]!=null&&data[key]!==value))throw new Error('교정 원문 연결 정보가 일치하지 않습니다.');
        setBinding(data);const spec=data.stored_specification;
        setDraft({reason:'',quantity:spec.package_quantity??'',unit:spec.package_unit??'',count:spec.bundle_count??'',price:data.stored_quote??'',specEnabled:false,priceEnabled:false,holdEnabled:false});
      }).catch(err=>{if(!controller.signal.aborted)fail(err);}).finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return ()=>controller.abort();
  },[product.public_product_id,variantId,listingId,eventId]);
  const payload = () => {
    if(!binding || !draft.reason.trim())throw new Error('선택한 원문 연결과 교정 사유가 필요합니다.');
    if(!draft.specEnabled&&!draft.priceEnabled&&!draft.holdEnabled)throw new Error('교정할 판매규격 또는 가격을 선택하세요.');
    const data={...tuple,binding_sha256:binding.binding_sha256,reason:draft.reason.trim()};
    if(draft.holdEnabled){if(!binding.quantity_scope_actions?.includes('hold_unresolved')||draft.specEnabled||draft.priceEnabled)throw new Error('수량 범위 보류는 허용된 원문에만 가능하며 숫자 교정과 함께 적용할 수 없습니다.');return {...data,quantity_scope_action:'hold_unresolved'};}
    if(draft.specEnabled){
      const q=Number(draft.quantity),count=Number(draft.count);
      if(String(draft.quantity).trim()===''||!Number.isFinite(q)||q<=0||!draft.unit.trim()||String(draft.count).trim()===''||!Number.isInteger(count)||count<=0)throw new Error('각량·단위·판매개수를 함께 입력하세요. 각량은 양수, 판매개수는 양의 정수여야 합니다.');
      Object.assign(data,{package_quantity:q,package_unit:draft.unit.trim(),bundle_count:count});
    }
    if(draft.priceEnabled){const price=Number(draft.price);if(String(draft.price).trim()===''||!Number.isFinite(price)||price<0)throw new Error('유효한 원문 교정 가격을 입력하세요.');data.price=price;}
    return data;
  };
  const submitPreview = async () => {
    if(uncertainApply)return;
    setError(null);setPreview(null);setPreviewPayload(null);setResult(null);
    let data;try{data=payload();}catch(err){fail(err);return;}
    setBusy(true);onBusyChange?.(true);
    try{const response=await api.previewNormalizedCorrection(product.public_product_id,data);if(typeof response.has_changes!=='boolean'||response.applied===true||response.snapshot_published===true)throw new Error('교정 미리보기 응답을 확인할 수 없습니다. 적용하지 않았습니다.');setPreview(response);setPreviewPayload(data);}
    catch(err){fail(err);}finally{setBusy(false);onBusyChange?.(false);}
  };
  const apply = async () => {
    if(!preview?.has_changes||preview.validation?.ok!==true||!preview.proposal_sha256||!previewPayload)return;
    try{if(JSON.stringify(payload())!==JSON.stringify(previewPayload))throw new Error('입력이 바뀌었습니다. 교정 미리보기를 다시 실행하세요.');}catch(err){fail(err);setPreview(null);return;}
    setBusy(true);onBusyChange?.(true);setError(null);
    try{const response=await api.applyNormalizedCorrection(product.public_product_id,{...previewPayload,expected_proposal_sha256:preview.proposal_sha256});setResult(response);setUncertainApply(false);if(response.applied===true||response.idempotent===true)onApplied?.(response);}
    catch(err){if(['TimeoutError','AbortError'].includes(err.name)){setUncertainApply(true);setError({message:'적용 결과 미확인 — 저장 내역 확인이 필요합니다. 같은 교정 결과만 확인할 수 있으며, 새로운 미리보기는 만들지 않습니다.'});}else{fail(err);setPreview(null);setPreviewPayload(null);}}finally{setBusy(false);onBusyChange?.(false);}
  };
  const previewPrice=typeof preview?.source_price==='number' ? preview.source_price : typeof preview?.source_price?.price==='number' ? preview.source_price.price : null;
  const blocked=disabled||busy||uncertainApply;
  return <details className={s.typedCorrection} open={initialSelection ? true : undefined}>
    <summary>선택 출처 가격·판매규격 교정</summary>
    <p>편집 대상: {product.display_name||product.canonical_name} · {listing?.source_name||'출처 선택 필요'}. 아래 미리보기·정식 적용은 표시 정보 저장과 별도입니다.</p>
    <p>원문 가격·시각·이력은 보존합니다. 교정은 원문과 대조한 해석을 정식 적용하며 새로운 수집 관측을 만들지 않습니다.</p>
    <label>교정 판매규격<select value={variantId} disabled={blocked} onChange={e=>{setVariantId(e.target.value);setListingId('');setPage(1);}}>
      <option value="">규격 선택</option>{(product.variants||[]).map(row=><option key={row.public_variant_id} value={row.public_variant_id}>{row.display_unit||row.variant_name||row.public_variant_id}{row.is_active===false?' · 보존 규격':''}</option>)}</select></label>
    <label>교정 출처<select value={listingId} disabled={blocked||!variant} onChange={e=>{setListingId(e.target.value);setPage(1);}}><option value="">출처 선택</option>{(variant?.source_listings||[]).map(row=><option key={row.public_source_listing_id} value={row.public_source_listing_id}>{row.source_name} · {row.source_title||row.source_record_key}</option>)}</select></label>
    {loading&&<p role="status">선택 출처 근거를 불러오는 중...</p>}
    <label>교정 관측 기록<select value={eventId} disabled={blocked||loading||!history} onChange={e=>setEventId(e.target.value)}><option value="">관측 기록 선택</option>{(history?.items||[]).map(row=><option key={row.public_offer_event_id} value={row.public_offer_event_id}>{row.crawled_at||'시각 미확인'} · {row.observed_quote??row.price??'가격 미확인'} · {row.observation_kind==='source_interpretation_correction'?'교정 해석':'저장 기록'} · …{row.public_offer_event_id.slice(-8)}</option>)}</select></label>
    {history?.total_pages>1&&<div><button type="button" disabled={blocked||loading||page<=1} onClick={()=>setPage(page-1)}>이전 관측 페이지</button> {page}/{history.total_pages} <button type="button" disabled={blocked||loading||page>=history.total_pages} onClick={()=>setPage(page+1)}>다음 관측 페이지</button></div>}
    {listing&&<a href={`/prices?${new URLSearchParams({public_product_id:product.public_product_id,public_variant_id:variantId,public_source_listing_id:listingId})}`}>선택 출처 원가격·전체 관측 이력</a>}
    {error&&<div role="alert"><p>{error.message}</p>{error.detail?.mutation_workflow&&<><p>이 범위는 공통 출처 검토가 필요합니다. 직접 교정을 적용하지 않았습니다.</p><a href={`/inbox?${reviewParams}`}>선택 출처 정식 검토로 이동</a>{error.detail.affected_match_keys&&<p>영향받는 매칭키: {error.detail.affected_match_keys.join(' · ')}</p>}</>}</div>}
    {binding&&<>
      <p>원문: {binding.source_title} · {binding.source_name}</p>
      {binding.source_url&&<a href={binding.source_url} target="_blank" rel="noreferrer">보존 원문 출처</a>}
      <p>저장 규격: {binding.stored_specification.display_unit||'미확인'} · 저장 표시가: {binding.stored_quote??'미확인'} · 관측 시각: {binding.observed_at||'미확인'}</p>
      <details><summary>보존 원문 연결 근거</summary><p>상품 {product.public_product_id} · 규격 {variantId} · 출처 {listingId} · 관측 {eventId} · native {binding.source_record_key}</p><p>binding {binding.binding_sha256}</p>{(binding.source_observations||[]).map(row=><p key={row.raw_record_id}>raw {row.raw_record_id} · {row.raw_payload_sha256}</p>)}</details>
      <div hidden={draft.holdEnabled}>
      <label className={s.checkboxLabel}><input type="checkbox" checked={draft.specEnabled} disabled={blocked||draft.holdEnabled} onChange={e=>setField('specEnabled',e.target.checked)}/>판매규격 교정</label>
      <label>교정 각량<input type="number" step="any" value={draft.quantity} disabled={blocked||!draft.specEnabled} onChange={e=>setField('quantity',e.target.value)}/></label>
      <label>교정 단위<input value={draft.unit} disabled={blocked||!draft.specEnabled} onChange={e=>setField('unit',e.target.value)}/></label>
      <label>교정 판매개수<input type="number" step="1" value={draft.count} disabled={blocked||!draft.specEnabled} onChange={e=>setField('count',e.target.value)}/></label>
      <small>각량·단위·판매개수는 함께 검증합니다. 최소 구매·할인 적용 수령량을 판매개수로 추정하지 않습니다.</small>
      <label className={s.checkboxLabel}><input type="checkbox" checked={draft.priceEnabled} disabled={blocked||draft.holdEnabled} onChange={e=>setField('priceEnabled',e.target.checked)}/>가격 교정</label>
      <label>교정 원문 가격<input type="number" step="any" value={draft.price} disabled={blocked||!draft.priceEnabled} onChange={e=>setField('price',e.target.value)}/></label>
      </div>
      {binding.quantity_scope_actions?.includes('hold_unresolved')&&<><label className={s.checkboxLabel}><input type="checkbox" checked={draft.holdEnabled} disabled={blocked} onChange={e=>setField('holdEnabled',e.target.checked)}/>정확 총수량·단위가 보류</label><small>원문 내용량의 각량·전체 범위가 미확인입니다. 원문 표시가·원문 수량 표기·관측 시각은 보존하며 숫자를 추정하지 않습니다.</small></>}
      <label>교정 사유<textarea value={draft.reason} disabled={blocked} onChange={e=>setField('reason',e.target.value)}/></label>
      <button className={s.saveBtn} type="button" disabled={blocked||loading} onClick={submitPreview}>가격·규격 교정 미리보기</button>
    </>}
    {preview&&<section className={s.formSection} aria-label="출처 교정 미리보기">
      <p>{preview.has_changes?'원문 검증 교정 변경 있음':'변경 없음 · 적용 불필요'}</p>
      {preview.quantity_scope_action==='hold_unresolved' || draft.holdEnabled
        ? <p>보관 규격 원문 유지 · 범위 미확인 / 비교 단가 보류 · 원문 표시가·관측 시각 유지</p>
        : <p>저장 규격 → 원문 검증 규격: {binding?.stored_specification.display_unit||'미확인'} → {preview.source_specification?.display_unit||`${preview.source_specification?.package_quantity??'미확인'}${preview.source_specification?.package_unit||''} × ${preview.source_specification?.bundle_count??'미확인'}`}</p>}
      <p>저장 표시가 → 원문 검증 가격: {binding?.stored_quote??'미확인'} → {previewPrice??'미확인'}</p>
      {preview.has_changes&&<p>{preview.validation?.ok===true?'원문 검증 통과 · 정식 적용 대기':preview.validation?.ok===false?'원문 검증 실패 · 아래 사유 확인':'원문 검증 결과 미확인 · 적용할 수 없습니다.'} · 공개 스냅샷 반영 전</p>}
      {(preview.validation?.errors||[]).map((row,i)=><p key={`error-${i}`} role="alert">{typeof row==='string'?row:row.message||row.msg||'원문 검증 오류'}</p>)}
      {(preview.validation?.warnings||[]).map((row,i)=><p key={`warning-${i}`}>{typeof row==='string'?row:row.message||row.msg||'검토 경고'}</p>)}
      <button className={s.saveBtn} type="button" disabled={disabled||busy||!preview.has_changes||preview.validation?.ok!==true||!preview.proposal_sha256||!!result} onClick={apply}>{uncertainApply?'같은 교정 적용 결과 확인':'검증된 교정 정식 적용'}</button>
    </section>}
    {result&&<><p role="status">{result.applied===true||result.idempotent===true?'교정 정식 적용 완료':'교정 적용 미확인'} · 공개 웹 반영은 관리자의 별도 스냅샷 갱신 후 확인합니다.</p><details><summary>교정 연결·진단</summary><p>새 규격 {result.new_variant_id||'미확인'} · 교정 해석 {result.new_event_id||'미확인'}</p></details></>}
  </details>;
}

const SOURCE_LABELS = {
  all: '전체', emart: '이마트', homeplus: '홈플러스',
  lottemart: '롯데마트', costco: '코스트코', hotdeal: '핫딜', government: '정부데이터',
  algumon: '알구몬', unknown: '알 수 없음', mart_crawl: '마트 크롤',
  community_deal: '커뮤니티 딜', baseline: '기준가', user_submitted: '사용자 등록',
};

const SOURCE_OPTIONS = [
  'unknown', 'algumon', 'hotdeal', 'community', 'community_deal',
  'mart_crawl', 'baseline', 'user_submitted', 'emart', 'homeplus',
  'lottemart', 'costco', 'government', 'musinsa', 'giordano',
];

const CHANNEL_OPTIONS = [
  { value: '', label: '선택 안 함' },
  { value: 'online', label: '온라인' },
  { value: 'offline', label: '오프라인' },
];

/* ─── 유사 상품 섹션 ─── */
function SimilarProducts({ productId }) {
  const [similar, setSimilar] = useState(null);
  useEffect(() => {
    if (!productId) return;
    api.getProductSimilar(productId, 5)
      .then(data => setSimilar(Array.isArray(data) ? data : []))
      .catch(() => setSimilar([]));
  }, [productId]);

  if (!similar || similar.length === 0) return null;
  return (
    <div className={s.comparisonSection}>
      <h4 className={s.chartTitle}>유사 상품 ({similar.length}건)</h4>
      <div className={s.comparisonGrid}>
        {similar.map(item => (
          <div key={item.id} className={s.compCard}>
            <span className={s.compSource}>유사도 {Math.round(item.similarity * 100)}%</span>
            <span className={s.compPrice}>{item.name}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ─── 상세 모달 본문 ─── */
function DetailBody({ product, keywords, onEdit, onDelete }) {
  const [detailHistory, setDetailHistory] = useState(null);
  const [detailComparison, setDetailComparison] = useState(null);

  useEffect(() => {
    if (!product?.id) return;
    Promise.allSettled([
      api.getProductHistory(product.id),
      api.getProductComparison(product.id),
    ]).then(([hist, comp]) => {
      if (hist.status === 'fulfilled') {
        setDetailHistory(Array.isArray(hist.value) ? hist.value : hist.value.history ?? []);
      }
      if (comp.status === 'fulfilled') {
        setDetailComparison(comp.value);
      }
    });
  }, [product?.id]);

  return (
    <div className={s.detail}>
      {product.image_url && (
        <div className={s.detailImage}>
          <img src={product.image_url} alt={product.name} />
        </div>
      )}
      <div className={s.detailGrid}>
        <div><span className={s.label}>카테고리</span><span>{product.category}</span></div>
        <div><span className={s.label}>단위</span><span>{product.unit}</span></div>
        <div><span className={s.label}>현재가</span><span>{product.currentPrice ? `${product.currentPrice.toLocaleString()}원` : '-'}</span></div>
        <div><span className={s.label}>원래가</span><span>{product.originalPrice ? `${product.originalPrice.toLocaleString()}원` : '-'}</span></div>
        <div>
          <span className={s.label}>할인율</span>
          <span className={s.discountBadge}>
            {product.discountRate ? `${product.discountRate.toFixed(1)}%` : '-'}
          </span>
        </div>
        <div>
          <span className={s.label}>소스</span>
          <span>{([...new Set([...(product.sources || []), product.source, product.source_type].filter(Boolean))]).map(src => SOURCE_LABELS[src] || src).join(', ') || '-'}</span>
        </div>
        <div><span className={s.label}>활성 상태</span><span>{product.is_active ? '활성' : '비활성'}</span></div>
      </div>

      {/* 소스별 가격 비교 */}
      {detailComparison && (
        <div className={s.comparisonSection}>
          <h4 className={s.chartTitle}>소스별 가격 비교</h4>
          <div className={s.comparisonGrid}>
            {(Array.isArray(detailComparison) ? detailComparison : detailComparison.comparisons ?? []).map((c, i) => (
              <div key={i} className={s.compCard}>
                <span className={s.compSource}>{SOURCE_LABELS[c.source] || c.source}</span>
                <span className={s.compPrice}>{(c.price ?? 0).toLocaleString()}원</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 가격 이력 차트 */}
      <h4 className={s.chartTitle}>가격 이력 (30일)</h4>
      <div className={s.chartWrap}>
        {detailHistory && detailHistory.length > 0 ? (
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={detailHistory.slice(-30)}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="date" tick={{ fill: 'var(--text3)', fontSize: 11 }} tickFormatter={v => String(v).slice(5)} />
              <YAxis tick={{ fill: 'var(--text3)', fontSize: 11 }} />
              <Tooltip contentStyle={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, color: 'var(--text)' }} />
              <Line type="monotone" dataKey="price" stroke="var(--accent)" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <p className={s.noData}>{detailHistory === null ? '불러오는 중...' : '가격 이력 데이터가 없습니다.'}</p>
        )}
      </div>

      {/* 유사 상품 */}
      <SimilarProducts productId={product.id} />

      {/* 키워드 */}
      {product.keywords?.length > 0 && (
        <div className={s.detailKeywords}>
          <span className={s.label}>키워드</span>
          <div className={s.keywordTags}>
            {product.keywords.map((kw, i) => (
              <span key={i} className={s.keywordTag}>
                {typeof kw === 'string' ? (keywords.find(k => k.id === kw)?.keyword || kw) : kw.keyword}
              </span>
            ))}
          </div>
        </div>
      )}

      <div className={s.detailActions}>
        <button className={s.editBtn} onClick={() => onEdit(product)}>수정하기</button>
        <button className={s.deleteBtn} onClick={() => onDelete(product.id)}>삭제</button>
      </div>
    </div>
  );
}

/* ─── 추가/수정 폼 ─── */
function FormBody({ form, setForm, formKeywords, setFormKeywords, categories, keywords, onSave, onClose, onCreateCategory, addKeyword }) {
  const handleCategoryChange = (id, name) => {
    setForm(prev => ({ ...prev, category: name, categoryId: id }));
  };

  const searchKeywordsApi = useCallback(async (q) => {
    try {
      const results = await api.searchKeywords(q);
      const arr = Array.isArray(results) ? results : results?.keywords ?? results?.data ?? [];
      return arr.map(kw => ({ ...kw, keyword: kw.keyword || kw.word || '' }));
    } catch {
      const q2 = q.toLowerCase();
      return keywords.filter(kw => (kw.keyword || kw.word || '').toLowerCase().includes(q2));
    }
  }, [keywords]);

  const handleCreateKeyword = useCallback(async (word) => {
    await addKeyword({ word, category_id: form.categoryId || null });
  }, [addKeyword, form.categoryId]);

  return (
    <div className={s.form}>
      <label>이름<input value={form.name || ''} onChange={e => setForm({ ...form, name: e.target.value })} /></label>
      <label>
        카테고리
        <SearchableSelect
          categories={categories}
          value={form.categoryId || form.category}
          onChange={handleCategoryChange}
          onCreateCategory={onCreateCategory}
        />
      </label>
      <label>단위<input value={form.unit || ''} onChange={e => setForm({ ...form, unit: e.target.value })} /></label>
      <label>
        소스 타입
        <select value={form.source_type || 'unknown'} onChange={e => setForm({ ...form, source_type: e.target.value })}>
          {SOURCE_OPTIONS.map(src => <option key={src} value={src}>{SOURCE_LABELS[src] || src}</option>)}
        </select>
      </label>
      <label>설명<input value={form.description || ''} onChange={e => setForm({ ...form, description: e.target.value })} /></label>
      <label>이미지 URL<input value={form.image_url || ''} onChange={e => setForm({ ...form, image_url: e.target.value })} /></label>
      <label>
        속성(JSON)
        <textarea
          rows={4}
          value={form.attributes_json || ''}
          placeholder='{"brand":"", "size":""}'
          onChange={e => setForm({ ...form, attributes_json: e.target.value })}
        />
      </label>
      <label className={s.checkboxLabel}>
        <input
          type="checkbox"
          checked={form.is_active !== false}
          onChange={e => setForm({ ...form, is_active: e.target.checked })}
        />
        활성 상품
      </label>
      <label>
        키워드
        <TagInput
          value={formKeywords}
          onChange={setFormKeywords}
          onSearch={searchKeywordsApi}
          onCreateKeyword={handleCreateKeyword}
        />
      </label>
      <fieldset className={s.formSection}>
        <legend>현재 행사/가격 정보</legend>
        <div className={s.formGrid}>
          <label>
            판매처/소스
            <input
              list="offer-source-options"
              value={form.offer_source || form.source || ''}
              placeholder="예: algumon, emart, 이마트 성수점"
              onChange={e => setForm({ ...form, offer_source: e.target.value })}
            />
            <datalist id="offer-source-options">
              {SOURCE_OPTIONS.map(src => <option key={src} value={src}>{SOURCE_LABELS[src] || src}</option>)}
            </datalist>
          </label>
          <label>
            채널
            <select value={form.channel || ''} onChange={e => setForm({ ...form, channel: e.target.value })}>
              {CHANNEL_OPTIONS.map(opt => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
            </select>
          </label>
          <label>현재/행사가<input type="number" min="1" step="1" value={form.current_price || ''} onChange={e => setForm({ ...form, current_price: e.target.value })} /></label>
          <label>원래가<input type="number" min="1" step="1" value={form.original_price || ''} onChange={e => setForm({ ...form, original_price: e.target.value })} /></label>
          <label>
            할인율(%)
            <input
              type="number"
              min="0"
              max="100"
              step="0.1"
              disabled={!form.discount_rate_manual}
              placeholder={form.discount_rate_manual ? '예: 25' : '원래가/현재가로 자동 계산'}
              value={form.discount_rate || ''}
              onChange={e => setForm({ ...form, discount_rate: e.target.value })}
            />
          </label>
          <label className={s.checkboxLabel}>
            <input
              type="checkbox"
              checked={!!form.discount_rate_manual}
              onChange={e => setForm({ ...form, discount_rate_manual: e.target.checked, discount_rate: e.target.checked ? form.discount_rate : '' })}
            />
            할인율 수동 입력
          </label>
          <label>행사 시작일<input type="date" value={form.valid_from || ''} onChange={e => setForm({ ...form, valid_from: e.target.value })} /></label>
          <label>행사 종료일<input type="date" value={form.valid_to || ''} onChange={e => setForm({ ...form, valid_to: e.target.value })} /></label>
          <label>원본 URL<input value={form.source_url || ''} onChange={e => setForm({ ...form, source_url: e.target.value })} /></label>
          <label>수량/규격<input value={form.quantity || ''} placeholder="예: 1+1, 2kg, 10개입" onChange={e => setForm({ ...form, quantity: e.target.value })} /></label>
        </div>
        <label>
          가격 메모/원문
          <textarea
            rows={3}
            value={form.offer_notes || ''}
            placeholder="오프라인 전단 내용, 지점명, 확인 메모 등"
            onChange={e => setForm({ ...form, offer_notes: e.target.value })}
          />
        </label>
        <label>
          행사 raw_data(JSON)
          <textarea
            rows={3}
            value={form.offer_raw_data_json || ''}
            placeholder='{"store":"이마트 성수점"}'
            onChange={e => setForm({ ...form, offer_raw_data_json: e.target.value })}
          />
        </label>
      </fieldset>
      <div className={s.formActions}>
        <button className={s.cancelBtn} onClick={onClose}>취소</button>
        <button className={s.saveBtn} onClick={onSave}>저장</button>
      </div>
    </div>
  );
}

function NormalizedMetadataForm({ form, setForm, product, categories, keywords, onSave, onClose, saving, error,correctionSelection,onCorrectionBusy,onCorrectionApplied }) {
  const setField = (field, value) => setForm(previous => ({ ...previous, [field]: value }));
  return <div className={s.form}>
    <p>출처 상품명: {product.canonical_name} · 수량·출처·가격 이력은 보존됩니다.</p>
    {product.group_display_name && <p>검토군 표시명: {product.group_display_name} · 표시명·브랜드는 연결된 검토군에 함께 적용됩니다. 검토군 분류 변경은 공식 번들을 사용합니다.</p>}
    {error && <p role="alert">{error}</p>}
    <details open={!correctionSelection}><summary>표시 정보 편집 · 이름·브랜드·분류</summary>
    <label>표시 상품명<input value={form.display_name || ''} onChange={e => setField('display_name', e.target.value)} disabled={saving} /></label>
    <label>표시 브랜드<input value={form.display_brand || ''} onChange={e => setField('display_brand', e.target.value)} disabled={saving} /></label>
    <label>통합 분류<SearchableSelect categories={categories} value={form.unified_category_id}
      onChange={id => { if (!saving) setField('unified_category_id', id); }} /></label>
    <label>별칭 (한 줄에 하나)<textarea rows={3} value={form.aliases || ''} onChange={e => setField('aliases', e.target.value)} disabled={saving} /></label>
    <label>기존 분류 키워드<select multiple value={(form.keyword_ids || []).map(String)} disabled={saving}
      onChange={e => setField('keyword_ids', [...e.target.selectedOptions].map(option => Number(option.value)))}>
      {keywords.map(keyword => <option key={keyword.id} value={keyword.id}>{keyword.word || keyword.keyword || `키워드 ${keyword.id}`}{keyword.is_active === false ? ' (기존 비활성 연결)' : ''}</option>)}
    </select></label>
    <small>기존 활성 분류 키워드만 연결합니다. 선택을 모두 해제하면 연결이 해제됩니다.</small>
    <label>대표 이미지 URL<input type="url" value={form.primary_image_url || ''} onChange={e => setField('primary_image_url', e.target.value)} disabled={saving} /></label>
    <label className={s.checkboxLabel}><input type="checkbox" checked={form.is_active === true} disabled={saving}
      onChange={e => setField('is_active', e.target.checked)} />활성 상품</label>
    </details>
    <NormalizedCorrectionForm product={product} initialSelection={correctionSelection} onBusyChange={onCorrectionBusy} onApplied={onCorrectionApplied} disabled={saving}/>
    <div className={`${s.formActions} ${s.normalizedActions}`}><button className={s.cancelBtn} onClick={onClose} disabled={saving}>취소</button>
      <button className={s.saveBtn} onClick={onSave} disabled={saving}>{saving ? '표시 정보 저장 중...' : '표시 정보 저장'}</button></div>
  </div>;
}

/* ─── 메인 모달 래퍼 ─── */
export default function ProductModal({
  modal, onClose,
  form, setForm,
  formKeywords, setFormKeywords,
  categories, keywords,
  onSave, onEdit, onDelete,
  onCreateCategory, addKeyword, saving = false, error = '',onCorrectionApplied,
}) {
  const [correctionBusy,setCorrectionBusy] = useState(false);
  if (!modal) return null;
  const safeClose=()=>{if(!saving&&!correctionBusy)onClose();};

  const title = modal.mode === 'add' ? '상품 추가'
    : modal.mode === 'normalized' ? '상품 표시 정보 · 출처 교정'
    : modal.mode === 'edit' ? '상품 수정'
    : modal.product.name;

  return (
    <div className={s.overlay} onClick={safeClose}>
      <div className={`${s.modal} ${modal.mode === 'normalized' ? s.normalizedModal : ''}`} onClick={e => e.stopPropagation()}>
        <div className={s.modalHeader}>
          <div><h3>{title}</h3>{modal.mode==='normalized'&&<p>{modal.product.display_name||modal.product.canonical_name}</p>}</div>
          <button onClick={safeClose} disabled={saving||correctionBusy}><X size={18} /></button>
        </div>
        {modal.mode === 'normalized' ? (
          <NormalizedMetadataForm form={form} setForm={setForm} product={modal.product} categories={categories}
            keywords={keywords} onSave={onSave} onClose={safeClose} saving={saving||correctionBusy} error={error}
            correctionSelection={modal.correctionSelection} onCorrectionBusy={setCorrectionBusy} onCorrectionApplied={onCorrectionApplied}/>
        ) : modal.mode === 'detail' ? (
          <DetailBody
            product={modal.product}
            keywords={keywords}
            onEdit={onEdit}
            onDelete={onDelete}
          />
        ) : (
          <FormBody
            form={form}
            setForm={setForm}
            formKeywords={formKeywords}
            setFormKeywords={setFormKeywords}
            categories={categories}
            keywords={keywords}
            onSave={onSave}
            onClose={onClose}
            onCreateCategory={onCreateCategory}
            addKeyword={addKeyword}
          />
        )}
      </div>
    </div>
  );
}

/* ─── 벌크 카테고리 모달 ─── */
export function BulkCategoryModal({ open, onClose, categories, bulkCatId, setBulkCatId, onApply, selectedCount, onCreateCategory }) {
  if (!open) return null;
  return (
    <div className={s.overlay} onClick={onClose}>
      <div className={s.modal} onClick={e => e.stopPropagation()} style={{ maxWidth: 420 }}>
        <div className={s.modalHeader}>
          <h3>카테고리 일괄 변경</h3>
          <button onClick={onClose}><X size={18} /></button>
        </div>
        <div className={s.form}>
          <label>
            새 카테고리
            <SearchableSelect
              categories={categories}
              value={bulkCatId}
              onChange={(id) => setBulkCatId(id)}
              onCreateCategory={onCreateCategory}
            />
          </label>
          <div className={s.formActions}>
            <button className={s.cancelBtn} onClick={onClose}>취소</button>
            <button className={s.saveBtn} onClick={onApply}>적용 ({selectedCount}개)</button>
          </div>
        </div>
      </div>
    </div>
  );
}
