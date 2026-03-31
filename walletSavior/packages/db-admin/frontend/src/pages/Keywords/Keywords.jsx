import { useState, useMemo } from 'react';
import { Plus, Pencil, Trash2, X, Tag } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';
import useDbAdminStore from '../../stores/dbAdminStore';
import s from './Keywords.module.css';

export default function Keywords() {
  const { keywords, addKeyword, updateKeyword, deleteKeyword, categories } = useDbAdminStore();
  const [search, setSearch] = useState('');
  const [modal, setModal] = useState(null);
  const [form, setForm] = useState({});
  const [synonymInput, setSynonymInput] = useState('');

  const sorted = useMemo(() => {
    const list = [...keywords].sort((a, b) => b.searchCount - a.searchCount);
    if (!search) return list;
    return list.filter(k => k.keyword.includes(search) || k.synonyms.some(s => s.includes(search)));
  }, [keywords, search]);

  const chartData = useMemo(() => sorted.slice(0, 15).map(k => ({ name: k.keyword, 검색수: k.searchCount })), [sorted]);

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
    const val = synonymInput.trim();
    if (val && !form.synonyms.includes(val)) {
      setForm({ ...form, synonyms: [...form.synonyms, val] });
    }
    setSynonymInput('');
  };

  const removeSynonym = (syn) => {
    setForm({ ...form, synonyms: form.synonyms.filter(s => s !== syn) });
  };

  const handleSave = () => {
    const data = { ...form, searchCount: Number(form.searchCount) };
    if (modal.mode === 'add') addKeyword(data);
    else updateKeyword(modal.keyword.id, data);
    setModal(null);
  };

  const handleDelete = (id) => {
    if (confirm('키워드를 삭제하시겠습니까?')) deleteKeyword(id);
  };

  const getCategoryName = (id) => flatCategories.find(c => c.id === id)?.label || '-';

  return (
    <div className={s.page}>
      <div className={s.header}>
        <h2 className={s.title}>키워드 관리</h2>
        <button className={s.addBtn} onClick={openAdd}><Plus size={16} /> 키워드 추가</button>
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

      {/* 검색 */}
      <div className={s.searchWrap}>
        <input
          placeholder="키워드 또는 동의어 검색..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          className={s.searchInput}
        />
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
              <th>관리</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map(kw => (
              <tr key={kw.id}>
                <td className={s.bold}>{kw.keyword}</td>
                <td>{kw.searchCount.toLocaleString()}</td>
                <td>
                  <div className={s.synonyms}>
                    {kw.synonyms.map(syn => (
                      <span key={syn} className={s.synonymTag}>{syn}</span>
                    ))}
                  </div>
                </td>
                <td className={s.catCol}>{getCategoryName(kw.categoryId)}</td>
                <td>
                  <div className={s.actions}>
                    <button className={s.iconBtn} onClick={() => openEdit(kw)}><Pencil size={14} /></button>
                    <button className={s.iconBtn} onClick={() => handleDelete(kw.id)}><Trash2 size={14} /></button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className={s.count}>{sorted.length}개 키워드</p>

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
                  {form.synonyms.map(syn => (
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
                    placeholder="동의어 입력"
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
