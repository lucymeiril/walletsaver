import s from './Spinner.module.css';

export default function Spinner({
  size = 'md',
  color = 'primary',
  overlay = false,
  className = '',
}) {
  const spinner = (
    <div
      className={`${s.spinner} ${s[size]} ${s[color]} ${className}`}
      role="status"
      aria-label="로딩 중"
    >
      <span className={s.srOnly}>로딩 중...</span>
    </div>
  );

  if (overlay) {
    return <div className={s.overlay}>{spinner}</div>;
  }

  return spinner;
}
