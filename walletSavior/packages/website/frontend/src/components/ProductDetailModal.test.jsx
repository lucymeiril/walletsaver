import { render, screen, waitFor, cleanup } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ProductDetailModal from './ProductDetailModal';
import { api } from '../services/api';

vi.mock('../services/api', () => ({
  api: {
    getJson: vi.fn(),
    post: vi.fn(() => Promise.resolve()),
  },
}));

vi.mock('../hooks/useActivityTracker', () => ({
  default: () => ({
    trackView: vi.fn(),
    trackCartAdd: vi.fn(),
    trackWishlistAdd: vi.fn(),
  }),
}));

const approvedPipelineProduct = {
  id: 2,
  canonical_name: '오리온 오징어땅콩',
  category_id: 'snack.nut',
  keywords: ['오징어땅콩', '과자'],
  brand: '오리온',
  source_name: 'emart',
  source_title: '오리온 오징어땅콩 202g 행사',
  price: 2990,
  original_price: 3990,
  unit: '202g',
  standard_unit_price: 1480.2,
  standard_unit: '100g',
};

describe('ProductDetailModal public catalog rendering', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    api.getJson.mockImplementation((path) => {
      if (path.endsWith('/price-compare')) {
        return Promise.resolve({
          data: [
            { source_name: 'emart', price: 2990 },
            { source_name: 'homeplus', price: 3190 },
          ],
        });
      }
      if (path.endsWith('/price-history')) {
        return Promise.resolve({
          data: [
            { date: '2026-04-01', price: 3990 },
            { date: '2026-04-30', price: 2990 },
          ],
        });
      }
      if (path.endsWith('/trust')) {
        return Promise.resolve({
          data: {
            hotdeal_score: 95,
            rationale: '최근 이력 기준 최저가 수준입니다.',
            current_price: 2990,
            historical_low_price: 2990,
            historical_average_price: 3490,
            reference_count: 4,
          },
        });
      }
      return Promise.resolve({ data: null });
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('renders approved pipeline product, offer, unit price, history, and trust data', async () => {
    render(<ProductDetailModal product={approvedPipelineProduct} onClose={vi.fn()} mode="product" />);

    expect(screen.getByRole('dialog', { name: '오리온 오징어땅콩' })).toBeInTheDocument();
    expect(screen.getByText('snack.nut', { exact: false })).toBeInTheDocument();
    expect(screen.getByText('오징어땅콩 202g 행사', { exact: false })).toBeInTheDocument();
    expect(screen.getByText('오징어땅콩')).toBeInTheDocument();
    expect(screen.getByText('과자')).toBeInTheDocument();
    expect(screen.getByText('1,480원/100g')).toBeInTheDocument();
    expect(screen.getByText('3,990원')).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText('최근 이력 기준 최저가 수준입니다.')).toBeInTheDocument();
      expect(screen.getByText('homeplus')).toBeInTheDocument();
      expect(screen.getByText('04-30')).toBeInTheDocument();
    });
  });

  it('handles missing optional public catalog fields gracefully', async () => {
    render(<ProductDetailModal product={{ id: 3, canonical_name: '승인 상품', price: 1000 }} onClose={vi.fn()} mode="preview" />);

    expect(screen.getByRole('dialog', { name: '승인 상품' })).toBeInTheDocument();
    expect(screen.getByText('온라인')).toBeInTheDocument();
    expect(screen.queryByText('키워드')).not.toBeInTheDocument();
  });
});
