import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { useState, useEffect, useRef, useCallback } from 'react';
import { Wallet, Bell, User, X, Search, Sun, Moon, Clock } from 'lucide-react';
import useStore from '../../stores/appStore';
import { searchService } from '../../services/searchService';
import s from './Header.module.css';

const NAV = [
  { to: '/',          label: '홈' },
  { to: '/price',     label: '물가비교' },
  { to: '/hotdeal',   label: '핫딜' },
  { to: '/mart',      label: '마트할인' },
  { to: '/local',     label: '동네물가' },
  { to: '/community', label: '커뮤니티' },
];

export default function Header() {
  const [scrolled, setScrolled] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [suggestions, setSuggestions] = useState([]);
  const [showDropdown, setShowDropdown] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const debounceRef = useRef(null);
  const dropdownRef = useRef(null);

  const { isLoggedIn, logout, notifications } = useStore();
  const theme = useStore((s) => s.theme);
  const toggleTheme = useStore((s) => s.toggleTheme);
  const recentSearches = useStore((s) => s.recentSearches);
  const addRecentSearch = useStore((s) => s.addRecentSearch);
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

  // 자동완성 API 호출 (2글자 이상, 300ms 디바운스)
  const fetchAutocomplete = useCallback((value) => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!value || value.length < 2) {
      setSuggestions([]);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      try {
        const res = await searchService.autocomplete(value);
        setSuggestions(res.data || []);
      } catch {
        setSuggestions([]);
      }
    }, 300);
  }, []);

  useEffect(() => {
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, []);

  const openLoginModal = useStore((s) => s.openLoginModal);
  const openLogin = () => openLoginModal();

  const unreadCount = notifications?.filter(n => !n.read).length || 0;

  const handleSearch = () => {
    if (searchQuery.trim()) {
      addRecentSearch(searchQuery.trim());
      navigate(`/search?q=${encodeURIComponent(searchQuery.trim())}`);
      setSearchQuery('');
      setSearchOpen(false);
      setShowDropdown(false);
      setSuggestions([]);
    }
  };

  const handleInputChange = (e) => {
    const value = e.target.value;
    setSearchQuery(value);
    setActiveIndex(-1);
    setShowDropdown(true);
    fetchAutocomplete(value);
  };

  const handleSelectSuggestion = (text) => {
    setSearchQuery(text);
    addRecentSearch(text);
    navigate(`/search?q=${encodeURIComponent(text)}`);
    setSearchOpen(false);
    setShowDropdown(false);
    setSuggestions([]);
  };

  const handleKeyDown = (e) => {
    const items = suggestions.length > 0
      ? suggestions.map((s) => s.text || s)
      : recentSearches.map((r) => r.query);
    if (!items.length) {
      if (e.key === 'Enter') handleSearch();
      return;
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIndex((p) => (p < items.length - 1 ? p + 1 : 0));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIndex((p) => (p > 0 ? p - 1 : items.length - 1));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (activeIndex >= 0) handleSelectSuggestion(items[activeIndex]);
      else handleSearch();
    } else if (e.key === 'Escape') {
      setShowDropdown(false);
    }
  };

  const recentList = recentSearches.map((r) => r.query);
  const hasDropdownContent = suggestions.length > 0 || (searchQuery === '' && recentList.length > 0);

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
                {suggestions.length > 0
                  ? suggestions.map((item, i) => (
                      <button
                        key={i}
                        className={`${s.dropItem} ${i === activeIndex ? s.dropItemActive : ''}`}
                        onClick={() => handleSelectSuggestion(item.text || item)}
                        onMouseEnter={() => setActiveIndex(i)}
                      >
                        <Search size={14} className={s.dropItemIcon} />
                        <span>{item.text || item}</span>
                      </button>
                    ))
                  : recentList.map((item, i) => (
                      <button
                        key={i}
                        className={`${s.dropItem} ${i === activeIndex ? s.dropItemActive : ''}`}
                        onClick={() => handleSelectSuggestion(item)}
                        onMouseEnter={() => setActiveIndex(i)}
                      >
                        <Clock size={14} className={s.dropItemIcon} />
                        <span>{item}</span>
                      </button>
                    ))
                }
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
