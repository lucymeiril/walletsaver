import { beforeEach, afterEach, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import MatchingTablePage from './MatchingTablePage';
import { api } from '../../api/client';
vi.mock('../../api/client', () => ({ api: {
  getClassifiedMappings: vi.fn(), getMatchingRules: vi.fn(), getMatchingRuleStats: vi.fn(),
} }));
beforeEach(() => {
  vi.clearAllMocks();
  api.getClassifiedMappings.mockResolvedValue({ items: [
    { match_key: 'actual-key', public_product_id: 'prod-opaque', public_variant_id: 'var-opaque',
      unified_category_id: 'food.grapes', canonical_name: '포도', variant_name: '원문 규격',
      display_unit: '씨없는블랙포도3.6kg내외', package_quantity: null, package_unit: null, bundle_count: 1,
      source: 'reviewed', confidence: 0.9 },
    { match_key: 'unknown-key', public_product_id: 'prod-unknown', public_variant_id: 'var-unknown',
      unified_category_id: 'food.grapes', package_quantity: null, package_unit: null, bundle_count: 1 },
  ], total: 6371, total_pages: 255 });
  api.getMatchingRules.mockResolvedValue({ items: [], total: 0, total_pages: 1 });
  api.getMatchingRuleStats.mockResolvedValue({ total: 0 });
});
afterEach(cleanup);
it('defaults to real normalized mappings with read-only IDs/specification and separates legacy rules', async () => {
  render(<MatchingTablePage />);
  expect(await screen.findByText('actual-key')).toBeTruthy();
  expect(screen.getByText('prod-opaque')).toBeTruthy();
  expect(screen.getByText('var-opaque')).toBeTruthy();
  expect(screen.getByText('var-opaque').closest('td').textContent).toContain('씨없는블랙포도3.6kg내외');
  expect(screen.queryByText(/미확인 ×1/)).toBeNull();
  expect(screen.getByText('총 6,371개')).toBeTruthy();
  expect(screen.queryByRole('button', { name: '추가' })).toBeNull();
  expect(screen.queryByLabelText('패턴 값')).toBeNull();
  expect(api.getMatchingRules).not.toHaveBeenCalled();
  fireEvent.change(screen.getByPlaceholderText('정규화 키/상품/규격/통합 분류 검색'), { target: { value: '포도' } });
  await waitFor(() => expect(api.getClassifiedMappings).toHaveBeenLastCalledWith({ page: 1, per_page: 25, q: '포도' }, expect.any(Object)));
  fireEvent.change(screen.getByLabelText('매칭 체계'), { target: { value: 'legacy' } });
  await waitFor(() => expect(api.getMatchingRules).toHaveBeenCalled());
  expect(screen.getByLabelText('패턴 값')).toBeTruthy();
  expect(screen.getByRole('button', { name: '추가' })).toBeTruthy();
});
