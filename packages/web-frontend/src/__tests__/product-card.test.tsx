import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
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
    expect(discountEl.textContent).toMatch(/^-\d+%$/)
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
