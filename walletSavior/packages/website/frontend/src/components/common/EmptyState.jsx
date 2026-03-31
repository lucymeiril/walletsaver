import { PackageOpen } from 'lucide-react';
import Button from './Button';
import s from './EmptyState.module.css';

export default function EmptyState({
  icon: Icon = PackageOpen,
  title = '데이터가 없습니다',
  description,
  actionLabel,
  onAction,
  className = '',
}) {
  return (
    <div className={`${s.empty} ${className}`}>
      <Icon className={s.icon} size={48} />
      <h3 className={s.title}>{title}</h3>
      {description && <p className={s.desc}>{description}</p>}
      {actionLabel && onAction && (
        <Button variant="outline" onClick={onAction}>{actionLabel}</Button>
      )}
    </div>
  );
}
