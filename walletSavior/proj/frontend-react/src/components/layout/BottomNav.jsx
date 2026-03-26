import { NavLink } from 'react-router-dom';
import { Home, BarChart3, Zap, Store, MoreHorizontal } from 'lucide-react';
import s from './BottomNav.module.css';

const TABS = [
  { to: '/',        label: '홈',     icon: Home,           end: true },
  { to: '/price',   label: '물가비교', icon: BarChart3,    end: false },
  { to: '/hotdeal', label: '핫딜',   icon: Zap,            end: false },
  { to: '/mart',    label: '마트',   icon: Store,          end: false },
  { to: '/community', label: '더보기', icon: MoreHorizontal, end: false },
];

export default function BottomNav() {
  return (
    <nav className={s.bar}>
      {TABS.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          className={({ isActive }) => `${s.tab} ${isActive ? s.active : ''}`}
        >
          <Icon size={20} />
          <span>{label}</span>
        </NavLink>
      ))}
    </nav>
  );
}
