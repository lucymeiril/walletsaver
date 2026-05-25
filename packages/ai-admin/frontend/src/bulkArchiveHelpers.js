/**
 * AI 제안 비우기 wizard 헬퍼.
 *
 * 사용자 비판 직격: "34,300건 대기 중인데 이걸 진짜 하자고? 못 비워? 내역은 어떻게 보는데?"
 * 응답:
 *  - 필터(상태/타입/소스/날짜) → 미리보기 → 확인 → 일괄 archive → 30초 undo → audit log.
 *  - 미리보기 텍스트, undo countdown, 위험 분류를 순수 함수로 분리해 테스트 가능하게 한다.
 */

export const DEFAULT_FILTER = Object.freeze({
  statuses: [],
  proposal_types: [],
  source_names: [],
  target_fields: [],
  created_before: '',
  created_after: '',
});

export function serializeFilters(filters) {
  const f = filters || {};
  const out = {};
  if (Array.isArray(f.statuses) && f.statuses.length) out.statuses = f.statuses;
  if (Array.isArray(f.proposal_types) && f.proposal_types.length) out.proposal_types = f.proposal_types;
  if (Array.isArray(f.source_names) && f.source_names.length) out.source_names = f.source_names;
  if (Array.isArray(f.target_fields) && f.target_fields.length) out.target_fields = f.target_fields;
  if (f.created_before) out.created_before = new Date(f.created_before).toISOString();
  if (f.created_after) out.created_after = new Date(f.created_after).toISOString();
  return out;
}

export function describeFilters(filters) {
  const f = filters || {};
  const parts = [];
  if (f.statuses?.length) parts.push(`상태 = ${f.statuses.join(', ')}`);
  if (f.proposal_types?.length) parts.push(`타입 = ${f.proposal_types.join(', ')}`);
  if (f.source_names?.length) parts.push(`소스 = ${f.source_names.join(', ')}`);
  if (f.target_fields?.length) parts.push(`필드 = ${f.target_fields.join(', ')}`);
  if (f.created_before) parts.push(`이전: ${f.created_before}`);
  if (f.created_after) parts.push(`이후: ${f.created_after}`);
  return parts.length ? parts.join(' · ') : '전체 검수 대기·반려·보류 제안';
}

export function classifyImpact(matched) {
  const n = Number(matched) || 0;
  if (n === 0) return { tone: 'muted', label: '영향 없음' };
  if (n < 100) return { tone: 'safe', label: '소규모' };
  if (n < 5000) return { tone: 'warn', label: '대규모' };
  return { tone: 'danger', label: '초대규모 · 신중' };
}

export function confirmMessage(matched, filters) {
  const n = Number(matched) || 0;
  return `${n.toLocaleString()}건을 비웁니다.\n조건: ${describeFilters(filters)}\n30초 안에 "되돌리기" 누르면 복원됩니다.`;
}

/**
 * undo countdown 상태 계산.
 * 입력: { issuedAt:ISO, expiresAt:ISO, now:Date }
 * 반환: { secondsLeft, ratio (0..1), expired }
 */
export function undoCountdown({ expiresAt, now }) {
  if (!expiresAt) return { secondsLeft: 0, ratio: 0, expired: true };
  const t = new Date(expiresAt).getTime();
  const cur = (now instanceof Date ? now : new Date()).getTime();
  const ms = Math.max(0, t - cur);
  const secondsLeft = Math.ceil(ms / 1000);
  const ratio = Math.max(0, Math.min(1, ms / 30000));
  return { secondsLeft, ratio, expired: ms <= 0 };
}
