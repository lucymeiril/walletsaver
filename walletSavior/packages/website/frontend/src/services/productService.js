import { api } from './api';

export const productService = {
  async search(query, params = {}) {
    const res = await api.get('/api/products/search', { q: query, ...params });
    if (!res.ok) throw new Error('검색에 실패했습니다');
    return res.json();
  },

  async getProduct(productId) {
    const res = await api.get(`/api/products/${productId}`);
    if (!res.ok) throw new Error('상품 조회에 실패했습니다');
    return res.json();
  },

  async getPriceHistory(productId, params = {}) {
    const res = await api.get(`/api/products/${productId}/price-history`, params);
    if (!res.ok) throw new Error('가격 히스토리 조회에 실패했습니다');
    return res.json();
  },

  async getCategories() {
    const res = await api.get('/api/products/categories');
    if (!res.ok) throw new Error('카테고리 조회에 실패했습니다');
    return res.json();
  },

  async compareProducts(productIds) {
    const res = await api.post('/api/products/compare', { product_ids: productIds });
    if (!res.ok) throw new Error('상품 비교에 실패했습니다');
    return res.json();
  },

  async getPopular(params = {}) {
    const res = await api.get('/api/products/popular', params);
    if (!res.ok) throw new Error('인기 상품 조회에 실패했습니다');
    return res.json();
  },
};
