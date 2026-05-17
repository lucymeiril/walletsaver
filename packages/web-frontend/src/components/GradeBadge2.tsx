import type { GradeSummary } from '../types'

interface Props {
  dealPrice: number | null
  grade: GradeSummary | null
}

function fmt(n: number | null | undefined) {
  if (n == null) return '-'
  return '₩' + Math.round(n).toLocaleString()
}

export default function GradeBadge2({ dealPrice, grade }: Props) {
  if (!grade || !grade.sufficient || grade.p10 == null) {
    return (
      <div
        style={{
          padding: '8px 12px',
          borderRadius: 12,
          background: '#f3f4f6',
          color: '#6b7280',
          fontSize: 13,
        }}
      >
        DB 데이터 부족
      </div>
    )
  }
  let label = '일반가'
  let color = '#374151'
  let bg = '#f3f4f6'
  if (dealPrice != null) {
    if (dealPrice <= grade.p10) {
      label = '진짜 핫딜!'
      color = 'white'
      bg = '#ef4444'
    } else if (grade.p50 != null && dealPrice <= grade.p50) {
      label = '세일'
      color = 'white'
      bg = '#f59e0b'
    } else {
      label = '높은 가격'
      color = 'white'
      bg = '#1d4ed8'
    }
  }
  return (
    <div
      style={{
        padding: '8px 12px',
        borderRadius: 12,
        background: bg,
        color,
        fontSize: 13,
        display: 'inline-flex',
        gap: 12,
        alignItems: 'center',
      }}
    >
      <strong>{label}</strong>
      <span>현재가 {fmt(dealPrice)}</span>
      <span>DB 핫딜가 {fmt(grade.p10)}</span>
      <span>중앙가 {fmt(grade.p50)}</span>
    </div>
  )
}
