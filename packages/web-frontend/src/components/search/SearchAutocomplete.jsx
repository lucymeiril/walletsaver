import { useState, useEffect, useRef, useCallback, useMemo, memo } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, Clock } from 'lucide-react';
import useStore from '../../stores/appStore';
import useModalStore from '../../stores/modalStore';
import { searchService } from '../../services/searchService';
import { fmt } from '../../utils/helpers';
import s from './SearchAutocomplete.module.css';

function highlightMatch(text, query) {
  if (!query || !text) return text;
  const idx = text.toLowerCase().indexOf(query.toLowerCase());
  if (idx === -1) return text;
  return (
    <>
      {text.slice(0, idx)}
      <strong>{text.slice(idx, idx + query.length)}</strong>
      {text.slice(idx + query.length)}
    </>
  );
}

/**
 * Shared autocomplete search component.
 *
 * @param {"header"|"page"|"inline"} variant
 * @param {string}   placeholder
 * @param {function} onSearch        — called on Enter / submit (receives query string)
 * @param {function} onKeywordClick  — optional override for keyword click
 * @param {function} onProductClick  — optional override for product click
 * @param {string}   initialValue
 * @param {boolean}  autoFocus
 * @param {string}   className       — extra wrapper class
 * @param {function} onAfterAction   — called after any navigation / click (e.g. to close header search bar)
 */
const SearchAutocomplete = memo(function SearchAutocomplete({
  variant = 'inline',
  placeholder = '검색어를 입력하세요...',
  onSearch,
  onKeywordClick,
  onProductClick,
  initialValue = '',
  autoFocus = false,
  className = '',
  onAfterAction,
}) {
  /* ── All hooks first (before any early return) ── */
  const [searchQuery, setSearchQuery] = useState(initialValue);
  const [keywords, setKeywords] = useState([]);
  const [products, setProducts] = useState([]);
  const [totalKeywords, setTotalKeywords] = useState(0);
  const [totalProducts, setTotalProducts] = useState(0);
  const [trendingKeywords, setTrendingKeywords] = useState([]);
  const [showDropdown, setShowDropdown] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);

  const debounceRef = useRef(null);
  const abortRef = useRef(null);
  const wrapperRef = useRef(null);
  const inputRef = useRef(null);

  const navigate = useNavigate();
  const recentSearches = useStore((st) => st.recentSearches);
  const addRecentSearch = useStore((st) => st.addRecentSearch);
  const { openMartModal, openHotdealModal, openProductModal } = useModalStore();

  // sync initialValue when it changes externally (e.g. URL param)
  useEffect(() => {
    setSearchQuery(initialValue);
  }, [initialValue]);

  // load trending keywords once
  useEffect(() => {
    searchService
      .trending(8)
      .then((res) => setTrendingKeywords(res.data || []))
      .catch(() => {});
  }, []);

  // close dropdown on outside click
  useEffect(() => {
    const handleClick = (e) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target)) {
        setShowDropdown(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  // cleanup debounce timer and abort controller on unmount
  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      if (abortRef.current) abortRef.current.abort();
    };
  }, []);

  /* ── Autocomplete fetch (200ms debounce, with abort controller) ── */
  const fetchAutocomplete = useCallback((value) => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (abortRef.current) abortRef.current.abort();

    if (!value || value.length < 1) {
      setKeywords([]);
      setProducts([]);
      setTotalKeywords(0);
      setTotalProducts(0);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      const controller = new AbortController();
      abortRef.current = controller;
      try {
        const res = await searchService.autocomplete(value, 10, { signal: controller.signal });
        if (controller.signal.aborted) return;
        const d = res.data || {};
        setKeywords(d.keywords || []);
        setProducts(d.products || []);
        setTotalKeywords(d.total_keyword_count || 0);
        setTotalProducts(d.total_product_count || 0);
      } catch (err) {
        if (err?.name === 'AbortError') return;
        setKeywords([]);
        setProducts([]);
      }
    }, 200);
  }, []);

  /* ── helpers to reset state after an action ── */
  const resetState = useCallback(() => {
    setShowDropdown(false);
    setKeywords([]);
    setProducts([]);
    setSearchQuery('');
    if (onAfterAction) onAfterAction();
  }, [onAfterAction]);

  /* ── search submit ── */
  const handleSearch = useCallback(() => {
    if (!searchQuery.trim()) return;
    addRecentSearch(searchQuery.trim());
    if (onSearch) {
      onSearch(searchQuery.trim());
    } else {
      navigate(`/search?q=${encodeURIComponent(searchQuery.trim())}`);
    }
    resetState();
  }, [searchQuery, addRecentSearch, onSearch, navigate, resetState]);

  /* ── input change ── */
  const handleInputChange = useCallback((e) => {
    const value = e.target.value;
    setSearchQuery(value);
    setActiveIndex(-1);
    setShowDropdown(true);
    fetchAutocomplete(value);
  }, [fetchAutocomplete]);

  /* ── keyword click ── */
  const handleKeywordClick = useCallback(
    (kw) => {
      addRecentSearch(kw.word);
      searchService.trackKeyword(kw.id);

      if (onKeywordClick) {
        onKeywordClick(kw);
      } else if (products.length > 0) {
        // Prioritize product name match over keyword category redirect
        navigate(`/search?q=${encodeURIComponent(kw.word)}`);
      } else if (kw.suggested_action === 'category_page' && kw.category_id && kw.category_path?.toLowerCase().includes(kw.word?.toLowerCase?.().slice(0, 2))) {
        navigate(`/price/category/${kw.category_id}`);
      } else {
        navigate(`/search?q=${encodeURIComponent(kw.word)}`);
      }
      resetState();
    },
    [addRecentSearch, onKeywordClick, navigate, resetState, products],
  );

  /* ── product click ── */
  const handleProductClick = useCallback(
    (p) => {
      // Product clicks should not be tracked as keyword searches

      if (onProductClick) {
        onProductClick(p);
        resetState();
        return;
      }

      const action = p.suggested_action || 'price_page';
      switch (action) {
        case 'mart_modal':
          openMartModal(p);
          break;
        case 'hotdeal_modal':
          openHotdealModal(p);
          break;
        case 'product_modal':
          openProductModal(p);
          break;
        case 'price_page':
        default:
          navigate(`/price/${p.id}`);
          break;
      }
      resetState();
    },
    [onProductClick, openMartModal, openHotdealModal, openProductModal, navigate, resetState],
  );

  /* ── recent search click ── */
  const handleSelectRecent = useCallback(
    (text) => {
      addRecentSearch(text);
      if (onSearch) {
        onSearch(text);
      } else {
        navigate(`/search?q=${encodeURIComponent(text)}`);
      }
      resetState();
    },
    [addRecentSearch, onSearch, navigate, resetState],
  );

  /* ── keyboard navigation ── */
  const allItems = useMemo(() => [...keywords, ...products], [keywords, products]);

  const handleKeyDown = useCallback((e) => {
    const hasResults = allItems.length > 0;
    const recentList = recentSearches.map((r) => r.query);
    const totalLen = hasResults ? allItems.length : recentList.length;

    if (!totalLen) {
      if (e.key === 'Enter') {
        e.preventDefault();
        handleSearch();
      }
      return;
    }

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIndex((p) => (p < totalLen - 1 ? p + 1 : 0));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIndex((p) => (p > 0 ? p - 1 : totalLen - 1));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (activeIndex >= 0) {
        if (hasResults) {
          const item = allItems[activeIndex];
          if (item.type === 'keyword') handleKeywordClick(item);
          else handleProductClick(item);
        } else {
          handleSelectRecent(recentList[activeIndex]);
        }
      } else {
        handleSearch();
      }
    } else if (e.key === 'Escape') {
      setShowDropdown(false);
    }
  }, [allItems, recentSearches, activeIndex, handleSearch, handleKeywordClick, handleProductClick, handleSelectRecent]);

  /* ── form submit for page variant ── */
  const handleFormSubmit = useCallback((e) => {
    e.preventDefault();
    handleSearch();
  }, [handleSearch]);

  const handleFocus = useCallback(() => setShowDropdown(true), []);

  /* ── derived state ── */
  const recentList = useMemo(() => recentSearches.map((r) => r.query), [recentSearches]);
  const hasAcResults = keywords.length > 0 || products.length > 0;
  const showRecent = searchQuery === '' && recentList.length > 0;
  const showTrending = searchQuery === '' && trendingKeywords.length > 0;
  const hasDropdownContent =
    hasAcResults || showRecent || showTrending || (searchQuery && !hasAcResults);

  /* ── variant class ── */
  const variantCls =
    variant === 'header'
      ? s.variantHeader
      : variant === 'page'
        ? s.variantPage
        : s.variantInline;

  /* ── render ── */
  return (
    <div
      ref={wrapperRef}
      className={`${s.wrapper} ${variantCls} ${className}`}
    >
      {variant === 'page' ? (
        <form className={s.inputRow} onSubmit={handleFormSubmit}>
          <span className={s.formIcon}>
            <Search size={20} />
          </span>
          <input
            ref={inputRef}
            type="search"
            className={s.input}
            placeholder={placeholder}
            autoFocus={autoFocus}
            value={searchQuery}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            onFocus={handleFocus}
            autoComplete="off"
          />
        </form>
      ) : (
        <div className={s.inputRow}>
          <input
            ref={inputRef}
            type="search"
            className={s.input}
            placeholder={placeholder}
            autoFocus={autoFocus}
            value={searchQuery}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            onFocus={handleFocus}
            autoComplete="off"
          />
        </div>
      )}

      {showDropdown && hasDropdownContent && (
        <div className={s.dropdown}>
          {hasAcResults ? (
            <>
              {keywords.length > 0 && (
                <>
                  <div className={s.acSectionLabel}>키워드</div>
                  {keywords.map((kw, i) => (
                    <button
                      key={`kw-${kw.id}`}
                      className={`${s.dropItem} ${i === activeIndex ? s.dropItemActive : ''}`}
                      onClick={() => handleKeywordClick(kw)}
                      onMouseEnter={() => setActiveIndex(i)}
                    >
                      <span className={s.acIconEmoji}>🔍</span>
                      <div className={s.acContent}>
                        <span className={s.acWord}>
                          {highlightMatch(kw.word, searchQuery)}
                        </span>
                        {kw.matched_synonym && (
                          <span className={s.acHint}>
                            ← &ldquo;{kw.matched_synonym}&rdquo; 포함
                          </span>
                        )}
                        <span className={s.acPath}>{kw.category_path}</span>
                      </div>
                    </button>
                  ))}
                </>
              )}
              {keywords.length > 0 && products.length > 0 && (
                <div className={s.acDivider} />
              )}
              {products.length > 0 && (
                <>
                  <div className={s.acSectionLabel}>상품</div>
                  {products.map((p, i) => {
                    const idx = keywords.length + i;
                    return (
                      <button
                        key={`p-${p.id}`}
                        className={`${s.dropItem} ${idx === activeIndex ? s.dropItemActive : ''}`}
                        onClick={() => handleProductClick(p)}
                        onMouseEnter={() => setActiveIndex(idx)}
                      >
                        <span className={s.acIconEmoji}>{p.icon || '📦'}</span>
                        <div className={s.acContent}>
                          <span className={s.acWord}>
                            {highlightMatch(p.name, searchQuery)}
                          </span>
                          <span className={s.acMeta}>
                            {p.unit}{' '}
                            {p.current_price ? `· ${fmt(p.current_price)}원` : ''}
                          </span>
                        </div>
                      </button>
                    );
                  })}
                </>
              )}
              {(totalKeywords > 3 || totalProducts > 5) && (
                <div
                  className={s.acFooter}
                  onClick={handleSearch}
                >
                  🔍 &ldquo;{searchQuery}&rdquo; 전체 검색 결과 보기 (
                  {totalKeywords + totalProducts}건)
                </div>
              )}
            </>
          ) : searchQuery ? (
            <div className={s.acEmpty}>
              <span>
                😅 &ldquo;{searchQuery}&rdquo;에 대한 결과가 없습니다.
              </span>
              {trendingKeywords.length > 0 && (
                <div className={s.acTrending}>
                  {trendingKeywords.map((t) => (
                    <button
                      key={t.word}
                      className={s.acTrendBtn}
                      onClick={() => {
                        setSearchQuery(t.word);
                        fetchAutocomplete(t.word);
                      }}
                    >
                      🔥 {t.word}
                    </button>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <>
              {recentList.length > 0 && (
                <>
                  <div className={s.acSectionLabel}>최근 검색</div>
                  {recentList.slice(0, 5).map((item, i) => (
                    <button
                      key={`recent-${item}`}
                      className={`${s.dropItem} ${i === activeIndex ? s.dropItemActive : ''}`}
                      onClick={() => handleSelectRecent(item)}
                      onMouseEnter={() => setActiveIndex(i)}
                    >
                      <Clock size={14} className={s.dropItemIcon} />
                      <span>{item}</span>
                    </button>
                  ))}
                </>
              )}
              {trendingKeywords.length > 0 && (
                <>
                  {recentList.length > 0 && <div className={s.acDivider} />}
                  <div className={s.acSectionLabel}>🔥 인기 검색어</div>
                  {trendingKeywords.map((t) => (
                    <button
                      key={t.word}
                      className={s.dropItem}
                      onClick={() => {
                        setSearchQuery(t.word);
                        addRecentSearch(t.word);
                        fetchAutocomplete(t.word);
                      }}
                    >
                      <span className={s.acIconEmoji}>{t.icon || '🔥'}</span>
                      <span>{t.word}</span>
                    </button>
                  ))}
                </>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
});

export default SearchAutocomplete;
