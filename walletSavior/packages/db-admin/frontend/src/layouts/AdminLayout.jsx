import { NavLink, Outlet } from 'react-router-dom';
import {
  LayoutDashboard, Package, DollarSign,
  FolderTree, Search, BarChart3, Menu, X, Database,
} from 'lucide-react';
import { useState, useEffect } from 'react';
import s from './AdminLayout.module.css';

const NAV = [
  { to: '/',           label: '대시보드', icon: LayoutDashboard },
  { to: '/products',   label: '상품',     icon: Package },
  { to: '/prices',     label: '가격',     icon: DollarSign },
  { to: '/categories', label: '카테고리', icon: FolderTree },
  { to: '/keywords',   label: '키워드',   icon: Search },
  { to: '/analytics',  label: '분석',     icon: BarChart3 },
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
