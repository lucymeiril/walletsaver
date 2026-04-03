import { api } from './api';

export const searchService = {
  /**
   * 통합 검색 — 상품/핫딜/커뮤니티/동네 통합 결과.
   * @param {string} query 검색어
   * @param {{ type?: string, sort?: string, page?: number, per_page?: number }} params
   */
  async search(query, params = {}) {
    const res = await api.get('/api/search', { q: query, ...params });
    return res.json();
  },

  /**
   * 자동완성 — 2글자 이상일 때 호출.
   * @param {string} query 검색어 (최소 2글자)
   * @param {number} [limit=10]
   */
  async autocomplete(query, limit = 10) {
    if (!query || query.length < 2) return { data: [] };
    const res = await api.get('/api/search/autocomplete', { q: query, limit });
    return res.json();
  },
};
