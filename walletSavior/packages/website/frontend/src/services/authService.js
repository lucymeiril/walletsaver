import { api } from './api';

export const authService = {
  async login(email, password) {
    const res = await api.post('/api/auth/login', { email, password });
    const data = await res.json();
    return data;
  },

  async register(userData) {
    const res = await api.post('/api/auth/register', userData);
    const data = await res.json();
    return data;
  },

  async logout() {
    try {
      await api.post('/api/auth/logout');
    } catch {
      // ignore — cookies cleared server-side
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
