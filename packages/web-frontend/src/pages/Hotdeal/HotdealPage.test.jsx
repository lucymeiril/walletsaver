import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import HotdealPage from './HotdealPage';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(__dirname, 'HotdealPage.jsx'), 'utf8');

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function showDeals(deals) {
  vi.stubGlobal('fetch', vi.fn(async url => ({ ok: true, json: async () =>
    String(url).includes('/comments') ? { data: [] }
      : String(url).includes('/sources') ? { data: ['전체', '루리웹', '유니클로'] }
        : { data: deals, meta: { total_pages: 1 } } })));
  return render(<MemoryRouter><HotdealPage /></MemoryRouter>);
}

describe('HotdealPage regressions', () => {
  it('does not notify parent comment count from inside setComments updater', () => {
    expect(source).not.toMatch(/setComments\s*\(\s*prev\s*=>\s*\{[\s\S]*onCommentCountChange/);
    expect(source).toContain('onCommentCountChange?.(item.id, comments.length)');
  });

  it('sends backend vote aliases and handles pending modal votes', () => {
    expect(source).toContain("if (type === 'cold') return 'not';");
    expect(source).toContain("disabled={isVotePending}");
    expect(source).toContain("response.status === 429");
  });

  it('retains community source quote, conditions and clocks in list/detail without a checkout or verification claim', async () => {
    showDeals([{ id: 'ruliweb:123', title: '원문 관측 상품', source: 'OTHER', source_label: '루리웹',
      price: 32000, origPrice: 64000, price_currency: 'KRW', price_basis: 'community_quote',
      posted_at: '2026-10-06T03:00:00Z', fetched_at: '2026-10-06T04:00:00Z',
      expires_at: null, expired: true, source_conditions: ['선택 옵션 확인 필요', '회원 자격 미확인'],
      url: 'https://example.invalid/native/123', hotVotes: 12 }]);
    const title = await screen.findByText('원문 관측 상품');
    expect(screen.getByText('원문 표시가 32,000원')).toBeInTheDocument();
    expect(screen.getByText('원문 조건 종료 · 기간 미명시')).toBeInTheDocument();
    expect(screen.getByText(/수집 시각 2026-10-06T04:00:00Z/)).toBeInTheDocument();
    expect(screen.queryByText(/커뮤니티 검증|역대급|50%/)).not.toBeInTheDocument();
    fireEvent.click(title);
    const dialog = within(screen.getByRole('dialog', { name: '핫딜 상세' }));
    expect(dialog.getByText('루리웹')).toBeInTheDocument();
    expect(dialog.getByText('원문 표시가 32,000원')).toBeInTheDocument();
    expect(dialog.getByText(/원문 조건: 선택 옵션 확인 필요 · 회원 자격 미확인/)).toBeInTheDocument();
    expect(dialog.getByText(/실제 조건 충족·현재 선택 결제 금액 미확인/)).toBeInTheDocument();
    expect(dialog.getByRole('link', { name: /원본 사이트/ })).toHaveAttribute('href', 'https://example.invalid/native/123');
    expect(global.fetch.mock.calls.every(([, options]) => !options?.method)).toBe(true);
  });

  it('keeps unknown currency and missing/zero prices unknown while preserving official conditional price arithmetic', async () => {
    showDeals([
      { id: 'unknown', title: '화폐 미명시 상품', source: 'OTHER', price: 2190, price_currency: null, price_basis: 'community_quote' },
      { id: 'zero', title: '가격 미확인 상품', source: 'OTHER', price: 0, price_currency: 'KRW' },
      { id: 'official', title: '회원 조건 상품', source: 'OTHER', source_label: '유니클로', price: 59900,
        origPrice: 79900, price_currency: 'KRW', price_basis: 'official_conditional_quote',
        source_period: '2026/10/08 까지', source_conditions: ['APP회원 한정', '선택 옵션 미확인'] },
    ]);
    await screen.findByText('화폐 미명시 상품');
    expect(screen.getByText('원문 표시가 2,190 (통화 미명시)')).toBeInTheDocument();
    expect(screen.getByText('원문 표시가 미확인')).toBeInTheDocument();
    expect(screen.queryByText(/2,190원|원문 표시가 0원/)).not.toBeInTheDocument();
    expect(screen.getByText('원문 표시가 기준 25%')).toBeInTheDocument();
    expect(screen.getByText(/원문 기간: 2026\/10\/08 까지 · 시간대·종료 경계 미확인/)).toBeInTheDocument();
    expect(screen.getByText('종료 시각·시간대 미확인')).toBeInTheDocument();
    fireEvent.click(screen.getByText('회원 조건 상품'));
    const dialog = within(screen.getByRole('dialog', { name: '핫딜 상세' }));
    expect(dialog.getByText('원문 표시가 59,900원')).toBeInTheDocument();
    expect(dialog.getByText('원문 비교 표시가 79,900원')).toBeInTheDocument();
    expect(dialog.getByText(/원문 조건: APP회원 한정 · 선택 옵션 미확인/)).toBeInTheDocument();
    expect(dialog.getByText(/실제 조건 충족·현재 선택 결제 금액 미확인/)).toBeInTheDocument();
  });
});
