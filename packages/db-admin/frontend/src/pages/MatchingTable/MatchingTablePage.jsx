import { useEffect, useMemo, useState } from 'react';
import { api } from '../../api/client';

const emptyForm = {
  pattern_type: 'normalized',
  pattern_value: '',
  canonical_category_id: '',
  canonical_product_id: '',
  trust: 1,
  created_by: 'admin',
};

const patternLabels = { exact: '정확히 일치', normalized: '정규화 키', regex: '정규식' };

const panel = {
  padding: 20,
  borderRadius: 16,
  background: 'var(--bg2)',
  border: '1px solid var(--border)',
  boxShadow: 'var(--shadow-sm)',
};

function asPayload(form) {
  return {
    pattern_type: form.pattern_type,
    pattern_value: form.pattern_value.trim(),
    canonical_category_id: form.canonical_category_id.trim() || null,
    canonical_product_id: form.canonical_product_id ? Number(form.canonical_product_id) : null,
    trust: Number(form.trust),
    created_by: form.created_by.trim() || 'admin',
  };
}

export default function MatchingTablePage() {
  const [rules, setRules] = useState([]);
  const [stats, setStats] = useState(null);
  const [search, setSearch] = useState('');
  const [patternType, setPatternType] = useState('');
  const [page, setPage] = useState(1);
  const [pagination, setPagination] = useState({ total: 0, total_pages: 1 });
  const [form, setForm] = useState(emptyForm);
  const [editingId, setEditingId] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const params = useMemo(() => ({ page, per_page: 20, ...(search ? { search } : {}), ...(patternType ? { pattern_type: patternType } : {}) }), [page, search, patternType]);

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const [list, stat] = await Promise.all([api.getMatchingRules(params), api.getMatchingRuleStats()]);
      setRules(list.items || []);
      setPagination({ total: list.total || 0, total_pages: list.total_pages || 1 });
      setStats(stat);
    } catch (err) {
      setError(err.message || '매칭 규칙을 불러오지 못했습니다');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [params]); // eslint-disable-line react-hooks/exhaustive-deps

  const submit = async (event) => {
    event.preventDefault();
    setError('');
    try {
      const payload = asPayload(form);
      if (editingId) await api.updateMatchingRule(editingId, payload);
      else await api.createMatchingRule(payload);
      setForm(emptyForm);
      setEditingId(null);
      await load();
    } catch (err) {
      setError(err.message || '저장 실패');
    }
  };

  const edit = (rule) => {
    setEditingId(rule.id);
    setForm({
      pattern_type: rule.pattern_type,
      pattern_value: rule.pattern_value,
      canonical_category_id: rule.canonical_category_id || '',
      canonical_product_id: rule.canonical_product_id || '',
      trust: rule.trust ?? 1,
      created_by: rule.created_by || 'admin',
    });
  };

  const remove = async (rule) => {
    if (!confirm(`매칭 규칙 #${rule.id}을 삭제하시겠습니까?`)) return;
    try {
      await api.deleteMatchingRule(rule.id);
      await load();
    } catch (err) {
      setError(err.message || '삭제 실패');
    }
  };

  return (
    <div style={{ display: 'grid', gap: 20 }}>
      <header>
        <h1 style={{ margin: 0 }}>매칭 테이블</h1>
        <p style={{ color: 'var(--text3)' }}>상품 제목/정규화 키 → 통합 카테고리/표준 상품 자동 매칭 규칙입니다.</p>
      </header>

      <section style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 12 }}>
        <div style={panel}>총 규칙<br /><strong>{stats?.total ?? '-'}</strong></div>
        <div style={panel}>유형별<br /><strong>{Object.entries(stats?.by_pattern_type || {}).map(([k, v]) => `${k}:${v}`).join(' · ') || '-'}</strong></div>
        <div style={panel}>trust별<br /><strong>{Object.entries(stats?.by_trust || {}).map(([k, v]) => `${k}:${v}`).join(' · ') || '-'}</strong></div>
        <div style={panel}>누적 hit<br /><strong>{stats?.hit_count_sum ?? '-'}</strong></div>
      </section>

      <section style={panel}>
        <form onSubmit={submit} style={{ display: 'grid', gridTemplateColumns: '140px 1fr 180px 160px 90px 130px auto auto', gap: 8, alignItems: 'end' }}>
          <label>패턴 유형<select value={form.pattern_type} onChange={e => setForm({ ...form, pattern_type: e.target.value })}><option value="exact">정확히 일치</option><option value="normalized">정규화 키</option><option value="regex">정규식</option></select></label>
          <label>패턴 값<input value={form.pattern_value} onChange={e => setForm({ ...form, pattern_value: e.target.value })} placeholder="상품명 또는 정규식" required /></label>
          <label>unified 카테고리<input value={form.canonical_category_id} onChange={e => setForm({ ...form, canonical_category_id: e.target.value })} placeholder="예: meat.pork" /></label>
          <label>표준 상품 ID<input value={form.canonical_product_id} onChange={e => setForm({ ...form, canonical_product_id: e.target.value })} type="number" min="1" /></label>
          <label>trust<select value={form.trust} onChange={e => setForm({ ...form, trust: e.target.value })}><option value="0">0</option><option value="1">1</option><option value="2">2</option></select></label>
          <label>생성자<input value={form.created_by} onChange={e => setForm({ ...form, created_by: e.target.value })} /></label>
          <button type="submit">{editingId ? '수정' : '추가'}</button>
          {editingId && <button type="button" onClick={() => { setEditingId(null); setForm(emptyForm); }}>취소</button>}
        </form>
      </section>

      <section style={panel}>
        <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
          <input value={search} onChange={e => { setSearch(e.target.value); setPage(1); }} placeholder="패턴/카테고리/상품 검색" style={{ flex: 1 }} />
          <select value={patternType} onChange={e => { setPatternType(e.target.value); setPage(1); }}><option value="">전체 유형</option><option value="exact">정확히 일치</option><option value="normalized">정규화 키</option><option value="regex">정규식</option></select>
        </div>
        {error && <p style={{ color: 'var(--danger)' }}>{error}</p>}
        {loading ? <p>불러오는 중...</p> : (
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr><th>패턴 유형</th><th>패턴 값</th><th>매칭된 unified 카테고리</th><th>매칭된 표준 상품</th><th>trust</th><th>생성자</th><th>hit_count</th><th>관리</th></tr></thead>
            <tbody>
              {rules.map(rule => (
                <tr key={rule.id}>
                  <td>{patternLabels[rule.pattern_type] || rule.pattern_type}</td>
                  <td><code>{rule.pattern_value}</code></td>
                  <td>{rule.canonical_category_name || rule.canonical_category_id || '-'}</td>
                  <td>{rule.canonical_product_name || rule.canonical_product_id || '-'}</td>
                  <td>{rule.trust}</td>
                  <td>{rule.created_by}</td>
                  <td>{rule.hit_count}</td>
                  <td><button onClick={() => edit(rule)}>수정</button> <button onClick={() => remove(rule)}>삭제</button></td>
                </tr>
              ))}
              {rules.length === 0 && <tr><td colSpan="8" style={{ textAlign: 'center', padding: 24 }}>매칭 규칙이 없습니다.</td></tr>}
            </tbody>
          </table>
        )}
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 12 }}>
          <span>총 {pagination.total.toLocaleString()}개</span>
          <div><button disabled={page <= 1} onClick={() => setPage(p => p - 1)}>이전</button> <span>{page} / {pagination.total_pages}</span> <button disabled={page >= pagination.total_pages} onClick={() => setPage(p => p + 1)}>다음</button></div>
        </div>
      </section>
    </div>
  );
}
