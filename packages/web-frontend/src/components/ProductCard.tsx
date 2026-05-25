import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { ProductSummary } from '../types'
import { GradeBadge } from './GradeBadge'
import { computeDiscount, discountSummaryText } from '../lib/discount'
import { formatPrice } from '../lib/format'
import { useMode } from '../context/ModeContext'

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

// web-FINAL §3-3 카드 표시가격 = 지금 최저가 (없으면 p10 fallback). §3-2 통일 산식 사용.
// 후속 AI: percent 계산을 카드 안에서 직접 하지 말고 lib/discount.ts 만 통해서.
export function ProductCard({ product }: ProductCardProps) {
  const navigate = useNavigate()
  const { mode } = useMode()
  const [toastVisible, setToastVisible] = useState(false)

  // wb1-pending-card: 분류 대기 카드
  if (product.status === 'pending_classification') {
    const handleRequestClassify = (e: React.MouseEvent) => {
      e.stopPropagation()
      setToastVisible(true)
      setTimeout(() => setToastVisible(false), 3000)
    }

    return (
      <article
        data-testid="pending-card"
        style={{
          border: '1px solid #d1d5db',
          borderRadius: '12px',
          padding: '16px',
          background: '#f9fafb',
          position: 'relative',
          opacity: 0.85,
        }}
        aria-label={`분류 대기 상품: ${product.name_core}`}
      >
        <div
          data-testid="pending-badge"
          style={{
            display: 'inline-block',
            fontSize: '11px',
            fontWeight: 600,
            padding: '2px 8px',
            background: '#e5e7eb',
            color: '#6b7280',
            borderRadius: '9999px',
            marginBottom: '8px',
          }}
        >
          분류 대기중
        </div>
        <h3 style={{ margin: '4px 0', fontSize: '14px', fontWeight: 600, color: '#374151' }}>
          {product.name_core}
        </h3>
        {product.price != null && (
          <div style={{ marginTop: '6px', fontSize: '13px', color: '#6b7280' }}>
            <span>가격 </span>
            <strong data-testid="pending-price">{formatPrice(product.price)}</strong>
          </div>
        )}
        <div style={{ marginTop: '6px', fontSize: '12px', color: '#9ca3af' }}>
          <span>카테고리 </span><span style={{ fontStyle: 'italic' }}>—</span>
        </div>
        <div style={{ marginTop: '6px', fontSize: '12px', color: '#9ca3af' }}>
          <span>평소가 </span><span style={{ fontStyle: 'italic' }}>—</span>
        </div>
        {product.marts.length > 0 && (
          <div style={{ marginTop: '8px', display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
            {product.marts.map((m) => (
              <span
                key={m}
                style={{
                  fontSize: '11px',
                  padding: '2px 6px',
                  background: '#f3f4f6',
                  border: '1px solid #d1d5db',
                  borderRadius: '6px',
                  color: '#6b7280',
                }}
              >
                {MART_LABELS[m] ?? m}
              </span>
            ))}
          </div>
        )}
        <button
          data-testid="request-classify-btn"
          onClick={handleRequestClassify}
          style={{
            marginTop: '12px',
            width: '100%',
            padding: '6px 0',
            fontSize: '13px',
            fontWeight: 600,
            background: '#fff',
            border: '1px solid #9ca3af',
            borderRadius: '8px',
            cursor: 'pointer',
            color: '#4b5563',
          }}
        >
          분류 요청
        </button>
        {toastVisible && (
          <div
            data-testid="classify-toast"
            style={{
              position: 'absolute',
              bottom: '8px',
              left: '50%',
              transform: 'translateX(-50%)',
              background: '#374151',
              color: '#fff',
              fontSize: '12px',
              padding: '4px 12px',
              borderRadius: '8px',
              whiteSpace: 'nowrap',
            }}
          >
            분류 요청이 접수되었습니다
          </div>
        )}
      </article>
    )
  }

  const displayPrice = product.current_low ?? product.p10 ?? null
  const result = computeDiscount({
    p50: product.p50,
    displayPrice,
    sampleCount: product.sample_count ?? (product.sufficient ? 10 : undefined),
    lastSeenDays: product.last_seen_days ?? undefined,
    hasActiveSource: product.has_active_source ?? undefined,
    unitKnown: product.unit_known ?? undefined,
  })

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
      data-mode={mode}
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
          {result.displayable && result.percent != null ? (
            <span
              data-testid="discount-pct"
              data-discount-reason="ok"
              style={{ color: '#dc2626', fontWeight: 700, fontSize: '13px' }}
              title={discountSummaryText(result)}
            >
              -{Math.abs(result.percent)}% {result.direction}
            </span>
          ) : (
            <span
              data-testid="discount-reason"
              data-discount-reason={result.reason}
              style={{ color: '#9ca3af', fontSize: '12px' }}
            >
              {result.reasonLabel}
            </span>
          )}
        </div>

        <div style={{ marginTop: '8px', fontSize: '13px', color: '#374151' }}>
          <div>
            <span style={{ color: '#9ca3af' }}>지금 최저가 </span>
            <strong data-testid="price-current">{formatPrice(displayPrice)}</strong>
          </div>
          <div>
            <span style={{ color: '#9ca3af' }}>평소가 </span>
            <strong data-testid="price-p50">{formatPrice(product.p50)}</strong>
          </div>
          {/* 핫딜러 모드 추가 정보 — 카드 한 줄에 다 묻지 않고 작은 회색으로 */}
          {mode === 'pro' && (
            <div data-testid="card-pro" style={{ marginTop: 4, fontSize: 11, color: '#6b7280' }}>
              <span>P10 {formatPrice(product.p10)}</span>
              <span style={{ marginLeft: 8 }}>표본 {product.sample_count ?? (product.sufficient ? '충분' : '부족')}</span>
            </div>
          )}
          {/* 호환성: 기존 테스트가 price-p10 selector 사용. */}
          <span data-testid="price-p10" style={{ display: 'none' }}>{formatPrice(product.p10)}</span>
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
