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
   * 자동완성 — 키워드+상품 2섹션 응답.
   * @param {string} query 검색어 (최소 1글자)
   * @param {number} [limit=10]
   * @param {{ signal?: AbortSignal }} [options]
   * @returns {{ data: { keywords: Array, products: Array, total_keyword_count: number, total_product_count: number } }}
   */
  async autocomplete(query, limit = 10, options = {}) {
    if (!query || query.length < 1) return { data: { keywords: [], products: [], total_keyword_count: 0, total_product_count: 0 } };
    const res = await api.get('/api/search/autocomplete', { q: query, limit }, options);
    return res.json();
  },

  /**
   * 인기 검색어 조회.
   * @param {number} [limit=8]
   */
  async trending(limit = 8) {
    const res = await api.get('/api/search/trending', { limit });
    return res.json();
  },

  /**
   * 카테고리 비교 — 동일 카테고리 상품 비교 데이터.
   * 보관/원산지 같은 속성 필터는 public snapshot에 계약된 필드가 생기기 전까지
   * 보내지 않는다. 화면에만 있는 가짜 필터를 API 계약처럼 취급하지 않기 위함이다.
   * @param {string} categoryId 카테고리 ID (예: livestock.pork.neck)
   * @param {{ sort?: string, page?: number, perPage?: number }} params
   */
  async categoryCompare(categoryId, { sort, page, perPage } = {}) {
    const params = new URLSearchParams();
    if (sort) params.set('sort', sort);
    if (page) params.set('page', page);
    if (perPage) params.set('per_page', perPage);

    const res = await api.get(`/api/products/category/${categoryId}/compare`, Object.fromEntries(params));
    const data = await res.json();
    return data.data || data;
  },

  /**
   * 키워드 검색 횟수 추적.
   * @param {number} keywordId
   */
  async trackKeyword(keywordId) {
    try {
      await api.post(`/api/search/track?keyword_id=${keywordId}`);
    } catch {
      // 트래킹 실패는 무시
    }
  },
};
