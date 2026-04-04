const API_BASE = '/api';

// ETag 캐시: 상태 폴링 시 304 응답으로 불필요한 JSON 파싱 방지
const _etagCache = new Map();

/**
 * ETag 지원 fetch — 변경 없으면 캐시된 데이터 반환 (폴링 최적화).
 */
async function fetchWithETag(url, options = {}) {
  const cached = _etagCache.get(url);
  const headers = { ...options.headers };
  if (cached?.etag) {
    headers['If-None-Match'] = cached.etag;
  }

  const resp = await fetch(url, { ...options, headers });

  if (resp.status === 304 && cached?.data) {
    return cached.data;
  }

  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

  const data = await resp.json();
  const etag = resp.headers.get('etag');
  if (etag) {
    _etagCache.set(url, { etag, data });
  }
  return data;
}

/**
 * SSE 연결 헬퍼 — 크롤러 실행 상태를 실시간 수신 (폴링 대체).
 * @returns {{ close: () => void }} 연결 해제 핸들
 */
function subscribeCrawlerStatus(crawlerId, { onData, onError, onComplete }) {
  const url = `${API_BASE}/crawlers/${crawlerId}/status/stream`;
  const eventSource = new EventSource(url);

  eventSource.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      onData?.(data);
      if (data.status === 'success' || data.status === 'failed') {
        eventSource.close();
        onComplete?.(data);
      }
    } catch (e) {
      onError?.(e);
    }
  };

  eventSource.onerror = () => {
    eventSource.close();
    onError?.(new Error('SSE connection failed'));
  };

  return { close: () => eventSource.close() };
}

export const api = {
  // 크롤러 목록
  getCrawlers: () => fetch(`${API_BASE}/crawlers`).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
  // 크롤러 실행
  runCrawler: (id) => fetch(`${API_BASE}/crawlers/${id}/run`, { method: 'POST' }).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
  // 크롤러 상태 — ETag 기반 캐시로 변경 없으면 304 반환
  getCrawlerStatus: (id) => fetchWithETag(`${API_BASE}/crawlers/${id}/status`),
  // 크롤러 상태 SSE 구독
  subscribeCrawlerStatus,
  // 크롤러 토글
  toggleCrawler: (id, status) => fetch(`${API_BASE}/crawlers/${id}/toggle`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status }),
  }).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
  // 크롤러 벌크 실행
  bulkRunCrawlers: (ids) => fetch(`${API_BASE}/crawlers/bulk-run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ crawler_ids: ids }),
  }).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
  // 크롤러 설정
  getCrawlerSettings: (id) => fetch(`${API_BASE}/crawlers/${id}/settings`).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
  updateCrawlerSettings: (id, data) => fetch(`${API_BASE}/crawlers/${id}/settings`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
  // 대시보드 통계
  getDashboardStats: (params = {}) => fetch(`${API_BASE}/dashboard/stats?${new URLSearchParams(params)}`).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
  // 로그
  getLogs: (params) => fetch(`${API_BASE}/logs?${new URLSearchParams(params)}`).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
  // 로그 CSV 내보내기
  exportLogsCsv: (params = {}) => fetch(`${API_BASE}/logs/export?${new URLSearchParams(params)}`).then(r => {
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.blob();
  }),
  // 스케줄
  getSchedules: () => fetch(`${API_BASE}/schedules`).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
  createSchedule: (data) => fetch(`${API_BASE}/schedules`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
  updateSchedule: (name, data) => fetch(`${API_BASE}/schedules/${name}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
  deleteSchedule: (name) => fetch(`${API_BASE}/schedules/${name}`, { method: 'DELETE' }),
  toggleSchedule: (name, enabled) => fetch(`${API_BASE}/schedules/${name}/toggle`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled }),
  }).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
  runScheduleNow: (name) => fetch(`${API_BASE}/schedules/${name}/run-now`, {
    method: 'POST',
  }).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
  // 플러그인
  getPlugins: () => fetch(`${API_BASE}/plugins`).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
  togglePlugin: (id, status) => fetch(`${API_BASE}/plugins/${id}/status`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status }),
  }).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
  updatePluginSettings: (id, data) => fetch(`${API_BASE}/plugins/${id}/settings`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
  // 대기열
  getIngestions: (params) => fetch(`${API_BASE}/ingestions?${new URLSearchParams(params)}`).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
  getIngestion: (id) => fetch(`${API_BASE}/ingestions/${id}`).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
  reviewIngestion: (id, data) => fetch(`${API_BASE}/ingestions/${id}/crawler-review`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
  cleanupIngestions: (data) => fetch(`${API_BASE}/ingestions/cleanup`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
};
