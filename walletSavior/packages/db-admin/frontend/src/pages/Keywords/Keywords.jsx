import { useState, useMemo, useEffect, useCallback, useRef } from 'react';
import { Plus, Pencil, Trash2, X, Tag, ChevronLeft, ChevronRight, AlertTriangle, Package } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';
import useDbAdminStore from '../../stores/dbAdminStore';
import s from './Keywords.module.css';

export default function Keywords() {
  const {
    keywords, addKeyword, updateKeyword, deleteKeyword, bulkDeleteKeywords,
    categories, fetchKeywords, fetchCategories, fetchKeywordStats,
    keywordPagination, keywordStats, loading, error,
  } = useDbAdminStore();

  const [search, setSearch] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');
  const [showUnused, setShowUnused] = useState(false);
  const [page, setPage] = useState(1);
  const [modal, setModal] = useState(null);
  const [form, setForm] = useState({});
  const [synonymInput, setSynonymInput] = useState('');
  const [toast, setToast] = useState(null);
  const debounceRef = useRef(null);

  const flatCategories = useMemo(() => {
    const flat = [];
    const walk = (nodes, prefix = '') => {
      nodes.forEach(n => {
        flat.push({ id: n.id, label: prefix + n.name });
        if (n.children) walk(n.children, prefix + n.name + ' > ');
      });
    };
    walk(categories);
    return flat;
  }, [categories]);

  const loadKeywords = useCallback((p = page) => {
    const params = { page: p, per_page: 20 };
    if (search) params.q = search;
    if (categoryFilter) params.category_id = categoryFilter;
    if (showUnused) params.show_unused = true;
    params.sort_by = 'search_count';
    params.sort_dir = 'desc';
    fetchKeywords(params);
  }, [search, categoryFilter, showUnused, page, fetchKeywords]);

  useEffect(() => {
    fetchCategories();
    fetchKeywordStats();
  }, [fetchCategories, fetchKeywordStats]);

  useEffect(() => {
    loadKeywords(page);
  }, [page]); // eslint-disable-line react-hooks/exhaustive-deps

  // 검색·필터 변경 시 디바운스 후 1페이지로 리셋
  useEffect(() => {
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setPage(1);
      loadKeywords(1);
    }, 300);
    return () => clearTimeout(debounceRef.current);
  }, [search, categoryFilter, showUnused]); // eslint-disable-line react-hooks/exhaustive-deps

  const chartData = useMemo(
    () => keywords.slice(0, 15).map(k => ({ name: k.keyword, 검색수: k.searchCount ?? 0 })),
    [keywords],
  );

  const showToast = (msg, type = 'info') => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 3000);
  };

  /* ── 모달 ── */
  const openAdd = () => {
    setForm({ keyword: '', searchCount: 0, synonyms: [], categoryId: '' });
    setSynonymInput('');
    setModal({ mode: 'add' });
  };

  const openEdit = (kw) => {
    setForm({ ...kw });
    setSynonymInput('');
    setModal({ mode: 'edit', keyword: kw });
  };

  const addSynonym = () => {
    // 콤마 구분 다중 입력 지원
    const values = synonymInput.split(',').map(v => v.trim()).filter(Boolean);
    const syns = form.synonyms || [];
    const newSyns = [...syns];
    values.forEach(val => {
      if (!newSyns.includes(val)) newSyns.push(val);
    });
    setForm({ ...form, synonyms: newSyns });
    setSynonymInput('');
  };

  const removeSynonym = (syn) => {
    setForm({ ...form, synonyms: (form.synonyms || []).filter(v => v !== syn) });
  };

  const handleSave = async () => {
    const data = { ...form, searchCount: Number(form.searchCount) };
    if (modal.mode === 'add') {
      const result = await addKeyword(data);
      if (result?.status === 409) {
        showToast(result.message, 'error');
        return;
      }
      if (result?.ok) {
        showToast('키워드가 추가되었습니다.', 'success');
      }
    } else {
      await updateKeyword(modal.keyword.id, data);
      showToast('키워드가 수정되었습니다.', 'success');
    }
    setModal(null);
  };

  const handleDelete = async (id) => {
    if (confirm('키워드를 삭제하시겠습니까?')) {
      await deleteKeyword(id);
      showToast('키워드가 삭제되었습니다.', 'success');
    }
  };

  const handleBulkDelete = async () => {
    if (!confirm(`미사용 키워드 ${keywordStats.unused_count}개를 모두 삭제하시겠습니까?`)) return;
    const result = await bulkDeleteKeywords();
    if (result) {
      showToast(`${result.deleted}개 키워드가 삭제되었습니다.`, 'success');
      loadKeywords(1);
      setPage(1);
    }
  };

  const getCategoryName = (id) => flatCategories.find(c => c.id === id)?.label || '-';

  const { total, total_pages } = keywordPagination;

  return (
    <div className={s.page}>
      {/* 토스트 */}
      {toast && (
        <div className={`${s.toast} ${s[toast.type]}`}>{toast.msg}</div>
      )}

      <div className={s.header}>
        <h2 className={s.title}>키워드 관리</h2>
        <div className={s.headerActions}>
          {keywordStats.unused_count > 0 && (
            <button className={s.unusedBtn} onClick={handleBulkDelete}>
              <AlertTriangle size={14} />
              미사용 {keywordStats.unused_count}개 삭제
            </button>
          )}
          <button className={s.addBtn} onClick={openAdd}><Plus size={16} /> 키워드 추가</button>
        </div>
      </div>

      {/* 통계 카드 */}
      <div className={s.statsRow}>
        <div className={s.statCard}>
          <span className={s.statLabel}>전체 키워드</span>
          <span className={s.statValue}>{keywordStats.total?.toLocaleString()}</span>
        </div>
        <div className={s.statCard}>
          <span className={s.statLabel}>미사용 키워드</span>
          <span className={`${s.statValue} ${keywordStats.unused_count > 0 ? s.unusedValue : ''}`}>
            {keywordStats.unused_count?.toLocaleString()}
          </span>
        </div>
      </div>

      {/* 인기 검색어 차트 */}
      <div className={s.chartCard}>
        <h3 className={s.sectionTitle}>인기 검색어 (Top 15)</h3>
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={chartData} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis dataKey="name" tick={{ fill: 'var(--text3)', fontSize: 11 }} angle={-30} textAnchor="end" height={60} />
            <YAxis tick={{ fill: 'var(--text3)', fontSize: 11 }} />
            <Tooltip contentStyle={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, color: 'var(--text)' }} />
            <Bar dataKey="검색수" fill="var(--accent)" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* 필터 바 */}
      <div className={s.filterBar}>
        <input
          placeholder="키워드 또는 동의어 검색..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          className={s.searchInput}
        />
        <select
          value={categoryFilter}
          onChange={e => setCategoryFilter(e.target.value)}
          className={s.filterSelect}
        >
          <option value="">모든 카테고리</option>
          {flatCategories.map(c => <option key={c.id} value={c.id}>{c.label}</option>)}
        </select>
        <label className={s.checkLabel}>
          <input
            type="checkbox"
            checked={showUnused}
            onChange={e => setShowUnused(e.target.checked)}
          />
          미사용만
        </label>
      </div>

      {/* 테이블 */}
      <div className={s.tableWrap}>
        <table className={s.table}>
          <thead>
            <tr>
              <th>키워드</th>
              <th>검색 횟수</th>
              <th>동의어</th>
              <th>연결 카테고리</th>
              <th>연결 상품</th>
              <th>관리</th>
            </tr>
          </thead>
          <tbody>
            {keywords.map(kw => (
              <tr key={kw.id} className={kw.searchCount === 0 ? s.unusedRow : ''}>
                <td className={s.bold}>
                  {kw.keyword}
                  {kw.searchCount === 0 && <span className={s.unusedBadge}>미사용</span>}
                </td>
                <td>{(kw.searchCount ?? 0).toLocaleString()}</td>
                <td>
                  <div className={s.synonyms}>
                    {(kw.synonyms ?? []).map(syn => (
                      <span key={syn} className={s.synonymTag}>{syn}</span>
                    ))}
                  </div>
                </td>
                <td className={s.catCol}>{getCategoryName(kw.categoryId)}</td>
                <td>
                  <span className={s.productCount}>
                    <Package size={12} /> {kw.productCount ?? 0}
                  </span>
                </td>
                <td>
                  <div className={s.actions}>
                    <button className={s.iconBtn} onClick={() => openEdit(kw)}><Pencil size={14} /></button>
                    <button className={s.iconBtn} onClick={() => handleDelete(kw.id)}><Trash2 size={14} /></button>
                  </div>
                </td>
              </tr>
            ))}
            {keywords.length === 0 && !loading && (
              <tr><td colSpan={6} className={s.empty}>키워드가 없습니다.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* 페이지네이션 */}
      <div className={s.pagination}>
        <span className={s.count}>총 {total.toLocaleString()}개</span>
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

      {/* 모달 */}
      {modal && (
        <div className={s.overlay} onClick={() => setModal(null)}>
          <div className={s.modal} onClick={e => e.stopPropagation()}>
            <div className={s.modalHeader}>
              <h3>{modal.mode === 'add' ? '키워드 추가' : '키워드 수정'}</h3>
              <button onClick={() => setModal(null)}><X size={18} /></button>
            </div>
            <div className={s.form}>
              <label>키워드<input value={form.keyword} onChange={e => setForm({ ...form, keyword: e.target.value })} /></label>
              <label>검색 횟수<input type="number" value={form.searchCount} onChange={e => setForm({ ...form, searchCount: e.target.value })} /></label>
              <label>
                연결 카테고리
                <select value={form.categoryId} onChange={e => setForm({ ...form, categoryId: e.target.value })}>
                  <option value="">선택 안 함</option>
                  {flatCategories.map(c => <option key={c.id} value={c.id}>{c.label}</option>)}
                </select>
              </label>
              <label>동의어</label>
              <div className={s.synonymEditor}>
                <div className={s.synonymTags}>
                  {(form.synonyms || []).map(syn => (
                    <span key={syn} className={s.editTag}>
                      {syn}
                      <button onClick={() => removeSynonym(syn)}><X size={12} /></button>
                    </span>
                  ))}
                </div>
                <div className={s.synonymAdd}>
                  <input
                    value={synonymInput}
                    onChange={e => setSynonymInput(e.target.value)}
                    placeholder="동의어 입력 (콤마로 구분)"
                    onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), addSynonym())}
                  />
                  <button type="button" onClick={addSynonym}><Tag size={14} /> 추가</button>
                </div>
              </div>
              <div className={s.formActions}>
                <button className={s.cancelBtn} onClick={() => setModal(null)}>취소</button>
                <button className={s.saveBtn} onClick={handleSave}>저장</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
