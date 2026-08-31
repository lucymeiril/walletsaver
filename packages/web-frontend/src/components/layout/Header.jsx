import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { useState, useEffect, useCallback, useMemo, useRef, memo } from 'react';
import { Wallet, Bell, User, X, Search, Sun, Moon, LogOut, Heart, BellRing, ChevronDown } from 'lucide-react';
import useStore from '../../stores/appStore';
import useCartStore from '../../stores/cartStore';
import { authService } from '../../services/authService';
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

const Header = memo(function Header() {
  const [scrolled, setScrolled] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);

  const isLoggedIn = useStore((st) => st.isLoggedIn);
  const user = useStore((st) => st.user);
  const logout = useStore((st) => st.logout);
  const addToast = useStore((st) => st.addToast);
  const notifications = useStore((st) => st.notifications);
  const theme = useStore((st) => st.theme);
  const toggleTheme = useStore((st) => st.toggleTheme);
  const hotdealerMode = useStore((st) => st.hotdealerMode);
  const toggleHotdealerMode = useStore((st) => st.toggleHotdealerMode);
  const openLoginModal = useStore((st) => st.openLoginModal);
  const cartItems = useCartStore((st) => st.items);
  const location = useLocation();
  const navigate = useNavigate();
  const [profileOpen, setProfileOpen] = useState(false);
  const profileRef = useRef(null);

  useEffect(() => {
    setMobileOpen(false);
    setProfileOpen(false);
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

  const openLogin = useCallback(() => openLoginModal(), [openLoginModal]);

  useEffect(() => {
    const handleClickOutside = (e) => {
      if (profileRef.current && !profileRef.current.contains(e.target)) {
        setProfileOpen(false);
      }
    };
    if (profileOpen) document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [profileOpen]);

  const performLogout = useCallback(async () => {
    let serverConfirmed = true;
    try {
      await authService.logout();
    } catch {
      serverConfirmed = false;
      // httpOnly 쿠키 삭제는 확인 못 했지만, 이 브라우저의 자동 세션 복원은 막는다.
      authService.clearLocalSession();
    }
    logout();
    addToast(
      serverConfirmed
        ? '로그아웃 되었습니다'
        : '화면에서는 로그아웃했지만 서버 세션 종료를 확인하지 못했습니다.',
      serverConfirmed ? 'info' : 'warning',
    );
    return serverConfirmed;
  }, [logout, addToast]);

  const handleLogout = useCallback(async () => {
    await performLogout();
    setProfileOpen(false);
  }, [performLogout]);

  const unreadCount = useMemo(
    () => notifications?.filter(n => !n.read).length || 0,
    [notifications],
  );

  const closeSearch = useCallback(() => setSearchOpen(false), []);

  const handleHeaderSearch = useCallback((query) => {
    navigate(`/search?q=${encodeURIComponent(query)}`);
    setSearchOpen(false);
  }, [navigate]);

  const toggleSearch = useCallback(() => setSearchOpen(prev => !prev), []);
  const toggleMobile = useCallback(() => setMobileOpen(prev => !prev), []);
  const closeMobile = useCallback(() => setMobileOpen(false), []);

  const handleDrawerLogout = useCallback(async () => {
    await performLogout();
    setMobileOpen(false);
  }, [performLogout]);
  const handleDrawerLogin = useCallback(() => { openLoginModal(); setMobileOpen(false); }, [openLoginModal]);

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
            <button className={s.iconBtn} onClick={toggleSearch} aria-label="검색">
              <Search size={20} />
            </button>

            <button
              className={`${s.iconBtn} ${hotdealerMode ? s.iconBtnActive : ''}`}
              onClick={toggleHotdealerMode}
              aria-label={hotdealerMode ? '핫딜러 모드 끄기' : '핫딜러 모드 켜기'}
              title={hotdealerMode ? '핫딜러 모드 ON — 클릭으로 끄기' : '핫딜러 모드 OFF — 클릭으로 켜기'}
              aria-pressed={hotdealerMode}
            >
              🔥
              <span className={s.hotdealerLabel} style={{ fontSize: 11, marginLeft: 2, fontWeight: hotdealerMode ? 700 : 400 }}>
                핫딜러 {hotdealerMode ? 'ON' : 'OFF'}
              </span>
            </button>

            <button
              className={s.iconBtn}
              onClick={toggleTheme}
              aria-label={theme === 'light' ? '다크 모드' : '라이트 모드'}
              title={theme === 'light' ? '다크 모드로 전환' : '라이트 모드로 전환'}
            >
              {theme === 'light' ? <Moon size={20} /> : <Sun size={20} />}
            </button>

            <button className={s.iconBtn} aria-label="알림" onClick={() => navigate('/profile?tab=alerts')}>
              <Bell size={20} />
              {unreadCount > 0 && <span className={s.badge}>{unreadCount > 9 ? '9+' : unreadCount}</span>}
            </button>

            {isLoggedIn ? (
              <div className={s.profileWrap} ref={profileRef}>
                <button className={s.avatarBtn} onClick={() => setProfileOpen((p) => !p)} aria-label="프로필 메뉴">
                  <span className={s.avatarInitial}>{(user?.nickname || user?.email || 'U').charAt(0).toUpperCase()}</span>
                  <ChevronDown size={14} className={`${s.chevron} ${profileOpen ? s.chevronOpen : ''}`} />
                </button>
                {profileOpen && (
                  <div className={s.profileDropdown}>
                    <div className={s.profileInfo}>
                      <span className={s.profileName}>{user?.nickname || user?.email}</span>
                      {user?.email && <span className={s.profileEmail}>{user.email}</span>}
                    </div>
                    <div className={s.profileDivider} />
                    <button className={s.profileItem} onClick={() => { setProfileOpen(false); navigate('/profile'); }}>
                      <User size={16} /> 프로필
                    </button>
                    <button className={s.profileItem} onClick={() => { setProfileOpen(false); navigate('/wishlist'); }}>
                      <Heart size={16} /> 찜 목록
                    </button>
                    <button className={s.profileItem} onClick={() => { setProfileOpen(false); navigate('/profile?tab=alerts'); }}>
                      <BellRing size={16} /> 가격 알림
                    </button>
                    <div className={s.profileDivider} />
                    <button className={s.profileItem} onClick={handleLogout}>
                      <LogOut size={16} /> 로그아웃
                    </button>
                  </div>
                )}
              </div>
            ) : (
              <button className={s.loginBtn} onClick={openLogin}>로그인</button>
            )}

            <button
              className={`${s.mobileBtn} ${mobileOpen ? s.mobileBtnOpen : ''}`}
              onClick={toggleMobile}
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

      <div
        className={`${s.overlay} ${mobileOpen ? s.overlayOpen : ''}`}
        onClick={closeMobile}
      />
      <aside className={`${s.drawer} ${mobileOpen ? s.drawerOpen : ''}`}>
        <div className={s.drawerHeader}>
          <span className={s.drawerTitle}>메뉴</span>
          <button className={s.drawerClose} onClick={closeMobile}>
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
              onClick={closeMobile}
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className={s.drawerFooter}>
          {isLoggedIn ? (
            <button className={s.drawerBtn} onClick={handleDrawerLogout}>로그아웃</button>
          ) : (
            <button className={s.drawerBtn} onClick={handleDrawerLogin}>로그인</button>
          )}
        </div>
      </aside>
    </>
  );
});

export default Header;
