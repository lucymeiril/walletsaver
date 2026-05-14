import { useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import {
  LayoutDashboard,
  Bot,
  Puzzle,
  FileText,
  Clock,
  Menu,
  X,
  ClipboardCheck,
  LogOut,
} from 'lucide-react';
import { logout } from '../stores/authStore';
import styles from './AdminLayout.module.css';

const navItems = [
  { to: '/', label: '대시보드', icon: LayoutDashboard },
  { to: '/crawlers', label: '크롤러', icon: Bot },
  { to: '/data-review', label: '데이터 검토', icon: ClipboardCheck },
  { to: '/plugins', label: '플러그인', icon: Puzzle },
  { to: '/logs', label: '로그', icon: FileText },
  { to: '/schedule', label: '스케줄', icon: Clock },
];

export default function AdminLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <>
      <button
        className={styles.hamburger}
        onClick={() => setSidebarOpen(true)}
        aria-label="메뉴 열기"
      >
        <Menu size={20} />
      </button>

      {sidebarOpen && (
        <div
          className={styles.overlay}
          onClick={() => setSidebarOpen(false)}
        />
      )}

      <aside
        className={`${styles.sidebar} ${sidebarOpen ? styles.sidebarOpen : ''}`}
      >
        <div className={styles.logo}>
          <div className={styles.logoIcon}>WS</div>
          <span className={styles.logoText}>크롤러 관리</span>
          {sidebarOpen && (
            <button
              className={styles.hamburger}
              onClick={() => setSidebarOpen(false)}
              style={{ position: 'static', display: 'flex' }}
              aria-label="메뉴 닫기"
            >
              <X size={18} />
            </button>
          )}
        </div>

        <nav className={styles.nav}>
          {navItems.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                isActive ? styles.navItemActive : styles.navItem
              }
              onClick={() => setSidebarOpen(false)}
            >
              <Icon size={18} />
              {label}
            </NavLink>
          ))}
        </nav>

        <button className={styles.logoutBtn} onClick={logout}>
          <LogOut size={18} />
          로그아웃
        </button>
      </aside>

      <main className={styles.main}>
        <Outlet />
      </main>
    </>
  );
}
