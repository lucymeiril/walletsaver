import { useState, useRef, useMemo, useEffect } from 'react';
import { X, Plus, ChevronDown } from 'lucide-react';
import s from './SearchableSelect.module.css';

/**
 * Flatten a hierarchical category tree into a list with path labels.
 * e.g. "농축산물 > 육류 > 소고기"
 */
function flattenTree(nodes, path = []) {
  const result = [];
  for (const node of nodes) {
    const currentPath = [...path, node.name];
    result.push({ id: node.id, name: node.name, path: currentPath.join(' > ') });
    if (node.children?.length) {
      result.push(...flattenTree(node.children, currentPath));
    }
  }
  return result;
}

export default function SearchableSelect({
  categories = [],
  value,           // selected category id or name
  onChange,         // (id, name, path) => void
  onCreateCategory, // async (parentId, { name }) => created category
  placeholder = '카테고리 검색...',
}) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [activeIdx, setActiveIdx] = useState(-1);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState('');
  const [newParent, setNewParent] = useState('');
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState('');
  const wrapRef = useRef(null);
  const inputRef = useRef(null);

  const flat = useMemo(() => flattenTree(categories), [categories]);

  const selectedItem = useMemo(
    () => flat.find((c) => c.id === value || c.name === value),
    [flat, value],
  );

  const filtered = useMemo(() => {
    if (!query) return flat;
    const q = query.toLowerCase();
    return flat.filter(
      (c) => c.name.toLowerCase().includes(q) || c.path.toLowerCase().includes(q),
    );
  }, [flat, query]);

  // Close on outside click
  useEffect(() => {
    const handler = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) {
        setOpen(false);
        setShowCreate(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const handleSelect = (item) => {
    onChange(item.id, item.name, item.path);
    setQuery('');
    setOpen(false);
    setActiveIdx(-1);
  };

  const handleClear = (e) => {
    e.stopPropagation();
    onChange('', '', '');
    setQuery('');
    inputRef.current?.focus();
  };

  const handleKeyDown = (e) => {
    if (!open) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIdx((i) => Math.min(i + 1, filtered.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter' && activeIdx >= 0 && filtered[activeIdx]) {
      e.preventDefault();
      handleSelect(filtered[activeIdx]);
    } else if (e.key === 'Escape') {
      setOpen(false);
    }
  };

  const handleCreate = async () => {
    if (!newName.trim()) return;
    setCreating(true);
    setCreateError('');
    try {
      await onCreateCategory(newParent || null, { name: newName.trim() });
      // After creation, categories will update from store — find and select
      const createdId = `cat-${newName.trim().replace(/\s+/g, '-')}-${Date.now()}`;
      onChange(createdId, newName.trim(), newName.trim());
      setNewName('');
      setNewParent('');
      setShowCreate(false);
      setOpen(false);
    } catch (err) {
      setCreateError('카테고리 생성 실패');
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className={s.wrap} ref={wrapRef}>
      <div
        className={s.selected}
        onClick={() => { setOpen(true); setTimeout(() => inputRef.current?.focus(), 0); }}
      >
        {selectedItem ? (
          <>
            <span className={s.chip}>
              {selectedItem.name}
              <span className={s.chipX} onClick={handleClear}><X size={12} /></span>
            </span>
          </>
        ) : null}
        <input
          ref={inputRef}
          className={s.input}
          value={query}
          onChange={(e) => { setQuery(e.target.value); setOpen(true); setActiveIdx(-1); }}
          onFocus={() => setOpen(true)}
          onKeyDown={handleKeyDown}
          placeholder={selectedItem ? '' : placeholder}
        />
        <ChevronDown size={14} style={{ color: 'var(--text3)', flexShrink: 0 }} />
      </div>

      {open && (
        <div className={s.dropdown}>
          {filtered.length > 0 ? (
            filtered.map((item, idx) => (
              <div
                key={item.id}
                className={`${s.option} ${idx === activeIdx ? s.optionActive : ''}`}
                onClick={() => handleSelect(item)}
                onMouseEnter={() => setActiveIdx(idx)}
              >
                <span>{item.name}</span>
                {item.path !== item.name && (
                  <span className={s.optionPath}>{item.path}</span>
                )}
              </div>
            ))
          ) : (
            <div className={s.empty}>일치하는 카테고리가 없습니다</div>
          )}

          {!showCreate ? (
            <div className={s.createRow} onClick={() => setShowCreate(true)}>
              <Plus size={14} /> 새 카테고리
            </div>
          ) : (
            <div className={s.inlineForm} onClick={(e) => e.stopPropagation()}>
              <div className={s.inlineFormRow}>
                <input
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="카테고리 이름"
                  onKeyDown={(e) => { if (e.key === 'Enter') handleCreate(); }}
                  autoFocus
                />
              </div>
              <select value={newParent} onChange={(e) => setNewParent(e.target.value)}>
                <option value="">최상위</option>
                {flat.map((c) => (
                  <option key={c.id} value={c.id}>{c.path}</option>
                ))}
              </select>
              {createError && <span className={s.inlineError}>{createError}</span>}
              <div className={s.inlineFormRow}>
                <button className={s.inlineCancelBtn} onClick={() => { setShowCreate(false); setNewName(''); setCreateError(''); }}>
                  취소
                </button>
                <button className={s.inlineBtn} onClick={handleCreate} disabled={creating || !newName.trim()}>
                  {creating ? '생성 중...' : '생성'}
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
