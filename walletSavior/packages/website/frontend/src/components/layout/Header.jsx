import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { useState, useEffect } from 'react';
import { Wallet, Bell, User, X, Search, Sun, Moon } from 'lucide-react';
import useStore from '../../stores/appStore';
import SearchAutocomplete from '../search/SearchAutocomplete';
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

  const { isLoggedIn, logout, notifications } = useStore();
  const theme = useStore((st) => st.theme);
  const toggleTheme = useStore((st) => st.toggleTheme);
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

  const openLoginModal = useStore((st) => st.openLoginModal);
  const openLogin = () => openLoginModal();

  const unreadCount = notifications?.filter(n => !n.read).length || 0;

  const closeSearch = () => setSearchOpen(false);

  const handleHeaderSearch = (query) => {
    navigate(`/search?q=${encodeURIComponent(query)}`);
    closeSearch();
  };

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
          <div className={s.searchBar}>
            <div className={s.searchInner}>
              <SearchAutocomplete
                variant="header"
                placeholder="상품, 가격, 핫딜 검색..."
                autoFocus
                onSearch={handleHeaderSearch}
                onAfterAction={closeSearch}
              />
              <button className={s.searchClose} onClick={closeSearch}>
                <X size={18} />
              </button>
            </div>
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
