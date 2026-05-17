import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../api/client', () => ({
  fetchReports: vi.fn(),
  fetchAuditLog: vi.fn().mockResolvedValue([]),
  resolveReport: vi.fn().mockResolvedValue(undefined),
  banUser: vi.fn(),
  unbanUser: vi.fn(),
}))

import * as client from '../api/client'
import AdminPage from '../pages/AdminPage'

describe('AdminPage reports', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(client.fetchAuditLog as any).mockResolvedValue([])
  })

  it('신고 목록 렌더링', async () => {
    ;(client.fetchReports as any).mockResolvedValue([
      { id: 'r1', target_kind: 'post', target_id: 'p1', reason: '광고', status: 'open', created_at: 't', reporter_user_id: 'u1' },
    ])
    render(
      <MemoryRouter>
        <AdminPage />
      </MemoryRouter>
    )
    await waitFor(() => expect(screen.getByText('광고')).toBeInTheDocument())
  })

  it('resolve 버튼 클릭 시 resolveReport 호출', async () => {
    ;(client.fetchReports as any).mockResolvedValue([
      { id: 'r1', target_kind: 'post', target_id: 'p1', reason: '광고', status: 'open', created_at: 't', reporter_user_id: 'u1' },
    ])
    render(
      <MemoryRouter>
        <AdminPage />
      </MemoryRouter>
    )
    await waitFor(() => expect(screen.getByText('숨김')).toBeInTheDocument())
    fireEvent.click(screen.getByText('숨김'))
    await waitFor(() => expect(client.resolveReport).toHaveBeenCalledWith('r1', 'hide_target'))
  })

  it('대기 중인 신고 없으면 안내 문구 표시', async () => {
    ;(client.fetchReports as any).mockResolvedValue([])
    render(
      <MemoryRouter>
        <AdminPage />
      </MemoryRouter>
    )
    await waitFor(() => expect(screen.getByText(/대기 중인 신고/)).toBeInTheDocument())
  })
})
