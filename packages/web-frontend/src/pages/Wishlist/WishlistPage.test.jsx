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

  it('keeps selected receipt and observed money visible while unknown eligibility holds current price and cart action', async () => {
    const context = { display_unit: '65g×6', total_price: 6980, total_quantity: 390, quantity_unit: 'g',
      received_package_count: 1, minimum_quantity: 2, membership_required: true, coupon_required: null, current_eligible: true };
    api.getJson.mockResolvedValue({ data: [{ id: 12, product_id: 'prod-ramen', item_name: '참깨라면',
      variant_id: 'var-six', listing_id: 'listing-six', offer_id: 'offer-saved', current_offer_id: 'offer-new',
      price_at_add: 6980, current_price: null, quoted_price: 6980, item_price: 15490, target_price: 8000,
      saved_receipt_valid: true, offer_context: context, current_offer_context: context, comparison_reason: 'membership_or_coupon_unverified' }] });
    render(<MemoryRouter><WishlistPage /></MemoryRouter>);
    await screen.findByText('참깨라면');
    expect(screen.getByText('65g×6')).toBeInTheDocument();
    expect(screen.getAllByText(/수령 390g.*최소 구매 2.*회원 필요/)).toHaveLength(2);
    expect(screen.getByText('판정 보류 · 회원·쿠폰 이용 조건 미확인')).toBeInTheDocument();
    expect(screen.getByText('선택한 판매처 관측 가격 · 6,980원')).toBeInTheDocument();
    expect(screen.queryByText('15,490원')).not.toBeInTheDocument();
    expect(screen.queryByText(/목표 달성/)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '담기' })).toBeDisabled();
    expect(screen.queryByText('0원')).not.toBeInTheDocument();
  });

  it('carts only the eligible latest same-listing tuple and actual transaction amount, never the saved event or product-wide price', async () => {
    const context = { display_unit: '65g×6', total_price: 6900, total_quantity: 390, quantity_unit: 'g',
      received_package_count: 1, minimum_quantity: 1, membership_required: false, coupon_required: false, current_eligible: true };
    api.getJson.mockResolvedValue({ data: [{ id: 12, product_id: 'prod-ramen', item_name: '참깨라면',
      variant_id: 'var-six', listing_id: 'listing-six', offer_id: 'offer-saved', current_offer_id: 'offer-new',
      price_at_add: 6980, current_price: 6900, quoted_price: 6900, item_price: 15490,
      saved_receipt_valid: true, offer_context: context, current_offer_context: context, comparison_reason: null }] });
    const originalAdd = useCartStore.getState().addItem;
    const add = vi.fn().mockResolvedValue({}); useCartStore.setState({ addItem: add });
    try {
      render(<MemoryRouter><WishlistPage /></MemoryRouter>);
      await screen.findByText('참깨라면');
      fireEvent.click(screen.getByRole('button', { name: '담기' }));
      await waitFor(() => expect(add).toHaveBeenCalledWith(expect.objectContaining({ product_id: 'prod-ramen',
        variant_id: 'var-six', listing_id: 'listing-six', offer_id: 'offer-new', item_price: 6900, quantity: 1,
        offer_context: context })));
      expect(useStore.getState().favoriteItems['product:prod-ramen:var-six:listing-six'].offer_id).toBe('offer-saved');
    } finally { useCartStore.setState({ addItem: originalAdd }); }
  });
  it('labels an expired observation as past pricing and holds target and cart despite a lower observed amount', async () => {
    const context = { display_unit: '65g×6', total_price: 5900, total_quantity: 390, quantity_unit: 'g',
      received_package_count: 1, minimum_quantity: 1, membership_required: false, coupon_required: false,
      current_eligible: false, availability_reason: 'expired', valid_to: '2026-09-30', crawled_at: '2026-09-29 12:00:00' };
    api.getJson.mockResolvedValue({ data: [{ id: 12, product_id: 'prod-ramen', item_name: '참깨라면',
      variant_id: 'var-six', listing_id: 'listing-six', offer_id: 'offer-saved', current_offer_id: 'offer-new',
      price_at_add: 6980, current_price: null, quoted_price: 5900, target_price: 6000,
      saved_receipt_valid: true, offer_context: context, current_offer_context: context, comparison_reason: 'quote_unavailable' }] });
    render(<MemoryRouter><WishlistPage /></MemoryRouter>);
    await screen.findByText('참깨라면');
    expect(screen.getByText('판매 기간 종료 · 과거 관측 가격 · 종료 2026-09-30')).toBeInTheDocument();
    expect(screen.getByText('관측 시각 · 2026-09-29 12:00:00')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '담기' })).toBeDisabled();
    expect(screen.queryByText(/목표 달성/)).not.toBeInTheDocument();
  });
  it.each([false, null])('holds saved receipt %s while retaining capacity title and quoted money without silently carting another specification', async (valid) => {
    const context = { display_unit: '2PK (950ml)', total_quantity: 950, quantity_unit: 'ml', received_package_count: 1,
      total_price: 30990, minimum_quantity: 2, membership_required: true, coupon_required: null, current_eligible: true };
    api.getJson.mockResolvedValue({ data: [{ id: 12, product_id: 'prod-bottle', item_name: '보온보냉병',
      variant_id: 'old-variant', listing_id: 'listing-bottle', offer_id: 'saved-offer', current_offer_id: 'new-offer',
      price_at_add: 30990, current_price: 30990, target_price: 30990, quoted_price: 30990, saved_receipt_valid: valid,
      saved_receipt_reason: 'selected_specification_revised', offer_context: context, current_offer_context: context }] });
    render(<MemoryRouter><WishlistPage /></MemoryRouter>);
    await screen.findByText('보온보냉병');
    expect(screen.getByText('2PK (950ml)')).toBeInTheDocument();
    expect(screen.getByText(/규격 확인·다시 선택 필요/)).toBeInTheDocument();
    expect(screen.queryByText(/수령 950ml|수령 패키지 1/)).not.toBeInTheDocument();
    expect(screen.getByText('30,990원')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '담기' })).toBeDisabled();
    expect(screen.queryByText(/목표 달성/)).not.toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
    expect(api.delete).not.toHaveBeenCalled();
  });

});
