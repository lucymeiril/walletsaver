import { useState, useMemo, useEffect } from 'react';
import { Plus, Pencil, Trash2, X, Search } from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';
import useDbAdminStore from '../../stores/dbAdminStore';
import s from './Products.module.css';

const TIER_LABEL = { ultra: '초특가', great: '특가', good: '적정', wait: '관망', bad: '비쌈' };
const TIER_CLASS = { ultra: 'tierUltra', great: 'tierGreat', good: 'tierGood', wait: 'tierWait', bad: 'tierBad' };

export default function Products() {
  const { products, addProduct, updateProduct, deleteProduct, priceHistories, fetchProducts, loading } = useDbAdminStore();
  const [search, setSearch] = useState('');
  const [catFilter, setCatFilter] = useState('');
  const [modal, setModal] = useState(null); // null | { mode: 'add'|'edit'|'detail', product? }
  const [form, setForm] = useState({});

  const allCategories = useMemo(() => [...new Set(products.map(p => p.category))].sort(), [products]);

  useEffect(() => {
    fetchProducts();
  }, [fetchProducts]);

  const filtered = useMemo(() => {
    return products.filter(p => {
      const matchName = !search || p.name.includes(search);
      const matchCat = !catFilter || p.category === catFilter;
      return matchName && matchCat;
    });
  }, [products, search, catFilter]);

  const openAdd = () => {
    setForm({ name: '', category: '', unit: '', basePrice: '', currentAvg: '', tier: 'good' });
    setModal({ mode: 'add' });
  };

  const openEdit = (p) => {
    setForm({ ...p, basePrice: String(p.basePrice), currentAvg: String(p.currentAvg) });
    setModal({ mode: 'edit', product: p });
  };

  const openDetail = (p) => {
    setModal({ mode: 'detail', product: p });
  };

  const handleSave = () => {
    const data = { ...form, basePrice: Number(form.basePrice), currentAvg: Number(form.currentAvg) };
    if (modal.mode === 'add') addProduct(data);
    else updateProduct(modal.product.id, data);
    setModal(null);
  };

  const handleDelete = (id) => {
    if (confirm('정말 삭제하시겠습니까?')) deleteProduct(id);
  };

  return (
    <div className={s.page}>
      <div className={s.header}>
        <h2 className={s.title}>상품 관리</h2>
        <button className={s.addBtn} onClick={openAdd}><Plus size={16} /> 상품 추가</button>
      </div>

      {/* 필터 */}
      <div className={s.filters}>
        <div className={s.searchWrap}>
          <Search size={16} className={s.searchIcon} />
          <input
            className={s.searchInput}
            placeholder="상품명 검색..."
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>
        <select className={s.select} value={catFilter} onChange={e => setCatFilter(e.target.value)}>
          <option value="">전체 카테고리</option>
          {allCategories.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>

      {/* 테이블 */}
      <div className={s.tableWrap}>
        <table className={s.table}>
          <thead>
            <tr>
              <th>이름</th>
              <th>카테고리</th>
              <th>단위</th>
              <th>기준가</th>
              <th>현재 평균가</th>
              <th>가격 티어</th>
              <th>관리</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map(p => (
              <tr key={p.id} onClick={() => openDetail(p)} className={s.row}>
                <td className={s.nameCol}>{p.name}</td>
                <td>{p.category}</td>
                <td>{p.unit}</td>
                <td>{p.basePrice.toLocaleString()}원</td>
                <td>{p.currentAvg.toLocaleString()}원</td>
                <td><span className={`${s.tier} ${s[TIER_CLASS[p.tier]]}`}>{TIER_LABEL[p.tier]}</span></td>
                <td>
                  <div className={s.actions} onClick={e => e.stopPropagation()}>
                    <button className={s.iconBtn} onClick={() => openEdit(p)} title="수정"><Pencil size={14} /></button>
                    <button className={s.iconBtn} onClick={() => handleDelete(p.id)} title="삭제"><Trash2 size={14} /></button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className={s.count}>{filtered.length}개 상품</p>

      {/* 모달 */}
      {modal && (
        <div className={s.overlay} onClick={() => setModal(null)}>
          <div className={s.modal} onClick={e => e.stopPropagation()}>
            <div className={s.modalHeader}>
              <h3>{modal.mode === 'add' ? '상품 추가' : modal.mode === 'edit' ? '상품 수정' : modal.product.name}</h3>
              <button onClick={() => setModal(null)}><X size={18} /></button>
            </div>

            {modal.mode === 'detail' ? (
              <div className={s.detail}>
                <div className={s.detailGrid}>
                  <div><span className={s.label}>카테고리</span><span>{modal.product.category}</span></div>
                  <div><span className={s.label}>단위</span><span>{modal.product.unit}</span></div>
                  <div><span className={s.label}>기준가</span><span>{modal.product.basePrice.toLocaleString()}원</span></div>
                  <div><span className={s.label}>현재 평균가</span><span>{modal.product.currentAvg.toLocaleString()}원</span></div>
                  <div><span className={s.label}>가격 티어</span><span className={`${s.tier} ${s[TIER_CLASS[modal.product.tier]]}`}>{TIER_LABEL[modal.product.tier]}</span></div>
                </div>
                <h4 className={s.chartTitle}>가격 이력 (90일)</h4>
                <div className={s.chartWrap}>
                  <ResponsiveContainer width="100%" height={250}>
                    <LineChart data={priceHistories[modal.product.id]?.slice(-30) || []}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                      <XAxis dataKey="date" tick={{ fill: 'var(--text3)', fontSize: 11 }} tickFormatter={v => v.slice(5)} />
                      <YAxis tick={{ fill: 'var(--text3)', fontSize: 11 }} />
                      <Tooltip contentStyle={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, color: 'var(--text)' }} />
                      <Line type="monotone" dataKey="price" stroke="var(--accent)" strokeWidth={2} dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
                <button className={s.editBtn} onClick={() => openEdit(modal.product)}>수정하기</button>
              </div>
            ) : (
              <div className={s.form}>
                <label>이름<input value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} /></label>
                <label>카테고리<input value={form.category} onChange={e => setForm({ ...form, category: e.target.value })} /></label>
                <label>단위<input value={form.unit} onChange={e => setForm({ ...form, unit: e.target.value })} /></label>
                <label>기준가<input type="number" value={form.basePrice} onChange={e => setForm({ ...form, basePrice: e.target.value })} /></label>
                <label>현재 평균가<input type="number" value={form.currentAvg} onChange={e => setForm({ ...form, currentAvg: e.target.value })} /></label>
                <label>가격 티어
                  <select value={form.tier} onChange={e => setForm({ ...form, tier: e.target.value })}>
                    {Object.entries(TIER_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
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
