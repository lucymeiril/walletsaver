import { getApiKey, logout as authLogout } from '../stores/authStore';

const API_BASE = '/api';
const FETCH_TIMEOUT_MS = 30000;

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

const CRAWLER_DISPLAY_NAMES = {
  emart: '이마트',
  homeplus: '홈플러스',
  lottemart: '롯데마트',
  costco: '코스트코',
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

function injectAuth(headers = {}) {
  const key = getApiKey();
  if (!key) return headers;
  return { ...headers, 'X-API-Key': key };
}

async function fetchWithTimeout(url, options = {}) {
  const { timeoutMs = FETCH_TIMEOUT_MS, signal: externalSignal, ...fetchOptions } = options;
  fetchOptions.headers = injectAuth(fetchOptions.headers);

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

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
    throw err;
  } finally {
    clearTimeout(timeoutId);
  }
}

const _etagCache = new Map();

async function fetchWithETag(url, options = {}) {
  const cached = _etagCache.get(url);
  const headers = injectAuth({ ...options.headers });
  if (cached?.etag) headers['If-None-Match'] = cached.etag;

  const resp = await fetch(url, { ...options, headers });
  if (resp.status === 304 && cached?.data) return cached.data;

  if (resp.status === 401 || resp.status === 403) {
    authLogout();
    throw new Error(getHttpErrorMessage(resp.status));
  }
  if (!resp.ok) throw new Error(getHttpErrorMessage(resp.status));

  const data = await resp.json();
  const etag = resp.headers.get('etag');
  if (etag) _etagCache.set(url, { etag, data });
  return data;
}

function subscribeCrawlerStatus(crawlerId, { onData, onError, onComplete }) {
  const MAX_RETRIES = 5;
  const BASE_DELAY_MS = 1000;
  const MAX_DELAY_MS = 10000;

  let retryCount = 0;
  let currentSource = null;
  let closed = false;
  let retryTimer = null;

  function connect() {
    if (closed) return;

    const url = `${API_BASE}/crawlers/${crawlerId}/status/stream`;
    const eventSource = new EventSource(url);
    currentSource = eventSource;

    eventSource.onmessage = (event) => {
      retryCount = 0;
      try {
        const data = JSON.parse(event.data);
        onData?.(data);
        if (['success', 'failed', 'partial_failure'].includes(data.status)) {
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

function toScheduleView(row) {
  const pluginName = row.plugin_name || '';
  const cron = row.cron_expr || '';
  return {
    id: row.id,
    crawlerId: pluginName,
    crawlerName: CRAWLER_DISPLAY_NAMES[pluginName] || pluginName,
    cron,
    description: '',
    nextRun: null,
    nextRuns: [],
    enabled: Boolean(row.enabled),
  };
}

async function fetchScheduleRows() {
  const data = await fetchWithTimeout(`${API_BASE}/v1/schedules`).then(r => r.json());
  return Array.isArray(data) ? data : data.schedules ?? [];
}

async function resolveSchedule(identifier) {
  const rows = await fetchScheduleRows();
  const row = rows.find(
    (item) => item.id === identifier || item.plugin_name === identifier,
  );
  if (!row) throw new Error('스케줄을 찾을 수 없습니다.');
  return row;
}

export const api = {
  getCrawlers: () => fetchWithTimeout(`${API_BASE}/crawlers`).then(r => r.json()),
  runCrawler: (id) => fetchWithTimeout(`${API_BASE}/crawlers/${id}/run`, { method: 'POST', timeoutMs: 120000 }).then(r => r.json()),
  retryWafBlocked: (id) => fetchWithTimeout(`${API_BASE}/crawlers/${id}/retry-waf-blocked`, { method: 'POST', timeoutMs: 120000 }).then(r => r.json()),
  getLotteCategories: (refresh = false) => fetchWithTimeout(`${API_BASE}/crawlers/lottemart/categories?refresh=${refresh ? 'true' : 'false'}`, { timeoutMs: 120000 }).then(r => r.json()),
  runLotteCategory: (category) => fetchWithTimeout(`${API_BASE}/crawlers/lottemart/run-category`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url: category.url, query: category.query, category_hint: category.category_hint }),
    timeoutMs: 120000,
  }).then(r => r.json()),
  getCrawlerStatus: (id) => fetchWithETag(`${API_BASE}/crawlers/${id}/status`),
  subscribeCrawlerStatus,
  toggleCrawler: (id, status) => fetchWithTimeout(`${API_BASE}/crawlers/${id}/toggle`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status }),
  }).then(r => r.json()),
  bulkRunCrawlers: (ids) => fetchWithTimeout(`${API_BASE}/crawlers/bulk-run`, {
    method: 'POST',
    timeoutMs: 120000,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ crawler_ids: ids }),
  }).then(r => r.json()),
  getCrawlerSettings: (id) => fetchWithTimeout(`${API_BASE}/crawlers/${id}/settings`).then(r => r.json()),
  updateCrawlerSettings: (id, data) => fetchWithTimeout(`${API_BASE}/crawlers/${id}/settings`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }).then(r => r.json()),
  getDashboardStats: (params = {}) => fetchWithTimeout(`${API_BASE}/dashboard/stats?${new URLSearchParams(params)}`).then(r => r.json()),
  getLogs: (params) => fetchWithTimeout(`${API_BASE}/logs?${new URLSearchParams(params)}`).then(r => r.json()),
  exportLogsCsv: (params = {}) => fetchWithTimeout(`${API_BASE}/logs/export?${new URLSearchParams(params)}`).then(r => r.blob()),

  // Schedule page compatibility methods, backed only by the canonical /api/v1 control plane.
  getSchedules: async () => {
    const rows = await fetchScheduleRows();
    return { schedules: rows.map(toScheduleView) };
  },
  createSchedule: async (data) => {
    const row = await fetchWithTimeout(`${API_BASE}/v1/schedules`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        plugin_name: data.crawler_name,
        cron_expr: data.cron,
        enabled: true,
      }),
    }).then(r => r.json());
    return toScheduleView(row);
  },
  updateSchedule: async (identifier, data) => {
    const current = await resolveSchedule(identifier);
    const row = await fetchWithTimeout(`${API_BASE}/v1/schedules/${current.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cron_expr: data.cron }),
    }).then(r => r.json());
    return toScheduleView(row);
  },
  deleteSchedule: async (identifier) => {
    const current = await resolveSchedule(identifier);
    return fetchWithTimeout(`${API_BASE}/v1/schedules/${current.id}`, { method: 'DELETE' }).then(r => r.json());
  },
  toggleSchedule: async (identifier, enabled) => {
    const current = await resolveSchedule(identifier);
    const row = await fetchWithTimeout(`${API_BASE}/v1/schedules/${current.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    }).then(r => r.json());
    return toScheduleView(row);
  },
  runScheduleNow: (pluginName) => fetchWithTimeout(`${API_BASE}/v1/runs/trigger`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ plugin_name: pluginName }),
    timeoutMs: 120000,
  }).then(r => r.json()),

  getIngestions: (params = {}) => fetchWithTimeout(`${API_BASE}/ingestions?${new URLSearchParams(params)}`).then(r => r.json()),
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

  getOrchestratorPlugins: () => fetchWithTimeout(`${API_BASE}/v1/plugins`).then(r => r.json()),
  getOrchestratorSchedules: () => fetchWithTimeout(`${API_BASE}/v1/schedules`).then(r => r.json()),
  createOrchestratorSchedule: (data) => fetchWithTimeout(`${API_BASE}/v1/schedules`, {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data),
  }).then(r => r.json()),
  updateOrchestratorSchedule: (id, data) => fetchWithTimeout(`${API_BASE}/v1/schedules/${id}`, {
    method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data),
  }).then(r => r.json()),
  deleteOrchestratorSchedule: (id) => fetchWithTimeout(`${API_BASE}/v1/schedules/${id}`, { method: 'DELETE' }).then(r => r.json()),
  triggerRun: (data) => fetchWithTimeout(`${API_BASE}/v1/runs/trigger`, {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data),
  }).then(r => r.json()),
  runAdHoc: (data) => fetchWithTimeout(`${API_BASE}/v1/runs/ad-hoc`, {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data),
    timeoutMs: 120000,
  }).then(r => r.json()),
  getRuns: (params = {}) => fetchWithTimeout(`${API_BASE}/v1/runs?${new URLSearchParams(params)}`).then(r => r.json()),
  getRunLogs: (runId) => fetchWithTimeout(`${API_BASE}/v1/runs/${runId}/logs`).then(r => r.json()),
  retryRun: (runId) => fetchWithTimeout(`${API_BASE}/v1/runs/${runId}/retry`, { method: 'POST' }).then(r => r.json()),
  retryLastFailed: (pluginName) =>
    fetchWithTimeout(`${API_BASE}/v1/runs/retry-last-failed/${encodeURIComponent(pluginName)}`, { method: 'POST' })
      .then(async (r) => {
        const text = await r.text();
        const data = text ? JSON.parse(text) : {};
        if (!r.ok) {
          const err = new Error(data.detail || `재시도 실패 (status=${r.status})`);
          err.status = r.status;
          throw err;
        }
        return data;
      }),

  getRecentExports: (limit = 20) =>
    fetchWithTimeout(`${API_BASE}/export/raw-batch/recent?limit=${limit}`).then(r => r.json()),
  triggerRawBatchExport: (payload) =>
    fetchWithTimeout(`${API_BASE}/export/raw-batch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).then(r => r.json()),
  getRawBatchExportDownloadUrl: (exportId) =>
    `${API_BASE}/export/raw-batch/${encodeURIComponent(exportId)}/download`,
};
