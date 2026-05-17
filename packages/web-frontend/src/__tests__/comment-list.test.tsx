import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

vi.mock('react-markdown', () => ({
  default: ({ children }: any) => <div>{children}</div>,
}))

vi.mock('../api/client', () => ({
  fetchMe: vi.fn().mockResolvedValue(null),
  fetchPost: vi.fn(),
  fetchVerdictSummary: vi.fn().mockResolvedValue({ hot_deal: 1, not_hot_deal: 1, neutral: 1 }),
  createComment: vi.fn(),
  deletePost: vi.fn(),
  reportPost: vi.fn(),
  reportComment: vi.fn(),
}))

import * as client from '../api/client'
import PostDetailPage from '../pages/PostDetailPage'

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/post/p1']}>
      <Routes>
        <Route path="/post/:id" element={<PostDetailPage />} />
      </Routes>
    </MemoryRouter>
  )
}

describe('Comment list', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(client.fetchMe as any).mockResolvedValue(null)
    ;(client.fetchVerdictSummary as any).mockResolvedValue({ hot_deal: 1, not_hot_deal: 1, neutral: 1 })
  })

  it('verdict 배지와 함께 댓글 목록 렌더링', async () => {
    ;(client.fetchPost as any).mockResolvedValue({
      id: 'p1',
      board_slug: 'free',
      title: 'T',
      user: { id: 'u1', display_name: '작성자', role: 'user' },
      category_id: null,
      freeform_category: null,
      deal_price: null,
      canonical_id: null,
      created_at: '2024-01-01',
      comment_count: 3,
      hidden_at: null,
      body_markdown: 'hello',
      images: [],
      mart_name: null,
      deal_url: null,
      grade_summary: null,
      comments: [
        { id: 'c1', user: { id: 'u1', display_name: 'A', role: 'user' }, body: '핫딜!', verdict: 'hot_deal', created_at: 't1', hidden_at: null },
        { id: 'c2', user: { id: 'u2', display_name: 'B', role: 'user' }, body: '아니야', verdict: 'not_hot_deal', created_at: 't2', hidden_at: null },
        { id: 'c3', user: { id: 'u3', display_name: 'C', role: 'user' }, body: '글쎄', verdict: 'neutral', created_at: 't3', hidden_at: null },
      ],
    })
    renderPage()
    await waitFor(() => expect(screen.getByText('핫딜!')).toBeInTheDocument())
    expect(screen.getByText('아니야')).toBeInTheDocument()
    expect(screen.getByText('글쎄')).toBeInTheDocument()
  })

  it('hot_deal verdict는 🔥 배지 표시', async () => {
    ;(client.fetchPost as any).mockResolvedValue({
      id: 'p1',
      board_slug: 'free',
      title: 'T',
      user: { id: 'u1', display_name: '작성자', role: 'user' },
      category_id: null,
      freeform_category: null,
      deal_price: null,
      canonical_id: null,
      created_at: '2024-01-01',
      comment_count: 1,
      hidden_at: null,
      body_markdown: 'b',
      images: [],
      mart_name: null,
      deal_url: null,
      grade_summary: null,
      comments: [
        { id: 'c1', user: { id: 'u1', display_name: 'A', role: 'user' }, body: '좋아', verdict: 'hot_deal', created_at: 't1', hidden_at: null },
      ],
    })
    renderPage()
    const badge = await screen.findByTestId('verdict-badge')
    expect(badge.textContent).toContain('🔥')
  })

  it('not_hot_deal verdict는 ❌ 배지 표시', async () => {
    ;(client.fetchPost as any).mockResolvedValue({
      id: 'p1',
      board_slug: 'free',
      title: 'T',
      user: { id: 'u1', display_name: '작성자', role: 'user' },
      category_id: null,
      freeform_category: null,
      deal_price: null,
      canonical_id: null,
      created_at: '2024-01-01',
      comment_count: 1,
      hidden_at: null,
      body_markdown: 'b',
      images: [],
      mart_name: null,
      deal_url: null,
      grade_summary: null,
      comments: [
        { id: 'c1', user: { id: 'u1', display_name: 'A', role: 'user' }, body: 'nope', verdict: 'not_hot_deal', created_at: 't1', hidden_at: null },
      ],
    })
    renderPage()
    const badge = await screen.findByTestId('verdict-badge')
    expect(badge.textContent).toContain('❌')
  })
})
