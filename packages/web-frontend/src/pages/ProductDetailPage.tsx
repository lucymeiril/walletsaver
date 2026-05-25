import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { PriceGauge } from '../components/PriceGauge'
import { GradeBadge } from '../components/GradeBadge'
import { PluginSlot } from '../components/plugin/PluginSlot'
import { fetchProduct } from '../api/client'
import type { ProductDetail } from '../types'
import { useMode } from '../context/ModeContext'
import { computeDiscount, discountSummaryText } from '../lib/discount'
import { formatPrice, formatRelativeDays } from '../lib/format'

const MART_LABELS: Record<string, string> = {
  EMART: '이마트',
  HOMEPLUS: '홈플러스',
  LOTTEMART: '롯데마트',
  COSTCO: '코스트코',
  COUPANG: '쿠팡',
}

// web-FINAL §3-1: 3계층 구조.
// [계층 1 항상 펼침] ① 결론 라벨 박스 / ② 마트표(첫 3행) / ③ 검증 요약 1줄
// [계층 2 헤더만, 클릭 시 펼침] ④ 가격대 게이지 / ⑤ 가격 추이 / ⑥ 도매가 / ⑦ 핫딜러 패널
// 모드별 초기 상태: beginner = 계층1만, pro = 계층1 + ④⑤⑦.
// 후속 AI: 항상 펼침 3개 멤버는 절대 줄이지 말 것. v4 지적의 핵심.
export default function ProductDetailPage() {
  const { canonical_id } = useParams<{ canonical_id: string }>()
  const [product, setProduct] = useState<ProductDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showAllMarts, setShowAllMarts] = useState(false)
  const [showVerifyDetails, setShowVerifyDetails] = useState(false)
  const { mode } = useMode()

  // 계층 2 토글 상태 — 모드에 따라 초기값 결정.
  const [openGauge, setOpenGauge] = useState(mode === 'pro')
  const [openHistory, setOpenHistory] = useState(mode === 'pro')
  const [openWholesale, setOpenWholesale] = useState(false)
  const [openProPanel, setOpenProPanel] = useState(mode === 'pro')

  useEffect(() => {
    setOpenGauge(mode === 'pro')
    setOpenHistory(mode === 'pro')
    setOpenProPanel(mode === 'pro')
  }, [mode])

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
  const displayPrice = product.current_low ?? pg.p10 ?? null
  const result = computeDiscount({
    p50: pg.p50,
    displayPrice,
    sampleCount: product.sample_count ?? (pg.sufficient ? pg.sample_size : undefined),
    lastSeenDays: product.last_seen_days ?? undefined,
    hasActiveSource: product.has_active_source ?? undefined,
    unitKnown: product.unit_known ?? undefined,
  })

  const marts = product.mart_aliases
  const visibleMarts = showAllMarts ? marts : marts.slice(0, 3)

  return (
    <div
      className="ws-product-detail"
      style={{ maxWidth: '900px', margin: '0 auto', padding: '24px 16px' }}
      data-mode={mode}
    >
      <Link to="/" style={{ color: '#2563eb', textDecoration: 'none', fontSize: '13px' }}>
        ← 홈으로
      </Link>

      <div style={{ marginTop: '16px' }}>
        {product.brand && <small style={{ color: '#6b7280' }}>{product.brand}</small>}
        <h1 style={{ fontSize: '24px', fontWeight: 700, margin: '4px 0 12px' }}>
          {product.name_core}
        </h1>

        {/* ─── 계층 1 항상 펼침 ① 결론 라벨 박스 ─── */}
        <section
          data-testid="layer1-verdict"
          style={{
            background: '#fff7ed',
            border: '1px solid #fed7aa',
            borderRadius: 12,
            padding: 16,
            marginBottom: 12,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <GradeBadge label={pg.grade_label} />
            <strong style={{ fontSize: 18 }}>{formatPrice(displayPrice)}</strong>
            <span
              data-testid="detail-discount"
              data-discount-reason={result.reason}
              style={{ color: result.displayable ? '#b91c1c' : '#6b7280', fontSize: 14, fontWeight: 600 }}
            >
              {result.displayable
                ? `평소(${formatPrice(pg.p50)}) 대비 -${Math.abs(result.percent!)}% ${result.direction}`
                : discountSummaryText(result)}
            </span>
          </div>
          {product.current_low_label && (
            <div style={{ marginTop: 6, color: '#6b7280', fontSize: 12 }}>
              {product.current_low_label}
            </div>
          )}
          {product.last_seen_days != null && (
            <div style={{ marginTop: 4, color: '#9ca3af', fontSize: 12 }}>
              {formatRelativeDays(product.last_seen_days)}
            </div>
          )}
        </section>

        {/* ─── 계층 1 항상 펼침 ② 마트표 첫 3행 ─── */}
        <section data-testid="layer1-mart-table" style={{ marginBottom: 12 }}>
          <h2 style={{ fontSize: '15px', fontWeight: 600, marginBottom: '8px' }}>마트별 가격</h2>
          {marts.length === 0 ? (
            <p style={{ color: '#9ca3af', fontSize: 13 }}>마트 데이터가 없습니다.</p>
          ) : (
            <>
              <table className="ws-mart-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
                <thead>
                  <tr style={{ borderBottom: '2px solid #e5e7eb' }}>
                    <th style={{ textAlign: 'left', padding: '8px' }}>마트</th>
                    <th style={{ textAlign: 'left', padding: '8px' }}>상품명</th>
                    <th style={{ textAlign: 'left', padding: '8px' }}>최근 확인</th>
                    <th style={{ textAlign: 'left', padding: '8px' }}>링크</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleMarts.map((a, i) => (
                    <tr key={i} data-testid="mart-row" style={{ borderBottom: '1px solid #f3f4f6' }}>
                      <td style={{ padding: '8px', fontWeight: 500 }}>{MART_LABELS[a.mart] ?? a.mart}</td>
                      <td style={{ padding: '8px', color: '#374151' }}>{a.mart_item_name_raw ?? '-'}</td>
                      <td style={{ padding: '8px', color: '#9ca3af' }}>{a.last_seen_at ?? '-'}</td>
                      <td style={{ padding: '8px' }}>
                        {a.source_url ? (
                          <a href={a.source_url} target="_blank" rel="noopener noreferrer" style={{ color: '#2563eb' }}>
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
              {marts.length > 3 && (
                <button
                  type="button"
                  onClick={() => setShowAllMarts((v) => !v)}
                  data-testid="toggle-all-marts"
                  style={{
                    marginTop: 8,
                    padding: '6px 12px',
                    border: '1px solid #d1d5db',
                    background: 'white',
                    borderRadius: 8,
                    cursor: 'pointer',
                    fontSize: 13,
                  }}
                >
                  {showAllMarts ? `처음 3개만 보기` : `전체 ${marts.length}개 마트 보기`}
                </button>
              )}
            </>
          )}
        </section>

        {/* ─── 계층 1 항상 펼침 ③ 검증 요약 1줄 ─── */}
        <section data-testid="layer1-verify-summary" style={{ marginBottom: 24, background: '#f9fafb', border: '1px solid #e5e7eb', borderRadius: 12, padding: 12 }}>
          <button
            type="button"
            onClick={() => setShowVerifyDetails((v) => !v)}
            data-testid="toggle-verify-details"
            style={{
              background: 'transparent',
              border: 'none',
              padding: 0,
              cursor: 'pointer',
              fontSize: 14,
              color: '#374151',
              textAlign: 'left',
              width: '100%',
            }}
          >
            💬 커뮤니티 검증 요약 — 관련 게시글의 verdict 집계 [{showVerifyDetails ? '접기 ▲' : '펼치기 ▼'}]
          </button>
          {showVerifyDetails && (
            <div style={{ marginTop: 8, fontSize: 13, color: '#6b7280' }}>
              관련 게시글 verdict 집계는 P1에서 상품 단위 ProductVerdict 테이블로 본격화됩니다. 현재는 글 단위 verdict 만 게시판에서 확인.
            </div>
          )}
        </section>

        {/* ─── 계층 2 (헤더만, 클릭 시 펼침) ─── */}
        <Collapsible label="④ 가격대 게이지 (P10~P75)" open={openGauge} setOpen={setOpenGauge} testid="layer2-gauge">
          <PriceGauge p10={pg.p10} p25={pg.p25} p50={pg.p50} p75={pg.p75} currentPrice={displayPrice} sufficient={pg.sufficient} />
        </Collapsible>

        <Collapsible label="⑤ 가격 추이 그래프" open={openHistory} setOpen={setOpenHistory} testid="layer2-history">
          <p style={{ color: '#9ca3af', fontSize: 13 }}>
            가격 추이 그래프는 `/api/v1/products/{product.canonical_id}/history` 응답을 사용합니다. (UI 본격 차트는 후속 todo)
          </p>
        </Collapsible>

        <Collapsible label="⑥ 도매가/적정가" open={openWholesale} setOpen={setOpenWholesale} testid="layer2-wholesale">
          <p style={{ color: '#9ca3af', fontSize: 13 }}>도매가 데이터 없음 (DB 영역 의존, 데이터 도착 시 자동 노출).</p>
        </Collapsible>

        <Collapsible label="⑦ 핫딜러 패널 (P10/P25/P50/P75 + 표본)" open={openProPanel} setOpen={setOpenProPanel} testid="layer2-pro">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 8 }}>
            {[
              { label: 'P10 핫딜', value: pg.p10, color: '#22c55e' },
              { label: 'P25 세일', value: pg.p25, color: '#f59e0b' },
              { label: 'P50 평소', value: pg.p50, color: '#6b7280' },
              { label: 'P75 상한', value: pg.p75, color: '#ef4444' },
            ].map(({ label, value, color }) => (
              <div key={label} style={{ textAlign: 'center', padding: '10px 6px', background: '#fff', borderRadius: 8, border: `2px solid ${color}20` }}>
                <div style={{ fontSize: 11, color: '#9ca3af' }}>{label}</div>
                <div style={{ fontWeight: 700, color, fontSize: 13 }}>{formatPrice(value)}</div>
              </div>
            ))}
          </div>
          <div style={{ fontSize: 12, color: '#6b7280' }}>
            표본 {pg.sample_size}건 · {pg.sufficient ? '충분' : '부족 (5건 미만)'}
            {product.pack_quantity != null && product.pack_unit && (
              <> · 단위가 {formatPrice((displayPrice ?? 0) / Math.max(1, product.pack_quantity))}/{product.pack_unit}</>
            )}
          </div>
        </Collapsible>

        {/* ─── 하단 액션바 (항상 노출) ─── */}
        <div
          data-testid="action-bar"
          style={{
            display: 'flex',
            gap: 8,
            marginTop: 20,
            paddingTop: 12,
            borderTop: '1px solid #e5e7eb',
            overflowX: 'auto',
          }}
        >
          <ActionBtn>⭐ 즐겨찾기</ActionBtn>
          <ActionBtn>🔔 ₩X 이하 알림</ActionBtn>
          <Link
            to={`/board/hotdeal/new`}
            style={{ ...actionBtnStyle, color: '#374151', textDecoration: 'none' }}
            role="button"
          >
            ✍ 글쓰기
          </Link>
          <Link to="/compare" style={{ ...actionBtnStyle, color: '#374151', textDecoration: 'none' }} role="button">
            🍳 조합 추가
          </Link>
        </div>

        {/* ─── 플러그인 슬롯 (web-FINAL §10) ─── */}
        <PluginSlot
          src={`/plugins/unit-calculator.html?id=${product.canonical_id}`}
          title="단위가 계산기 (샘플 위젯)"
          context={{
            slot: 'product_detail',
            canonical_id: product.canonical_id,
            product_name: product.name_core,
            displayed_price: displayPrice,
            p50: pg.p50,
            grade: pg.grade_label,
          }}
        />
      </div>
    </div>
  )
}

const actionBtnStyle: React.CSSProperties = {
  padding: '8px 14px',
  border: '1px solid #d1d5db',
  borderRadius: 8,
  background: 'white',
  cursor: 'pointer',
  fontSize: 13,
  whiteSpace: 'nowrap',
}

function ActionBtn({ children }: { children: React.ReactNode }) {
  return (
    <button type="button" style={actionBtnStyle}>
      {children}
    </button>
  )
}

function Collapsible({
  label,
  open,
  setOpen,
  children,
  testid,
}: {
  label: string
  open: boolean
  setOpen: (v: boolean) => void
  children: React.ReactNode
  testid: string
}) {
  return (
    <section data-testid={testid} data-open={open} style={{ border: '1px solid #e5e7eb', borderRadius: 12, marginBottom: 10 }}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        data-testid={`${testid}-header`}
        style={{
          width: '100%',
          padding: 12,
          background: 'transparent',
          border: 'none',
          textAlign: 'left',
          cursor: 'pointer',
          fontSize: 14,
          fontWeight: 600,
          color: '#374151',
        }}
      >
        {label} {open ? '▲' : '▼'}
      </button>
      {open && <div style={{ padding: '0 12px 12px' }}>{children}</div>}
    </section>
  )
}
