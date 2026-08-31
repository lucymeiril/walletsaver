import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api/client', () => ({
  api: {
    getCrawlers: vi.fn(),
    runCrawler: vi.fn(),
    retryWafBlocked: vi.fn(),
    getEmartCategories: vi.fn(),
    runEmartCategory: vi.fn(),
    getLotteCategories: vi.fn().mockResolvedValue({ categories: [] }),
    runLotteCategory: vi.fn(),
    getCrawlerStatus: vi.fn().mockResolvedValue({ status: 'running' }),
    bulkRunCrawlers: vi.fn(),
  },
}));

import { api } from '../api/client';
import Crawlers from '../pages/Crawlers/Crawlers';
import useAdminStore from '../stores/adminStore';

beforeEach(() => {
  vi.clearAllMocks();
  api.getCrawlers.mockResolvedValue({
    crawlers: [{
      name: 'emart',
      display_name: '이마트',
      category: 'mart',
      status: 'active',
      success_rate: 0,
      total_runs: 1,
      recent_runs: [],
    }],
  });
  api.getEmartCategories.mockResolvedValue({
    categories: [
      { category_id: '6000213114', category_hint: '과일' },
      { category_id: '6000213534', category_hint: '우유/유제품' },
    ],
  });
  api.runEmartCategory.mockResolvedValue({
    status: 'running',
    message: '이마트 카테고리 수동 실행 시작: 우유/유제품',
  });
  useAdminStore.setState({
    crawlers: [],
    crawlerFilter: 'all',
    crawlersLoading: false,
    crawlersError: null,
  });
});

describe('Crawlers 페이지 - 이마트 카테고리 수동 실행', () => {
  it('등록된 카테고리만 선택해 한 건 실행한다', async () => {
    render(<Crawlers />);

    fireEvent.click(await screen.findByRole('button', { name: '카테고리 목록' }));
    const select = await screen.findByLabelText('이마트 카테고리 선택');
    fireEvent.change(select, { target: { value: '6000213534' } });
    fireEvent.click(screen.getByRole('button', { name: '선택 카테고리 실행' }));

    await waitFor(() => expect(api.runEmartCategory).toHaveBeenCalledWith({
      category_id: '6000213534',
      category_hint: '우유/유제품',
    }));
    expect(await screen.findByText('이마트 카테고리 수동 실행 시작: 우유/유제품')).toBeTruthy();
  });
});
