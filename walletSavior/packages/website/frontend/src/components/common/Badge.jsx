import s from './Badge.module.css';

export default function Badge({
  children,
  variant = 'solid',
  color = 'primary',
  size = 'md',
  className = '',
}) {
  return (
    <span className={[s.badge, s[variant], s[color], s[size], className].filter(Boolean).join(' ')}>
      {children}
    </span>
  );
}
