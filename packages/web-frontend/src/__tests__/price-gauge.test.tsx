import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { PriceGauge, priceToPosition } from '../components/PriceGauge'

describe('priceToPosition', () => {
  it('최솟값 → 0', () => {
    expect(priceToPosition(100, 100, 200)).toBe(0)
  })

  it('최댓값 → 100', () => {
    expect(priceToPosition(200, 100, 200)).toBe(100)
  })

  it('중간값 → 50', () => {
    expect(priceToPosition(150, 100, 200)).toBe(50)
  })

  it('범위 밖 하한 → 0으로 클램프', () => {
    expect(priceToPosition(50, 100, 200)).toBe(0)
  })

  it('범위 밖 상한 → 100으로 클램프', () => {
    expect(priceToPosition(250, 100, 200)).toBe(100)
  })

  it('min === max → 50 반환', () => {
    expect(priceToPosition(100, 100, 100)).toBe(50)
  })
})

describe('PriceGauge 렌더링', () => {
  const baseProps = {
    p10: 1500,
    p25: 1800,
    p50: 2200,
    p75: 2800,
    currentPrice: 2200,
    sufficient: true,
  }

  it('sufficient=true → 게이지 렌더링', () => {
    render(<PriceGauge {...baseProps} />)
    expect(screen.getByTestId('price-gauge')).toBeInTheDocument()
  })

  it('P10/P25/P50/P75 마커 렌더링', () => {
    render(<PriceGauge {...baseProps} />)
    expect(screen.getByTestId('marker-P10')).toBeInTheDocument()
    expect(screen.getByTestId('marker-P25')).toBeInTheDocument()
    expect(screen.getByTestId('marker-P50')).toBeInTheDocument()
    expect(screen.getByTestId('marker-P75')).toBeInTheDocument()
  })

  it('현재가 마커 렌더링', () => {
    render(<PriceGauge {...baseProps} />)
    expect(screen.getByTestId('current-price-marker')).toBeInTheDocument()
  })

  it('가격 라벨 표시', () => {
    render(<PriceGauge {...baseProps} />)
    expect(screen.getByTestId('label-p10')).toHaveTextContent('₩1,500')
    expect(screen.getByTestId('label-p75')).toHaveTextContent('₩2,800')
  })

  it('sufficient=false → 데이터 부족 메시지', () => {
    render(
      <PriceGauge
        p10={null}
        p25={null}
        p50={2200}
        p75={null}
        currentPrice={null}
        sufficient={false}
      />
    )
    expect(screen.getByText(/데이터 부족/)).toBeInTheDocument()
    expect(screen.queryByTestId('price-gauge')).not.toBeInTheDocument()
  })

  it('p75 null → 데이터 부족 처리', () => {
    render(
      <PriceGauge
        p10={1500}
        p25={null}
        p50={2200}
        p75={null}
        currentPrice={2200}
        sufficient={true}
      />
    )
    expect(screen.getByText(/데이터 부족/)).toBeInTheDocument()
  })

  it('currentPrice null → 현재가 마커 없음', () => {
    render(
      <PriceGauge
        p10={1500}
        p25={1800}
        p50={2200}
        p75={2800}
        currentPrice={null}
        sufficient={true}
      />
    )
    expect(screen.queryByTestId('current-price-marker')).not.toBeInTheDocument()
  })
})
