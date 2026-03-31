import { NavLink } from 'react-router-dom';
import { Home, BarChart3, Zap, Store, MapPin } from 'lucide-react';
import s from './BottomNav.module.css';

const TABS = [
  { to: '/',           label: '홈',      icon: Home,       end: true  },
  { to: '/price',      label: '물가비교', icon: BarChart3, end: false },
  { to: '/hotdeal',    label: '핫딜',    icon: Zap,        end: false, badgeKey: 'hotdeal' },
  { to: '/mart',       label: '마트',    icon: Store,      end: false },
  { to: '/local',      label: '동네',    icon: MapPin,     end: false },
];

export default function BottomNav({ badgeCounts = {} }) {
  return (
    <nav className={s.bar} aria-label="하단 네비게이션">
      {TABS.map(({ to, label, icon: Icon, end, badgeKey }) => {
        const count = badgeKey ? badgeCounts[badgeKey] : 0;
        return (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) => `${s.tab} ${isActive ? s.active : ''}`}
          >
            <div className={s.iconWrap}>
              <Icon size={20} />
              {count > 0 && (
                <span className={s.badge}>{count > 99 ? '99+' : count}</span>
              )}
            </div>
            <span>{label}</span>
          </NavLink>
        );
      })}
    </nav>
  );
}
