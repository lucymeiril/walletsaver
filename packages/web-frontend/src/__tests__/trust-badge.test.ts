import { describe, it, expect } from 'vitest'
import { classifyTrust, parseDomain } from '../lib/trustBadge'

describe('parseDomain', () => {
  it('https URL', () => expect(parseDomain('https://emart.ssg.com/item/x')).toBe('emart.ssg.com'))
  it('www. 제거', () => expect(parseDomain('https://www.coupang.com/y')).toBe('coupang.com'))
  it('스키마 없음 보정', () => expect(parseDomain('homeplus.co.kr/z')).toBe('homeplus.co.kr'))
  it('null/잘못된 URL', () => {
    expect(parseDomain(null)).toBe(null)
    expect(parseDomain('not a url')).toBe(null)
  })
})

describe('classifyTrust — web-FINAL §4-4', () => {
  it('🟢 마트명+링크 일치', () => {
    expect(classifyTrust({ dealUrl: 'https://emart.ssg.com/x', martName: 'EMART' }).level).toBe('green')
  })

  it('🔴 마트명 EMART 인데 링크는 쿠팡 → red', () => {
    expect(classifyTrust({ dealUrl: 'https://coupang.com/x', martName: 'EMART' }).level).toBe('red')
  })

  it('🟡 외부(비화이트리스트) 링크', () => {
    expect(classifyTrust({ dealUrl: 'https://random-blog.tistory.com/x', martName: 'EMART' }).level).toBe('yellow')
  })

  it('🟡 링크 없음', () => {
    expect(classifyTrust({ dealUrl: null, martName: 'EMART' }).level).toBe('yellow')
  })

  it('마트명 비어도 화이트리스트 도메인이면 (다른 마트와 일치 안 함) yellow 또는 red', () => {
    const r = classifyTrust({ dealUrl: 'https://coupang.com/x', martName: '' })
    expect(['yellow', 'red']).toContain(r.level)
  })

  it('ariaLabel 항상 제공', () => {
    const r = classifyTrust({ dealUrl: 'https://emart.ssg.com/x', martName: 'EMART' })
    expect(r.ariaLabel.length).toBeGreaterThan(0)
  })
})
