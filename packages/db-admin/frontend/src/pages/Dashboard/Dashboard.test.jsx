import { afterEach, it, expect, vi } from 'vitest';
import { render, screen, waitFor, cleanup, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Dashboard from './Dashboard';
import useDbAdminStore from '../../stores/dbAdminStore';
import { api } from '../../api/client';
vi.mock('../../api/client', () => ({ api: { getDashboardStats: vi.fn(), getIngestionStats: vi.fn() } }));
afterEach(cleanup);
it('preserves normalized admin totals and unknown quality/timestamps without fake empty or collection claims', async () => {
  api.getDashboardStats.mockResolvedValue({
    source_scope: 'admin_normalized_catalog', totalProducts: 6308, totalPriceRecords: 9112,
    totalCategories: 1210, totalKeywords: 314, qualityScore: null,
    qualityDetails: { fillRate: null, dupRate: null, noCategoryRate: null },
    lastUpdated: null, freshness: [{ source: '원문 출처', hoursSince: null, status: 'unknown' }],
    changes: { products: null, priceRecords: 0, categories: null, keywords: null },
    offerStates: { active: 8800, pending_review: 312 }, catalogCounts: { products: { total: 6308, active: 6308, inactive: 0 } },
    recentIngestions: [{ id: 1, source: '수신 자료', count: 0, countKind: 'received', activityKind: 'ingestion_receipt', date: '2026-10-04', status: 'pending' }],
  });
  api.getIngestionStats.mockResolvedValue({ pending: 0 });
  useDbAdminStore.setState({ lastFetchedAt: {}, dashboardStats: { totalProducts: 0, totalPriceRecords: 0, recentIngestions: [] } });
  render(<MemoryRouter><Dashboard /></MemoryRouter>);
  expect(screen.queryByText('데이터 없음')).toBeNull();
  await screen.findByText('9,112');
  expect(screen.getByText('6308')).toBeTruthy();
  expect(screen.getByText('1210')).toBeTruthy();
  expect(screen.getByText('통합 분류 수')).toBeTruthy();
  expect(screen.getByText('품질 점수 미산출')).toBeTruthy();
  expect(screen.getByText('관측 시각 미확인')).toBeTruthy();
  expect(screen.getByText('승인 대기')).toBeTruthy();
  expect(screen.getByText('0 · 접수')).toBeTruthy();
  expect(screen.queryByText('0점')).toBeNull();
  expect(screen.queryByText('0%')).toBeNull();
  expect(screen.queryByText('주의 필요')).toBeNull();
  expect(screen.queryByText('방금 전')).toBeNull();
  expect(screen.queryByText('성공')).toBeNull();
  expect(screen.queryByText('데이터 없음')).toBeNull();
  expect(useDbAdminStore.getState().dashboardStats.qualityScore).toBeNull();
  api.getDashboardStats.mockResolvedValue({ totalProducts: 1, totalPriceRecords: 1, totalCategories: 1, totalKeywords: 1, qualityScore: 0 });
  fireEvent.click(screen.getByText('새로고침'));
  await screen.findByText('0점');
  expect(screen.getByText('주의 필요')).toBeTruthy();
});
