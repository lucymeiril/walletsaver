import s from './Card.module.css';

export default function Card({
  children,
  variant = 'default',
  padding = 'md',
  onClick,
  header,
  footer,
  className = '',
  ...props
}) {
  const isInteractive = variant === 'interactive' || !!onClick;
  const Tag = onClick ? 'button' : 'div';

  return (
    <Tag
      className={[s.card, s[variant], s[`pad-${padding}`], isInteractive && s.interactive, className].filter(Boolean).join(' ')}
      onClick={onClick}
      {...props}
    >
      {header && <div className={s.header}>{header}</div>}
      <div className={s.body}>{children}</div>
      {footer && <div className={s.footer}>{footer}</div>}
    </Tag>
  );
}
