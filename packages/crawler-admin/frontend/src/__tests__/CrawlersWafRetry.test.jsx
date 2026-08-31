import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api/client', () => ({
  api: {
    getCrawlers: vi.fn(),
    runCrawler: vi.fn(),
    retryWafBlocked: vi.fn(),
    getLotteCategories: vi.fn().mockResolvedValue({ categories: [] }),
    runLotteCategory: vi.fn(),
    getCrawlerStatus: vi.fn().mockResolvedValue({ status: 'running' }),
    bulkRunCrawlers: vi.fn(),
  },
}));

import Crawlers from '../pages/Crawlers/Crawlers';
import useAdminStore from '../stores/adminStore';
import { api } from '../api/client';

function seed(wafBlockedCount) {
  api.getCrawlers.mockResolvedValue({
    crawlers: [{
      name: 'lottemart', display_name: '롯데마트', category: 'mart',
      status: 'active', success_rate: 0, total_runs: 1, recent_runs: [],
      wafBlockedCount,
      wafBlockedItems: wafBlockedCount ? [{ url: 'https://example.test/category' }] : [],
    }],
  });
  useAdminStore.setState({
    crawlers: [], crawlerFilter: 'all', crawlersLoading: false, crawlersError: null,
  });
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('Crawlers 페이지 - 현재 WAF 보류 재시도 계약', () => {
  it('보류 건수가 있으면 명시적 재시도 API를 호출하고 결과를 표시한다', async () => {
    seed(2);
    api.retryWafBlocked.mockResolvedValue({
      status: 'nothing_to_retry', message: '재시도할 WAF 보류 카테고리가 없습니다.',
    });
    render(<Crawlers />);

    const button = await screen.findByRole('button', { name: 'WAF 재시도 (2)' });
    fireEvent.click(button);

    await waitFor(() => expect(api.retryWafBlocked).toHaveBeenCalledWith('lottemart'));
    expect(await screen.findByText('재시도할 WAF 보류 카테고리가 없습니다.')).toBeTruthy();
  });

  it('보류 건수가 0이면 재시도 버튼을 비활성화한다', async () => {
    seed(0);
    render(<Crawlers />);

    const button = await screen.findByRole('button', { name: 'WAF 재시도 (0)' });
    expect(button.disabled).toBe(true);
    expect(api.retryWafBlocked).not.toHaveBeenCalled();
  });

  it('재시도 요청 실패를 숨기지 않고 운영자에게 표시한다', async () => {
    seed(1);
    api.retryWafBlocked.mockRejectedValue(new Error('network down'));
    render(<Crawlers />);

    fireEvent.click(await screen.findByRole('button', { name: 'WAF 재시도 (1)' }));
    expect(await screen.findByText(/WAF 재시도 실패: network down/)).toBeTruthy();
  });
});
