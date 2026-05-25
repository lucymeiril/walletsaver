import { describe, it, expect } from 'vitest'
import { computeDiscount, gradeFromPercent, discountSummaryText } from '../lib/discount'

describe('computeDiscount — 통일 산식 (web-FINAL §3-2)', () => {
  it('정상 케이스: -32% 계산', () => {
    const r = computeDiscount({
      p50: 2200,
      displayPrice: 1500,
      sampleCount: 12,
      lastSeenDays: 5,
      hasActiveSource: true,
      unitKnown: true,
    })
    expect(r.displayable).toBe(true)
    expect(r.percent).toBeGreaterThan(30)
    expect(r.percent).toBeLessThan(33)
    expect(r.direction).toBe('↓')
  })

  it('인상: +5% 양수, ↑', () => {
    const r = computeDiscount({
      p50: 2000,
      displayPrice: 2100,
      sampleCount: 12,
      lastSeenDays: 5,
      hasActiveSource: true,
      unitKnown: true,
    })
    expect(r.percent).toBeLessThan(0)
    expect(r.direction).toBe('↑')
  })

  it('4축 미설정(서버 미지원): 통과 + 산식만', () => {
    const r = computeDiscount({ p50: 2000, displayPrice: 1600 })
    expect(r.displayable).toBe(true)
    expect(r.percent).toBe(20)
  })

  it('표본 부족(<10): 비표시', () => {
    const r = computeDiscount({
      p50: 2000,
      displayPrice: 1500,
      sampleCount: 3,
      lastSeenDays: 5,
      hasActiveSource: true,
      unitKnown: true,
    })
    expect(r.displayable).toBe(false)
    expect(r.reason).toBe('sample_low')
  })

  it('너무 오래된 데이터(>30일): 비표시', () => {
    const r = computeDiscount({
      p50: 2000,
      displayPrice: 1500,
      sampleCount: 20,
      lastSeenDays: 45,
      hasActiveSource: true,
      unitKnown: true,
    })
    expect(r.displayable).toBe(false)
    expect(r.reason).toBe('stale')
  })

  it('활성 소스 없음: 비표시', () => {
    const r = computeDiscount({
      p50: 2000,
      displayPrice: 1500,
      sampleCount: 20,
      lastSeenDays: 5,
      hasActiveSource: false,
      unitKnown: true,
    })
    expect(r.displayable).toBe(false)
    expect(r.reason).toBe('unavailable')
  })

  it('단위 불명: 비표시', () => {
    const r = computeDiscount({
      p50: 2000,
      displayPrice: 1500,
      sampleCount: 20,
      lastSeenDays: 5,
      hasActiveSource: true,
      unitKnown: false,
    })
    expect(r.displayable).toBe(false)
    expect(r.reason).toBe('unit_unknown')
  })

  it('p50 또는 displayPrice null: 비표시', () => {
    expect(computeDiscount({ p50: null, displayPrice: 1500 }).displayable).toBe(false)
    expect(computeDiscount({ p50: 2000, displayPrice: null }).displayable).toBe(false)
  })
})

describe('gradeFromPercent — 임계 (≥25/≥10/-5~10/<-5)', () => {
  it('25% 이상 → HOT_DEAL', () => {
    expect(gradeFromPercent(30)).toBe('HOT_DEAL')
    expect(gradeFromPercent(25)).toBe('HOT_DEAL')
  })
  it('10~25 → SALE', () => {
    expect(gradeFromPercent(15)).toBe('SALE')
    expect(gradeFromPercent(10)).toBe('SALE')
  })
  it('-5~10 → NORMAL', () => {
    expect(gradeFromPercent(0)).toBe('NORMAL')
    expect(gradeFromPercent(-5)).toBe('NORMAL')
    expect(gradeFromPercent(9)).toBe('NORMAL')
  })
  it('<-5 → OVERPRICED', () => {
    expect(gradeFromPercent(-10)).toBe('OVERPRICED')
  })
})

describe('discountSummaryText', () => {
  it('표시 가능 시 -N% 텍스트 포함', () => {
    const r = computeDiscount({ p50: 2000, displayPrice: 1600 })
    expect(discountSummaryText(r)).toMatch(/20/)
  })
  it('비표시 사유 라벨', () => {
    const r = computeDiscount({
      p50: 2000,
      displayPrice: 1500,
      sampleCount: 3,
      lastSeenDays: 5,
      hasActiveSource: true,
      unitKnown: true,
    })
    expect(discountSummaryText(r)).toMatch(/표본/)
  })
})
