import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { useState, useEffect, useRef, useCallback } from 'react';
import { Wallet, Bell, User, X, Search, Sun, Moon, Clock } from 'lucide-react';
import useStore from '../../stores/appStore';
import { searchService } from '../../services/searchService';
import { fmt } from '../../utils/helpers';
import s from './Header.module.css';

const NAV = [
  { to: '/',          label: '홈' },
  { to: '/price',     label: '물가비교' },
  { to: '/hotdeal',   label: '핫딜' },
  { to: '/mart',      label: '마트할인' },
  { to: '/local',     label: '동네물가' },
  { to: '/community', label: '커뮤니티' },
];

function highlightMatch(text, query) {
  if (!query || !text) return text;
  const idx = text.toLowerCase().indexOf(query.toLowerCase());
  if (idx === -1) return text;
  return <>{text.slice(0, idx)}<strong>{text.slice(idx, idx + query.length)}</strong>{text.slice(idx + query.length)}</>;
}

export default function Header() {
  const [scrolled, setScrolled] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [keywords, setKeywords] = useState([]);
  const [products, setProducts] = useState([]);
  const [totalKeywords, setTotalKeywords] = useState(0);
  const [totalProducts, setTotalProducts] = useState(0);
  const [trendingKeywords, setTrendingKeywords] = useState([]);
  const [showDropdown, setShowDropdown] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const debounceRef = useRef(null);
  const dropdownRef = useRef(null);

  const { isLoggedIn, logout, notifications } = useStore();
  const theme = useStore((st) => st.theme);
  const toggleTheme = useStore((st) => st.toggleTheme);
  const recentSearches = useStore((st) => st.recentSearches);
  const addRecentSearch = useStore((st) => st.addRecentSearch);
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 20);
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  useEffect(() => {
    document.body.style.overflow = mobileOpen ? 'hidden' : '';
    return () => { document.body.style.overflow = ''; };
  }, [mobileOpen]);

  // 인기 검색어 로드
  useEffect(() => {
    searchService.trending(8)
      .then(res => setTrendingKeywords(res.data || []))
      .catch(() => {});
  }, []);

  // 외부 클릭 시 드롭다운 닫기
  useEffect(() => {
    const handleClick = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setShowDropdown(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  // 자동완성 API 호출 (1글자 이상, 200ms 디바운스)
  const fetchAutocomplete = useCallback((value) => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!value || value.length < 1) {
      setKeywords([]);
      setProducts([]);
      setTotalKeywords(0);
      setTotalProducts(0);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      try {
        const res = await searchService.autocomplete(value);
        const d = res.data || {};
        setKeywords(d.keywords || []);
        setProducts(d.products || []);
        setTotalKeywords(d.total_keyword_count || 0);
        setTotalProducts(d.total_product_count || 0);
      } catch {
        setKeywords([]);
        setProducts([]);
      }
    }, 200);
  }, []);

  useEffect(() => {
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, []);

  const openLoginModal = useStore((st) => st.openLoginModal);
  const openLogin = () => openLoginModal();

  const unreadCount = notifications?.filter(n => !n.read).length || 0;

  const handleSearch = () => {
    if (searchQuery.trim()) {
      addRecentSearch(searchQuery.trim());
      navigate(`/search?q=${encodeURIComponent(searchQuery.trim())}`);
      setSearchQuery('');
      setSearchOpen(false);
      setShowDropdown(false);
      setKeywords([]);
      setProducts([]);
    }
  };

  const handleInputChange = (e) => {
    const value = e.target.value;
    setSearchQuery(value);
    setActiveIndex(-1);
    setShowDropdown(true);
    fetchAutocomplete(value);
  };

  const handleKeywordClick = (kw) => {
    addRecentSearch(kw.word);
    searchService.trackKeyword(kw.id);
    navigate(`/search?q=${encodeURIComponent(kw.word)}`);
    setSearchOpen(false);
    setShowDropdown(false);
    setSearchQuery('');
    setKeywords([]);
    setProducts([]);
  };

  const handleProductClick = (p) => {
    navigate(`/price/${p.id}`);
    setSearchOpen(false);
    setShowDropdown(false);
    setSearchQuery('');
    setKeywords([]);
    setProducts([]);
  };

  const handleSelectRecent = (text) => {
    setSearchQuery(text);
    addRecentSearch(text);
    navigate(`/search?q=${encodeURIComponent(text)}`);
    setSearchOpen(false);
    setShowDropdown(false);
    setKeywords([]);
    setProducts([]);
  };

  const allItems = [...keywords, ...products];

  const handleKeyDown = (e) => {
    const hasResults = allItems.length > 0;
    const recentList = recentSearches.map((r) => r.query);
    const totalLen = hasResults ? allItems.length : recentList.length;
    if (!totalLen) {
      if (e.key === 'Enter') handleSearch();
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
  };

  const recentList = recentSearches.map((r) => r.query);
  const hasAcResults = keywords.length > 0 || products.length > 0;
  const showRecent = searchQuery === '' && recentList.length > 0;
  const showTrending = searchQuery === '' && trendingKeywords.length > 0;
  const hasDropdownContent = hasAcResults || showRecent || showTrending || (searchQuery && !hasAcResults);

  return (
    <>
      <header className={`${s.hdr} ${scrolled ? s.scrolled : ''}`}>
        <div className={s.inner}>
          <NavLink to="/" className={s.logo}>
            <Wallet size={24} className={s.logoIcon} />
            <span>지갑 지키미</span>
          </NavLink>

          <nav className={s.nav}>
            {NAV.map(n => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.to === '/'}
                className={({ isActive }) => `${s.link} ${isActive ? s.linkActive : ''}`}
              >
                {n.label}
              </NavLink>
            ))}
          </nav>

          <div className={s.right}>
            <button
              className={s.iconBtn}
              onClick={() => setSearchOpen(!searchOpen)}
              aria-label="검색"
            >
              <Search size={20} />
            </button>

            <button
              className={s.iconBtn}
              onClick={toggleTheme}
              aria-label={theme === 'light' ? '다크 모드' : '라이트 모드'}
              title={theme === 'light' ? '다크 모드로 전환' : '라이트 모드로 전환'}
            >
              {theme === 'light' ? <Moon size={20} /> : <Sun size={20} />}
            </button>

            <button className={s.iconBtn} aria-label="알림">
              <Bell size={20} />
              {unreadCount > 0 && <span className={s.badge}>{unreadCount > 9 ? '9+' : unreadCount}</span>}
            </button>

            {isLoggedIn ? (
              <button className={s.avatarBtn} onClick={logout} aria-label="프로필">
                <User size={18} />
              </button>
            ) : (
              <button className={s.loginBtn} onClick={openLogin}>로그인</button>
            )}

            <button
              className={`${s.mobileBtn} ${mobileOpen ? s.mobileBtnOpen : ''}`}
              onClick={() => setMobileOpen(!mobileOpen)}
              aria-label="메뉴"
            >
              <span /><span /><span />
            </button>
          </div>
        </div>

        {searchOpen && (
          <div className={s.searchBar} ref={dropdownRef}>
            <div className={s.searchInner}>
              <input
                type="search"
                className={s.searchInput}
                placeholder="상품, 가격, 핫딜 검색..."
                autoFocus
                value={searchQuery}
                onChange={handleInputChange}
                onKeyDown={handleKeyDown}
                onFocus={() => setShowDropdown(true)}
                autoComplete="off"
              />
              <button className={s.searchClose} onClick={() => setSearchOpen(false)}>
                <X size={18} />
              </button>
            </div>

            {showDropdown && hasDropdownContent && (
              <div className={s.searchDropdown}>
                {/* 검색 결과 있을 때 — 2섹션 */}
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
                              <span className={s.acWord}>{highlightMatch(kw.word, searchQuery)}</span>
                              {kw.matched_synonym && <span className={s.acHint}>← &ldquo;{kw.matched_synonym}&rdquo; 포함</span>}
                              <span className={s.acPath}>{kw.category_path}</span>
                            </div>
                          </button>
                        ))}
                      </>
                    )}
                    {keywords.length > 0 && products.length > 0 && <div className={s.acDivider} />}
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
                                <span className={s.acWord}>{highlightMatch(p.name, searchQuery)}</span>
                                <span className={s.acMeta}>{p.unit} {p.current_price ? `· ${fmt(p.current_price)}원` : ''}</span>
                              </div>
                            </button>
                          );
                        })}
                      </>
                    )}
                    {(totalKeywords > 3 || totalProducts > 5) && (
                      <div className={s.acFooter} onClick={() => { handleSearch(); }}>
                        🔍 &ldquo;{searchQuery}&rdquo; 전체 검색 결과 보기 ({totalKeywords + totalProducts}건)
                      </div>
                    )}
                  </>
                ) : searchQuery ? (
                  /* 빈 결과 */
                  <div className={s.acEmpty}>
                    <span>😅 &ldquo;{searchQuery}&rdquo;에 대한 결과가 없습니다.</span>
                    {trendingKeywords.length > 0 && (
                      <div className={s.acTrending}>
                        {trendingKeywords.map(t => (
                          <button key={t.word} className={s.acTrendBtn} onClick={() => { setSearchQuery(t.word); fetchAutocomplete(t.word); }}>
                            🔥 {t.word}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                ) : (
                  /* 포커스 시 최근 검색 + 인기 키워드 */
                  <>
                    {recentList.length > 0 && (
                      <>
                        <div className={s.acSectionLabel}>최근 검색</div>
                        {recentList.slice(0, 5).map((item, i) => (
                          <button
                            key={i}
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
                        {trendingKeywords.map((t, i) => (
                          <button
                            key={t.word}
                            className={s.dropItem}
                            onClick={() => { setSearchQuery(t.word); addRecentSearch(t.word); fetchAutocomplete(t.word); }}
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
        )}
      </header>

      {/* Mobile drawer */}
      <div
        className={`${s.overlay} ${mobileOpen ? s.overlayOpen : ''}`}
        onClick={() => setMobileOpen(false)}
      />
      <aside className={`${s.drawer} ${mobileOpen ? s.drawerOpen : ''}`}>
        <div className={s.drawerHeader}>
          <span className={s.drawerTitle}>메뉴</span>
          <button className={s.drawerClose} onClick={() => setMobileOpen(false)}>
            <X size={20} />
          </button>
        </div>
        <nav className={s.drawerNav}>
          {NAV.map(n => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.to === '/'}
              className={({ isActive }) => `${s.drawerLink} ${isActive ? s.drawerLinkActive : ''}`}
              onClick={() => setMobileOpen(false)}
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className={s.drawerFooter}>
          {isLoggedIn ? (
            <button className={s.drawerBtn} onClick={() => { logout(); setMobileOpen(false); }}>로그아웃</button>
          ) : (
            <button className={s.drawerBtn} onClick={() => { openLogin(); setMobileOpen(false); }}>로그인</button>
          )}
        </div>
      </aside>
    </>
  );
}
