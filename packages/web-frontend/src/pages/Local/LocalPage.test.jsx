import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import LocalPage from './LocalPage';

vi.mock('../../stores/appStore', () => ({
  default: () => ({
    addToast: vi.fn(),
    setSavedLocation: vi.fn(),
  }),
}));

function jsonResponse(payload) {
  return Promise.resolve({
    ok: true,
    json: () => Promise.resolve(payload),
  });
}

function streamResponse(events) {
  const bytes = new TextEncoder().encode(
    events.map(event => `data: ${JSON.stringify(event)}\n\n`).join(''),
  );
  let sent = false;
  return Promise.resolve({
    ok: true,
    body: {
      getReader: () => ({
        read: async () => {
          if (sent) return { done: true, value: undefined };
          sent = true;
          return { done: false, value: bytes };
        },
        releaseLock: vi.fn(),
      }),
    },
  });
}

describe('LocalPage browser-search consent', () => {
  beforeEach(() => {
    global.fetch = vi.fn((url) => {
      const href = String(url);
      if (href.includes('/api/local/geocode')) {
        return jsonResponse({
          success: true,
          data: { name: '강남역', lat: 37.4979, lng: 127.0276 },
        });
      }
      if (href.includes('/api/local/area-explore-stream')) {
        return streamResponse([{ name: '음식', items: [], source: 'unavailable' }, { done: true }]);
      }
      return jsonResponse({ success: true, data: { items: [] } });
    });
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('searches only after opt-in and never embeds the blocked Naver iframe', async () => {
    const user = userEvent.setup();
    render(<LocalPage />);

    const consent = screen.getByRole('checkbox', {
      name: /네이버 공개 페이지 브라우저 검색 사용/,
    });
    expect(consent).not.toBeChecked();
    expect(screen.queryByTitle('네이버 지도')).not.toBeInTheDocument();

    await user.type(screen.getByPlaceholderText(/위치를 입력하세요/), '강남역');
    await user.click(screen.getAllByRole('button').find(button => button.querySelector('svg')));

    await waitFor(() => {
      const areaCall = global.fetch.mock.calls.find(([url]) =>
        String(url).includes('/api/local/area-explore-stream'),
      );
      expect(areaCall).toBeTruthy();
      expect(String(areaCall[0])).toContain('browser_search=false');
    });

    await user.click(consent);

    await waitFor(() => {
      const areaCalls = global.fetch.mock.calls.filter(([url]) =>
        String(url).includes('/api/local/area-explore-stream'),
      );
      expect(areaCalls.length).toBeGreaterThanOrEqual(2);
      expect(String(areaCalls.at(-1)[0])).toContain('browser_search=true');
    });
  });
});
