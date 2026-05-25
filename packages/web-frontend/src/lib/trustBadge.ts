// web-FINAL §4-4: 글쓰기 신뢰 배지 통합.
// 의도: 카드(게시판 리스트/홈 인기글) 1배지, 글 상세 3종 펼침. 서버 판정(`/products/trust_badge`) 로
//       도메인 매칭 후 카드 라벨은 GREEN/YELLOW/RED 1개로 통합.
// 후속 AI에게: 화이트리스트는 코드 변경 없이 운영자 편집 가능해야 함 → 서버 환경 설정(`web-api/config/...`).
//             클라이언트는 도메인 추출 + 미리보기 즉시 배지(서버 응답 도착 전)만 책임.

export type TrustLevel = 'green' | 'yellow' | 'red'

export interface TrustBadge {
  level: TrustLevel
  cardLabel: string
  detailLabel: string
  ariaLabel: string
}

// 클라이언트 측 기본 매핑 — 서버 화이트리스트 응답 도착 전 즉시 표시용.
const KOREAN_MART_DOMAINS: Record<string, string[]> = {
  EMART: ['emart.ssg.com', 'emart.com', 'shinsegae.com'],
  HOMEPLUS: ['homeplus.co.kr'],
  LOTTEMART: ['lotteon.com', 'lottemart.com'],
  COSTCO: ['costco.co.kr'],
  COUPANG: ['coupang.com'],
}

export function parseDomain(url: string | null | undefined): string | null {
  if (!url) return null
  try {
    const u = new URL(/^https?:\/\//.test(url) ? url : `https://${url}`)
    return u.hostname.replace(/^www\./, '').toLowerCase()
  } catch {
    return null
  }
}

export function classifyTrust(opts: {
  dealUrl?: string | null
  martName?: string | null
}): TrustBadge {
  const domain = parseDomain(opts.dealUrl)
  const mart = (opts.martName || '').toUpperCase()

  if (!domain) {
    return {
      level: 'yellow',
      cardLabel: '🟡 검증 중',
      detailLabel: '🟡 링크 없음 — 작성자 입력 정보',
      ariaLabel: '신뢰도 검증 중 (링크 없음)',
    }
  }

  const expected = KOREAN_MART_DOMAINS[mart]
  const allKnown = Object.values(KOREAN_MART_DOMAINS).flat()
  const inSomeWhitelist = allKnown.some((d) => domain === d || domain.endsWith(`.${d}`))

  if (expected && expected.some((d) => domain === d || domain.endsWith(`.${d}`))) {
    return {
      level: 'green',
      cardLabel: '🟢 검증됨',
      detailLabel: '🟢 공식몰 링크 확인됨',
      ariaLabel: '신뢰도 검증됨 (공식몰 일치)',
    }
  }

  if (!inSomeWhitelist) {
    return {
      level: 'yellow',
      cardLabel: '🟡 검증 중',
      detailLabel: '🟡 외부 링크 — 공식몰 아님',
      ariaLabel: '신뢰도 검증 중 (외부 링크)',
    }
  }

  return {
    level: 'red',
    cardLabel: '🔴 불일치',
    detailLabel: '🔴 마트명/링크 불일치',
    ariaLabel: '신뢰도 불일치 (마트명과 링크 도메인 다름)',
  }
}
