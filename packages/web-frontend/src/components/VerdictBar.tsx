import type { VerdictSummary } from '../types'

interface Props { summary: VerdictSummary }

export default function VerdictBar({ summary }: Props) {
  const total = summary.hot_deal + summary.not_hot_deal + summary.neutral
  const pct = (n: number) => (total === 0 ? 0 : Math.round((n / total) * 100))
  return (
    <div data-testid="verdict-bar" style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div
        style={{
          display: 'flex',
          height: 14,
          borderRadius: 999,
          overflow: 'hidden',
          background: '#f3f4f6',
        }}
      >
        <div style={{ width: `${pct(summary.hot_deal)}%`, background: '#ef4444' }} />
        <div style={{ width: `${pct(summary.neutral)}%`, background: '#9ca3af' }} />
        <div style={{ width: `${pct(summary.not_hot_deal)}%`, background: '#1d4ed8' }} />
      </div>
      <div style={{ display: 'flex', gap: 12, fontSize: 13, color: '#374151' }}>
        <span>🔥 핫딜 {summary.hot_deal}</span>
        <span>😐 보통 {summary.neutral}</span>
        <span>❌ 비핫딜 {summary.not_hot_deal}</span>
        <span style={{ marginLeft: 'auto', color: '#6b7280' }}>총 {total}표</span>
      </div>
    </div>
  )
}
