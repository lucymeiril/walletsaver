import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

vi.mock('../api/client', () => ({
  api: {
    getCrawlers: vi.fn().mockResolvedValue({ crawlers: [] }),
    runCrawler: vi.fn(),
    getDashboardStats: vi.fn().mockResolvedValue({
      totalCrawlers: 0, activeCrawlers: 0, todayCrawls: 0, successRate: 0,
      statusDistribution: { success: 0, failure: 0, partial: 0 },
      errorTrend: [],
      alerts: [],
      crawlerCards: [],
      freshness: [
        { category: 'emart', label: '이마트', status: 'unknown', lastUpdate: null },
        { category: 'homeplus', label: '홈플러스', status: 'unknown', lastUpdate: null },
        { category: 'lottemart', label: '롯데마트', status: 'unknown', lastUpdate: null },
        { category: 'costco', label: '코스트코', status: 'unknown', lastUpdate: null },
      ],
    }),
  },
}));

import Dashboard from '../pages/Dashboard/Dashboard';
import useAdminStore from '../stores/adminStore';

function wrap(ui) {
  return <BrowserRouter>{ui}</BrowserRouter>;
}

beforeEach(() => {
  vi.clearAllMocks();
  useAdminStore.setState({
    dashboardStats: {
      totalCrawlers: 0, activeCrawlers: 0, todayCrawls: 0, successRate: 0,
      statusDistribution: { success: 0, failure: 0, partial: 0 },
      errorTrend: [],
      alerts: [],
      crawlerCards: [],
      freshness: [
        { category: 'emart', label: '이마트', status: 'unknown', lastUpdate: null },
        { category: 'homeplus', label: '홈플러스', status: 'unknown', lastUpdate: null },
        { category: 'lottemart', label: '롯데마트', status: 'unknown', lastUpdate: null },
        { category: 'costco', label: '코스트코', status: 'unknown', lastUpdate: null },
      ],
    },
    dashboardLoading: false,
    dashboardError: null,
    crawlers: [
      { id: 'emart', name: '이마트', category: 'mart', lastCrawl: '' },
      { id: 'homeplus', name: '홈플러스', category: 'mart', lastCrawl: '' },
    ],
  });
});

describe('Dashboard 빈 상태 → 다음 액션 버튼', () => {
  it('실행 데이터가 없을 때 "첫 크롤 실행하기" CTA를 노출한다', async () => {
    render(wrap(<Dashboard />));
    await waitFor(() => {
      expect(screen.getByText('크롤 실행 이력이 아직 없어요')).toBeInTheDocument();
    });
    const buttons = screen.getAllByRole('button', { name: /첫 크롤 실행하기/ });
    expect(buttons.length).toBeGreaterThanOrEqual(1);
  });

  it('CTA 클릭 시 첫 크롤 실행 모달이 열린다', async () => {
    render(wrap(<Dashboard />));
    const cta = (await screen.findAllByRole('button', { name: /첫 크롤 실행하기/ }))[0];
    fireEvent.click(cta);
    expect(screen.getByRole('dialog', { name: /첫 크롤 실행/ })).toBeInTheDocument();
  });

  it('신선도 카드가 모두 unknown일 때 "아직 적재 전 — 크롤 실행 필요" 안내가 표시된다', async () => {
    render(wrap(<Dashboard />));
    await waitFor(() => {
      const labels = screen.getAllByText(/아직 적재 전/);
      expect(labels.length).toBe(4);
    });
  });
});
