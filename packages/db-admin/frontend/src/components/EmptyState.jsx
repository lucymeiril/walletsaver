import { PackageOpen } from 'lucide-react';

export default function EmptyState({
  icon: Icon = PackageOpen,
  title = '데이터 없음',
  description = '표시할 항목이 없습니다.',
  action,
  actionLabel,
}) {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      justifyContent: 'center', padding: '3rem 1rem', gap: '0.75rem',
      color: 'var(--text3, #999)',
    }}>
      <Icon size={48} strokeWidth={1.5} />
      <h3 style={{ margin: 0, color: 'var(--text2, #666)' }}>{title}</h3>
      <p style={{ margin: 0, textAlign: 'center', maxWidth: 300 }}>{description}</p>
      {action && (
        <button onClick={action} style={{
          marginTop: '0.5rem', padding: '0.5rem 1rem', borderRadius: 8,
          border: '1px solid var(--border, #ddd)', background: 'transparent',
          cursor: 'pointer', color: 'var(--primary, #3b82f6)',
        }}>
          {actionLabel || '새로 만들기'}
        </button>
      )}
    </div>
  );
}
