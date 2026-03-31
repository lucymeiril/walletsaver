const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

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
    const headers = {
      'Content-Type': 'application/json',
      ...options.headers,
    };
    if (this.token) {
      headers['Authorization'] = `Bearer ${this.token}`;
    }

    const response = await fetch(`${this.baseUrl}${path}`, {
      ...options,
      headers,
    });

    if (response.status === 401) {
      const refreshed = await this.refreshToken();
      if (refreshed) {
        headers['Authorization'] = `Bearer ${this.token}`;
        return fetch(`${this.baseUrl}${path}`, { ...options, headers });
      }
      this.clearToken();
      window.location.href = '/login';
    }

    return response;
  }

  async get(path, params) {
    const query = params ? '?' + new URLSearchParams(params).toString() : '';
    return this.request(`${path}${query}`);
  }

  async post(path, data) {
    return this.request(path, { method: 'POST', body: JSON.stringify(data) });
  }

  async put(path, data) {
    return this.request(path, { method: 'PUT', body: JSON.stringify(data) });
  }

  async delete(path) {
    return this.request(path, { method: 'DELETE' });
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
