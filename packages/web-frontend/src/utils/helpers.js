/**
 * 유틸리티 함수 — 포맷팅, 가격 검증 등.
 * mockData.js에서 분리한 순수 함수들.
 */

/** 숫자를 한국어 천단위 콤마로 포맷 */
export function fmt(n) {
  if (n == null) return '';
  return n.toLocaleString('ko-KR');
}

/** Unit-rate labels only; comparisons keep the original numeric value. */
export function fmtUnitPrice(value, prefix = '') {
  const number = typeof value === 'string' && value.trim() ? Number(value) : value;
  if (typeof number !== 'number' || !Number.isFinite(number) || number < 0) return '';
  const text = number.toLocaleString('ko-KR', {
    ...(number >= 1 ? { maximumFractionDigits: 2 } : { maximumSignificantDigits: 6 }),
    notation: number > 0 && number < 0.000001 ? 'scientific' : 'standard',
  });
  const approximate = Number(text.replace(/,/g, '')) !== number;
  return `${approximate ? '≈ ' : ''}${prefix}${text}`;
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

/** Short presentation only; native conditions and comparison numbers are unchanged. */
export function getOfferConditionSummary(offer = {}) {
  const c = offer.promotion_conditions || {};
  const parts = [];
  if (c.basket_selection_required === true) {
    if (c.required_selection_quantity > 0) parts.push(`선택 ${c.required_selection_quantity}개 조건`);
    if (c.conditional_discount_percent > 0) parts.push(`${c.conditional_discount_percent}% 혜택`);
    parts.push('동일 상품 적용 미확인');
  } else if (c.source_condition_kind === 'source_public_base_quote' && c.source_base_quote_only === true) {
    parts.push('기본 표시가 · 추가 혜택 별도');
    if (c.source_required_product_quantity > 0) parts.push(`선택 ${c.source_required_product_quantity}개 조건`);
    if (c.conditional_discount_percent > 0) parts.push(`${c.conditional_discount_percent}% 혜택 · 적용 미확인`);
    if (c.selected_product_scope_unconfirmed === true) parts.push('동일 상품 적용 미확인');
  } else if (offer.promotion_condition) {
    parts.push(offer.promotion_condition);
  }
  if (offer.membership_required === true) parts.push('회원 필요');
  if (offer.coupon_required === true) parts.push('쿠폰 필요');
  if (offer.membership_required == null || offer.coupon_required == null) parts.push('회원·쿠폰 조건 확인');
  if (offer.availability_reason === 'expired') parts.push('판매 기간 종료');
  return parts.join(' · ') || '별도 행사 조건 미표시';
}
