import { fireEvent, render, screen, waitFor, cleanup } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ProductDetailModal from './ProductDetailModal';
import { api } from '../services/api';
import useStore from '../stores/appStore';
import useCartStore from '../stores/cartStore';

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
  discount_rate: 25,
  has_discount_metadata: true,
  unit: '202g',
  standard_unit_price: 1480.2,
  standard_unit: '100g',
};

describe('ProductDetailModal public catalog rendering', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    useStore.setState({ isLoggedIn: true, favorites: [], toasts: [], _toastSeq: 0 });
    useCartStore.setState({ items: [] });
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
    expect(screen.getAllByText('1,480원/100g').length).toBeGreaterThan(0);
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
    expect(screen.getAllByText('온라인').length).toBeGreaterThan(0);
    expect(screen.queryByText('키워드')).not.toBeInTheDocument();
  });

  it('renders mart products with full image/info and normalized wishlist/cart actions', async () => {
    render(<ProductDetailModal product={{
      id: 'emart-sale-apple',
      type: 'mart',
      name: '행사 사과',
      sale: 9900,
      orig: 12900,
      img: 'https://example.com/apple.png',
      martName: '이마트',
      martKey: 'emart',
      category: '과일',
      unit: '1.5kg',
      keywords: ['사과', '과일'],
    }} onClose={vi.fn()} mode="preview" />);

    expect(screen.getByRole('dialog', { name: '행사 사과' })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: '행사 사과' })).toBeInTheDocument();
    expect(screen.getAllByText('이마트').length).toBeGreaterThan(0);
    expect(screen.getAllByText('1.5kg', { exact: false }).length).toBeGreaterThan(0);
    expect(screen.getByText('사과')).toBeInTheDocument();

    fireEvent.click(screen.getByText('찜하기'));
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/api/wishlist', expect.objectContaining({
        item_name: '행사 사과',
        item_image_url: 'https://example.com/apple.png',
        store_name: '이마트',
      }));
    });
    expect(api.post.mock.calls.at(-1)[1]).not.toHaveProperty('product_id');

    fireEvent.click(screen.getByText('장바구니 담기'));
    expect(useCartStore.getState().items[0]).toEqual(expect.objectContaining({
      name: '행사 사과',
      price: 9900,
      store_name: '이마트',
    }));
  });

  it('renders rich decision support for real-shaped hotdeal preview data', () => {
    render(<ProductDetailModal product={{
      id: 'hotdeal-ramen-1',
      type: 'hotdeal',
      title: '농심 신라면 20봉 핫딜',
      price: 12900,
      original_price: 18900,
      discount_rate: 32,
      has_discount_metadata: true,
      source: '뽐뿌',
      source_url: 'https://example.com/deal',
      unit: '20입',
      period: '오늘 23:59까지',
      hotVotes: 42,
      coldVotes: 3,
      comments: 18,
      price_history: [
        { date: '2026-04-01', price: 15900, has_discount_metadata: true },
        { date: '2026-04-12', price: 14500, has_discount_metadata: true },
        { date: '2026-04-30', price: 12900, has_discount_metadata: true },
      ],
      comparable_offers: [
        { source_name: '쿠팡', price: 13900, title: '신라면 20봉' },
        { source_name: '이마트', price: 14900, title: '신라면 멀티팩' },
      ],
    }} onClose={vi.fn()} mode="preview" />);

    expect(screen.getByText('구매 판단', { exact: false })).toBeInTheDocument();
    expect(screen.getByText('역대 최저가')).toBeInTheDocument();
    expect(screen.getByText('가격 이력 요약', { exact: false })).toBeInTheDocument();
    expect(screen.getByText('마지막 할인 04-30')).toBeInTheDocument();
    expect(screen.getByText('비교 가능한 판매처', { exact: false })).toBeInTheDocument();
    expect(screen.getByText('쿠팡')).toBeInTheDocument();
    expect(screen.getByText('커뮤니티 반응 🔥42 / ❄️3')).toBeInTheDocument();
    expect(screen.getByText('댓글 18개')).toBeInTheDocument();
  });

  it('renders price-only observations without fake discount UI', () => {
    render(<ProductDetailModal product={{
      id: 'emart-tofu-observation',
      type: 'mart',
      name: '국산콩 두부 300g',
      sale: 1980,
      orig: null,
      martName: '이마트',
      martKey: 'emart',
      unit: '300g',
      price_observation_only: true,
      has_discount_metadata: false,
      record_label: '관측 가격',
      claim_status_label: '할인 여부 미확인',
      price_history: [
        {
          date: '2026-05-01',
          price: 2200,
          price_observation_only: true,
          has_discount_metadata: false,
        },
        {
          date: '2026-05-05',
          price: 1980,
          price_observation_only: true,
          has_discount_metadata: false,
        },
      ],
    }} onClose={vi.fn()} mode="preview" />);

    expect(screen.getByText('관측 가격')).toBeInTheDocument();
    expect(screen.getByText('할인 여부 미확인')).toBeInTheDocument();
    expect(screen.queryByText(/절약/)).not.toBeInTheDocument();
    expect(screen.queryByText('마지막 할인 05-05')).not.toBeInTheDocument();
    expect(screen.getByText('저가 관측')).toBeInTheDocument();
  });
});
