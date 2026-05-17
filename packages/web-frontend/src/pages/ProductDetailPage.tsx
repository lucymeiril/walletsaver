import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { PriceGauge } from '../components/PriceGauge'
import { GradeBadge } from '../components/GradeBadge'
import { fetchProduct } from '../api/client'
import type { ProductDetail } from '../types'

const MART_LABELS: Record<string, string> = {
  EMART: '이마트',
  HOMEPLUS: '홈플러스',
  LOTTEMART: '롯데마트',
  COSTCO: '코스트코',
  COUPANG: '쿠팡',
}

export default function ProductDetailPage() {
  const { canonical_id } = useParams<{ canonical_id: string }>()
  const [product, setProduct] = useState<ProductDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!canonical_id) return
    setLoading(true)
    fetchProduct(canonical_id)
      .then((data) => {
        setProduct(data)
        setLoading(false)
      })
      .catch((e) => {
        setError(e.message)
        setLoading(false)
      })
  }, [canonical_id])

  if (loading) return <p style={{ padding: '24px', color: '#9ca3af' }}>로딩 중...</p>
  if (error) return <p style={{ padding: '24px', color: '#dc2626' }}>오류: {error}</p>
  if (!product) return <p style={{ padding: '24px', color: '#9ca3af' }}>상품을 찾을 수 없습니다.</p>

  const pg = product.price_grade
  const formatPrice = (v: number | null) =>
    v != null ? `₩${Math.round(v).toLocaleString('ko-KR')}` : '-'

  return (
    <div style={{ maxWidth: '900px', margin: '0 auto', padding: '24px 16px' }}>
      <Link to="/" style={{ color: '#2563eb', textDecoration: 'none', fontSize: '13px' }}>
        ← 홈으로
      </Link>

      <div style={{ marginTop: '16px' }}>
        {product.brand && (
          <small style={{ color: '#6b7280' }}>{product.brand}</small>
        )}
        <h1 style={{ fontSize: '24px', fontWeight: 700, margin: '4px 0 12px' }}>
          {product.name_core}
        </h1>

        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '16px' }}>
          <GradeBadge label={pg.grade_label} />
          <span style={{ color: '#6b7280', fontSize: '13px' }}>
            이 가격이 진짜 핫딜인가?
          </span>
        </div>

        {/* Price grade section */}
        <section
          style={{
            background: '#f9fafb',
            borderRadius: '12px',
            padding: '20px',
            marginBottom: '24px',
          }}
        >
          <h2 style={{ fontSize: '16px', fontWeight: 600, margin: '0 0 16px' }}>가격 등급</h2>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(4, 1fr)',
              gap: '12px',
              marginBottom: '16px',
            }}
          >
            {[
              { label: 'P10 핫딜', value: pg.p10, color: '#22c55e' },
              { label: 'P25 세일', value: pg.p25, color: '#f59e0b' },
              { label: 'P50 평소', value: pg.p50, color: '#6b7280' },
              { label: 'P75 상한', value: pg.p75, color: '#ef4444' },
            ].map(({ label, value, color }) => (
              <div
                key={label}
                style={{
                  textAlign: 'center',
                  padding: '12px 8px',
                  background: '#fff',
                  borderRadius: '8px',
                  border: `2px solid ${color}20`,
                }}
              >
                <div style={{ fontSize: '11px', color: '#9ca3af', marginBottom: '4px' }}>
                  {label}
                </div>
                <div style={{ fontWeight: 700, color, fontSize: '14px' }}>
                  {formatPrice(value)}
                </div>
              </div>
            ))}
          </div>
          <PriceGauge
            p10={pg.p10}
            p25={pg.p25}
            p50={pg.p50}
            p75={pg.p75}
            currentPrice={pg.p50}
            sufficient={pg.sufficient}
          />
          {!pg.sufficient && (
            <p style={{ color: '#9ca3af', fontSize: '13px', margin: '8px 0 0' }}>
              표본 {pg.sample_size}건 — 5건 이상 수집 시 등급 표시 가능
            </p>
          )}
        </section>

        {/* Mart comparison table */}
        <section>
          <h2 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '12px' }}>
            마트별 가격 비교
          </h2>
          {product.mart_aliases.length === 0 ? (
            <p style={{ color: '#9ca3af' }}>마트 데이터가 없습니다.</p>
          ) : (
            <table
              style={{
                width: '100%',
                borderCollapse: 'collapse',
                fontSize: '14px',
              }}
            >
              <thead>
                <tr style={{ borderBottom: '2px solid #e5e7eb' }}>
                  <th style={{ textAlign: 'left', padding: '8px' }}>마트</th>
                  <th style={{ textAlign: 'left', padding: '8px' }}>상품명</th>
                  <th style={{ textAlign: 'left', padding: '8px' }}>최근 확인</th>
                  <th style={{ textAlign: 'left', padding: '8px' }}>링크</th>
                </tr>
              </thead>
              <tbody>
                {product.mart_aliases.map((a, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid #f3f4f6' }}>
                    <td style={{ padding: '8px', fontWeight: 500 }}>
                      {MART_LABELS[a.mart] ?? a.mart}
                    </td>
                    <td style={{ padding: '8px', color: '#374151' }}>
                      {a.mart_item_name_raw ?? '-'}
                    </td>
                    <td style={{ padding: '8px', color: '#9ca3af' }}>
                      {a.last_seen_at ?? '-'}
                    </td>
                    <td style={{ padding: '8px' }}>
                      {a.source_url ? (
                        <a
                          href={a.source_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          style={{ color: '#2563eb' }}
                        >
                          보기
                        </a>
                      ) : (
                        '-'
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>
    </div>
  )
}
