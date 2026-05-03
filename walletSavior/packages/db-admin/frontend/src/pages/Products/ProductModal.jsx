import { useState, useEffect, useCallback } from 'react';
import { X } from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';
import SearchableSelect from '../../components/SearchableSelect';
import TagInput from '../../components/TagInput';
import { api } from '../../api/client';
import s from './Products.module.css';

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
        <div><span className={s.label}>현재가</span><span>{(product.currentPrice ?? 0).toLocaleString()}원</span></div>
        <div><span className={s.label}>원래가</span><span>{(product.originalPrice ?? 0).toLocaleString()}원</span></div>
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

/* ─── 메인 모달 래퍼 ─── */
export default function ProductModal({
  modal, onClose,
  form, setForm,
  formKeywords, setFormKeywords,
  categories, keywords,
  onSave, onEdit, onDelete,
  onCreateCategory, addKeyword,
}) {
  if (!modal) return null;

  const title = modal.mode === 'add' ? '상품 추가'
    : modal.mode === 'edit' ? '상품 수정'
    : modal.product.name;

  return (
    <div className={s.overlay} onClick={onClose}>
      <div className={s.modal} onClick={e => e.stopPropagation()}>
        <div className={s.modalHeader}>
          <h3>{title}</h3>
          <button onClick={onClose}><X size={18} /></button>
        </div>
        {modal.mode === 'detail' ? (
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
