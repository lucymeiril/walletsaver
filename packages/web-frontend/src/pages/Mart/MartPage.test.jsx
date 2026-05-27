import { render, screen, waitFor, cleanup } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import MartPage from './MartPage';

vi.mock('../../stores/appStore', () => ({
  default: () => ({
    addToShoppingList: vi.fn(),
    addToast: vi.fn(),
  }),
}));

function fetchJson(data) {
  return Promise.resolve({
    ok: true,
    json: () => Promise.resolve(data),
  });
}

describe('MartPage rendering', () => {
  beforeEach(() => {
    global.fetch = vi.fn((url) => {
      const href = String(url);
      if (href.includes('/api/marts/emart/promotions')) {
        return fetchJson({
          data: [
            {
              name: '테스트우유 1L',
              price: 1980,
              original_price: 2980,
              event_name: '신선식품 행사',
              unit: '1L',
            },
          ],
        });
      }
      if (href.includes('/api/marts/')) {
        return fetchJson({ data: [] });
      }
      if (href.includes('/api/products/search')) {
        return fetchJson({ data: [] });
      }
      return fetchJson({ data: null });
    });
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('does not crash when auto-opening a product from URL params', async () => {
    render(
      <MemoryRouter initialEntries={['/mart?mart=emart&product=테스트우유%201L']}>
        <MartPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText('테스트우유 1L')).toBeInTheDocument();
    });
    expect(screen.getByText('총 1개 상품')).toBeInTheDocument();
  });

  it('shows price observations without original-price or discount badges', async () => {
    global.fetch = vi.fn((url) => {
      const href = String(url);
      if (href.includes('/api/marts/emart/promotions')) {
        return fetchJson({
          data: [
            {
              name: '국산콩 두부 300g',
              price: 1980,
              original_price: null,
              discount_rate: null,
              record_label: '관측 가격',
              claim_status_label: '할인 여부 미확인',
              price_observation_only: true,
              has_discount_metadata: false,
              unit: '300g',
            },
          ],
        });
      }
      if (href.includes('/api/marts/')) return fetchJson({ data: [] });
      if (href.includes('/api/products/search')) return fetchJson({ data: [] });
      return fetchJson({ data: null });
    });

    render(
      <MemoryRouter initialEntries={['/mart?mart=emart']}>
        <MartPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText('국산콩 두부 300g')).toBeInTheDocument();
    });
    expect(screen.getAllByText('관측 가격').length).toBeGreaterThan(0);
    expect(screen.getByText('1,980', { exact: false })).toBeInTheDocument();
    expect(screen.queryByText(/-\d+%/)).not.toBeInTheDocument();
  });
});
