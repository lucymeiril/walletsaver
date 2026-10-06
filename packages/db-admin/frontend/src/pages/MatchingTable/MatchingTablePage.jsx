import { useEffect, useMemo, useState, useRef } from 'react';
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

function mappingSpecification(row) {
  if (typeof row.display_unit === 'string' && row.display_unit.trim()) return row.display_unit.trim();
  const quantity = row.package_quantity;
  const unit = typeof row.package_unit === 'string' ? row.package_unit.trim() : '';
  if (typeof quantity !== 'number' || !Number.isFinite(quantity) || quantity <= 0 || !unit) return '미확인';
  const scalar = `${quantity}${unit}`;
  return Number.isInteger(row.bundle_count) && row.bundle_count > 0
    ? `${scalar} ×${row.bundle_count}` : `${scalar} · 묶음 수 미확인`;
}

export default function MatchingTablePage() {
  const [namespace, setNamespace] = useState('normalized');
  const normalized = namespace === 'normalized';
  const requestRef = useRef(0);
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

  const params = useMemo(() => normalized
    ? { page, per_page: 25, ...(search ? { q: search } : {}) }
    : { page, per_page: 20, ...(search ? { search } : {}), ...(patternType ? { pattern_type: patternType } : {}) }, [normalized, page, search, patternType]);

  const load = async ({ signal } = {}) => {
    const request = ++requestRef.current;
    setLoading(true);
    setError('');
    try {
      const [list, stat] = normalized
        ? [await api.getClassifiedMappings(params, { signal }), null]
        : await Promise.all([api.getMatchingRules(params, { signal }), api.getMatchingRuleStats({ signal })]);
      if (request !== requestRef.current || signal?.aborted) return;
      setRules(list.items || []);
      setPagination({ total: list.total || 0, total_pages: list.total_pages || 1 });
      setStats(stat);
    } catch (err) {
      if (request === requestRef.current && err.name !== 'AbortError') setError(err.message || '매칭을 불러오지 못했습니다');
    } finally {
      if (request === requestRef.current) setLoading(false);
    }
  };

  useEffect(() => {
    const controller = new AbortController();
    load({ signal: controller.signal });
    return () => controller.abort();
  }, [params]); // eslint-disable-line react-hooks/exhaustive-deps

  const submit = async (event) => {
    event.preventDefault();
    if (normalized) return;
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
    if (normalized) return;
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
    if (normalized) return;
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
        <p style={{ color: 'var(--text3)' }}>승인된 정규화 키의 상품·규격 연결과 기존 보조 규칙을 구분하여 관리합니다.</p>
        <label>매칭 체계 <select aria-label="매칭 체계" value={namespace} onChange={e => {
          setNamespace(e.target.value); setPage(1); setSearch(''); setPatternType(''); setRules([]);
          setPagination({ total: 0, total_pages: 1 }); setStats(null); setForm(emptyForm); setEditingId(null);
        }}>
          <option value="normalized">승인된 상품·규격 연결 · 조회 전용</option>
          <option value="legacy">기존 보조 매칭 규칙 · 편집 가능</option>
        </select></label>
        {normalized && <p>연결 수정은 <a href="/import">공식 매칭 가져오기</a>에서 검토합니다. 새 상품·분류·규격은 공식 카탈로그 번들을 사용합니다.</p>}
      </header>

      {!normalized && <section style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 12 }}>
        <div style={panel}>총 규칙<br /><strong>{stats?.total ?? '-'}</strong></div>
        <div style={panel}>유형별<br /><strong>{Object.entries(stats?.by_pattern_type || {}).map(([k, v]) => `${k}:${v}`).join(' · ') || '-'}</strong></div>
        <div style={panel}>trust별<br /><strong>{Object.entries(stats?.by_trust || {}).map(([k, v]) => `${k}:${v}`).join(' · ') || '-'}</strong></div>
        <div style={panel}>누적 hit<br /><strong>{stats?.hit_count_sum ?? '-'}</strong></div>
      </section>}

      {!normalized && <section style={panel}>
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
      </section>}

      <section style={panel}>
        <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
          <input value={search} onChange={e => { setSearch(e.target.value); setPage(1); }} placeholder={normalized ? "정규화 키/상품/규격/통합 분류 검색" : "패턴/카테고리/상품 검색"} style={{ flex: 1 }} />
          {!normalized && <select value={patternType} onChange={e => { setPatternType(e.target.value); setPage(1); }}><option value="">전체 유형</option><option value="exact">정확히 일치</option><option value="normalized">정규화 키</option><option value="regex">정규식</option></select>}
        </div>
        {error && <p style={{ color: 'var(--danger)' }}>{error}</p>}
        {loading ? <p>불러오는 중...</p> : normalized ? (
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr><th>정규화 키</th><th>공개 상품</th><th>선택 규격</th><th>통합 말단 분류</th><th>출처 / 신뢰도</th></tr></thead>
            <tbody>{rules.map(row => <tr key={row.match_key}>
              <td><code>{row.match_key}</code></td>
              <td>{row.canonical_name || '이름 미확인'}<br /><code>{row.public_product_id}</code></td>
              <td>{row.variant_name || '규격명 미확인'}<br />{mappingSpecification(row)}<br /><code>{row.public_variant_id}</code></td>
              <td><code>{row.unified_category_id}</code></td>
              <td>{row.source ?? '미확인'} / {row.confidence ?? '미확인'}</td>
            </tr>)}
              {!error && rules.length === 0 && <tr><td colSpan="5">승인된 상품·규격 연결이 없습니다.</td></tr>}
            </tbody>
          </table>
        ) : (
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
              {!error && rules.length === 0 && <tr><td colSpan="8" style={{ textAlign: 'center', padding: 24 }}>매칭 규칙이 없습니다.</td></tr>}
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
