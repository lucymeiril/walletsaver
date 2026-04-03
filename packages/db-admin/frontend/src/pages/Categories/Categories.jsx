import { useState } from 'react';
import { ChevronRight, ChevronDown, Plus, Pencil, Trash2, X, Package } from 'lucide-react';
import useDbAdminStore from '../../stores/dbAdminStore';
import s from './Categories.module.css';

export default function Categories() {
  const { categories, addCategory, updateCategory, deleteCategory } = useDbAdminStore();
  const [expanded, setExpanded] = useState(new Set(['cat-1']));
  const [modal, setModal] = useState(null);
  const [form, setForm] = useState({});

  const toggle = (id) => {
    setExpanded(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const openAdd = (parentId = null) => {
    setForm({ name: '', attributes: { origin: '', storage: '', grade: '' } });
    setModal({ mode: 'add', parentId });
  };

  const openEdit = (cat) => {
    setForm({ name: cat.name, attributes: cat.attributes || { origin: '', storage: '', grade: '' } });
    setModal({ mode: 'edit', category: cat });
  };

  const handleSave = () => {
    if (modal.mode === 'add') {
      addCategory(modal.parentId, { name: form.name, attributes: form.attributes });
    } else {
      updateCategory(modal.category.id, { name: form.name, attributes: form.attributes });
    }
    setModal(null);
  };

  const handleDelete = (id) => {
    if (confirm('하위 카테고리도 함께 삭제됩니다. 계속하시겠습니까?')) deleteCategory(id);
  };

  return (
    <div className={s.page}>
      <div className={s.header}>
        <h2 className={s.title}>카테고리 관리</h2>
        <button className={s.addBtn} onClick={() => openAdd(null)}>
          <Plus size={16} /> 최상위 카테고리 추가
        </button>
      </div>

      <div className={s.treeWrap}>
        {categories.map(cat => (
          <TreeNode
            key={cat.id}
            node={cat}
            depth={0}
            expanded={expanded}
            toggle={toggle}
            onAdd={openAdd}
            onEdit={openEdit}
            onDelete={handleDelete}
          />
        ))}
      </div>

      {/* 모달 */}
      {modal && (
        <div className={s.overlay} onClick={() => setModal(null)}>
          <div className={s.modal} onClick={e => e.stopPropagation()}>
            <div className={s.modalHeader}>
              <h3>{modal.mode === 'add' ? '카테고리 추가' : '카테고리 수정'}</h3>
              <button onClick={() => setModal(null)}><X size={18} /></button>
            </div>
            <div className={s.form}>
              <label>
                이름
                <input value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} />
              </label>
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

function TreeNode({ node, depth, expanded, toggle, onAdd, onEdit, onDelete }) {
  const hasChildren = node.children && node.children.length > 0;
  const isOpen = expanded.has(node.id);
  const count = node.productCount ?? countProducts(node);

  return (
    <div className={s.treeNode}>
      <div className={s.nodeRow} style={{ paddingLeft: `${depth * 24 + 12}px` }}>
        <button
          className={s.expandBtn}
          onClick={() => hasChildren && toggle(node.id)}
          style={{ visibility: hasChildren ? 'visible' : 'hidden' }}
        >
          {isOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        </button>
        <span className={s.nodeName}>{node.name}</span>
        {count > 0 && (
          <span className={s.badge}><Package size={11} /> {count}</span>
        )}
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
          <button title="삭제" onClick={() => onDelete(node.id)}><Trash2 size={14} /></button>
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
            />
          ))}
        </div>
      )}
    </div>
  );
}

function countProducts(node) {
  if (node.productCount) return node.productCount;
  if (!node.children) return 0;
  return node.children.reduce((sum, child) => sum + countProducts(child), 0);
}
