import { api } from './api';

export const authService = {
  async login(email, password) {
    const res = await api.post('/api/auth/login', { email, password });
    if (!res.ok) throw new Error('로그인에 실패했습니다');
    const data = await res.json();
    api.setToken(data.access_token);
    localStorage.setItem('refresh_token', data.refresh_token);
    return data;
  },

  async register(userData) {
    const res = await api.post('/api/auth/register', userData);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || '회원가입에 실패했습니다');
    }
    return res.json();
  },

  async logout() {
    try {
      await api.post('/api/auth/logout');
    } finally {
      api.clearToken();
      localStorage.removeItem('refresh_token');
    }
  },

  async getProfile() {
    const res = await api.get('/api/auth/me');
    if (!res.ok) throw new Error('프로필 조회에 실패했습니다');
    return res.json();
  },

  async updateProfile(data) {
    const res = await api.put('/api/auth/me', data);
    if (!res.ok) throw new Error('프로필 수정에 실패했습니다');
    return res.json();
  },

  async socialLogin(provider, token) {
    const res = await api.post(`/api/auth/social/${provider}`, { token });
    if (!res.ok) throw new Error('소셜 로그인에 실패했습니다');
    const data = await res.json();
    api.setToken(data.access_token);
    localStorage.setItem('refresh_token', data.refresh_token);
    return data;
  },
};
