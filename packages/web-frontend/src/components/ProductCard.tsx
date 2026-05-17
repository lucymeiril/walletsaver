import { useNavigate } from 'react-router-dom'
import type { ProductSummary } from '../types'
import { GradeBadge } from './GradeBadge'

interface ProductCardProps {
  product: ProductSummary
}

const MART_LABELS: Record<string, string> = {
  EMART: '이마트',
  HOMEPLUS: '홈플러스',
  LOTTEMART: '롯데마트',
  COSTCO: '코스트코',
  COUPANG: '쿠팡',
}

export function ProductCard({ product }: ProductCardProps) {
  const navigate = useNavigate()

  const formatPrice = (v: number | null) =>
    v != null ? `₩${Math.round(v).toLocaleString('ko-KR')}` : '-'

  const discountPct =
    product.sufficient && product.p50 && product.p10
      ? Math.round(((product.p50 - product.p10) / product.p50) * 100)
      : null

  return (
    <article
      onClick={() => navigate(`/p/${product.canonical_id}`)}
      style={{
        border: '1px solid #e5e7eb',
        borderRadius: '12px',
        padding: '16px',
        cursor: 'pointer',
        background: '#fff',
        transition: 'box-shadow 0.15s',
      }}
      aria-label={`상품: ${product.name_core}`}
    >
      {product.image_url && (
        <img
          src={product.image_url}
          alt={product.name_core}
          style={{ width: '100%', height: '140px', objectFit: 'cover', borderRadius: '8px' }}
        />
      )}
      <div style={{ marginTop: '8px' }}>
        {product.brand && (
          <small style={{ color: '#6b7280' }}>{product.brand}</small>
        )}
        <h3 style={{ margin: '4px 0', fontSize: '14px', fontWeight: 600 }}>
          {product.name_core}
        </h3>

        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '6px' }}>
          <GradeBadge label={product.grade_label} />
          {discountPct !== null && (
            <span
              data-testid="discount-pct"
              style={{ color: '#dc2626', fontWeight: 700, fontSize: '13px' }}
            >
              -{discountPct}%
            </span>
          )}
        </div>

        <div style={{ marginTop: '8px', fontSize: '13px', color: '#374151' }}>
          <div>
            <span style={{ color: '#9ca3af' }}>핫딜가 </span>
            <strong data-testid="price-p10">{formatPrice(product.p10)}</strong>
          </div>
          <div>
            <span style={{ color: '#9ca3af' }}>평소가 </span>
            <strong data-testid="price-p50">{formatPrice(product.p50)}</strong>
          </div>
        </div>

        {product.marts.length > 0 && (
          <div style={{ marginTop: '8px', display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
            {product.marts.map((m) => (
              <span
                key={m}
                style={{
                  fontSize: '11px',
                  padding: '2px 6px',
                  background: '#f9fafb',
                  border: '1px solid #e5e7eb',
                  borderRadius: '6px',
                }}
              >
                {MART_LABELS[m] ?? m}
              </span>
            ))}
          </div>
        )}
      </div>
    </article>
  )
}
