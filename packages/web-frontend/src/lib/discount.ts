// web-FINAL §3-2: "평소 대비 -X%" 통일 산식.
// 의도: 카드/상세/글쓰기/검색 결과 어디서든 같은 산식·4축 검사·라벨 임계를 거치게 한다.
// 후속 AI에게: 이 모듈을 우회해서 컴포넌트에서 직접 계산하지 말 것. 산식 흔들리면 사용자 신뢰 깨짐.
//
// 4축 검사 (모두 통과 시에만 discount_pct 노출):
//   ① 표본: sample_count >= 10
//   ② 최근성: last_seen_days <= 30
//   ③ 구매 가능성: has_active_source === true
//   ④ 용량 신뢰도: unit_known === true
// 하나라도 실패하면 reason 텍스트로 사유 노출, percent 는 숨김.

export type DiscountReason =
  | 'ok'
  | 'sample_low'
  | 'stale'
  | 'unavailable'
  | 'unit_unknown'
  | 'no_p50'
  | 'no_price'

export interface DiscountInput {
  p50: number | null | undefined
  displayPrice: number | null | undefined
  sampleCount?: number | null
  lastSeenDays?: number | null
  hasActiveSource?: boolean | null
  unitKnown?: boolean | null
}

export interface DiscountResult {
  percent: number | null
  rawPercent: number | null
  displayable: boolean
  reason: DiscountReason
  reasonLabel: string
  grade: 'HOT_DEAL' | 'SALE' | 'NORMAL' | 'OVERPRICED' | 'UNKNOWN'
  direction: '↓' | '—' | '↑' | ''
}

const SAMPLE_MIN = 10
const STALE_DAYS = 30

export function computeDiscount(input: DiscountInput): DiscountResult {
  const { p50, displayPrice } = input

  if (p50 == null || p50 <= 0) {
    return {
      percent: null,
      rawPercent: null,
      displayable: false,
      reason: 'no_p50',
      reasonLabel: '평소가 미확정',
      grade: 'UNKNOWN',
      direction: '',
    }
  }

  if (displayPrice == null) {
    return {
      percent: null,
      rawPercent: null,
      displayable: false,
      reason: 'no_price',
      reasonLabel: '현재가 미확인',
      grade: 'UNKNOWN',
      direction: '',
    }
  }

  const rawPercent = ((p50 - displayPrice) / p50) * 100
  const grade = gradeFromPercent(rawPercent)
  const direction: DiscountResult['direction'] =
    rawPercent >= 10 ? '↓' : rawPercent <= -5 ? '↑' : '—'

  const allUnset =
    input.sampleCount === undefined &&
    input.lastSeenDays === undefined &&
    input.hasActiveSource === undefined &&
    input.unitKnown === undefined

  if (allUnset) {
    return {
      percent: Math.round(rawPercent),
      rawPercent,
      displayable: true,
      reason: 'ok',
      reasonLabel: '',
      grade,
      direction,
    }
  }

  if (input.sampleCount != null && input.sampleCount < SAMPLE_MIN) {
    return {
      percent: null,
      rawPercent,
      displayable: false,
      reason: 'sample_low',
      reasonLabel: `표본 ${input.sampleCount}건 · 참고용`,
      grade,
      direction,
    }
  }
  if (input.lastSeenDays != null && input.lastSeenDays > STALE_DAYS) {
    return {
      percent: null,
      rawPercent,
      displayable: false,
      reason: 'stale',
      reasonLabel: `최근 확인 ${input.lastSeenDays}일 전`,
      grade,
      direction,
    }
  }
  if (input.hasActiveSource === false) {
    return {
      percent: null,
      rawPercent,
      displayable: false,
      reason: 'unavailable',
      reasonLabel: '재고 불확실',
      grade,
      direction,
    }
  }
  if (input.unitKnown === false) {
    return {
      percent: null,
      rawPercent,
      displayable: false,
      reason: 'unit_unknown',
      reasonLabel: '⚠️ 용량 미확정',
      grade,
      direction,
    }
  }

  return {
    percent: Math.round(rawPercent),
    rawPercent,
    displayable: true,
    reason: 'ok',
    reasonLabel: '',
    grade,
    direction,
  }
}

// 라벨 임계 (web-FINAL §3-2): ≥25% 핫딜, ≥10% 세일, -5~10% 평소, <-5% 비쌈.
export function gradeFromPercent(pct: number): DiscountResult['grade'] {
  if (pct >= 25) return 'HOT_DEAL'
  if (pct >= 10) return 'SALE'
  if (pct >= -5) return 'NORMAL'
  return 'OVERPRICED'
}

// 카드 한 줄용 짧은 텍스트: "평소 대비 -32% ↓" 또는 사유 텍스트.
export function discountSummaryText(r: DiscountResult): string {
  if (r.displayable && r.percent != null) {
    const sign = r.percent >= 0 ? '-' : '+'
    return `평소 대비 ${sign}${Math.abs(r.percent)}% ${r.direction}`.trim()
  }
  return r.reasonLabel || '정보 부족'
}
