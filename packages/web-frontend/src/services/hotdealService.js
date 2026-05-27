import { api } from './api';

export const hotdealService = {
  async getDeals(params = {}) {
    const res = await api.get('/api/hotdeals', params);
    if (!res.ok) throw new Error('핫딜 조회에 실패했습니다');
    return res.json();
  },

  async getDeal(dealId) {
    const res = await api.get(`/api/hotdeals/${dealId}`);
    if (!res.ok) throw new Error('핫딜 상세 조회에 실패했습니다');
    return res.json();
  },

  async getCategories() {
    const res = await api.get('/api/hotdeals/categories');
    if (!res.ok) throw new Error('핫딜 카테고리 조회에 실패했습니다');
    return res.json();
  },

  async voteDeal(dealId, voteType) {
    const res = await api.post(`/api/hotdeals/${dealId}/vote`, { vote_type: voteType });
    if (!res.ok) throw new Error('투표에 실패했습니다');
    return res.json();
  },

  async reportDeal(dealId, reason) {
    const res = await api.post(`/api/hotdeals/${dealId}/report`, { reason });
    if (!res.ok) throw new Error('신고에 실패했습니다');
    return res.json();
  },
};
