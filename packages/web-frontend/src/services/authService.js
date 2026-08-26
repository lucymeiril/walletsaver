import { api, clearApiCache } from './api';

const SESSION_KEY = 'walletsavior-auth-session';
const LEGACY_DEMO_PROFILE_KEY = 'walletsavior-demo-profile';

export const authService = {
  async login(email, password) {
    clearApiCache();
    const res = await api.post('/api/auth/login', { email, password });
    return res.json();
  },

  async register(userData) {
    clearApiCache();
    const res = await api.post('/api/auth/register', userData);
    return res.json();
  },

  markSessionVerified() {
    localStorage.setItem(SESSION_KEY, '1');
    localStorage.removeItem(LEGACY_DEMO_PROFILE_KEY);
  },

  clearLocalSession() {
    localStorage.removeItem(SESSION_KEY);
    localStorage.removeItem(LEGACY_DEMO_PROFILE_KEY);
    clearApiCache();
  },

  hasSessionMarker() {
    return localStorage.getItem(SESSION_KEY) === '1';
  },

  async logout() {
    clearApiCache();
    await api.post('/api/auth/logout');
    this.clearLocalSession();
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
