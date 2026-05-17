import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import NewPostPage from '../pages/NewPostPage'

vi.mock('../api/client', () => ({
  fetchBoardCategories: vi.fn().mockResolvedValue([
    { id: 'c1', board_slug: 'free', name: '잡담', slug: 'chat' },
  ]),
  createPost: vi.fn().mockResolvedValue({ id: 'p1', board_slug: 'free' }),
}))

import * as client from '../api/client'

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/board/free/new']}>
      <Routes>
        <Route path="/board/:slug/new" element={<NewPostPage />} />
        <Route path="/post/:id" element={<div>navigated</div>} />
      </Routes>
    </MemoryRouter>
  )
}

describe('NewPostPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(client.fetchBoardCategories as any).mockResolvedValue([
      { id: 'c1', board_slug: 'free', name: '잡담', slug: 'chat' },
    ])
    ;(client.createPost as any).mockResolvedValue({ id: 'p1', board_slug: 'free' })
  })

  it('렌더링: 제목/본문/제출 필드', () => {
    renderPage()
    expect(screen.getByPlaceholderText('제목')).toBeInTheDocument()
    expect(screen.getByLabelText('body')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /게시/ })).toBeInTheDocument()
  })

  it('제목 비어있으면 submit 비활성화', () => {
    renderPage()
    const btn = screen.getByRole('button', { name: /게시/ }) as HTMLButtonElement
    expect(btn.disabled).toBe(true)
  })

  it('폼 제출 시 createPost 호출', async () => {
    renderPage()
    fireEvent.change(screen.getByPlaceholderText('제목'), { target: { value: 'T' } })
    fireEvent.change(screen.getByLabelText('body'), { target: { value: 'B' } })
    const btn = screen.getByRole('button', { name: /게시/ })
    fireEvent.click(btn)
    await waitFor(() => expect(client.createPost).toHaveBeenCalled())
    const args = (client.createPost as any).mock.calls[0]
    expect(args[0]).toBe('free')
    const fd: FormData = args[1]
    expect(fd.get('title')).toBe('T')
    expect(fd.get('body_markdown')).toBe('B')
  })
})
