interface PriceGaugeProps {
  p10: number | null
  p25: number | null
  p50: number | null
  p75: number | null
  currentPrice: number | null
  sufficient: boolean
}

/** Map a price to a 0-100 position on the gauge between min..max. */
export function priceToPosition(price: number, min: number, max: number): number {
  if (max === min) return 50
  const pos = ((price - min) / (max - min)) * 100
  return Math.max(0, Math.min(100, pos))
}

export function PriceGauge({ p10, p25, p50, p75, currentPrice, sufficient }: PriceGaugeProps) {
  if (!sufficient || p10 == null || p75 == null) {
    return (
      <div style={{ color: '#9ca3af', fontSize: '13px' }}>
        가격 데이터 부족 (5건 이상 필요)
      </div>
    )
  }

  const min = p10 * 0.9
  const max = p75 * 1.1

  const p10Pos = priceToPosition(p10, min, max)
  const p25Pos = p25 != null ? priceToPosition(p25, min, max) : null
  const p50Pos = p50 != null ? priceToPosition(p50, min, max) : null
  const p75Pos = priceToPosition(p75, min, max)
  const currentPos = currentPrice != null ? priceToPosition(currentPrice, min, max) : null

  const formatPrice = (v: number) => `₩${Math.round(v).toLocaleString('ko-KR')}`

  return (
    <div data-testid="price-gauge" style={{ width: '100%' }}>
      <div style={{ position: 'relative', height: '24px', margin: '16px 0' }}>
        {/* Track */}
        <div
          style={{
            position: 'absolute',
            top: '10px',
            left: 0,
            right: 0,
            height: '4px',
            background: '#e5e7eb',
            borderRadius: '2px',
          }}
        />
        {/* Colored zone: p10 → p75 */}
        <div
          style={{
            position: 'absolute',
            top: '10px',
            left: `${p10Pos}%`,
            width: `${p75Pos - p10Pos}%`,
            height: '4px',
            background: 'linear-gradient(to right, #22c55e, #f59e0b, #ef4444)',
          }}
        />
        {/* Markers */}
        {[
          { pos: p10Pos, label: 'P10', color: '#22c55e' },
          ...(p25Pos != null ? [{ pos: p25Pos, label: 'P25', color: '#f59e0b' }] : []),
          ...(p50Pos != null ? [{ pos: p50Pos, label: 'P50', color: '#6b7280' }] : []),
          { pos: p75Pos, label: 'P75', color: '#ef4444' },
        ].map(({ pos, label, color }) => (
          <div
            key={label}
            data-testid={`marker-${label}`}
            style={{
              position: 'absolute',
              top: '4px',
              left: `${pos}%`,
              transform: 'translateX(-50%)',
              width: '2px',
              height: '16px',
              background: color,
            }}
          />
        ))}
        {/* Current price indicator */}
        {currentPos != null && (
          <div
            data-testid="current-price-marker"
            style={{
              position: 'absolute',
              top: '2px',
              left: `${currentPos}%`,
              transform: 'translateX(-50%)',
              width: '12px',
              height: '20px',
              background: '#1d4ed8',
              borderRadius: '3px',
            }}
          />
        )}
      </div>
      {/* Labels */}
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: '#6b7280' }}>
        <span data-testid="label-p10">핫딜 {formatPrice(p10)}</span>
        {p50 != null && <span data-testid="label-p50">평소 {formatPrice(p50)}</span>}
        <span data-testid="label-p75">상한 {formatPrice(p75)}</span>
      </div>
    </div>
  )
}
