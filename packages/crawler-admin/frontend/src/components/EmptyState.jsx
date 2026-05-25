import { PackageOpen } from 'lucide-react';

/**
 * 빈 상태(empty state)를 명시적으로 표시하는 공용 컴포넌트.
 * 사용자가 다음에 무엇을 할지 명확히 알 수 있도록 액션 버튼을 강제 노출한다.
 *
 * 사용자 헌법: 메트릭 0 = 정상 가정 금지.
 * 데이터가 없을 때 빈 슬롯 대신 "원인 + 대응 액션"을 노출하라.
 */
export default function EmptyState({
  icon: Icon = PackageOpen,
  title = '데이터 없음',
  description = '표시할 항목이 없습니다.',
  action,
  actionLabel,
  secondaryAction,
  secondaryActionLabel,
}) {
  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '2.5rem 1rem',
        gap: '0.75rem',
        color: 'var(--text3, #94a3b8)',
        background: 'var(--surface, rgba(30,41,59,0.5))',
        border: '1px dashed rgba(148,163,184,0.18)',
        borderRadius: 12,
        margin: '12px 0',
      }}
    >
      <Icon size={44} strokeWidth={1.5} />
      <h3 style={{ margin: 0, color: 'var(--text2, #cbd5e1)', fontSize: '1rem' }}>{title}</h3>
      <p style={{ margin: 0, textAlign: 'center', maxWidth: 360, fontSize: '.88rem' }}>{description}</p>
      {(action || secondaryAction) && (
        <div style={{ display: 'flex', gap: 8, marginTop: 6, flexWrap: 'wrap', justifyContent: 'center' }}>
          {action && (
            <button
              onClick={action}
              style={{
                padding: '0.55rem 1.1rem',
                borderRadius: 8,
                border: '1px solid var(--accent, #38bdf8)',
                background: 'var(--accent, #38bdf8)',
                color: '#0b1220',
                cursor: 'pointer',
                fontWeight: 600,
              }}
            >
              {actionLabel || '시작하기'}
            </button>
          )}
          {secondaryAction && (
            <button
              onClick={secondaryAction}
              style={{
                padding: '0.55rem 1.1rem',
                borderRadius: 8,
                border: '1px solid var(--border, rgba(148,163,184,0.2))',
                background: 'transparent',
                cursor: 'pointer',
                color: 'var(--text2, #cbd5e1)',
              }}
            >
              {secondaryActionLabel}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
