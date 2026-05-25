import { api, clearApiCache } from './api';

export const authService = {
  async login(email, password) {
    clearApiCache();
    const res = await api.post('/api/auth/login', { email, password });
    const data = await res.json();
    return data;
  },

  async register(userData) {
    clearApiCache();
    const res = await api.post('/api/auth/register', userData);
    const data = await res.json();
    return data;
  },

  async logout() {
    clearApiCache();
    try {
      await api.post('/api/auth/logout');
    } catch {
      // ignore — cookies cleared server-side
    }
  },

  async getProfile(options = {}) {
    const res = await api.get('/api/auth/me', undefined, options);
    return res.json();
  },

  async updateProfile(data) {
    const res = await api.put('/api/profile', data);
    const result = await res.json();
    return result.data || result;
  },
};
