import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../api/client', () => ({
  api: {
    getRuns: vi.fn().mockResolvedValue({
      items: [
        {
          run_id: 'run_aaa',
          plugin_name: 'emart',
          status: 'success',
          started_at: '2025-01-01T00:00:00',
          finished_at: '2025-01-01T00:01:00',
          items_found: 10,
          items_saved: 9,
        },
        {
          run_id: 'run_bbb',
          plugin_name: 'homeplus',
          status: 'failed',
          started_at: '2025-01-01T00:02:00',
          finished_at: null,
          items_found: 0,
          items_saved: 0,
        },
        {
          run_id: 'run_ccc',
          plugin_name: 'costco',
          status: 'partial',
          started_at: '2025-01-01T00:03:00',
          finished_at: '2025-01-01T00:04:00',
          items_found: 5,
          items_saved: 3,
        },
      ],
      page: 1,
      page_size: 20,
      total: 3,
    }),
    getOrchestratorPlugins: vi.fn().mockResolvedValue({ plugins: [
      { name: 'emart', display_name: '이마트' },
    ] }),
    getRunLogs: vi.fn(),
    retryRun: vi.fn(),
  },
}));

import RunHistory from '../pages/RunHistory/RunHistory';

describe('RunHistory page', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders Korean table headers', async () => {
    render(<MemoryRouter><RunHistory /></MemoryRouter>);
    expect(await screen.findByText('실행 히스토리')).toBeInTheDocument();
    expect(screen.getByText('실행ID')).toBeInTheDocument();
    expect(screen.getByText('플러그인')).toBeInTheDocument();
    expect(screen.getByText('상태')).toBeInTheDocument();
    expect(screen.getByText('수집건수')).toBeInTheDocument();
    expect(screen.getByText('저장건수')).toBeInTheDocument();
  });

  it('renders status badges for success, partial, failed', async () => {
    const { container } = render(<MemoryRouter><RunHistory /></MemoryRouter>);
    await waitFor(() => expect(container.querySelector('tbody tr')).toBeTruthy());
    const badges = Array.from(container.querySelectorAll('tbody span'));
    const labels = badges.map((b) => b.textContent);
    expect(labels).toContain('성공');
    expect(labels).toContain('실패');
    expect(labels).toContain('부분 성공');
    // 클래스 검증
    const failedBadge = badges.find((b) => b.textContent === '실패');
    expect(failedBadge.className).toMatch(/failed/);
  });
});
