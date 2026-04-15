import { api } from './api';

export const authService = {
  async login(email, password) {
    const res = await api.post('/api/auth/login', { email, password });
    const data = await res.json();
    // Server also sets httpOnly cookies; keep in-memory token for Bearer header
    api.setToken(data.access_token);
    sessionStorage.setItem('refresh_token', data.refresh_token);
    return data;
  },

  async register(userData) {
    const res = await api.post('/api/auth/register', userData);
    const data = await res.json();
    api.setToken(data.access_token);
    sessionStorage.setItem('refresh_token', data.refresh_token);
    return data;
  },

  async logout() {
    try {
      await api.post('/api/auth/logout');
    } finally {
      api.clearToken();
      sessionStorage.removeItem('refresh_token');
    }
  },

  async getProfile() {
    const res = await api.get('/api/auth/me');
    return res.json();
  },

  async updateProfile(data) {
    const res = await api.put('/api/auth/me', data);
    return res.json();
  },
};
