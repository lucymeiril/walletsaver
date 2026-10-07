import { act, cleanup, render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

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

afterEach(() => { cleanup(); vi.useRealTimers(); });

describe('Crawlers pipeline outcome diagnostics', () => {
  async function finish(data) {
    vi.useFakeTimers();
    seed(0);
    api.runCrawler.mockResolvedValue({ status: 'running' });
    api.getCrawlerStatus.mockResolvedValue(data);
    render(<Crawlers />);
    await act(async () => {});
    fireEvent.click(screen.getByRole('button', { name: '실행', exact: true }));
    await act(async () => {});
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
  }

  it.each(['partial', 'partial_failure'])('finishes %s once with source-stop counts and no approval claim', async status => {
    await finish({ status, items_found: 5, items_valid: 4, items_saved: 2, duration: 1.2,
      errors: ['Source access stopped after HTTP429'], quality_details: {
        delivery: { target: 'pending_review', acknowledged: 2 },
        operator_diagnostics: [{ message: 'Remaining source context not collected.' }],
      } });
    const message = screen.getByText(/부분 완료 — 발견 5건, 유효 4건, 저장 2건/);
    expect(message.parentElement.parentElement.className).toContain('runResultFail');
    expect(screen.getByText('Source access stopped after HTTP429')).toBeInTheDocument();
    expect(screen.getByText('Remaining source context not collected.')).toBeInTheDocument();
    expect(screen.getByText('저장 대상: 검토 대기 접수 · 승인·공개 반영 미확인')).toBeInTheDocument();
    expect(screen.queryByText(/✅ 수집·저장 단계 완료/)).not.toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(api.getCrawlerStatus).toHaveBeenCalledTimes(1);
  });

  it.each([
    [{ status: 'success', items_found: 0, items_valid: 0, items_saved: 0, errors: [] }, /완료 확인 미충족 — 발견 0건, 유효 0건, 저장 0건/],
    [{ status: 'failed', items_found: 3, items_valid: 0, items_saved: 0, errors: ['validation rejected all collected items'] }, /수집·저장 실패 — 발견 3건, 유효 0건, 저장 0건/],
    [{ status: 'success', items_found: 3, items_saved: 2, errors: [] }, /완료 확인 미충족 — 발견 3건, 유효 미확인, 저장 2건/],
  ])('keeps zero or missing acknowledgement diagnostics honest (%s)', async (data, text) => {
    await finish(data);
    const message = screen.getByText(text);
    expect(message.parentElement.parentElement.className).toContain('runResultFail');
    expect(screen.queryByText(/✅ 수집·저장 단계 완료/)).not.toBeInTheDocument();
    expect(screen.getByText('중복 미확인')).toBeInTheDocument();
    if (data.errors.length) expect(screen.getByText(data.errors[0])).toBeInTheDocument();
  });

  it('shows positive validated pending-review acknowledgement without calling it catalog approval', async () => {
    await finish({ status: 'success', items_found: 3, items_valid: 2, items_saved: 2, errors: [],
      quality_details: { delivery: { target: 'pending_review' } } });
    const message = screen.getByText(/✅ 수집·저장 단계 완료 — 발견 3건, 유효 2건, 저장 2건/);
    expect(message.parentElement.parentElement.className).toContain('runResultSuccess');
    expect(screen.getByText('저장 대상: 검토 대기 접수 · 승인·공개 반영 미확인')).toBeInTheDocument();
  });
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

describe('Crawlers bounded Lotte source URL option', () => {
  it('passes one exact URL through the existing store and run client, without a broad run', async () => {
    seed(0);
    api.runCrawler.mockResolvedValue({ status: 'running' });
    render(<Crawlers />);
    const input = await screen.findByLabelText('롯데마트 상품 URL · 한 상품 수집');
    const run = screen.getByRole('button', { name: '상품 URL 한 번 수집' });
    expect(run).toBeDisabled();
    fireEvent.change(input, { target: { value: 'https://example.test/products/OS8801114119426/details' } });
    expect(run).toBeDisabled();
    const source_url = 'https://lottemartzetta.com/products/OS8801114119426/details';
    fireEvent.change(input, { target: { value: source_url } });
    fireEvent.click(run);
    await waitFor(() => expect(api.runCrawler).toHaveBeenCalledWith('lottemart', { source_url }));
    expect(api.runCrawler).toHaveBeenCalledTimes(1);
  });
});
