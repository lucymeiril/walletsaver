import useStore from '../stores/appStore';

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

class ApiClient {
  constructor(baseUrl) {
    this.baseUrl = baseUrl;
    this.token = localStorage.getItem('access_token');
  }

  setToken(token) {
    this.token = token;
    localStorage.setItem('access_token', token);
  }

  clearToken() {
    this.token = null;
    localStorage.removeItem('access_token');
  }

  async request(path, options = {}) {
    const { timeout = DEFAULT_TIMEOUT, ...fetchOptions } = options;
    const headers = {
      'Content-Type': 'application/json',
      ...fetchOptions.headers,
    };
    if (this.token) {
      headers['Authorization'] = `Bearer ${this.token}`;
    }

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeout);

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
        useStore.getState().openLoginModal();
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
    return this.request(`${path}${query}`, options);
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

  /** JSON 파싱 포함 편의 메서드 */
  async getJson(path, params, options = {}) {
    const res = await this.get(path, params, options);
    return res.json();
  }

  async postJson(path, data, options = {}) {
    const res = await this.post(path, data, options);
    return res.json();
  }

  async refreshToken() {
    try {
      const refreshToken = localStorage.getItem('refresh_token');
      if (!refreshToken) return false;

      const response = await fetch(`${this.baseUrl}/api/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });

      if (!response.ok) return false;

      const data = await response.json();
      this.setToken(data.access_token);
      localStorage.setItem('refresh_token', data.refresh_token);
      return true;
    } catch {
      return false;
    }
  }
}

export const api = new ApiClient(API_BASE);
export { ERROR_MESSAGES };
