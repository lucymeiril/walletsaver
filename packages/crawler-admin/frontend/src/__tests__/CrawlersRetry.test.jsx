import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api/client', () => ({
  api: {
    getCrawlers: vi.fn(),
    runCrawler: vi.fn(),
    retryLastFailed: vi.fn(),
    subscribeCrawlerStatus: vi.fn(() => { throw new Error('no sse in test'); }),
    getCrawlerStatus: vi.fn().mockResolvedValue({ status: 'running' }),
    bulkRunCrawlers: vi.fn(),
  },
}));

import Crawlers from '../pages/Crawlers/Crawlers';
import useAdminStore from '../stores/adminStore';
import { api } from '../api/client';

function seed(rawCrawlers) {
  api.getCrawlers.mockResolvedValue({ crawlers: rawCrawlers });
  // 초기 zustand 상태 초기화 (이전 테스트 잔재 제거)
  useAdminStore.setState({
    crawlers: [],
    crawlerFilter: 'all',
    crawlersLoading: false,
    crawlersError: null,
  });
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('Crawlers 페이지 - 실패 재시도 퀵버튼', () => {
  it('마지막 실행이 실패가 아니면 재시도 버튼을 노출하지 않는다', async () => {
    seed([{
      name: 'emart',
      display_name: '이마트',
      category: 'mart',
      difficulty: '중',
      status: 'active',
      success_rate: 100,
      total_runs: 1,
      recent_runs: [{ status: 'success', duration: 1.2, timestamp: '2025-01-01T00:00:00Z' }],
    }]);
    render(<Crawlers />);
    await waitFor(() => expect(screen.getByText('이마트')).toBeTruthy());
    expect(screen.queryByTestId('retry-last-failed-emart')).toBeNull();
  });

  it('마지막 실행이 실패면 버튼이 노출되고 클릭 시 retryLastFailed가 호출된다', async () => {
    seed([{
      name: 'homeplus',
      display_name: '홈플러스',
      category: 'mart',
      status: 'active',
      success_rate: 0,
      total_runs: 1,
      recent_runs: [{ status: 'failed', duration: 0, timestamp: '2025-01-01T00:00:00Z' }],
    }]);
    api.retryLastFailed.mockResolvedValue({
      run_id: 'run_new_001', retried_from: 'run_old_999', plugin_name: 'homeplus',
    });
    render(<Crawlers />);
    const btn = await screen.findByTestId('retry-last-failed-homeplus');
    expect(btn).toBeTruthy();
    fireEvent.click(btn);
    await waitFor(() => expect(api.retryLastFailed).toHaveBeenCalledWith('homeplus'));
    expect(await screen.findByText(/run_new_001/)).toBeTruthy();
  });

  it('실패 run이 없을 때 (404) 친절한 메시지를 보여준다', async () => {
    seed([{
      name: 'costco',
      display_name: '코스트코',
      category: 'mart',
      status: 'active',
      success_rate: 0,
      total_runs: 0,
      recent_runs: [{ status: 'failed', duration: 0, timestamp: '2025-01-01T00:00:00Z' }],
    }]);
    const err = new Error('no failed');
    err.status = 404;
    api.retryLastFailed.mockRejectedValue(err);
    render(<Crawlers />);
    const btn = await screen.findByTestId('retry-last-failed-costco');
    fireEvent.click(btn);
    await waitFor(() => expect(api.retryLastFailed).toHaveBeenCalled());
    expect(await screen.findByText(/재시도할 실패 run이 없습니다/)).toBeTruthy();
  });
});
