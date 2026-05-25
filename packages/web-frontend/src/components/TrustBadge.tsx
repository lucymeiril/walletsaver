// web-FINAL §4-4: 단일 카드 1배지 / 상세 펼침 3종.
// 의도: 카드용 컴팩트 1배지 + 상세에서 클릭 시 사유 펼침.
// 후속 AI에게: 색만으로 구분 금지(§11-2) — 이모지·텍스트 동시 사용.

import type { TrustBadge } from '../lib/trustBadge'
import { classifyTrust } from '../lib/trustBadge'

const COLORS: Record<TrustBadge['level'], { bg: string; fg: string }> = {
  green: { bg: '#dcfce7', fg: '#15803d' },
  yellow: { bg: '#fef9c3', fg: '#854d0e' },
  red: { bg: '#fee2e2', fg: '#b91c1c' },
}

interface TrustBadgeProps {
  dealUrl?: string | null
  martName?: string | null
  // 'card' = 한 줄 1배지 / 'detail' = 사유 텍스트 풀.
  variant?: 'card' | 'detail'
}

export function TrustBadgeView({ dealUrl, martName, variant = 'card' }: TrustBadgeProps) {
  const badge = classifyTrust({ dealUrl, martName })
  const c = COLORS[badge.level]
  return (
    <span
      data-testid="trust-badge"
      data-trust-level={badge.level}
      data-trust-variant={variant}
      aria-label={badge.ariaLabel}
      style={{
        display: 'inline-block',
        padding: variant === 'card' ? '2px 8px' : '4px 10px',
        borderRadius: 12,
        background: c.bg,
        color: c.fg,
        fontSize: variant === 'card' ? 12 : 13,
        fontWeight: 600,
      }}
    >
      {variant === 'card' ? badge.cardLabel : badge.detailLabel}
    </span>
  )
}

// 상세 펼침용: 3종 row 표시 (현 상태 행은 강조, 나머지는 회색)
export function TrustBadgeDetailList({
  dealUrl,
  martName,
}: {
  dealUrl?: string | null
  martName?: string | null
}) {
  const active = classifyTrust({ dealUrl, martName })
  const rows: { level: TrustBadge['level']; text: string }[] = [
    { level: 'green', text: '🟢 공식몰 링크 확인됨' },
    { level: 'yellow', text: '🟡 링크 없음 · 외부 링크' },
    { level: 'red', text: '🔴 마트명/링크 불일치' },
  ]
  return (
    <ul data-testid="trust-badge-detail" style={{ listStyle: 'none', padding: 0, margin: 0 }}>
      {rows.map((r) => {
        const isActive = r.level === active.level
        return (
          <li
            key={r.level}
            data-active={isActive}
            data-trust-level={r.level}
            style={{
              padding: '6px 8px',
              borderRadius: 8,
              background: isActive ? COLORS[r.level].bg : 'transparent',
              color: isActive ? COLORS[r.level].fg : '#9ca3af',
              fontWeight: isActive ? 700 : 400,
              fontSize: 13,
            }}
          >
            {r.text}
          </li>
        )
      })}
      <li style={{ marginTop: 6, color: '#6b7280', fontSize: 12 }}>제보가 기준</li>
    </ul>
  )
}
