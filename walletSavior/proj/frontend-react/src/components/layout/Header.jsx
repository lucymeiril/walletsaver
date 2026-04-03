import { NavLink, useNavigate } from 'react-router-dom';
import { useState, useEffect } from 'react';
import { Wallet, Menu } from 'lucide-react';
import useStore from '../../stores/appStore';
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
  const { isLoggedIn, logout } = useStore();

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 20);
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  const openLogin = () => {
    document.getElementById('modal-login')?.classList.add('open');
  };

  return (
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
          {isLoggedIn ? (
            <button className={s.loginBtn} onClick={logout}>로그아웃</button>
          ) : (
            <button className={s.loginBtn} onClick={openLogin}>로그인</button>
          )}
          <button className={s.mobileBtn} onClick={() => setMobileOpen(!mobileOpen)} aria-label="메뉴">
            <span /><span /><span />
          </button>
        </div>
      </div>
    </header>
  );
}
