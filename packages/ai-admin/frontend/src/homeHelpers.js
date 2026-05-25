/**
 * 홈 화면 KPI/다음 액션 계산.
 *
 * 사용자 비판 해소:
 *  - "정보량이 너무 많고, 뭘 해야 할지도 직관적이지 않다" → 단 한 가지 다음 액션을 강제 표시.
 *  - "AI 제안 비우기 어디감?" → 누적 큐 카운터와 비우기 진입을 홈에 노출.
 *  - "매칭 누적 쪽도 뭘 어쩌라는 건지" → 의미가 명료한 3개 KPI 만 노출 (큐/이번주 발행/검토 필요).
 */

export function summarizeReviewQueue(items) {
  const list = Array.isArray(items) ? items : [];
  const counts = {
    ai_proposed: 0,
    human_reviewing: 0,
    approved: 0,
    pending_db_review: 0,
    published_total: 0,
    total: list.length,
  };
  for (const p of list) {
    const s = p?.status;
    if (s === 'ai_proposed') counts.ai_proposed += 1;
    else if (s === 'human_reviewing') counts.human_reviewing += 1;
    else if (s === 'approved') counts.approved += 1;
    else if (s === 'pending_db_review') counts.pending_db_review += 1;
    else if (s === 'published') counts.published_total += 1;
  }
  counts.review_needed = counts.ai_proposed + counts.human_reviewing;
  return counts;
}

/**
 * 30일 처리량 계산. items 의 created_at 또는 decided_at 기반.
 * status=published 만 카운트.
 */
export function countRecentPublished(items, now = new Date(), windowDays = 30) {
  const list = Array.isArray(items) ? items : [];
  const cutoff = now.getTime() - windowDays * 24 * 60 * 60 * 1000;
  let n = 0;
  for (const p of list) {
    if (p?.status !== 'published') continue;
    const raw = p?.decided_at || p?.updated_at || p?.created_at;
    if (!raw) continue;
    const t = new Date(raw).getTime();
    if (Number.isFinite(t) && t >= cutoff) n += 1;
  }
  return n;
}

/**
 * 다음 액션 단 1~2 개를 추천.
 * 우선순위:
 *  1. 백엔드 끊김 → 재연결
 *  2. 검토 대기가 50건 초과 → "비우기" 우선 (사용자 명시 요구)
 *  3. 검토 대기 1건 이상 → "검수 열기"
 *  4. approved 1건 이상 → "발행 진행"
 *  5. 아무것도 없으면 → "AI 처리 가동"
 */
export function nextActions({ backendDown, counts }) {
  const c = counts || {};
  if (backendDown) {
    return [{ id: 'reconnect', label: '백엔드 재연결', tone: 'danger', target: 'banner' }];
  }
  if ((c.review_needed || 0) > 50) {
    return [
      { id: 'bulk-archive', label: `AI 제안 ${c.review_needed.toLocaleString()}건 비우기`, tone: 'primary', target: 'bulk-archive' },
      { id: 'open-review', label: '하나씩 검수', tone: 'secondary', target: 'review' },
    ];
  }
  if ((c.review_needed || 0) >= 1) {
    return [{ id: 'open-review', label: `검수 ${c.review_needed}건 열기`, tone: 'primary', target: 'review' }];
  }
  if ((c.approved || 0) >= 1) {
    return [{ id: 'publish', label: `발행 대기 ${c.approved}건 진행`, tone: 'primary', target: 'advanced-publish' }];
  }
  return [{ id: 'idle', label: '큐 비어 있음 · 다음 배치 대기', tone: 'muted', target: null }];
}

/**
 * KPI 카드 3개 명세를 만들어준다. 매칭 누적 패널의 무의미한 숫자 더미를
 * "이번 주 자동 매칭 / 운영자 검토 필요 / 비우기 대기" 의 액션 가능한 3개로 압축.
 */
export function buildHomeKpis({ counts, publishedRecent, matchSummary }) {
  const c = counts || {};
  const m = matchSummary || {};
  return [
    {
      id: 'review-needed',
      label: '운영자 검토 필요',
      value: c.review_needed || 0,
      hint: '검수 탭에서 J/K 이동, Enter 승인',
      target: 'review',
    },
    {
      id: 'published-recent',
      label: '최근 30일 발행',
      value: publishedRecent || 0,
      hint: 'published 상태 누적',
      target: null,
    },
    {
      id: 'auto-matched',
      label: '이번 주 자동 매칭',
      value: m.auto_matched_week || 0,
      hint: '운영자 개입 없이 매칭된 건',
      target: 'advanced-match',
    },
  ];
}
