import type { GradeLabel } from '../types'

interface GradeBadgeProps {
  label: GradeLabel
}

const GRADE_CONFIG: Record<GradeLabel, { text: string; bg: string; color: string }> = {
  HOT_DEAL: { text: '🔥 핫딜', bg: '#fee2e2', color: '#dc2626' },
  SALE: { text: '🏷️ 세일', bg: '#ffedd5', color: '#ea580c' },
  NORMAL: { text: '일반가', bg: '#f3f4f6', color: '#6b7280' },
  OVERPRICED: { text: '⚠️ 높은가격', bg: '#dbeafe', color: '#2563eb' },
  INSUFFICIENT_DATA: { text: '데이터 부족', bg: '#f3f4f6', color: '#9ca3af' },
}

export function GradeBadge({ label }: GradeBadgeProps) {
  const cfg = GRADE_CONFIG[label]
  return (
    <span
      data-grade={label}
      style={{
        display: 'inline-block',
        padding: '2px 8px',
        borderRadius: '12px',
        fontSize: '12px',
        fontWeight: 600,
        background: cfg.bg,
        color: cfg.color,
      }}
    >
      {cfg.text}
    </span>
  )
}
