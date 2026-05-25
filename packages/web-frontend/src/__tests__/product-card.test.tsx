import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ProductCard } from '../components/ProductCard'
import type { ProductSummary } from '../types'

function makeProduct(overrides: Partial<ProductSummary> = {}): ProductSummary {
  return {
    canonical_id: 'prod_001',
    name_core: '풀무원 국산 부침두부',
    brand: '풀무원',
    pack_quantity: 300,
    pack_unit: 'g',
    category_id: 'tofu_cat',
    image_url: null,
    p10: 1500,
    p25: 1800,
    p50: 2200,
    p75: 2800,
    sufficient: true,
    grade_label: 'HOT_DEAL',
    marts: ['LOTTEMART', 'HOMEPLUS'],
    ...overrides,
  }
}

function makePendingProduct(overrides: Partial<ProductSummary> = {}): ProductSummary {
  return {
    canonical_id: 'pending_raw_001',
    name_core: '이마트 미분류 과자 A',
    brand: null,
    pack_quantity: null,
    pack_unit: null,
    category_id: null,
    image_url: null,
    p10: null,
    p25: null,
    p50: null,
    p75: null,
    sufficient: false,
    grade_label: 'INSUFFICIENT_DATA',
    marts: ['EMART'],
    status: 'pending_classification',
    pending_raw_id: 'raw_001',
    price: 3500,
    captured_at: '2024-06-01T10:00:00',
    ...overrides,
  }
}

describe('ProductCard — pending_classification', () => {
  it('"분류 대기중" 배지 렌더링', () => {
    render(
      <MemoryRouter>
        <ProductCard product={makePendingProduct()} />
      </MemoryRouter>
    )
    expect(screen.getByTestId('pending-badge')).toHaveTextContent('분류 대기중')
  })

  it('상품명 표시', () => {
    render(
      <MemoryRouter>
        <ProductCard product={makePendingProduct()} />
      </MemoryRouter>
    )
    expect(screen.getByText('이마트 미분류 과자 A')).toBeInTheDocument()
  })

  it('가격 표시 (price 필드)', () => {
    render(
      <MemoryRouter>
        <ProductCard product={makePendingProduct({ price: 3500 })} />
      </MemoryRouter>
    )
    expect(screen.getByTestId('pending-price')).toHaveTextContent('₩3,500')
  })

  it('가격 없을 때 pending-price 미표시', () => {
    render(
      <MemoryRouter>
        <ProductCard product={makePendingProduct({ price: null })} />
      </MemoryRouter>
    )
    expect(screen.queryByTestId('pending-price')).toBeNull()
  })

  it('"분류 요청" 버튼 클릭 시 토스트 표시', async () => {
    vi.useFakeTimers()
    render(
      <MemoryRouter>
        <ProductCard product={makePendingProduct()} />
      </MemoryRouter>
    )
    const btn = screen.getByTestId('request-classify-btn')
    expect(btn).toHaveTextContent('분류 요청')
    fireEvent.click(btn)
    expect(screen.getByTestId('classify-toast')).toBeInTheDocument()
    vi.useRealTimers()
  })

  it('마트 레이블 표시', () => {
    render(
      <MemoryRouter>
        <ProductCard product={makePendingProduct({ marts: ['EMART'] })} />
      </MemoryRouter>
    )
    expect(screen.getByText('이마트')).toBeInTheDocument()
  })

  it('aria-label에 상품명 포함', () => {
    render(
      <MemoryRouter>
        <ProductCard product={makePendingProduct()} />
      </MemoryRouter>
    )
    expect(screen.getByRole('article')).toHaveAttribute(
      'aria-label',
      '분류 대기 상품: 이마트 미분류 과자 A'
    )
  })
})

describe('ProductCard', () => {
  it('HOT_DEAL 배지 렌더링', () => {
    render(
      <MemoryRouter>
        <ProductCard product={makeProduct({ grade_label: 'HOT_DEAL' })} />
      </MemoryRouter>
    )
    // Use data-grade selector to avoid ambiguity with "핫딜가" label
    const badge = document.querySelector('[data-grade="HOT_DEAL"]')
    expect(badge).toBeInTheDocument()
    expect(badge).toHaveTextContent('핫딜')
  })

  it('SALE 배지 렌더링', () => {
    render(
      <MemoryRouter>
        <ProductCard product={makeProduct({ grade_label: 'SALE' })} />
      </MemoryRouter>
    )
    expect(screen.getByText(/세일/i)).toBeInTheDocument()
    expect(screen.getByText(/세일/i)).toHaveAttribute('data-grade', 'SALE')
  })

  it('OVERPRICED 배지 렌더링', () => {
    render(
      <MemoryRouter>
        <ProductCard product={makeProduct({ grade_label: 'OVERPRICED' })} />
      </MemoryRouter>
    )
    expect(screen.getByText(/높은가격/i)).toHaveAttribute('data-grade', 'OVERPRICED')
  })

  it('가격 등급 P10/P50 표시', () => {
    render(
      <MemoryRouter>
        <ProductCard product={makeProduct({ p10: 1500, p50: 2200 })} />
      </MemoryRouter>
    )
    expect(screen.getByTestId('price-p10')).toHaveTextContent('₩1,500')
    expect(screen.getByTestId('price-p50')).toHaveTextContent('₩2,200')
  })

  it('할인율 표시 (p50 대비 p10)', () => {
    // discount = (2200 - 1500) / 2200 * 100 ≈ 31%
    render(
      <MemoryRouter>
        <ProductCard product={makeProduct({ p10: 1500, p50: 2200, sufficient: true })} />
      </MemoryRouter>
    )
    const discountEl = screen.getByTestId('discount-pct')
    expect(discountEl.textContent).toMatch(/^-\d+%\s*[↓↑—]?$/)
  })

  it('p10/p50 없을 때 대시(-) 표시', () => {
    render(
      <MemoryRouter>
        <ProductCard
          product={makeProduct({
            p10: null,
            p50: null,
            sufficient: false,
            grade_label: 'INSUFFICIENT_DATA',
          })}
        />
      </MemoryRouter>
    )
    const p10Els = screen.getAllByTestId('price-p10')
    expect(p10Els[0]).toHaveTextContent('-')
  })

  it('마트 이름 표시', () => {
    render(
      <MemoryRouter>
        <ProductCard product={makeProduct({ marts: ['LOTTEMART', 'HOMEPLUS'] })} />
      </MemoryRouter>
    )
    expect(screen.getByText('롯데마트')).toBeInTheDocument()
    expect(screen.getByText('홈플러스')).toBeInTheDocument()
  })
})
