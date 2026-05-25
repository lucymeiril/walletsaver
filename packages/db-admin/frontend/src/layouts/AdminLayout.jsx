import { NavLink, Outlet } from 'react-router-dom';
import {
  LayoutDashboard, Package, DollarSign,
  FolderTree, BarChart3, Menu, X, Database, Inbox, LogOut, ShieldCheck, MessageSquareWarning, Wrench, Upload,
} from 'lucide-react';
import { useState, useEffect } from 'react';
import { logout } from '../stores/authStore';
import s from './AdminLayout.module.css';

const NAV = [
  { to: '/',               label: '대시보드',   icon: LayoutDashboard },
  { to: '/inbox',          label: '📥 수신함',  icon: Inbox },
  { to: '/products',       label: '상품',       icon: Package },
  { to: '/prices',         label: '가격',       icon: DollarSign },
  { to: '/classification', label: '분류 관리',  icon: FolderTree },
  { to: '/analytics',      label: '분석',       icon: BarChart3 },
  { to: '/integrity',      label: '무결성',     icon: ShieldCheck },
  { to: '/maintenance',    label: 'DB 유지보수', icon: Wrench },
  { to: '/community',      label: '커뮤니티',   icon: MessageSquareWarning },
  { to: '/import',         label: '분류 Import', icon: Upload },
];

export default function AdminLayout() {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    const onResize = () => { if (window.innerWidth > 768) setMobileOpen(false); };
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  return (
    <div className={s.wrap}>
      {/* Mobile overlay */}
      {mobileOpen && <div className={s.overlay} onClick={() => setMobileOpen(false)} />}

      {/* Sidebar */}
      <aside className={`${s.sidebar} ${collapsed ? s.collapsed : ''} ${mobileOpen ? s.mobileOpen : ''}`}>
        <div className={s.brand}>
          <Database size={24} className={s.brandIcon} />
          {!collapsed && <span className={s.brandText}>DB 관리자</span>}
        </div>

        <nav className={s.nav}>
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) => `${s.link} ${isActive ? s.active : ''}`}
              onClick={() => setMobileOpen(false)}
              title={label}
            >
              <Icon size={20} />
              {!collapsed && <span>{label}</span>}
            </NavLink>
          ))}
        </nav>

        <button className={s.collapseBtn} onClick={() => setCollapsed(!collapsed)}>
          {collapsed ? <Menu size={18} /> : <X size={18} />}
          {!collapsed && <span>접기</span>}
        </button>

        <button className={s.logoutBtn} onClick={logout} title="로그아웃">
          <LogOut size={18} />
          {!collapsed && <span>로그아웃</span>}
        </button>
      </aside>

      {/* Main */}
      <div className={`${s.main} ${collapsed ? s.mainExpanded : ''}`}>
        <header className={s.topbar}>
          <button className={s.mobileMenuBtn} onClick={() => setMobileOpen(true)}>
            <Menu size={22} />
          </button>
          <h1 className={s.topTitle}>WalletSavior DB Admin</h1>
        </header>
        <div className={s.content}>
          <Outlet />
        </div>
      </div>
    </div>
  );
}
