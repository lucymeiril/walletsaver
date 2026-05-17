import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { SearchBar } from '../components/SearchBar'

// Mock the API client
vi.mock('../api/client', () => ({
  fetchAutocomplete: vi.fn(),
}))

import { fetchAutocomplete } from '../api/client'
const mockFetchAutocomplete = vi.mocked(fetchAutocomplete)

describe('SearchBar', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('입력 후 자동완성 항목 노출', async () => {
    mockFetchAutocomplete.mockResolvedValue({
      prefix: '두',
      suggestions: [
        { token: '두부', display: '두부', source: 'category', weight: 0.8, canonical_id: null, category_node_id: 'tofu' },
        { token: '두유', display: '두유', source: 'product_name_core', weight: 0.7, canonical_id: 'prod_001', category_node_id: null },
      ],
    })

    render(
      <MemoryRouter>
        <SearchBar />
      </MemoryRouter>
    )

    const input = screen.getByRole('textbox', { name: /검색/i })
    await userEvent.type(input, '두')

    await waitFor(() => {
      expect(screen.getByRole('listbox')).toBeInTheDocument()
    }, { timeout: 500 })

    const options = screen.getAllByRole('option')
    expect(options).toHaveLength(2)
    expect(options[0]).toHaveTextContent('두부')
    expect(options[1]).toHaveTextContent('두유')
  })

  it('빈 입력에는 자동완성이 보이지 않음', async () => {
    render(
      <MemoryRouter>
        <SearchBar />
      </MemoryRouter>
    )

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(mockFetchAutocomplete).not.toHaveBeenCalled()
  })

  it('API 오류 시 빈 목록', async () => {
    mockFetchAutocomplete.mockRejectedValue(new Error('network error'))

    render(
      <MemoryRouter>
        <SearchBar />
      </MemoryRouter>
    )

    const input = screen.getByRole('textbox')
    await userEvent.type(input, '두부')

    await waitFor(() => {
      expect(mockFetchAutocomplete).toHaveBeenCalled()
    })

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('제안 클릭 시 onSearch 콜백 호출', async () => {
    mockFetchAutocomplete.mockResolvedValue({
      prefix: '두부',
      suggestions: [
        { token: '두부', display: '두부', source: 'category', weight: 0.8, canonical_id: null, category_node_id: null },
      ],
    })

    const onSearch = vi.fn()
    render(
      <MemoryRouter>
        <SearchBar onSearch={onSearch} />
      </MemoryRouter>
    )

    const input = screen.getByRole('textbox')
    await userEvent.type(input, '두부')

    await waitFor(() => {
      expect(screen.getByRole('listbox')).toBeInTheDocument()
    }, { timeout: 500 })

    const option = screen.getByRole('option', { name: /두부/ })
    await userEvent.click(option)

    expect(onSearch).toHaveBeenCalledWith('두부')
  })
})
