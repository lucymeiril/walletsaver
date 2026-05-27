import { useEffect, useState, useMemo, useCallback } from 'react';
import {
  ChevronRight, ChevronDown, Folder, FolderOpen, Edit2, Trash2,
  Merge, RefreshCw, AlertTriangle, Package,
} from 'lucide-react';
import { api } from '../../api/client';
import MartBadge, { MartBadgeRow } from '../../components/MartBadge';
import s from './ProductExplorer.module.css';

/* ────────────────────────────────────────────
   카테고리 트리 (좌측) — L1 → L2 → L3 드릴다운
   ──────────────────────────────────────────── */
function TreeNode({ node, depth, selectedId, onSelect }) {
  const [open, setOpen] = useState(depth === 0);
  const hasChildren = node.children?.length > 0;
  const selected = selectedId === node.id;

  return (
    <div className={s.treeNode}>
      <div
        className={`${s.treeRow} ${selected ? s.treeSel : ''}`}
        style={{ paddingLeft: 8 + depth * 14 }}
        onClick={() => { onSelect(node.id, node); if (hasChildren) setOpen(o => !o); }}
      >
        <span className={s.treeCaret}>
          {hasChildren
            ? (open ? <ChevronDown size={14} /> : <ChevronRight size={14} />)
            : <span style={{ width: 14, display: 'inline-block' }} />}
        </span>
        {hasChildren
          ? (open ? <FolderOpen size={14} /> : <Folder size={14} />)
          : <Package size={14} />}
        <span className={s.treeLabel}>{node.name}</span>
        {node.productCount > 0 && (
          <span className={s.treeCount}>{node.productCount}</span>
        )}
      </div>
      {open && hasChildren && (
        <div>
          {node.children.map(c => (
            <TreeNode key={c.id} node={c} depth={depth + 1}
                      selectedId={selectedId} onSelect={onSelect} />
          ))}
        </div>
      )}
    </div>
  );
}

/* ────────────────────────────────────────────
   메인
   ──────────────────────────────────────────── */
export default function ProductExplorer() {
  const [categories, setCategories] = useState([]);
  const [selCat, setSelCat] = useState(null);
  const [selCatNode, setSelCatNode] = useState(null);
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);
  const [sortBy, setSortBy] = useState('brand');
  const [sortDir, setSortDir] = useState('asc');
  const [onlySingleMart, setOnlySingleMart] = useState(false);
  const [unitKind, setUnitKind] = useState('');
  const [page, setPage] = useState(1);

  /* ── 카테고리 트리 로드 ── */
  useEffect(() => {
    api.getCategories().then(setCategories).catch(e => setErr(e?.message));
  }, []);

  /* ── 상품 로드 ── */
  const loadProducts = useCallback(async () => {
    setLoading(true); setErr(null);
    try {
      const params = {
        sort_by: sortBy, sort_dir: sortDir, page, per_page: 50,
      };
      if (selCat) params.category = selCat;
      if (onlySingleMart) params.only_single_mart = 'true';
      if (unitKind) params.unit_kind = unitKind;
      const res = await api.getHealthProducts(params);
      setProducts(res.items || []);
    } catch (e) {
      if (e?.name !== 'AbortError') setErr(e?.message || '상품 조회 실패');
    } finally { setLoading(false); }
  }, [selCat, sortBy, sortDir, page, onlySingleMart, unitKind]);

  useEffect(() => { loadProducts(); }, [loadProducts]);

  const handleSelect = (id, node) => {
    setSelCat(id); setSelCatNode(node); setPage(1);
  };

  const toggleSort = (col) => {
    if (sortBy === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    else { setSortBy(col); setSortDir('asc'); }
  };

  const handleDelete = async (p) => {
    if (!confirm(`[${p.name}] 상품을 삭제하시겠습니까? (가격 이력도 함께 삭제됨)`)) return;
    try { await api.deleteProduct(p.id); loadProducts(); }
    catch (e) { alert(`삭제 실패: ${e?.message}`); }
  };

  return (
    <div className={s.page}>
      <div className={s.titleRow}>
        <h2 className={s.title}>상품 탐색 — 카테고리 드릴다운</h2>
        <button className={s.refresh} onClick={loadProducts} disabled={loading}>
          <RefreshCw size={14} className={loading ? s.spin : ''} /> 새로고침
        </button>
      </div>

      <div className={s.layout}>
        {/* ── 좌측: 카테고리 트리 ── */}
        <aside className={s.tree}>
          <div className={s.treeHead}>큰 카테고리 (L1) → 세부 카테고리</div>
          <div className={s.treeBody}>
            <div
              className={`${s.treeRow} ${selCat === null ? s.treeSel : ''}`}
              onClick={() => { setSelCat(null); setSelCatNode(null); setPage(1); }}
            >
              <Folder size={14} /> <span className={s.treeLabel}>전체</span>
            </div>
            {categories.map(c => (
              <TreeNode key={c.id} node={c} depth={0} selectedId={selCat} onSelect={handleSelect} />
            ))}
            {categories.length === 0 && (
              <div className={s.treeEmpty}>카테고리 없음</div>
            )}
          </div>
        </aside>

        {/* ── 우측: 상품 리스트 ── */}
        <main className={s.list}>
          <div className={s.crumb}>
            현재: <strong>{selCatNode?.name || '전체'}</strong>
            {selCat && <span className={s.crumbId}>({selCat})</span>}
            <span className={s.crumbCount}>{products.length}개 표시</span>
          </div>

          {/* 필터 바 */}
          <div className={s.filterBar}>
            <label>
              <input type="checkbox" checked={onlySingleMart}
                     onChange={e => setOnlySingleMart(e.target.checked)} />
              단일 마트만 보기
            </label>
            <label>
              unit_kind:
              <select value={unitKind} onChange={e => setUnitKind(e.target.value)}>
                <option value="">전체</option>
                <option value="weight">weight</option>
                <option value="volume">volume</option>
                <option value="count">count</option>
                <option value="pack">pack</option>
              </select>
            </label>
          </div>

          {err && <div className={s.err}><AlertTriangle size={14} /> {err}</div>}

          <table className={s.table}>
            <thead>
              <tr>
                <th onClick={() => toggleSort('brand')} className={s.sortable}>
                  brand {sortBy === 'brand' && (sortDir === 'asc' ? '▲' : '▼')}
                </th>
                <th>name_core</th>
                <th>pack</th>
                <th>unit_kind</th>
                <th>source_marts</th>
                <th onClick={() => toggleSort('price')} className={s.sortable}>
                  baseline 가격 {sortBy === 'price' && (sortDir === 'asc' ? '▲' : '▼')}
                </th>
                <th onClick={() => toggleSort('updated')} className={s.sortable}>
                  갱신일 {sortBy === 'updated' && (sortDir === 'asc' ? '▲' : '▼')}
                </th>
                <th>액션</th>
              </tr>
            </thead>
            <tbody>
              {products.map(p => (
                <tr key={p.id}>
                  <td className={s.brand}>{p.brand || <em className={s.naked}>—</em>}</td>
                  <td>
                    <div className={s.nameCore}>{p.name_core || p.name}</div>
                    {!p.brand && <div className={s.flatHint}>⚠ brand 분해 없음 (legacy mart_crawl)</div>}
                  </td>
                  <td>{p.pack_qty ? `${p.pack_qty} ${p.pack_unit || ''}` : (p.pack_unit || '-')}</td>
                  <td>{p.unit_kind ? <span className={s.kindChip}>{p.unit_kind}</span> : <span className={s.muted}>미지정</span>}</td>
                  <td>
                    {p.source_marts?.length > 0
                      ? <MartBadgeRow marts={p.source_marts} />
                      : <span className={s.muted}>마트 없음</span>}
                  </td>
                  <td>
                    {p.baseline
                      ? (
                        <span>
                          {Math.round(p.baseline.min).toLocaleString()}
                          {p.baseline.max !== p.baseline.min && ` ~ ${Math.round(p.baseline.max).toLocaleString()}`}원
                        </span>
                      )
                      : <span className={s.muted}>—</span>}
                  </td>
                  <td className={s.muted}>{fmt(p.updated_at)}</td>
                  <td>
                    <div className={s.actions}>
                      <button title="편집" onClick={() => alert(`상품 ${p.id} 편집 — 상세 모달은 기존 /products 페이지 사용`)}>
                        <Edit2 size={14} />
                      </button>
                      <button title="병합" onClick={() => alert(`병합 후보 검색은 정합성 점검 > 중복 의심에서 진입`)}>
                        <Merge size={14} />
                      </button>
                      <button title="삭제" className={s.del} onClick={() => handleDelete(p)}>
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {!loading && products.length === 0 && (
                <tr><td colSpan={8} className={s.empty}>해당 카테고리에 상품 없음</td></tr>
              )}
            </tbody>
          </table>

          <div className={s.pager}>
            <button disabled={page <= 1} onClick={() => setPage(p => p - 1)}>이전</button>
            <span>페이지 {page}</span>
            <button disabled={products.length < 50} onClick={() => setPage(p => p + 1)}>다음</button>
          </div>
        </main>
      </div>
    </div>
  );
}

function fmt(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('ko-KR');
}
