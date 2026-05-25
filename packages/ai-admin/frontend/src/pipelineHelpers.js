/**
 * UI 헬퍼 — 빈 데이터(0) vs 에러를 명확히 분류하기 위한 순수 함수.
 * App.jsx / LivePipelinePanel.jsx 에서 동일하게 사용.
 */

/**
 * fetch 실패/HTTP 에러를 사용자 친화 카테고리로 분류한다.
 *
 * @param {Error|string|null} err
 * @returns {{kind: string, label: string} | null}
 */
export function classifyError(err) {
  if (!err) return null;
  const s = String(err.message || err);
  if (/Failed to fetch|NetworkError|TypeError/i.test(s)) {
    return { kind: 'down', label: '백엔드 끊김 — 서버 실행 여부 확인' };
  }
  if (/HTTP 401|HTTP 403/.test(s)) {
    return { kind: 'auth', label: 'API 인증 실패 (401/403)' };
  }
  if (/HTTP 5\d\d/.test(s)) return { kind: 'server', label: `백엔드 5xx 오류: ${s}` };
  if (/HTTP 4\d\d/.test(s)) return { kind: 'client', label: `요청 오류: ${s}` };
  return { kind: 'other', label: s };
}

/**
 * 파이프라인 다음 단계 결정. 사용자 헌법: "딸깍 3번에 라이브 가동"
 *
 * @returns {{idx: number, key: string, label: string, action: string}}
 */
export function pickNextStep({
  errKind = null,
  rawCount = 0,
  proposalCount = 0,
  pendingReviewCount = 0,
  publishedCount = 0,
  failedJobs = 0,
  auditMissing = 0,
} = {}) {
  if (errKind) return { idx: -1, key: 'error', label: '백엔드 점검 필요', action: '다시 시도' };
  if (rawCount === 0) {
    return { idx: 0, key: 'crawl', label: '원본 수집 필요', action: 'crawler-admin 열기' };
  }
  if (proposalCount === 0 || auditMissing > 0) {
    return { idx: 1, key: 'ai', label: 'AI 처리 가동 필요', action: 'AI 처리 가동' };
  }
  if (pendingReviewCount > 0) {
    return { idx: 2, key: 'review', label: `${pendingReviewCount}건 검수/발행 대기`, action: '검수·발행 열기' };
  }
  if (failedJobs > 0) {
    return { idx: 2, key: 'failed', label: `${failedJobs}개 실패 잡`, action: '실패 잡 보기' };
  }
  return { idx: 3, key: 'idle', label: `발행 완료 ${publishedCount}건`, action: '새로고침' };
}

export function fmtNumberKR(n) {
  if (n == null) return '—';
  if (typeof n !== 'number') return String(n);
  return n.toLocaleString('ko-KR');
}
