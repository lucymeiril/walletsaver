import { useState, useMemo, useEffect, useCallback } from 'react';
import { Plus, Pencil, Trash2, X, Search, ChevronLeft, ChevronRight, ChevronDown, ChevronUp, ArrowUpDown, Check, Package, AlertTriangle } from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';
import useDbAdminStore from '../../stores/dbAdminStore';
import SearchableSelect from '../../components/SearchableSelect';
import TagInput from '../../components/TagInput';
import { api } from '../../api/client';
import s from './Products.module.css';

const TIER_LABEL = { ultra: '초특가', great: '특가', good: '적정', wait: '관망', bad: '비쌈' };
const TIER_CLASS = { ultra: 'tierUltra', great: 'tierGreat', good: 'tierGood', wait: 'tierWait', bad: 'tierBad' };

const SOURCE_LABELS = {
  all: '전체',
  emart: '이마트',
  homeplus: '홈플러스',
  lottemart: '롯데마트',
  costco: '코스트코',
  hotdeal: '핫딜',
  government: '정부데이터',
};

const SORT_OPTIONS = [
  { value: 'name', label: '이름순' },
  { value: 'price', label: '가격순' },
  { value: 'discount_rate', label: '할인율순' },
  { value: 'created_at', label: '등록일순' },
];

export default function Products() {
  const {
    products, addProduct, updateProduct, deleteProduct,
    bulkDeleteProducts, bulkUpdateCategory,
    fetchProducts, loading, error,
    productStats, fetchProductStats,
    productPagination,
    categories, fetchCategories, addCategory,
    keywords, fetchKeywords, addKeyword,
  } = useDbAdminStore();

  const [search, setSearch] = useState('');
  const [sourceFilter, setSourceFilter] = useState('all');
  const [catFilter, setCatFilter] = useState('');
  const [sortBy, setSortBy] = useState('name');
  const [sortDir, setSortDir] = useState('asc');
  const [page, setPage] = useState(1);
  const [modal, setModal] = useState(null);
  const [form, setForm] = useState({});
  const [formKeywords, setFormKeywords] = useState([]);
  const [selected, setSelected] = useState(new Set());
  const [expandedRow, setExpandedRow] = useState(null);
  const [rowHistory, setRowHistory] = useState(null);
  const [detailHistory, setDetailHistory] = useState(null);
  const [detailComparison, setDetailComparison] = useState(null);
  const [bulkCatModal, setBulkCatModal] = useState(false);
  const [bulkCatId, setBulkCatId] = useState('');

  const doFetch = useCallback((overrides = {}) => {
    const params = {};
    const src = overrides.source ?? sourceFilter;
    if (src && src !== 'all') params.source = src;
    if (overrides.category ?? catFilter) params.category = overrides.category ?? catFilter;
    if (overrides.search ?? search) params.search = overrides.search ?? search;
    params.sort_by = overrides.sort_by ?? sortBy;
    params.sort_dir = overrides.sort_dir ?? sortDir;
    params.page = overrides.page ?? page;
    params.per_page = 20;
    fetchProducts(params);
  }, [sourceFilter, catFilter, search, sortBy, sortDir, page, fetchProducts]);

  useEffect(() => {
    doFetch();
    fetchProductStats();
    fetchCategories();
    fetchKeywords();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    doFetch();
    setSelected(new Set());
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceFilter, catFilter, sortBy, sortDir, page]);

  const handleSearch = () => {
    setPage(1);
    doFetch({ page: 1 });
  };

  const handleSearchKey = (e) => {
    if (e.key === 'Enter') handleSearch();
  };

  const toggleSort = (col) => {
    if (sortBy === col) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    } else {
      setSortBy(col);
      setSortDir('asc');
    }
    setPage(1);
  };

  // Selection
  const allOnPageSelected = products.length > 0 && products.every(p => selected.has(p.id));
  const toggleSelectAll = () => {
    if (allOnPageSelected) {
      setSelected(new Set());
    } else {
      setSelected(new Set(products.map(p => p.id)));
    }
  };
  const toggleSelect = (id) => {
    setSelected(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  // Bulk actions
  const handleBulkDelete = async () => {
    if (!confirm(`선택한 ${selected.size}개 상품을 삭제하시겠습니까?`)) return;
    await bulkDeleteProducts([...selected]);
    setSelected(new Set());
    fetchProductStats();
  };

  const handleBulkCategory = async () => {
    if (!bulkCatId) return;
    await bulkUpdateCategory([...selected], bulkCatId);
    setBulkCatModal(false);
    setBulkCatId('');
    setSelected(new Set());
    fetchProductStats();
  };

  // Expand row
  const toggleExpand = async (id) => {
    if (expandedRow === id) {
      setExpandedRow(null);
      setRowHistory(null);
      return;
    }
    setExpandedRow(id);
    try {
      const hist = await api.getProductHistory(id);
      setRowHistory(Array.isArray(hist) ? hist : hist.history ?? []);
    } catch {
      setRowHistory([]);
    }
  };

  // Modal actions
  const openAdd = () => {
    setForm({ name: '', category: '', categoryId: '', unit: '', basePrice: '', currentAvg: '', tier: 'good' });
    setFormKeywords([]);
    setModal({ mode: 'add' });
  };

  const openEdit = (p) => {
    setForm({
      ...p,
      categoryId: p.category_id || '',
      basePrice: String(p.basePrice || p.originalPrice || ''),
      currentAvg: String(p.currentAvg || p.currentPrice || ''),
    });
    const productKws = (p.keywords || []).map(k =>
      typeof k === 'string'
        ? { id: k, keyword: keywords.find(kw => kw.id === k)?.keyword || k }
        : k,
    );
    setFormKeywords(productKws);
    setModal({ mode: 'edit', product: p });
  };

  const openDetail = async (p) => {
    setModal({ mode: 'detail', product: p });
    setDetailHistory(null);
    setDetailComparison(null);
    try {
      const [hist, comp] = await Promise.allSettled([
        api.getProductHistory(p.id),
        api.getProductComparison(p.id),
      ]);
      if (hist.status === 'fulfilled') {
        setDetailHistory(Array.isArray(hist.value) ? hist.value : hist.value.history ?? []);
      }
      if (comp.status === 'fulfilled') {
        setDetailComparison(comp.value);
      }
    } catch { /* ignore */ }
  };

  const handleSave = async () => {
    const data = {
      name: form.name,
      category_id: form.categoryId || null,
      unit: form.unit,
      description: form.description || null,
      image_url: form.image_url || null,
    };
    if (modal.mode === 'add') await addProduct(data);
    else await updateProduct(modal.product.id, data);

    if (form.categoryId && formKeywords.length > 0) {
      for (const kw of formKeywords) {
        if (String(kw.id).startsWith('kw-new-')) continue;
        try {
          await api.updateKeyword(kw.id, { category_id: form.categoryId });
        } catch { /* best-effort */ }
      }
    }

    setModal(null);
    fetchProductStats();
  };

  const handleDelete = async (id) => {
    if (confirm('정말 삭제하시겠습니까?')) {
      await deleteProduct(id);
      setModal(null);
      fetchProductStats();
    }
  };

  const handleCategoryChange = (id, name) => {
    setForm(prev => ({ ...prev, category: name, categoryId: id }));
  };

  const handleCreateCategory = async (parentId, catData) => {
    await addCategory(parentId, catData);
  };

  const searchKeywordsApi = useCallback(async (q) => {
    try {
      const results = await api.searchKeywords(q);
      const arr = Array.isArray(results) ? results : results?.keywords ?? results?.data ?? [];
      return arr.map(kw => ({
        ...kw,
        keyword: kw.keyword || kw.word || '',
      }));
    } catch {
      const q2 = q.toLowerCase();
      return keywords.filter(kw => (kw.keyword || kw.word || '').toLowerCase().includes(q2));
    }
  }, [keywords]);

  const handleCreateKeyword = useCallback(async (word) => {
    await addKeyword({ word, category_id: form.categoryId || null });
  }, [addKeyword, form.categoryId]);

  const { total, total_pages } = productPagination;

  const SortIcon = ({ col }) => {
    if (sortBy !== col) return <ArrowUpDown size={12} className={s.sortIconInactive} />;
    return sortDir === 'asc' ? <ChevronUp size={12} /> : <ChevronDown size={12} />;
  };

  return (
    <div className={s.page}>
      <div className={s.header}>
        <h2 className={s.title}>상품 관리</h2>
        <button className={s.addBtn} onClick={openAdd}><Plus size={16} /> 상품 추가</button>
      </div>

      {/* 통계 요약 */}
      {productStats && (
        <div className={s.statsBar}>
          <div className={s.statCard}>
            <span className={s.statLabel}>전체 상품</span>
            <span className={s.statValue}>{productStats.total?.toLocaleString() ?? 0}</span>
          </div>
          {Object.entries(productStats.by_source || {}).map(([src, cnt]) => (
            <div key={src} className={s.statCard}>
              <span className={s.statLabel}>{SOURCE_LABELS[src] || src}</span>
              <span className={s.statValue}>{cnt}</span>
              {productStats.last_crawl?.[src] && (
                <span className={s.statMini}>
                  최근: {new Date(productStats.last_crawl[src]).toLocaleDateString('ko-KR')}
                </span>
              )}
            </div>
          ))}
          {(productStats.by_category || []).slice(0, 5).map(cat => (
            <div key={cat.name} className={s.statCard}>
              <span className={s.statLabel}>{cat.name}</span>
              <span className={s.statValue}>{cat.count}</span>
            </div>
          ))}
        </div>
      )}

      {/* 소스 필터 탭 */}
      <div className={s.sourceTabs}>
        {Object.entries(SOURCE_LABELS).map(([key, label]) => (
          <button
            key={key}
            className={`${s.sourceTab} ${sourceFilter === key ? s.sourceTabActive : ''}`}
            onClick={() => { setSourceFilter(key); setPage(1); }}
          >
            {label}
            {key !== 'all' && productStats?.by_source?.[key] != null && (
              <span className={s.tabBadge}>{productStats.by_source[key]}</span>
            )}
            {key === 'all' && productStats && (
              <span className={s.tabBadge}>{productStats.total ?? 0}</span>
            )}
          </button>
        ))}
      </div>

      {/* 필터 / 검색 / 정렬 */}
      <div className={s.filters}>
        <div className={s.searchWrap}>
          <Search size={16} className={s.searchIcon} />
          <input
            className={s.searchInput}
            placeholder="상품명 검색..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            onKeyDown={handleSearchKey}
          />
          <button className={s.searchBtn} onClick={handleSearch}>검색</button>
        </div>
        <select className={s.select} value={catFilter} onChange={e => { setCatFilter(e.target.value); setPage(1); }}>
          <option value="">전체 카테고리</option>
          {(productStats?.by_category || []).map(c => (
            <option key={c.name} value={c.name}>{c.name} ({c.count})</option>
          ))}
        </select>
        <select className={s.select} value={`${sortBy}-${sortDir}`} onChange={e => {
          const [sb, sd] = e.target.value.split('-');
          setSortBy(sb);
          setSortDir(sd);
          setPage(1);
        }}>
          {SORT_OPTIONS.map(opt => (
            <optgroup key={opt.value} label={opt.label}>
              <option value={`${opt.value}-asc`}>{opt.label} ↑</option>
              <option value={`${opt.value}-desc`}>{opt.label} ↓</option>
            </optgroup>
          ))}
        </select>
      </div>

      {/* 벌크 액션 바 */}
      {selected.size > 0 && (
        <div className={s.bulkBar}>
          <span className={s.bulkCount}>{selected.size}개 선택됨</span>
          <button className={s.bulkBtn} onClick={handleBulkDelete}>
            <Trash2 size={14} /> 일괄 삭제
          </button>
          <button className={s.bulkBtn} onClick={() => setBulkCatModal(true)}>
            <Package size={14} /> 카테고리 변경
          </button>
          <button className={s.bulkCancelBtn} onClick={() => setSelected(new Set())}>선택 해제</button>
        </div>
      )}

      {/* 에러 상태 */}
      {error && (
        <div className={s.errorState}>
          <AlertTriangle size={20} />
          <span>{error}</span>
        </div>
      )}

      {/* 로딩 */}
      {loading && <div className={s.loadingBar}>불러오는 중...</div>}

      {/* 데이터 없음 */}
      {!loading && !error && products.length === 0 && (
        <div className={s.emptyState}>
          <Package size={40} />
          <p>데이터 없음</p>
          <span>등록된 상품이 없습니다. 상품을 추가하거나 크롤링을 실행하세요.</span>
        </div>
      )}

      {/* 테이블 */}
      {products.length > 0 && (
        <>
          <div className={s.tableWrap}>
            <table className={s.table}>
              <thead>
                <tr>
                  <th className={s.checkCol}>
                    <input type="checkbox" checked={allOnPageSelected} onChange={toggleSelectAll} />
                  </th>
                  <th className={s.sortableCol} onClick={() => toggleSort('name')}>
                    이름 <SortIcon col="name" />
                  </th>
                  <th>카테고리</th>
                  <th>단위</th>
                  <th className={s.sortableCol} onClick={() => toggleSort('price')}>
                    현재가 <SortIcon col="price" />
                  </th>
                  <th>원래가</th>
                  <th className={s.sortableCol} onClick={() => toggleSort('discount_rate')}>
                    할인율 <SortIcon col="discount_rate" />
                  </th>
                  <th>소스</th>
                  <th>관리</th>
                </tr>
              </thead>
              <tbody>
                {products.map(p => (
                  <ProductRow
                    key={p.id}
                    p={p}
                    selected={selected.has(p.id)}
                    onToggleSelect={() => toggleSelect(p.id)}
                    expanded={expandedRow === p.id}
                    onToggleExpand={() => toggleExpand(p.id)}
                    rowHistory={expandedRow === p.id ? rowHistory : null}
                    onDetail={() => openDetail(p)}
                    onEdit={() => openEdit(p)}
                    onDelete={() => handleDelete(p.id)}
                    s={s}
                  />
                ))}
              </tbody>
            </table>
          </div>

          {/* 페이지네이션 */}
          <div className={s.pagination}>
            <span className={s.count}>총 {total.toLocaleString()}개 상품</span>
            <div className={s.pageControls}>
              <button
                className={s.pageBtn}
                disabled={page <= 1}
                onClick={() => setPage(p => p - 1)}
              >
                <ChevronLeft size={16} />
              </button>
              <span className={s.pageInfo}>{page} / {total_pages}</span>
              <button
                className={s.pageBtn}
                disabled={page >= total_pages}
                onClick={() => setPage(p => p + 1)}
              >
                <ChevronRight size={16} />
              </button>
            </div>
          </div>
        </>
      )}

      {/* 벌크 카테고리 변경 모달 */}
      {bulkCatModal && (
        <div className={s.overlay} onClick={() => setBulkCatModal(false)}>
          <div className={s.modal} onClick={e => e.stopPropagation()} style={{ maxWidth: 420 }}>
            <div className={s.modalHeader}>
              <h3>카테고리 일괄 변경</h3>
              <button onClick={() => setBulkCatModal(false)}><X size={18} /></button>
            </div>
            <div className={s.form}>
              <label>
                새 카테고리
                <SearchableSelect
                  categories={categories}
                  value={bulkCatId}
                  onChange={(id) => setBulkCatId(id)}
                  onCreateCategory={handleCreateCategory}
                />
              </label>
              <div className={s.formActions}>
                <button className={s.cancelBtn} onClick={() => setBulkCatModal(false)}>취소</button>
                <button className={s.saveBtn} onClick={handleBulkCategory}>적용 ({selected.size}개)</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 상세/추가/수정 모달 */}
      {modal && (
        <div className={s.overlay} onClick={() => setModal(null)}>
          <div className={s.modal} onClick={e => e.stopPropagation()}>
            <div className={s.modalHeader}>
              <h3>{modal.mode === 'add' ? '상품 추가' : modal.mode === 'edit' ? '상품 수정' : modal.product.name}</h3>
              <button onClick={() => setModal(null)}><X size={18} /></button>
            </div>

            {modal.mode === 'detail' ? (
              <div className={s.detail}>
                {modal.product.image_url && (
                  <div className={s.detailImage}>
                    <img src={modal.product.image_url} alt={modal.product.name} />
                  </div>
                )}
                <div className={s.detailGrid}>
                  <div><span className={s.label}>카테고리</span><span>{modal.product.category}</span></div>
                  <div><span className={s.label}>단위</span><span>{modal.product.unit}</span></div>
                  <div><span className={s.label}>현재가</span><span>{(modal.product.currentPrice ?? 0).toLocaleString()}원</span></div>
                  <div><span className={s.label}>원래가</span><span>{(modal.product.originalPrice ?? 0).toLocaleString()}원</span></div>
                  <div>
                    <span className={s.label}>할인율</span>
                    <span className={s.discountBadge}>
                      {modal.product.discountRate ? `${modal.product.discountRate.toFixed(1)}%` : '-'}
                    </span>
                  </div>
                  <div>
                    <span className={s.label}>소스</span>
                    <span>{(modal.product.sources || []).map(src => SOURCE_LABELS[src] || src).join(', ') || modal.product.source || '-'}</span>
                  </div>
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
                    <p className={s.noData}>가격 이력 데이터가 없습니다.</p>
                  )}
                </div>

                {modal.product.keywords?.length > 0 && (
                  <div className={s.detailKeywords}>
                    <span className={s.label}>키워드</span>
                    <div className={s.keywordTags}>
                      {modal.product.keywords.map((kw, i) => (
                        <span key={i} className={s.keywordTag}>
                          {typeof kw === 'string' ? (keywords.find(k => k.id === kw)?.keyword || kw) : kw.keyword}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                <div className={s.detailActions}>
                  <button className={s.editBtn} onClick={() => openEdit(modal.product)}>수정하기</button>
                  <button className={s.deleteBtn} onClick={() => handleDelete(modal.product.id)}>삭제</button>
                </div>
              </div>
            ) : (
              <div className={s.form}>
                <label>이름<input value={form.name || ''} onChange={e => setForm({ ...form, name: e.target.value })} /></label>
                <label>
                  카테고리
                  <SearchableSelect
                    categories={categories}
                    value={form.categoryId || form.category}
                    onChange={handleCategoryChange}
                    onCreateCategory={handleCreateCategory}
                  />
                </label>
                <label>단위<input value={form.unit || ''} onChange={e => setForm({ ...form, unit: e.target.value })} /></label>
                <label>설명<input value={form.description || ''} onChange={e => setForm({ ...form, description: e.target.value })} /></label>
                <label>이미지 URL<input value={form.image_url || ''} onChange={e => setForm({ ...form, image_url: e.target.value })} /></label>
                <label>
                  키워드
                  <TagInput
                    value={formKeywords}
                    onChange={setFormKeywords}
                    onSearch={searchKeywordsApi}
                    onCreateKeyword={handleCreateKeyword}
                  />
                </label>
                <div className={s.formActions}>
                  <button className={s.cancelBtn} onClick={() => setModal(null)}>취소</button>
                  <button className={s.saveBtn} onClick={handleSave}>저장</button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function ProductRow({ p, selected, onToggleSelect, expanded, onToggleExpand, rowHistory, onDetail, onEdit, onDelete, s }) {
  return (
    <>
      <tr className={`${s.row} ${selected ? s.rowSelected : ''}`}>
        <td className={s.checkCol} onClick={e => e.stopPropagation()}>
          <input type="checkbox" checked={selected} onChange={onToggleSelect} />
        </td>
        <td className={s.nameCol} onClick={onDetail}>
          <div className={s.nameWrap}>
            {p.image_url && <img src={p.image_url} alt="" className={s.thumbImg} />}
            <span>{p.name}</span>
          </div>
        </td>
        <td onClick={onDetail}>{p.category}</td>
        <td onClick={onDetail}>{p.unit}</td>
        <td onClick={onDetail}>{p.currentPrice ? `${p.currentPrice.toLocaleString()}원` : '-'}</td>
        <td onClick={onDetail}>{p.originalPrice ? `${p.originalPrice.toLocaleString()}원` : '-'}</td>
        <td onClick={onDetail}>
          {p.discountRate ? (
            <span className={s.discountBadge}>{p.discountRate.toFixed(1)}%</span>
          ) : '-'}
        </td>
        <td onClick={onDetail}>
          <div className={s.sourceTags}>
            {(p.sources || (p.source ? [p.source] : [])).map(src => (
              <span key={src} className={s.sourceTag}>{SOURCE_LABELS[src] || src}</span>
            ))}
          </div>
        </td>
        <td>
          <div className={s.actions} onClick={e => e.stopPropagation()}>
            <button className={s.iconBtn} onClick={onToggleExpand} title="가격 이력">
              {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </button>
            <button className={s.iconBtn} onClick={onEdit} title="수정"><Pencil size={14} /></button>
            <button className={s.iconBtn} onClick={onDelete} title="삭제"><Trash2 size={14} /></button>
          </div>
        </td>
      </tr>
      {expanded && (
        <tr className={s.expandedRow}>
          <td colSpan={9}>
            <div className={s.expandedContent}>
              <h4 className={s.expandTitle}>가격 이력 (30일)</h4>
              {rowHistory && rowHistory.length > 0 ? (
                <div style={{ height: 160 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={rowHistory.slice(-30)}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                      <XAxis dataKey="date" tick={{ fill: 'var(--text3)', fontSize: 10 }} tickFormatter={v => String(v).slice(5)} />
                      <YAxis tick={{ fill: 'var(--text3)', fontSize: 10 }} />
                      <Tooltip contentStyle={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, color: 'var(--text)' }} />
                      <Line type="monotone" dataKey="price" stroke="var(--accent)" strokeWidth={2} dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <p className={s.noData}>{rowHistory === null ? '불러오는 중...' : '가격 이력이 없습니다.'}</p>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
