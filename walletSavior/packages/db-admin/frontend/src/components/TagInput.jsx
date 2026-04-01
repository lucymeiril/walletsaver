import { useState, useRef, useEffect, useCallback } from 'react';
import { X, Plus } from 'lucide-react';
import s from './TagInput.module.css';

export default function TagInput({
  value = [],        // [{ id, keyword }]
  onChange,           // (tags) => void
  onSearch,           // async (query) => [{ id, keyword, ... }]
  onCreateKeyword,    // async (word) => created keyword
  placeholder = '키워드 검색 또는 입력...',
}) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [suggestions, setSuggestions] = useState([]);
  const [activeIdx, setActiveIdx] = useState(-1);
  const [loading, setLoading] = useState(false);
  const wrapRef = useRef(null);
  const inputRef = useRef(null);
  const debounceRef = useRef(null);

  // Close on outside click
  useEffect(() => {
    const handler = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const doSearch = useCallback(async (q) => {
    if (!q.trim()) { setSuggestions([]); return; }
    setLoading(true);
    try {
      const results = await onSearch(q.trim());
      const arr = Array.isArray(results) ? results : results?.keywords ?? results?.data ?? [];
      // Filter out already selected
      const selectedIds = new Set(value.map((t) => t.id));
      setSuggestions(arr.filter((kw) => !selectedIds.has(kw.id)));
    } catch {
      setSuggestions([]);
    } finally {
      setLoading(false);
    }
  }, [onSearch, value]);

  const handleInputChange = (e) => {
    const q = e.target.value;
    setQuery(q);
    setActiveIdx(-1);
    setOpen(true);
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => doSearch(q), 200);
  };

  const selectKeyword = (kw) => {
    const tag = { id: kw.id, keyword: kw.keyword || kw.word || '' };
    onChange([...value, tag]);
    setQuery('');
    setSuggestions([]);
    setOpen(false);
    inputRef.current?.focus();
  };

  const removeTag = (id) => {
    onChange(value.filter((t) => t.id !== id));
  };

  const handleCreateAndSelect = async () => {
    if (!query.trim()) return;
    const word = query.trim();
    // Check if already selected
    if (value.some((t) => (t.keyword || t.word) === word)) { setQuery(''); return; }
    try {
      await onCreateKeyword(word);
      // Optimistic — use temporary id, will reconcile on next fetch
      const tempTag = { id: `kw-new-${Date.now()}`, keyword: word };
      onChange([...value, tempTag]);
      setQuery('');
      setSuggestions([]);
      setOpen(false);
      inputRef.current?.focus();
    } catch {
      // Error handled silently; keyword creation failed
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Backspace' && !query && value.length > 0) {
      removeTag(value[value.length - 1].id);
      return;
    }
    if (!open) return;
    const totalItems = suggestions.length + (query.trim() ? 1 : 0); // +1 for create option
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIdx((i) => Math.min(i + 1, totalItems - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (activeIdx >= 0 && activeIdx < suggestions.length) {
        selectKeyword(suggestions[activeIdx]);
      } else if (query.trim()) {
        handleCreateAndSelect();
      }
    } else if (e.key === 'Escape') {
      setOpen(false);
    }
  };

  const exactMatch = query.trim() && suggestions.some(
    (kw) => (kw.keyword || kw.word || '').toLowerCase() === query.trim().toLowerCase(),
  );

  return (
    <div className={s.wrap} ref={wrapRef}>
      <div className={s.box} onClick={() => inputRef.current?.focus()}>
        {value.map((tag) => (
          <span key={tag.id} className={s.tag}>
            {tag.keyword || tag.word}
            <span className={s.tagX} onClick={() => removeTag(tag.id)}><X size={11} /></span>
          </span>
        ))}
        <input
          ref={inputRef}
          className={s.input}
          value={query}
          onChange={handleInputChange}
          onFocus={() => { if (query.trim()) setOpen(true); }}
          onKeyDown={handleKeyDown}
          placeholder={value.length === 0 ? placeholder : ''}
        />
      </div>

      {open && (query.trim() || suggestions.length > 0) && (
        <div className={s.dropdown}>
          {loading && <div className={s.loading}>검색 중...</div>}
          {!loading && suggestions.map((kw, idx) => (
            <div
              key={kw.id}
              className={`${s.option} ${idx === activeIdx ? s.optionActive : ''}`}
              onClick={() => selectKeyword(kw)}
              onMouseEnter={() => setActiveIdx(idx)}
            >
              {kw.keyword || kw.word}
            </div>
          ))}
          {!loading && query.trim() && !exactMatch && (
            <div
              className={s.createOption}
              onClick={handleCreateAndSelect}
              onMouseEnter={() => setActiveIdx(suggestions.length)}
            >
              <Plus size={14} /> "{query.trim()}" 새 키워드 추가
            </div>
          )}
        </div>
      )}
    </div>
  );
}
