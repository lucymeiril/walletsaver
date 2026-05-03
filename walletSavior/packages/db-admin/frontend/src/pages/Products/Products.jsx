import { useState, useEffect, useCallback } from 'react';
import { Plus, Package, AlertTriangle, Database } from 'lucide-react';
import useDbAdminStore from '../../stores/dbAdminStore';
import { api } from '../../api/client';
import { useAbortController } from '../../hooks/useAbortController';
import LastUpdated from '../../components/LastUpdated';
import ProductStats from './ProductStats';
import ProductFilters from './ProductFilters';
import ProductTable from './ProductTable';
import ProductModal, { BulkCategoryModal } from './ProductModal';
import AdminResetModal from './AdminResetModal';
import s from './Products.module.css';

export default function Products() {
  const {
    products, addProduct, updateProduct, deleteProduct,
    bulkDeleteProducts, bulkUpdateCategory,
    fetchProducts, loadingProducts, error,
    productStats, fetchProductStats,
    productPagination,
    categories, fetchCategories, addCategory,
    keywords, fetchKeywords, addKeyword,
    lastFetchedAt,
  } = useDbAdminStore();
  const loading = loadingProducts;

  const [search, setSearch] = useState('');
  const [searchScope, setSearchScope] = useState('name');
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
  const [bulkCatModal, setBulkCatModal] = useState(false);
  const [bulkCatId, setBulkCatId] = useState('');
  const [adminResetOpen, setAdminResetOpen] = useState(false);
  const getSignal = useAbortController([sourceFilter, catFilter, sortBy, sortDir, page]);

  /* ─── 데이터 페칭 ─── */
  const doFetch = useCallback((overrides = {}) => {
    const params = {};
    const src = overrides.source ?? sourceFilter;
    if (src && src !== 'all') params.source = src;
    if (overrides.category ?? catFilter) params.category = overrides.category ?? catFilter;
    const currentSearch = overrides.search ?? search;
    const currentScope = overrides.searchScope ?? searchScope;
    if (currentSearch) {
      if (currentScope === 'category') {
        params.category_search = currentSearch;
      } else if (currentScope === 'all') {
        params.search = currentSearch;
        params.category_search = currentSearch;
      } else {
        params.search = currentSearch;
      }
    }
    params.sort_by = overrides.sort_by ?? sortBy;
    params.sort_dir = overrides.sort_dir ?? sortDir;
    params.page = overrides.page ?? page;
    params.per_page = 20;
    const signal = getSignal();
    fetchProducts(params, { signal });
  }, [sourceFilter, catFilter, search, searchScope, sortBy, sortDir, page, fetchProducts, getSignal]);

  useEffect(() => {
    doFetch(); fetchProductStats(); fetchCategories(); fetchKeywords();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    doFetch(); setSelected(new Set());
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceFilter, catFilter, sortBy, sortDir, page]);

  const handleSearch = () => { setPage(1); doFetch({ page: 1 }); };

  /* ─── 정렬 ─── */
  const toggleSort = (col) => {
    if (sortBy === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    else { setSortBy(col); setSortDir('asc'); }
    setPage(1);
  };

  /* ─── 선택 ─── */
  const toggleSelectAll = () => {
    const allSelected = products.length > 0 && products.every(p => selected.has(p.id));
    setSelected(allSelected ? new Set() : new Set(products.map(p => p.id)));
  };
  const toggleSelect = (id) => {
    setSelected(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  /* ─── 벌크 ─── */
  const handleBulkDelete = async () => {
    if (!confirm(`선택한 ${selected.size}개 상품을 삭제하시겠습니까?`)) return;
    await bulkDeleteProducts([...selected]);
    setSelected(new Set()); fetchProductStats();
  };
  const handleBulkCategory = async () => {
    if (!bulkCatId) return;
    await bulkUpdateCategory([...selected], bulkCatId);
    setBulkCatModal(false); setBulkCatId(''); setSelected(new Set()); fetchProductStats();
  };

  /* ─── 확장 행 ─── */
  const toggleExpand = async (id) => {
    if (expandedRow === id) { setExpandedRow(null); setRowHistory(null); return; }
    setExpandedRow(id);
    try {
      const hist = await api.getProductHistory(id);
      setRowHistory(Array.isArray(hist) ? hist : hist.history ?? []);
    } catch { setRowHistory([]); }
  };

  /* ─── 모달 ─── */
  const openAdd = () => {
    setForm({
      name: '', category: '', categoryId: '', unit: '',
      description: '', image_url: '', source_type: 'unknown',
      attributes_json: '', is_active: true,
    });
    setFormKeywords([]); setModal({ mode: 'add' });
  };
  const openEdit = (p) => {
    setForm({
      ...p,
      categoryId: p.category_id || '',
      basePrice: String(p.basePrice || p.originalPrice || ''),
      currentAvg: String(p.currentAvg || p.currentPrice || ''),
      source_type: p.source_type || 'unknown',
      attributes_json: p.attributes ? JSON.stringify(p.attributes, null, 2) : '',
      is_active: p.is_active !== false,
    });
    const kwList = (p.keywords || []).map(k => {
      if (typeof k === 'object' && k.id && k.keyword) return k;
      if (typeof k === 'string') return { id: k, keyword: keywords.find(kw => kw.id === k)?.keyword || k };
      return k;
    });
    setFormKeywords(kwList);
    setModal({ mode: 'edit', product: p });
  };
  const openDetail = (p) => setModal({ mode: 'detail', product: p });

  const handleSave = async () => {
    let attributes = null;
    if ((form.attributes_json || '').trim()) {
      try {
        attributes = JSON.parse(form.attributes_json);
      } catch {
        alert('속성(JSON) 형식이 올바르지 않습니다.');
        return;
      }
    }
    const data = {
      name: form.name,
      category_id: form.categoryId || null,
      unit: form.unit || '개',
      description: form.description || null,
      image_url: form.image_url || null,
      source_type: form.source_type || 'unknown',
      attributes,
      is_active: form.is_active !== false,
    };

    // Resolve keyword IDs — create new keywords first, then collect all IDs
    const resolvedKeywordIds = [];
    for (const kw of formKeywords) {
      if (String(kw.id).startsWith('kw-new-')) {
        try {
          const created = await api.createKeyword({ word: kw.keyword, category_id: form.categoryId || null });
          if (created?.id) resolvedKeywordIds.push(created.id);
        } catch { /* skip duplicates or errors */ }
      } else {
        resolvedKeywordIds.push(kw.id);
      }
    }
    data.keyword_ids = resolvedKeywordIds;

    if (modal.mode === 'add') await addProduct(data);
    else await updateProduct(modal.product.id, data);
    if (form.categoryId && formKeywords.length > 0) {
      for (const kw of formKeywords) {
        if (String(kw.id).startsWith('kw-new-')) continue;
        try { await api.updateKeyword(kw.id, { category_id: form.categoryId }); } catch { /* best-effort */ }
      }
    }
    setModal(null); fetchProductStats(); fetchKeywords();
  };

  const handleDelete = async (id) => {
    if (confirm('정말 삭제하시겠습니까?')) { await deleteProduct(id); setModal(null); fetchProductStats(); }
  };

  const handleCreateCategory = async (parentId, catData) => { await addCategory(parentId, catData); };

  const { total, total_pages } = productPagination;

  return (
    <div className={s.page}>
      <div className={s.header}>
        <div>
          <h2 className={s.title}>상품 관리</h2>
          <LastUpdated
            timestamp={lastFetchedAt.products}
            onRefresh={() => { doFetch(); fetchProductStats(); }}
            isLoading={loading}
          />
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className={s.adminResetBtn} onClick={() => setAdminResetOpen(true)}>
            <Database size={16} /> DB 초기화
          </button>
          <button className={s.addBtn} onClick={openAdd}><Plus size={16} /> 상품 추가</button>
        </div>
      </div>

      <ProductStats stats={productStats} />

      <ProductFilters
        sourceFilter={sourceFilter} setSourceFilter={setSourceFilter}
        catFilter={catFilter} setCatFilter={setCatFilter}
        search={search} setSearch={setSearch}
        searchScope={searchScope} setSearchScope={setSearchScope}
        sortBy={sortBy} setSortBy={setSortBy}
        sortDir={sortDir} setSortDir={setSortDir}
        setPage={setPage}
        onSearch={handleSearch}
        stats={productStats}
        selected={selected}
        onBulkDelete={handleBulkDelete}
        onBulkCategoryOpen={() => setBulkCatModal(true)}
        onClearSelection={() => setSelected(new Set())}
      />

      {error && <div className={s.errorState}><AlertTriangle size={20} /><span>{error}</span></div>}
      {loading && <div className={s.loadingBar}>불러오는 중...</div>}
      {!loading && !error && products.length === 0 && (
        <div className={s.emptyState}><Package size={40} /><p>데이터 없음</p><span>등록된 상품이 없습니다. 상품을 추가하거나 크롤링을 실행하세요.</span></div>
      )}

      {products.length > 0 && (
        <ProductTable
          products={products} selected={selected}
          onToggleSelect={toggleSelect} onToggleSelectAll={toggleSelectAll}
          expandedRow={expandedRow} onToggleExpand={toggleExpand} rowHistory={rowHistory}
          sortBy={sortBy} sortDir={sortDir} onToggleSort={toggleSort}
          onDetail={openDetail} onEdit={openEdit} onDelete={handleDelete}
          page={page} setPage={setPage} total={total} totalPages={total_pages}
        />
      )}

      <BulkCategoryModal
        open={bulkCatModal} onClose={() => setBulkCatModal(false)}
        categories={categories} bulkCatId={bulkCatId} setBulkCatId={setBulkCatId}
        onApply={handleBulkCategory} selectedCount={selected.size}
        onCreateCategory={handleCreateCategory}
      />

      <ProductModal
        modal={modal} onClose={() => setModal(null)}
        form={form} setForm={setForm}
        formKeywords={formKeywords} setFormKeywords={setFormKeywords}
        categories={categories} keywords={keywords}
        onSave={handleSave} onEdit={openEdit} onDelete={handleDelete}
        onCreateCategory={handleCreateCategory} addKeyword={addKeyword}
      />

      <AdminResetModal
        open={adminResetOpen}
        onClose={() => setAdminResetOpen(false)}
        onComplete={() => { doFetch(); fetchProductStats(); }}
      />
    </div>
  );
}
