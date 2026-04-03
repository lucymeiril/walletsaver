import { useState, useRef, useEffect, useCallback } from 'react';
import { Search, X, Clock } from 'lucide-react';
import s from './SearchBar.module.css';

export default function SearchBar({
  onSearch,
  onSelect,
  suggestions = [],
  placeholder = '검색어를 입력하세요',
  recentSearches = [],
  className = '',
}) {
  const [query, setQuery] = useState('');
  const [isOpen, setIsOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const inputRef = useRef(null);
  const wrapperRef = useRef(null);
  const debounceRef = useRef(null);

  const handleChange = useCallback((e) => {
    const value = e.target.value;
    setQuery(value);
    setActiveIndex(-1);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      if (onSearch) onSearch(value);
    }, 300);
  }, [onSearch]);

  useEffect(() => {
    const handleClick = (e) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  useEffect(() => {
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, []);

  const handleSelect = (value) => {
    setQuery(value);
    setIsOpen(false);
    if (onSelect) onSelect(value);
  };

  const handleClear = () => {
    setQuery('');
    setIsOpen(false);
    inputRef.current?.focus();
    if (onSearch) onSearch('');
  };

  const handleKeyDown = (e) => {
    const items = suggestions.length > 0 ? suggestions : recentSearches;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIndex((prev) => (prev < items.length - 1 ? prev + 1 : 0));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIndex((prev) => (prev > 0 ? prev - 1 : items.length - 1));
    } else if (e.key === 'Enter' && activeIndex >= 0) {
      e.preventDefault();
      const item = items[activeIndex];
      handleSelect(typeof item === 'string' ? item : item.label || item);
    } else if (e.key === 'Escape') {
      setIsOpen(false);
    }
  };

  const showDropdown = isOpen && (suggestions.length > 0 || (query === '' && recentSearches.length > 0));

  return (
    <div className={`${s.wrapper} ${className}`} ref={wrapperRef}>
      <div className={s.inputWrap}>
        <Search className={s.searchIcon} size={18} />
        <input
          ref={inputRef}
          type="search"
          className={s.input}
          placeholder={placeholder}
          value={query}
          onChange={handleChange}
          onFocus={() => setIsOpen(true)}
          onKeyDown={handleKeyDown}
          aria-label="검색"
          autoComplete="off"
        />
        {query && (
          <button className={s.clearBtn} onClick={handleClear} aria-label="검색어 지우기">
            <X size={16} />
          </button>
        )}
      </div>

      {showDropdown && (
        <div className={s.dropdown}>
          {suggestions.length > 0
            ? suggestions.map((item, i) => {
                const label = typeof item === 'string' ? item : item.label;
                return (
                  <button
                    key={i}
                    className={`${s.item} ${i === activeIndex ? s.active : ''}`}
                    onClick={() => handleSelect(label)}
                    onMouseEnter={() => setActiveIndex(i)}
                  >
                    <Search size={14} className={s.itemIcon} />
                    <span>{label}</span>
                  </button>
                );
              })
            : recentSearches.map((item, i) => (
                <button
                  key={i}
                  className={`${s.item} ${i === activeIndex ? s.active : ''}`}
                  onClick={() => handleSelect(item)}
                  onMouseEnter={() => setActiveIndex(i)}
                >
                  <Clock size={14} className={s.itemIcon} />
                  <span>{item}</span>
                </button>
              ))}
        </div>
      )}
    </div>
  );
}
