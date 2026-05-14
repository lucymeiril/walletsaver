import { getApiKey, logout as authLogout } from '../stores/authStore';

const API_BASE = '/api';
const FETCH_TIMEOUT_MS = 30000;

// HTTP 상태 코드별 사용자 친화적 에러 메시지
const HTTP_ERROR_MESSAGES = {
  400: '잘못된 요청입니다.',
  401: '인증이 필요합니다. 다시 로그인해 주세요.',
  403: '접근 권한이 없습니다.',
  404: '요청한 리소스를 찾을 수 없습니다.',
  408: '요청 시간이 초과되었습니다.',
  429: '요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.',
  500: '서버 내부 오류가 발생했습니다.',
  502: '서버에 연결할 수 없습니다.',
  503: '서비스를 일시적으로 사용할 수 없습니다.',
};

function getHttpErrorMessage(status) {
  return HTTP_ERROR_MESSAGES[status] || `서버 오류가 발생했습니다 (HTTP ${status})`;
}

async function getResponseErrorMessage(resp) {
  try {
    const data = await resp.clone().json();
    const detail = data?.detail || data?.error || data?.message;
    if (detail) return typeof detail === 'string' ? detail : JSON.stringify(detail);
  } catch {
    // Fall back to status-based message when the response is not JSON.
  }
  return getHttpErrorMessage(resp.status);
}

// ─── 인증 헤더 주입 ───
function injectAuth(headers = {}) {
  const key = getApiKey();
  if (!key) return headers;
  return { ...headers, 'X-API-Key': key };
}

/**
 * AbortController 기반 fetch — 타임아웃 및 컴포넌트 언마운트 시 정리 지원.
 * @param {string} url
 * @param {RequestInit & { timeoutMs?: number, signal?: AbortSignal }} options
 */
async function fetchWithTimeout(url, options = {}) {
  const { timeoutMs = FETCH_TIMEOUT_MS, signal: externalSignal, ...fetchOptions } = options;
  fetchOptions.headers = injectAuth(fetchOptions.headers);

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  // 외부 signal이 있으면 연결
  if (externalSignal) {
    if (externalSignal.aborted) {
      controller.abort();
    } else {
      externalSignal.addEventListener('abort', () => controller.abort(), { once: true });
    }
  }

  try {
    const resp = await fetch(url, { ...fetchOptions, signal: controller.signal });
    if (resp.status === 401 || resp.status === 403) {
      authLogout();
      throw new Error(getHttpErrorMessage(resp.status));
    }
    if (!resp.ok) throw new Error(await getResponseErrorMessage(resp));
    return resp;
  } catch (err) {
    if (err.name === 'AbortError') {
      throw new Error('요청 시간이 초과되었습니다. 네트워크 연결을 확인해 주세요.');
    }
    if (err.message && !err.message.startsWith('서버')) {
      throw err;
    }
    throw err;
  } finally {
    clearTimeout(timeoutId);
  }
}

// ETag 캐시: 상태 폴링 시 304 응답으로 불필요한 JSON 파싱 방지
const _etagCache = new Map();

/**
 * ETag 지원 fetch — 변경 없으면 캐시된 데이터 반환 (폴링 최적화).
 */
async function fetchWithETag(url, options = {}) {
  const cached = _etagCache.get(url);
  const headers = injectAuth({ ...options.headers });
  if (cached?.etag) {
    headers['If-None-Match'] = cached.etag;
  }

  const resp = await fetch(url, { ...options, headers });

  if (resp.status === 304 && cached?.data) {
    return cached.data;
  }

  if (resp.status === 401 || resp.status === 403) {
    authLogout();
    throw new Error(getHttpErrorMessage(resp.status));
  }

  if (!resp.ok) throw new Error(getHttpErrorMessage(resp.status));

  const data = await resp.json();
  const etag = resp.headers.get('etag');
  if (etag) {
    _etagCache.set(url, { etag, data });
  }
  return data;
}

/**
 * SSE 연결 헬퍼 — 크롤러 실행 상태를 실시간 수신.
 *
 * SSE reconnection with exponential backoff (audit fix).
 * - On transient error: retry up to MAX_RETRIES times with backoff
 * - On successful message: reset retry counter
 * - On terminal status (success/failed): close cleanly
 *
 * @returns {{ close: () => void }} 연결 해제 핸들
 */
function subscribeCrawlerStatus(crawlerId, { onData, onError, onComplete }) {
  const MAX_RETRIES = 5;
  const BASE_DELAY_MS = 1000;
  const MAX_DELAY_MS = 10000;

  let retryCount = 0;
  let currentSource = null;
  let closed = false;
  let retryTimer = null;
  let lastEventId = null;

  function connect() {
    if (closed) return;

    const url = `${API_BASE}/crawlers/${crawlerId}/status/stream`;
    const eventSource = new EventSource(url);
    currentSource = eventSource;

    eventSource.onmessage = (event) => {
      retryCount = 0;   // Reset on successful message
      if (event.lastEventId) {
        lastEventId = event.lastEventId;
      }
      try {
        const data = JSON.parse(event.data);
        onData?.(data);
        if (data.status === 'success' || data.status === 'failed') {
          cleanup();
          onComplete?.(data);
        }
      } catch (e) {
        onError?.(e);
      }
    };

    eventSource.onerror = () => {
      eventSource.close();
      currentSource = null;

      if (closed) return;

      if (retryCount < MAX_RETRIES) {
        retryCount++;
        const delay = Math.min(
          BASE_DELAY_MS * Math.pow(2, retryCount - 1) + Math.random() * 500,
          MAX_DELAY_MS,
        );
        retryTimer = setTimeout(connect, delay);
      } else {
        onError?.(new Error('SSE connection failed after ' + MAX_RETRIES + ' retries'));
      }
    };
  }

  function cleanup() {
    closed = true;
    if (retryTimer) {
      clearTimeout(retryTimer);
      retryTimer = null;
    }
    if (currentSource) {
      currentSource.close();
      currentSource = null;
    }
  }

  connect();
  return { close: cleanup };
}

export const api = {
  // 크롤러 목록
  getCrawlers: () => fetchWithTimeout(`${API_BASE}/crawlers`).then(r => r.json()),
  // 크롤러 실행
  runCrawler: (id) => fetchWithTimeout(`${API_BASE}/crawlers/${id}/run`, { method: 'POST' }).then(r => r.json()),
  // 크롤러 상태 — ETag 기반 캐시로 변경 없으면 304 반환
  getCrawlerStatus: (id) => fetchWithETag(`${API_BASE}/crawlers/${id}/status`),
  // 크롤러 상태 SSE 구독
  subscribeCrawlerStatus,
  // 크롤러 토글
  toggleCrawler: (id, status) => fetchWithTimeout(`${API_BASE}/crawlers/${id}/toggle`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status }),
  }).then(r => r.json()),
  // 크롤러 벌크 실행
  bulkRunCrawlers: (ids) => fetchWithTimeout(`${API_BASE}/crawlers/bulk-run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ crawler_ids: ids }),
  }).then(r => r.json()),
  // 크롤러 설정
  getCrawlerSettings: (id) => fetchWithTimeout(`${API_BASE}/crawlers/${id}/settings`).then(r => r.json()),
  updateCrawlerSettings: (id, data) => fetchWithTimeout(`${API_BASE}/crawlers/${id}/settings`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }).then(r => r.json()),
  // 대시보드 통계
  getDashboardStats: (params = {}) => fetchWithTimeout(`${API_BASE}/dashboard/stats?${new URLSearchParams(params)}`).then(r => r.json()),
  // 로그
  getLogs: (params) => fetchWithTimeout(`${API_BASE}/logs?${new URLSearchParams(params)}`).then(r => r.json()),
  // 로그 CSV 내보내기
  exportLogsCsv: (params = {}) => fetchWithTimeout(`${API_BASE}/logs/export?${new URLSearchParams(params)}`).then(r => r.blob()),
  // 스케줄
  getSchedules: () => fetchWithTimeout(`${API_BASE}/schedules`).then(r => r.json()),
  createSchedule: (data) => fetchWithTimeout(`${API_BASE}/schedules`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }).then(r => r.json()),
  updateSchedule: (name, data) => fetchWithTimeout(`${API_BASE}/schedules/${name}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }).then(r => r.json()),
  deleteSchedule: (name) => fetchWithTimeout(`${API_BASE}/schedules/${name}`, { method: 'DELETE' }),
  toggleSchedule: (name, enabled) => fetchWithTimeout(`${API_BASE}/schedules/${name}/toggle`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled }),
  }).then(r => r.json()),
  runScheduleNow: (name) => fetchWithTimeout(`${API_BASE}/schedules/${name}/run-now`, {
    method: 'POST',
  }).then(r => r.json()),
  // 플러그인
  getPlugins: () => fetchWithTimeout(`${API_BASE}/plugins`).then(r => r.json()),
  togglePlugin: (id, status) => fetchWithTimeout(`${API_BASE}/plugins/${id}/status`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status }),
  }).then(r => r.json()),
  updatePluginSettings: (id, data) => fetchWithTimeout(`${API_BASE}/plugins/${id}/settings`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }).then(r => r.json()),
  // 대기열
  getIngestions: (params) => fetchWithTimeout(`${API_BASE}/ingestions?${new URLSearchParams(params)}`).then(r => r.json()),
  getIngestion: (id) => fetchWithTimeout(`${API_BASE}/ingestions/${id}`).then(r => r.json()),
  reviewIngestion: (id, data) => fetchWithTimeout(`${API_BASE}/ingestions/${id}/crawler-review`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }).then(r => r.json()),
  updateIngestionRow: (id, index, data) => fetchWithTimeout(`${API_BASE}/ingestions/${id}/items/${index}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }).then(r => r.json()),
  removeIngestionRow: (id, index, notes) => {
    const qs = notes ? `?${new URLSearchParams({ notes })}` : '';
    return fetchWithTimeout(`${API_BASE}/ingestions/${id}/items/${index}${qs}`, {
      method: 'DELETE',
    }).then(r => r.json());
  },
  cleanupIngestions: (data) => fetchWithTimeout(`${API_BASE}/ingestions/cleanup`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }).then(r => r.json()),
  deleteIngestion: (id) => fetchWithTimeout(`${API_BASE}/ingestions/${id}`, {
    method: 'DELETE',
  }).then(r => r.json()),
  forwardRawRecordsToAi: (data) => fetchWithTimeout(`${API_BASE}/ai-export/raw-records/label`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
    timeoutMs: 120000,
  }).then(r => r.json()),
  getAiProviders: (aiAdminBaseUrl) => fetchWithTimeout(
    `${API_BASE}/ai-export/providers?${new URLSearchParams({ ai_admin_base_url: aiAdminBaseUrl })}`,
  ).then(r => r.json()),
};
