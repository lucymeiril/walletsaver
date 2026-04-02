/**
 * 유틸리티 함수 — 포맷팅, 가격 검증 등.
 * mockData.js에서 분리한 순수 함수들.
 */

/** 숫자를 한국어 천단위 콤마로 포맷 */
export function fmt(n) {
  if (n == null) return '';
  return n.toLocaleString('ko-KR');
}

/**
 * 커뮤니티 가격 검증 — 사용자 입력 가격과 평균가를 비교하여 신뢰도를 판단.
 * @param {number} userPrice 사용자가 입력한 가격
 * @param {number} avgPrice 수집된 평균 시세
 * @returns {{ status: string, label: string, emoji: string, canPost: boolean, pct?: number }}
 */
export function verifyPrice(userPrice, avgPrice) {
  if (!avgPrice || avgPrice <= 0) return { status: 'unmatched', label: '품목 매칭 필요', emoji: '❓', canPost: true };
  const ratio = userPrice / avgPrice;
  const pct = Math.round((ratio - 1) * 100);
  if (ratio < 0.20) return { status: 'sus_low', label: `⚠️ 허위 가격 의심 (${pct}%)`, emoji: '⚠️', canPost: false, pct };
  if (ratio < 0.70) return { status: 'great_deal', label: `🔥 진짜 핫딜! (${pct}%)`, emoji: '🔥', canPost: true, pct };
  if (ratio <= 1.20) return { status: 'verified', label: `✅ 검증됨 (${pct >= 0 ? '+' : ''}${pct}%)`, emoji: '✅', canPost: true, pct };
  return { status: 'sus_high', label: `🚨 바이럴 의심 (+${pct}%)`, emoji: '🚨', canPost: true, pct };
}
