// web-FINAL §11-4: single formatting module.
// 의도: 가격/퍼센트/날짜 포맷을 한 곳에서만 정의. 카드/상세/글쓰기/검색이 모두 같은 표기를 쓰도록.
// 후속 AI에게: 산식·임계는 ./discount.ts 에 있다. 여기는 표시만.

export function formatPrice(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '-'
  return `₩${Math.round(v).toLocaleString('ko-KR')}`
}

export function formatPct(v: number | null | undefined, opts: { sign?: boolean } = {}): string {
  if (v == null || Number.isNaN(v)) return '-'
  const rounded = Math.round(v)
  if (opts.sign) {
    if (rounded > 0) return `+${rounded}%`
    return `${rounded}%`
  }
  return `${rounded}%`
}

export function formatRelativeDays(days: number | null | undefined): string {
  if (days == null) return ''
  if (days <= 0) return '오늘 확인'
  if (days === 1) return '1일 전 확인'
  return `${days}일 전 확인`
}
