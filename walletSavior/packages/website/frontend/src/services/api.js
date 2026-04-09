import useStore from '../stores/appStore';
import { isTokenExpiringSoon } from '../utils/tokenUtils';

const API_BASE = import.meta.env.VITE_API_URL || '';
const DEFAULT_TIMEOUT = 15000;

/** 한국어 에러 메시지 맵 */
const ERROR_MESSAGES = {
  network: '네트워크 연결을 확인해주세요.',
  timeout: '요청 시간이 초과되었습니다. 다시 시도해주세요.',
  server: '서버에 문제가 발생했습니다. 잠시 후 다시 시도해주세요.',
  unauthorized: '로그인이 필요합니다.',
  forbidden: '접근 권한이 없습니다.',
  notFound: '요청한 데이터를 찾을 수 없습니다.',
  badRequest: '잘못된 요청입니다.',
  unknown: '알 수 없는 오류가 발생했습니다.',
};

export class ApiError extends Error {
  constructor(message, status, code, data = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.data = data;
  }

  get isNetwork() { return this.code === 'network'; }
  get isTimeout() { return this.code === 'timeout'; }
  get isServer() { return this.status >= 500; }
  get isAuth() { return this.status === 401; }
  get retryable() { return this.isNetwork || this.isTimeout || this.isServer; }
}

function getErrorMessage(status) {
  if (!status) return ERROR_MESSAGES.network;
  if (status === 401) return ERROR_MESSAGES.unauthorized;
  if (status === 403) return ERROR_MESSAGES.forbidden;
  if (status === 404) return ERROR_MESSAGES.notFound;
  if (status === 400) return ERROR_MESSAGES.badRequest;
  if (status >= 500) return ERROR_MESSAGES.server;
  return ERROR_MESSAGES.unknown;
}

// In-flight request deduplication for GET requests
const _inflight = new Map();

// Simple response cache with TTL for GET requests
const _cache = new Map();
const DEFAULT_CACHE_TTL = 30_000; // 30 seconds

function getCached(key) {
  const entry = _cache.get(key);
  if (!entry) return undefined;
  if (Date.now() > entry.expiry) {
    _cache.delete(key);
    return undefined;
  }
  return entry.value;
}

function setCache(key, value, ttl = DEFAULT_CACHE_TTL) {
  _cache.set(key, { value, expiry: Date.now() + ttl });
}

class ApiClient {
  constructor(baseUrl) {
    this.baseUrl = baseUrl;
    this.token = sessionStorage.getItem('access_token');
  }

  setToken(token) {
    if (this.token === token) return;
    this.token = token;
    sessionStorage.setItem('access_token', token);
  }

  clearToken() {
    this.token = null;
    sessionStorage.removeItem('access_token');
  }

  async request(path, options = {}) {
    const { timeout = DEFAULT_TIMEOUT, signal: externalSignal, ...fetchOptions } = options;

    // Proactive token refresh: if token expires within 60 s, refresh before request
    if (this.token && isTokenExpiringSoon(this.token)) {
      await this.refreshToken();
    }

    const headers = {
      'Content-Type': 'application/json',
      ...fetchOptions.headers,
    };
    if (this.token) {
      headers['Authorization'] = `Bearer ${this.token}`;
    }

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeout);

    // Link external signal (e.g. from component abort controller)
    if (externalSignal) {
      if (externalSignal.aborted) {
        clearTimeout(timeoutId);
        controller.abort();
      } else {
        externalSignal.addEventListener('abort', () => controller.abort(), { once: true });
      }
    }

    let response;
    try {
      response = await fetch(`${this.baseUrl}${path}`, {
        ...fetchOptions,
        headers,
        signal: controller.signal,
      });
    } catch (err) {
      clearTimeout(timeoutId);
      if (err.name === 'AbortError') {
        if (externalSignal?.aborted) throw err;
        throw new ApiError(ERROR_MESSAGES.timeout, 0, 'timeout');
      }
      throw new ApiError(ERROR_MESSAGES.network, 0, 'network');
    } finally {
      clearTimeout(timeoutId);
    }

    if (response.status === 401) {
      const refreshed = await this.refreshToken();
      if (refreshed) {
        headers['Authorization'] = `Bearer ${this.token}`;
        try {
          response = await fetch(`${this.baseUrl}${path}`, { ...fetchOptions, headers });
        } catch {
          throw new ApiError(ERROR_MESSAGES.network, 0, 'network');
        }
      } else {
        this.clearToken();
        sessionStorage.removeItem('refresh_token');
        const store = useStore.getState();
        store.logout();
        store.openLoginModal();
        throw new ApiError(ERROR_MESSAGES.unauthorized, 401, 'unauthorized');
      }
    }

    if (!response.ok) {
      let data = null;
      try { data = await response.json(); } catch { /* ignore */ }
      throw new ApiError(
        data?.message || getErrorMessage(response.status),
        response.status,
        response.status >= 500 ? 'server' : 'client',
        data,
      );
    }

    return response;
  }

  async get(path, params, options = {}) {
    const query = params ? '?' + new URLSearchParams(params).toString() : '';
    const fullPath = `${path}${query}`;
    const method = options.method || 'GET';
    const dedupKey = `${method}:${fullPath}`;

    // Dedup identical in-flight GET requests
    if (!_inflight.has(dedupKey)) {
      const promise = this.request(fullPath, options)
        .finally(() => _inflight.delete(dedupKey));
      _inflight.set(dedupKey, promise);
    }

    const res = await _inflight.get(dedupKey);
    return res.clone();
  }

  async post(path, data, options = {}) {
    return this.request(path, { method: 'POST', body: JSON.stringify(data), ...options });
  }

  async put(path, data, options = {}) {
    return this.request(path, { method: 'PUT', body: JSON.stringify(data), ...options });
  }

  async patch(path, data, options = {}) {
    return this.request(path, { method: 'PATCH', body: JSON.stringify(data), ...options });
  }

  async delete(path, options = {}) {
    return this.request(path, { method: 'DELETE', ...options });
  }

  /** JSON 파싱 포함 편의 메서드 (GET — with response caching) */
  async getJson(path, params, options = {}) {
    const query = params ? '?' + new URLSearchParams(params).toString() : '';
    const cacheKey = `${path}${query}`;
    const cached = getCached(cacheKey);
    if (cached !== undefined) return cached;

    const res = await this.get(path, params, options);
    const json = await res.json();
    setCache(cacheKey, json);
    return json;
  }

  async postJson(path, data, options = {}) {
    const res = await this.post(path, data, options);
    return res.json();
  }

  async refreshToken() {
    try {
      const refreshToken = sessionStorage.getItem('refresh_token');
      if (!refreshToken) return false;

      const response = await fetch(`${this.baseUrl}/api/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });

      if (!response.ok) return false;

      const data = await response.json();
      this.setToken(data.access_token);
      sessionStorage.setItem('refresh_token', data.refresh_token);
      return true;
    } catch {
      return false;
    }
  }
}

export const api = new ApiClient(API_BASE);
export { ERROR_MESSAGES };
