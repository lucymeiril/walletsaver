import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import IntegrityPage from './IntegrityPage';

vi.mock('../../api/client', () => ({
  api: {
    getIntegritySummary: vi.fn(),
    recheckIntegrity: vi.fn(),
    repairIntegrity: vi.fn(),
  },
}));

import { api } from '../../api/client';

const SAMPLE_REPORT = {
  generated_at: '2024-01-02T03:04:05',
  overall_severity: 'warning',
  issue_total: 7,
  checks: [
    {
      name: 'products_without_category',
      severity: 'warning',
      count: 5,
      null_category_count: 3,
      orphan_category_count: 2,
      samples: [{ product_id: 1, category_id: 99 }],
    },
    {
      name: 'invalid_product_prices',
      severity: 'ok',
      count: 0,
      by_table: { baseline_prices: 0, discount_history: 0, hotdeal_prices: 0 },
      samples: [],
    },
    {
      name: 'projection_health',
      severity: 'not_configured',
      count: 0,
      message: 'projection registry not configured',
    },
    {
      name: 'dlq_summary',
      severity: 'not_configured',
      count: 0,
      message: 'DLQ backend not configured',
    },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  api.getIntegritySummary.mockResolvedValue(SAMPLE_REPORT);
  api.recheckIntegrity.mockResolvedValue(SAMPLE_REPORT);
  api.repairIntegrity.mockResolvedValue({
    action: 'integrity.repair',
    check: 'products_without_category',
    status: 'not_implemented',
    message: '수동 복구 루틴이 아직 구성되지 않았습니다.',
  });
});

describe('IntegrityPage', () => {
  it('loads summary on mount and renders checks', async () => {
    render(<IntegrityPage />);
    await waitFor(() => expect(api.getIntegritySummary).toHaveBeenCalled());
    expect(await screen.findByText('카테고리 누락 상품')).toBeTruthy();
    expect(screen.getByText('유효하지 않은 가격')).toBeTruthy();
    // not_configured rendered as 미구성 (not as 정상)
    const notConfBadges = screen.getAllByText('미구성');
    expect(notConfBadges.length).toBeGreaterThanOrEqual(2);
  });

  it('calls recheck for all when 전체 재검사 clicked', async () => {
    render(<IntegrityPage />);
    await waitFor(() => expect(api.getIntegritySummary).toHaveBeenCalled());
    fireEvent.click(screen.getByTitle('전체 재검사'));
    await waitFor(() => expect(api.recheckIntegrity).toHaveBeenCalledWith(null, expect.anything()));
  });

  it('repair button stays disabled until confirm string matches', async () => {
    render(<IntegrityPage />);
    await screen.findByText('카테고리 누락 상품');

    const inputs = screen.getAllByPlaceholderText(/REPAIR_/);
    const firstInput = inputs[0];
    const repairBtns = screen.getAllByTitle(/복구 실행/);
    const firstBtn = repairBtns[0];

    expect(firstBtn.disabled).toBe(true);
    fireEvent.change(firstInput, { target: { value: 'wrong' } });
    expect(firstBtn.disabled).toBe(true);
    fireEvent.change(firstInput, { target: { value: 'REPAIR_PRODUCTS_WITHOUT_CATEGORY' } });
    expect(firstBtn.disabled).toBe(false);

    fireEvent.click(firstBtn);
    await waitFor(() => expect(api.repairIntegrity).toHaveBeenCalledWith(
      'products_without_category',
      'REPAIR_PRODUCTS_WITHOUT_CATEGORY',
      expect.anything(),
    ));
    expect(await screen.findByText(/not_implemented/)).toBeTruthy();
  });

  it('disables repair input for not_configured checks', async () => {
    render(<IntegrityPage />);
    await screen.findByText('프로젝션 상태');

    const placeholders = screen.getAllByPlaceholderText('미구성 검사 — 복구 사용 불가');
    expect(placeholders.length).toBe(2);
    placeholders.forEach((el) => expect(el.disabled).toBe(true));
  });
});
