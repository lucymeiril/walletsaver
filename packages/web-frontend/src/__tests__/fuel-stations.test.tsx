import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import FuelStationsPage from '../pages/FuelStationsPage'
import type { FuelSearchResult, FuelRegions, FuelStation } from '../types'

// ── API mock setup ─────────────────────────────────────────────────────────

vi.mock('../api/client', () => ({
  fetchFuelRegions: vi.fn(),
  searchFuelStations: vi.fn(),
  fetchFuelStation: vi.fn(),
}))

import { fetchFuelRegions, searchFuelStations } from '../api/client'

const mockRegions: FuelRegions = {
  sido_list: ['서울특별시', '경기도'],
  sigungu_list: ['강서구', '마포구'],
  brand_list: ['알뜰주유소', 'SK에너지', 'GS칼텍스'],
  fuel_kinds: [
    { value: 'gasoline_regular', label: '휘발유' },
    { value: 'gasoline_premium', label: '고급휘발유' },
    { value: 'diesel', label: '경유' },
    { value: 'lpg', label: 'LPG' },
  ],
}

const makeFuelStation = (overrides: Partial<FuelStation> = {}): FuelStation => ({
  id: 'st_001',
  brand: '알뜰주유소',
  name: '강서알뜰주유소',
  address: '서울특별시 강서구 허준로 57',
  sido: '서울특별시',
  sigungu: '강서구',
  lat: 37.5506,
  lng: 126.8418,
  self_service: true,
  has_car_wash: false,
  has_convenience: false,
  opinet_id: 'A0003461',
  price: 1598,
  fuel_kind: 'gasoline_regular',
  fuel_kind_label: '휘발유',
  grade_label: 'CHEAP',
  distance_km: null,
  ...overrides,
})

const mockSearchResult: FuelSearchResult = {
  total: 3,
  page: 1,
  page_size: 20,
  total_pages: 1,
  summary: {
    region: '서울특별시 강서구',
    fuel_kind: 'gasoline_regular',
    fuel_kind_label: '휘발유',
    avg_price: 1640,
    min_price: 1598,
    station_count: 3,
  },
  items: [
    makeFuelStation({ id: 'st_001', name: '강서알뜰주유소', price: 1598, grade_label: 'CHEAP' }),
    makeFuelStation({ id: 'st_002', name: '마곡SK주유소', brand: 'SK에너지', price: 1625, grade_label: 'NORMAL' }),
    makeFuelStation({ id: 'st_003', name: '화곡GS칼텍스', brand: 'GS칼텍스', price: 1688, grade_label: 'EXPENSIVE' }),
  ],
}

function renderPage() {
  return render(
    <MemoryRouter>
      <FuelStationsPage />
    </MemoryRouter>
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(fetchFuelRegions).mockResolvedValue(mockRegions)
  vi.mocked(searchFuelStations).mockResolvedValue(mockSearchResult)
})

// ══════════════════════════════════════════════════════
// 렌더링 기본 테스트
// ══════════════════════════════════════════════════════

describe('FuelStationsPage', () => {
  it('페이지 제목 렌더링', async () => {
    renderPage()
    await waitFor(() => {
      expect(screen.getByText(/주유소 가격/i)).toBeInTheDocument()
    })
  })

  it('검색 버튼 렌더링', async () => {
    renderPage()
    expect(screen.getByTestId('search-btn')).toBeInTheDocument()
  })

  it('유종 선택 라디오 렌더링', async () => {
    renderPage()
    await waitFor(() => {
      expect(screen.getByTestId('fuel-kind-gasoline_regular')).toBeInTheDocument()
      expect(screen.getByTestId('fuel-kind-diesel')).toBeInTheDocument()
    })
  })

  it('정렬 선택 라디오 렌더링', async () => {
    renderPage()
    await waitFor(() => {
      expect(screen.getByTestId('sort-price_asc')).toBeInTheDocument()
      expect(screen.getByTestId('sort-name_asc')).toBeInTheDocument()
    })
  })

  it('지역 목록 로드 후 시도 드롭다운에 서울 표시', async () => {
    renderPage()
    await waitFor(() => {
      expect(fetchFuelRegions).toHaveBeenCalled()
    })
    const sidoSelect = screen.getByTestId('sido-select') as HTMLSelectElement
    expect(sidoSelect.innerHTML).toContain('서울특별시')
  })

  it('검색 결과 카드 렌더링', async () => {
    renderPage()
    fireEvent.click(screen.getByTestId('search-btn'))
    await waitFor(() => {
      const cards = screen.getAllByTestId('fuel-station-card')
      expect(cards.length).toBe(3)
    })
  })

  it('주유소 이름 표시', async () => {
    renderPage()
    fireEvent.click(screen.getByTestId('search-btn'))
    await waitFor(() => {
      expect(screen.getByText('강서알뜰주유소')).toBeInTheDocument()
      expect(screen.getByText('마곡SK주유소')).toBeInTheDocument()
    })
  })

  it('가격 표시', async () => {
    renderPage()
    fireEvent.click(screen.getByTestId('search-btn'))
    await waitFor(() => {
      expect(screen.getAllByTestId('fuel-price')[0].textContent).toContain('1,598')
    })
  })
})

// ══════════════════════════════════════════════════════
// 등급 배지 테스트
// ══════════════════════════════════════════════════════

describe('FuelGradeBadge', () => {
  it('CHEAP 배지 렌더링', async () => {
    renderPage()
    fireEvent.click(screen.getByTestId('search-btn'))
    await waitFor(() => {
      const badge = document.querySelector('[data-fuel-grade="CHEAP"]')
      expect(badge).toBeInTheDocument()
    })
  })

  it('NORMAL 배지 렌더링', async () => {
    renderPage()
    fireEvent.click(screen.getByTestId('search-btn'))
    await waitFor(() => {
      const badge = document.querySelector('[data-fuel-grade="NORMAL"]')
      expect(badge).toBeInTheDocument()
    })
  })

  it('EXPENSIVE 배지 렌더링', async () => {
    renderPage()
    fireEvent.click(screen.getByTestId('search-btn'))
    await waitFor(() => {
      const badge = document.querySelector('[data-fuel-grade="EXPENSIVE"]')
      expect(badge).toBeInTheDocument()
    })
  })

  it('INSUFFICIENT_DATA 배지 렌더링', async () => {
    vi.mocked(searchFuelStations).mockResolvedValueOnce({
      ...mockSearchResult,
      items: [makeFuelStation({ grade_label: 'INSUFFICIENT_DATA' })],
    })
    renderPage()
    fireEvent.click(screen.getByTestId('search-btn'))
    await waitFor(() => {
      const badge = document.querySelector('[data-fuel-grade="INSUFFICIENT_DATA"]')
      expect(badge).toBeInTheDocument()
    })
  })
})

// ══════════════════════════════════════════════════════
// 요약 바 (summary) 테스트
// ══════════════════════════════════════════════════════

describe('검색 요약 바', () => {
  it('평균 가격 표시', async () => {
    renderPage()
    const searchBtn = screen.getByTestId('search-btn')
    fireEvent.click(searchBtn)
    await waitFor(() => {
      expect(screen.getByTestId('fuel-summary')).toBeInTheDocument()
      expect(screen.getByTestId('fuel-summary').textContent).toContain('1,640')
    })
  })

  it('최저 가격 표시', async () => {
    renderPage()
    const searchBtn = screen.getByTestId('search-btn')
    fireEvent.click(searchBtn)
    await waitFor(() => {
      expect(screen.getByTestId('fuel-summary')).toBeInTheDocument()
      expect(screen.getByTestId('fuel-summary').textContent).toContain('1,598')
    })
  })

  it('주유소 수 표시', async () => {
    renderPage()
    const searchBtn = screen.getByTestId('search-btn')
    fireEvent.click(searchBtn)
    await waitFor(() => {
      expect(screen.getByTestId('fuel-summary').textContent).toContain('3')
    })
  })
})

// ══════════════════════════════════════════════════════
// 인터랙션 테스트
// ══════════════════════════════════════════════════════

describe('유종 선택 인터랙션', () => {
  it('경유 라디오 선택 → API 파라미터 diesel', async () => {
    renderPage()
    await waitFor(() => {
      expect(screen.getByTestId('fuel-kind-diesel')).toBeInTheDocument()
    })
    const dieselRadio = screen.getByTestId('fuel-kind-diesel')
    fireEvent.click(dieselRadio)
    // 유종 변경 시 자동 재검색 (또는 검색 버튼 클릭 후)
    const searchBtn = screen.getByTestId('search-btn')
    fireEvent.click(searchBtn)
    await waitFor(() => {
      const calls = vi.mocked(searchFuelStations).mock.calls
      const lastCall = calls[calls.length - 1]
      expect(lastCall[0]).toMatchObject({ fuel_kind: 'diesel' })
    })
  })
})

describe('정렬 선택 인터랙션', () => {
  it('이름순 선택 → API sort=name_asc', async () => {
    renderPage()
    await waitFor(() => {
      expect(screen.getByTestId('sort-name_asc')).toBeInTheDocument()
    })
    const nameSort = screen.getByTestId('sort-name_asc')
    fireEvent.click(nameSort)
    const searchBtn = screen.getByTestId('search-btn')
    fireEvent.click(searchBtn)
    await waitFor(() => {
      const calls = vi.mocked(searchFuelStations).mock.calls
      const lastCall = calls[calls.length - 1]
      expect(lastCall[0]).toMatchObject({ sort: 'name_asc' })
    })
  })
})
