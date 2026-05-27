import { Loader2 } from 'lucide-react';
import s from './Button.module.css';

export default function Button({
  children,
  variant = 'primary',
  size = 'md',
  loading = false,
  disabled = false,
  fullWidth = false,
  onClick,
  type = 'button',
  className = '',
  ...props
}) {
  const classes = [
    s.btn,
    s[variant],
    s[size],
    fullWidth && s.fullWidth,
    loading && s.loading,
    className,
  ].filter(Boolean).join(' ');

  return (
    <button
      type={type}
      className={classes}
      disabled={disabled || loading}
      onClick={onClick}
      aria-busy={loading || undefined}
      {...props}
    >
      {loading && <Loader2 className={s.spinner} size={size === 'sm' ? 14 : size === 'lg' ? 20 : 16} />}
      <span className={loading ? s.hiddenText : ''}>{children}</span>
    </button>
  );
}
