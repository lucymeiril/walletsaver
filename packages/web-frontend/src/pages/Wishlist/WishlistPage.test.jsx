import { fireEvent, render, screen, waitFor, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import WishlistPage from './WishlistPage';
import { api } from '../../services/api';
import useStore from '../../stores/appStore';
import useCartStore from '../../stores/cartStore';

vi.mock('../../services/api', () => ({
  api: {
    getJson: vi.fn(),
    post: vi.fn(() => Promise.resolve()),
    put: vi.fn(() => Promise.resolve()),
    delete: vi.fn(() => Promise.resolve()),
  },
}));

vi.mock('../../hooks/useActivityTracker', () => ({
  default: () => ({
    trackView: vi.fn(),
    trackCartAdd: vi.fn(),
    trackWishlistAdd: vi.fn(),
  }),
}));

describe('WishlistPage rich product detail', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    useStore.setState({
      isLoggedIn: true,
      favorites: [],
      favoriteItems: {},
      toasts: [],
      _toastSeq: 0,
    });
    useCartStore.setState({ items: [] });
    api.getJson.mockResolvedValue({
      data: [
        {
          id: 77,
          local_id: 'external:hotdeal:ramen',
          item_name: '농심 신라면 20봉',
          item_image_url: 'https://example.com/ramen.png',
          store_name: '뽐뿌',
          source_type: 'hotdeal',
          source_url: 'https://example.com/deal',
          price_at_add: 14900,
          current_price: 12900,
          original_price: 18900,
          unit: '20입',
          period: '오늘 23:59까지',
          price_history: [
            { date: '2026-04-01', price: 15900 },
            { date: '2026-04-12', price: 14900 },
            { date: '2026-04-30', price: 12900 },
          ],
          comparable_offers: [
            { source_name: '쿠팡', price: 13900, title: '신라면 20봉' },
          ],
          price_trust: {
            hotdeal_score: 91,
            rationale: '커뮤니티 검증과 최근 이력 기준 매우 좋은 가격입니다.',
            reference_count: 5,
          },
          hotVotes: 31,
          coldVotes: 2,
          comments: 12,
        },
      ],
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('opens the shared decision modal with preserved wishlist metadata', async () => {
    render(<MemoryRouter><WishlistPage /></MemoryRouter>);

    await waitFor(() => expect(screen.getByText('농심 신라면 20봉')).toBeInTheDocument());
    expect(screen.getByText('hotdeal · 20입 · 오늘 23:59까지')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /농심 신라면 20봉/i }));

    expect(await screen.findByRole('dialog', { name: '농심 신라면 20봉' })).toBeInTheDocument();
    expect(screen.getByText('커뮤니티 검증과 최근 이력 기준 매우 좋은 가격입니다.')).toBeInTheDocument();
    expect(screen.getByText('가격 이력 요약', { exact: false })).toBeInTheDocument();
    expect(screen.getByText('쿠팡')).toBeInTheDocument();
    expect(screen.getByText('커뮤니티 반응 🔥31 / ❄️2')).toBeInTheDocument();
  });
});
