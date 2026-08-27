import { useState, useEffect, useRef, useCallback } from 'react';
import { fmt } from '../../utils/helpers';
import s from './ProductPicker.module.css';

export default function ProductPicker({ selected, onChange }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const wrapRef = useRef(null);
  const timerRef = useRef(null);
  const controllerRef = useRef(null);

  useEffect(() => {
    const handler = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  useEffect(() => () => {
    clearTimeout(timerRef.current);
    controllerRef.current?.abort();
  }, []);

  const search = useCallback(async (value) => {
    const q = value.trim();
    if (!q) {
      controllerRef.current?.abort();
      setResults([]);
      setOpen(false);
      setLoading(false);
      return;
    }

    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setLoading(true);

    try {
      const response = await fetch(
        `/api/products/search?q=${encodeURIComponent(q)}&per_page=5`,
        { signal: controller.signal },
      );
      if (!response.ok) throw new Error(`product search failed: ${response.status}`);
      const json = await response.json();
      setResults(Array.isArray(json.data) ? json.data.slice(0, 5) : []);
      setOpen(true);
    } catch (error) {
      if (error.name !== 'AbortError') {
        setResults([]);
        setOpen(true);
      }
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, []);

  const handleInputChange = (e) => {
    const value = e.target.value;
    setQuery(value);
    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => search(value), 300);
  };

  const handleSelect = (product) => {
    if (selected.some((p) => p.id === product.id)) return;
    onChange([...selected, product]);
    setQuery('');
    setResults([]);
    setOpen(false);
  };

  const handleRemove = (id) => {
    onChange(selected.filter((p) => p.id !== id));
  };

  return (
    <div className={s.wrap} ref={wrapRef}>
      <div className={s.searchBox}>
        <input
          className={s.searchInput}
          value={query}
          onChange={handleInputChange}
          onFocus={() => query.trim() && results.length > 0 && setOpen(true)}
          placeholder="품목명 검색 (자동완성)"
        />
        {open && (
          <div className={s.dropdown}>
            {loading && <div className={s.noResult}>검색 중...</div>}
            {!loading && results.length === 0 && query.trim() && (
              <div className={s.noResult}>검색 결과가 없습니다</div>
            )}
            {results.map((p) => (
              <div key={p.id} className={s.item} onClick={() => handleSelect(p)}>
                <div>
                  <div className={s.itemName}>{p.name}</div>
                  <div className={s.itemMeta}>{p.cat || p.category || ''}</div>
                </div>
                {p.avg != null && <span className={s.itemPrice}>평균 {fmt(p.avg)}원</span>}
              </div>
            ))}
          </div>
        )}
      </div>

      {selected.length > 0 && (
        <div className={s.chips}>
          {selected.map((p) => (
            <span key={p.id} className={s.chip}>
              {p.name}
              <button type="button" className={s.chipRemove} onClick={() => handleRemove(p.id)}>×</button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
