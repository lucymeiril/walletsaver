import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
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
import { api } from '../api/client';

afterEach(cleanup);

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
    expect(labels).toContain('수집·저장 완료');
    expect(labels).toContain('실패');
    expect(labels).toContain('부분 완료');
    // 클래스 검증
    const failedBadge = badges.find((b) => b.textContent === '실패');
    expect(failedBadge.className).toMatch(/failed/);
  });

  it('retains partial aliases, source failure reasons, zero acknowledgement and unknown validity', async () => {
    api.getRuns.mockResolvedValueOnce({ items: [
      { run_id: 'source-stop', plugin_name: 'costco', status: 'partial_failure', items_found: 5, items_saved: 2,
        failure_reasons: ['Source access stopped HTTP429'] },
      { run_id: 'zero-ack', plugin_name: 'homeplus', status: 'success', items_found: 4, items_saved: 0 },
      { run_id: 'unknown-ack', plugin_name: 'lottemart', status: 'success' },
    ] });
    render(<MemoryRouter><RunHistory /></MemoryRouter>);
    const partial = (await screen.findByText('source-stop')).closest('tr');
    expect(within(partial).getByText('부분 완료')).toBeInTheDocument();
    expect(partial).toHaveTextContent('Source access stopped HTTP429');
    expect(within(partial).getByText('미확인')).toBeInTheDocument();
    const zero = screen.getByText('zero-ack').closest('tr');
    expect(within(zero).getByText('완료 확인 미충족')).toBeInTheDocument();
    expect(within(zero).getByText('0')).toBeInTheDocument();
    const unknown = screen.getByText('unknown-ack').closest('tr');
    expect(within(unknown).getByText('완료 확인 미충족')).toBeInTheDocument();
    expect(within(unknown).getAllByText('미확인')).toHaveLength(3);
    expect(screen.getByText(/저장 수는 검토 승인·공개 업데이트 수를 뜻하지 않습니다/)).toBeInTheDocument();
    expect(api.retryRun).not.toHaveBeenCalled();
  });
});
