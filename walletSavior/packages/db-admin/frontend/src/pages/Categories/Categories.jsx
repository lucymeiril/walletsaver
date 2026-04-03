import { useState, useMemo, useEffect } from 'react';
import {
  ChevronRight, ChevronDown, Plus, Pencil, Trash2, X,
  Package, Search, FolderInput, AlertTriangle,
} from 'lucide-react';
import useDbAdminStore from '../../stores/dbAdminStore';
import s from './Categories.module.css';

/* ── 트리 평탄화: 드롭다운용 ── */
function flattenTree(nodes, depth = 0) {
  const result = [];
  for (const n of nodes) {
    result.push({ id: n.id, name: n.name, depth });
    if (n.children?.length) {
      result.push(...flattenTree(n.children, depth + 1));
    }
  }
  return result;
}

/* ── 재귀 상품 수 합산 ── */
function countProducts(node) {
  const own = node.productCount ?? 0;
  const childSum = (node.children || []).reduce((sum, c) => sum + countProducts(c), 0);
  return own + childSum;
}

/* ── 하위 ID 수집 (순환 방지용) ── */
function collectDescendantIds(node) {
  const ids = new Set([node.id]);
  for (const c of node.children || []) {
    for (const id of collectDescendantIds(c)) ids.add(id);
  }
  return ids;
}

/* ── 트리에서 노드 찾기 ── */
function findNode(nodes, id) {
  for (const n of nodes) {
    if (n.id === id) return n;
    if (n.children?.length) {
      const found = findNode(n.children, id);
      if (found) return found;
    }
  }
  return null;
}

/* ── 검색어로 트리 필터 ── */
function filterTree(nodes, query) {
  if (!query) return nodes;
  const q = query.toLowerCase();
  return nodes.reduce((acc, node) => {
    const nameMatch = node.name.toLowerCase().includes(q) || node.id.toLowerCase().includes(q);
    const filteredChildren = filterTree(node.children || [], query);
    if (nameMatch || filteredChildren.length > 0) {
      acc.push({ ...node, children: filteredChildren });
    }
    return acc;
  }, []);
}

export default function Categories() {
  const {
    categories, addCategory, updateCategory, deleteCategory, moveCategory, fetchCategories,
  } = useDbAdminStore();

  const [expanded, setExpanded] = useState(new Set());
  const [modal, setModal] = useState(null);
  const [form, setForm] = useState({});
  const [searchQuery, setSearchQuery] = useState('');

  useEffect(() => { fetchCategories(); }, []);

  // 검색 시 전체 펼치기
  const filteredCategories = useMemo(
    () => filterTree(categories, searchQuery),
    [categories, searchQuery],
  );

  // 검색 중이면 모든 노드를 펼침
  const effectiveExpanded = useMemo(() => {
    if (!searchQuery) return expanded;
    const all = new Set();
    const collect = (nodes) => {
      for (const n of nodes) {
        if (n.children?.length) {
          all.add(n.id);
          collect(n.children);
        }
      }
    };
    collect(filteredCategories);
    return all;
  }, [searchQuery, expanded, filteredCategories]);

  const flatList = useMemo(() => flattenTree(categories), [categories]);

  const toggle = (id) => {
    setExpanded(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const expandAll = () => {
    const all = new Set();
    const collect = (nodes) => {
      for (const n of nodes) {
        if (n.children?.length) { all.add(n.id); collect(n.children); }
      }
    };
    collect(categories);
    setExpanded(all);
  };

  const collapseAll = () => setExpanded(new Set());

  /* ── 추가 모달 ── */
  const openAdd = (parentId = null) => {
    setForm({ name: '', parentId, attributes: { origin: '', storage: '', grade: '' } });
    setModal({ mode: 'add' });
  };

  /* ── 수정 모달 ── */
  const openEdit = (cat) => {
    setForm({
      name: cat.name,
      attributes: cat.attributes || { origin: '', storage: '', grade: '' },
    });
    setModal({ mode: 'edit', category: cat });
  };

  /* ── 이동 모달 ── */
  const openMove = (cat) => {
    setForm({ newParentId: cat.parent_id || '' });
    setModal({ mode: 'move', category: cat });
  };

  /* ── 저장 ── */
  const handleSave = async () => {
    if (modal.mode === 'add') {
      const parentId = form.parentId || null;
      const parentNode = parentId ? findNode(categories, parentId) : null;
      const slug = form.name.replace(/\s+/g, '-').toLowerCase();
      const autoId = parentNode ? `${parentNode.id}.${slug}` : slug;
      await addCategory(parentId, {
        id: autoId,
        name: form.name,
        attributes: form.attributes,
      });
    } else if (modal.mode === 'edit') {
      await updateCategory(modal.category.id, {
        name: form.name,
        attributes: form.attributes,
      });
    } else if (modal.mode === 'move') {
      await moveCategory(modal.category.id, form.newParentId || null);
    }
    setModal(null);
  };

  /* ── 삭제 ── */
  const handleDelete = (cat) => {
    const count = countProducts(cat);
    const msg = count > 0
      ? `이 카테고리에 ${count}개의 상품이 소속되어 있습니다.\n삭제하면 상품의 카테고리가 해제됩니다. 계속하시겠습니까?`
      : '하위 카테고리도 함께 삭제됩니다. 계속하시겠습니까?';
    if (confirm(msg)) deleteCategory(cat.id);
  };

  /* ── 빈 카테고리 수 ── */
  const emptyCount = useMemo(() => {
    let count = 0;
    const walk = (nodes) => {
      for (const n of nodes) {
        if (countProducts(n) === 0) count++;
        if (n.children?.length) walk(n.children);
      }
    };
    walk(categories);
    return count;
  }, [categories]);

  return (
    <div className={s.page}>
      <div className={s.header}>
        <h2 className={s.title}>카테고리 관리</h2>
        <div className={s.headerActions}>
          <button className={s.addBtn} onClick={() => openAdd(null)}>
            <Plus size={16} /> 최상위 카테고리 추가
          </button>
        </div>
      </div>

      {/* 툴바: 검색 + 접기/펼치기 */}
      <div className={s.toolbar}>
        <div className={s.searchWrap}>
          <Search size={16} className={s.searchIcon} />
          <input
            className={s.searchInput}
            placeholder="카테고리 검색..."
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
          />
          {searchQuery && (
            <button className={s.clearBtn} onClick={() => setSearchQuery('')}>
              <X size={14} />
            </button>
          )}
        </div>
        <div className={s.toggleBtns}>
          <button onClick={expandAll} className={s.toolBtn}>전체 펼치기</button>
          <button onClick={collapseAll} className={s.toolBtn}>전체 접기</button>
        </div>
      </div>

      {/* 빈 카테고리 안내 */}
      {emptyCount > 0 && (
        <div className={s.emptyBanner}>
          <AlertTriangle size={16} />
          <span>상품이 없는 빈 카테고리가 <strong>{emptyCount}개</strong> 있습니다. 정리를 권장합니다.</span>
        </div>
      )}

      {/* 트리 */}
      <div className={s.treeWrap}>
        {filteredCategories.length === 0 ? (
          <div className={s.emptyTree}>
            {searchQuery ? '검색 결과가 없습니다.' : '카테고리가 없습니다.'}
          </div>
        ) : (
          filteredCategories.map(cat => (
            <TreeNode
              key={cat.id}
              node={cat}
              depth={0}
              expanded={effectiveExpanded}
              toggle={toggle}
              onAdd={openAdd}
              onEdit={openEdit}
              onDelete={handleDelete}
              onMove={openMove}
            />
          ))
        )}
      </div>

      {/* ── 모달 ── */}
      {modal && (
        <div className={s.overlay} onClick={() => setModal(null)}>
          <div className={s.modal} onClick={e => e.stopPropagation()}>
            <div className={s.modalHeader}>
              <h3>
                {modal.mode === 'add' && '카테고리 추가'}
                {modal.mode === 'edit' && '카테고리 수정'}
                {modal.mode === 'move' && '카테고리 이동'}
              </h3>
              <button onClick={() => setModal(null)}><X size={18} /></button>
            </div>
            <div className={s.form}>
              {/* ── 추가/수정 폼 ── */}
              {(modal.mode === 'add' || modal.mode === 'edit') && (
                <>
                  {modal.mode === 'add' && (
                    <label>
                      부모 카테고리
                      <select
                        value={form.parentId || ''}
                        onChange={e => setForm({ ...form, parentId: e.target.value || null })}
                      >
                        <option value="">없음 (최상위)</option>
                        {flatList.map(c => (
                          <option key={c.id} value={c.id}>
                            {'─'.repeat(c.depth)} {c.name}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                  <label>
                    이름
                    <input
                      value={form.name}
                      onChange={e => setForm({ ...form, name: e.target.value })}
                      placeholder="예: 소고기"
                    />
                  </label>
                  {modal.mode === 'add' && form.name && (
                    <div className={s.idPreview}>
                      ID 미리보기:{' '}
                      <code>
                        {form.parentId
                          ? `${findNode(categories, form.parentId)?.id || form.parentId}.${form.name.replace(/\s+/g, '-').toLowerCase()}`
                          : form.name.replace(/\s+/g, '-').toLowerCase()}
                      </code>
                    </div>
                  )}
                  <label>
                    등급
                    <input
                      value={form.attributes?.grade || ''}
                      onChange={e => setForm({ ...form, attributes: { ...form.attributes, grade: e.target.value } })}
                      placeholder="예: 1등급, 1++등급"
                    />
                  </label>
                  <label>
                    원산지
                    <input
                      value={form.attributes?.origin || ''}
                      onChange={e => setForm({ ...form, attributes: { ...form.attributes, origin: e.target.value } })}
                      placeholder="예: 국내산, 수입산"
                    />
                  </label>
                  <label>
                    보관 방법
                    <select
                      value={form.attributes?.storage || ''}
                      onChange={e => setForm({ ...form, attributes: { ...form.attributes, storage: e.target.value } })}
                    >
                      <option value="">선택</option>
                      <option value="냉장">냉장</option>
                      <option value="냉동">냉동</option>
                      <option value="상온">상온</option>
                    </select>
                  </label>
                </>
              )}

              {/* ── 이동 폼 ── */}
              {modal.mode === 'move' && (
                <>
                  <p className={s.moveInfo}>
                    <strong>{modal.category.name}</strong>의 새 부모 카테고리를 선택하세요.
                  </p>
                  <label>
                    새 부모 카테고리
                    <select
                      value={form.newParentId || ''}
                      onChange={e => setForm({ ...form, newParentId: e.target.value || null })}
                    >
                      <option value="">없음 (최상위로 이동)</option>
                      {flatList
                        .filter(c => {
                          const node = findNode(categories, modal.category.id);
                          if (!node) return c.id !== modal.category.id;
                          const descendants = collectDescendantIds(node);
                          return !descendants.has(c.id);
                        })
                        .map(c => (
                          <option key={c.id} value={c.id}>
                            {'─'.repeat(c.depth)} {c.name}
                          </option>
                        ))}
                    </select>
                  </label>
                </>
              )}

              <div className={s.formActions}>
                <button className={s.cancelBtn} onClick={() => setModal(null)}>취소</button>
                <button
                  className={s.saveBtn}
                  onClick={handleSave}
                  disabled={modal.mode !== 'move' && !form.name?.trim()}
                >
                  {modal.mode === 'move' ? '이동' : '저장'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── 트리 노드 컴포넌트 ── */
function TreeNode({ node, depth, expanded, toggle, onAdd, onEdit, onDelete, onMove }) {
  const hasChildren = node.children && node.children.length > 0;
  const isOpen = expanded.has(node.id);
  const totalCount = countProducts(node);
  const ownCount = node.productCount ?? 0;
  const childCount = (node.children || []).length;
  const isEmpty = totalCount === 0;

  return (
    <div className={s.treeNode}>
      <div
        className={`${s.nodeRow} ${isEmpty ? s.emptyNode : ''}`}
        style={{ paddingLeft: `${depth * 24 + 12}px` }}
      >
        <button
          className={s.expandBtn}
          onClick={() => hasChildren && toggle(node.id)}
          style={{ visibility: hasChildren ? 'visible' : 'hidden' }}
        >
          {isOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        </button>
        <span className={`${s.nodeName} ${isEmpty ? s.emptyName : ''}`}>{node.name}</span>
        {hasChildren && (
          <span className={s.childBadge}>{childCount}개 하위</span>
        )}
        <span className={`${s.badge} ${ownCount === 0 ? s.badgeEmpty : ''}`}>
          <Package size={11} /> {ownCount}
        </span>
        {node.attributes && (
          <div className={s.attrs}>
            {node.attributes.origin && <span className={s.attr}>{node.attributes.origin}</span>}
            {node.attributes.storage && <span className={s.attr}>{node.attributes.storage}</span>}
            {node.attributes.grade && <span className={s.attr}>{node.attributes.grade}</span>}
          </div>
        )}
        <div className={s.nodeActions}>
          <button title="하위 추가" onClick={() => onAdd(node.id)}><Plus size={14} /></button>
          <button title="수정" onClick={() => onEdit(node)}><Pencil size={14} /></button>
          <button title="이동" onClick={() => onMove(node)}><FolderInput size={14} /></button>
          <button title="삭제" onClick={() => onDelete(node)}><Trash2 size={14} /></button>
        </div>
      </div>
      {isOpen && hasChildren && (
        <div className={s.children}>
          {node.children.map(child => (
            <TreeNode
              key={child.id}
              node={child}
              depth={depth + 1}
              expanded={expanded}
              toggle={toggle}
              onAdd={onAdd}
              onEdit={onEdit}
              onDelete={onDelete}
              onMove={onMove}
            />
          ))}
        </div>
      )}
    </div>
  );
}
