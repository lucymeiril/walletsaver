import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../api/client', () => ({
  api: {
    getCrawlers: vi.fn().mockResolvedValue({ crawlers: [] }),
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

describe('registered crawler history read-only section', () => {
  beforeEach(() => { vi.clearAllMocks(); });
  it('finds actual recorded Lotte URL/time when orchestrator has no row without inventing receipt/counts', async () => {
    const source_url = 'https://lottemartzetta.com/products/OS8801114119426/details';
    api.getRuns.mockResolvedValueOnce({ items: [], total: 0 });
    api.getCrawlers.mockResolvedValueOnce({ crawlers: [{ name: 'lottemart', display_name: '롯데마트', recentRuns: [
      { status: 'success', duration: 2.2323403540067375, timestamp: '2026-10-07T18:12:38.211242+00:00', source_url },
    ] }] });
    render(<MemoryRouter><RunHistory /></MemoryRouter>);
    const section = screen.getByRole('region', { name: '등록 크롤러 실행 이력' });
    const row = (await within(section).findByText('롯데마트')).closest('tr');
    expect(row).toHaveTextContent('2026-10-07T18:12:38.211242+00:00');
    expect(row).toHaveTextContent('성공 기록 · 승인 미확인');
    expect(row).toHaveTextContent('발견 미확인 · 유효 미확인 · 저장 미확인');
    expect(row).toHaveTextContent('HIT 미확인 · MISS 미확인');
    expect(within(row).getByRole('link', { name: source_url })).toHaveAttribute('href', source_url);
    expect(within(row).getByRole('link', { name: '데이터 검토' })).toHaveAttribute('href', '/data-review');
    expect(within(row).getByText('미기록')).toBeInTheDocument();
    expect(api.retryRun).not.toHaveBeenCalled();
    expect(api.getRunLogs).not.toHaveBeenCalled();
  });

  it('shows only actually recorded diagnostic counts and pending delivery separately', async () => {
    api.getCrawlers.mockResolvedValueOnce({ crawlers: [{ name: 'lottemart', recentRuns: [{
      run_id: 'stored-original-run', status: 'partial_failure', timestamp: '2026-10-07T18:12:38Z',
      items_found: 2, items_valid: 1, items_saved: 1,
      quality_details: { matching: { hits: 1, misses: 0 }, delivery: { target: 'pending_review', attempted: 1, acknowledged: 1 } },
    }] }] });
    render(<MemoryRouter><RunHistory /></MemoryRouter>);
    const row = (await screen.findByText('stored-original-run')).closest('tr');
    expect(row).toHaveTextContent('발견 2 · 유효 1 · 저장 1');
    expect(row).toHaveTextContent('HIT 1 · MISS 0');
    expect(row).toHaveTextContent('접수 대상 검토 대기 · 시도 1 · 확인 1');
    expect(row).toHaveTextContent('부분 완료');
    expect(api.retryRun).not.toHaveBeenCalled();
  });

  it('keeps registered history visible when the separate orchestrator read fails', async () => {
    api.getRuns.mockRejectedValueOnce(new Error('예약 이력 응답 미확인'));
    api.getCrawlers.mockResolvedValueOnce({ crawlers: [{ name: 'lottemart', recentRuns: [{ status: 'failed', timestamp: 'stored-time' }] }] });
    render(<MemoryRouter><RunHistory /></MemoryRouter>);
    expect(await screen.findByText('예약 이력 응답 미확인')).toBeInTheDocument();
    const section = screen.getByRole('region', { name: '등록 크롤러 실행 이력' });
    expect(await within(section).findByText('stored-time')).toBeInTheDocument();
    expect(api.retryRun).not.toHaveBeenCalled();
  });
});
