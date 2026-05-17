import { useState, useEffect, useCallback, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import { fetchFuelRegions, searchFuelStations } from '../api/client'
import type { FuelKind, FuelGradeLabel, FuelStation, FuelSearchResult, FuelRegions } from '../types'

// ── 등급 배지 설정 ────────────────────────────────────────────────────────────
const FUEL_GRADE_CONFIG: Record<FuelGradeLabel, { text: string; bg: string; color: string }> = {
  CHEAP:             { text: '💚 저렴', bg: '#dcfce7', color: '#16a34a' },
  NORMAL:            { text: '보통',   bg: '#f3f4f6', color: '#6b7280' },
  EXPENSIVE:         { text: '🔴 비쌈', bg: '#fee2e2', color: '#dc2626' },
  INSUFFICIENT_DATA: { text: '정보부족', bg: '#f3f4f6', color: '#9ca3af' },
}

const FUEL_KIND_OPTIONS: { value: FuelKind; label: string }[] = [
  { value: 'gasoline_regular', label: '휘발유' },
  { value: 'gasoline_premium', label: '고급휘발유' },
  { value: 'diesel',           label: '경유' },
  { value: 'lpg',              label: 'LPG' },
]

const SORT_OPTIONS = [
  { value: 'price_asc', label: '가격 낮은순' },
  { value: 'name_asc',  label: '이름순' },
  { value: 'distance',  label: '거리순' },
]

// ── 서브 컴포넌트 ─────────────────────────────────────────────────────────────

function FuelGradeBadge({ label }: { label: FuelGradeLabel }) {
  const cfg = FUEL_GRADE_CONFIG[label]
  return (
    <span
      data-fuel-grade={label}
      style={{
        display: 'inline-block',
        padding: '2px 8px',
        borderRadius: '12px',
        fontSize: '11px',
        fontWeight: 600,
        background: cfg.bg,
        color: cfg.color,
      }}
    >
      {cfg.text}
    </span>
  )
}

function FuelStationCard({ station }: { station: FuelStation }) {
  return (
    <div
      data-testid="fuel-station-card"
      style={{
        border: '1px solid #e5e7eb',
        borderRadius: '12px',
        padding: '16px',
        background: '#fff',
        display: 'flex',
        flexDirection: 'column',
        gap: '6px',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <span
            style={{
              fontSize: '11px',
              background: '#f0f9ff',
              color: '#0369a1',
              borderRadius: '6px',
              padding: '2px 6px',
              fontWeight: 600,
              marginRight: '6px',
            }}
          >
            {station.brand}
          </span>
          {station.self_service && (
            <span
              style={{
                fontSize: '11px',
                background: '#f0fdf4',
                color: '#15803d',
                borderRadius: '6px',
                padding: '2px 6px',
              }}
            >
              셀프
            </span>
          )}
        </div>
        <FuelGradeBadge label={station.grade_label} />
      </div>

      <div style={{ fontWeight: 600, fontSize: '15px', color: '#111827' }}>{station.name}</div>
      <div style={{ fontSize: '12px', color: '#6b7280' }}>{station.address}</div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '4px' }}>
        <div>
          {station.price != null ? (
            <span style={{ fontSize: '18px', fontWeight: 700, color: '#111827' }} data-testid="fuel-price">
              ₩{station.price.toLocaleString()}
              <span style={{ fontSize: '12px', color: '#6b7280', fontWeight: 400 }}>/L</span>
            </span>
          ) : (
            <span style={{ fontSize: '14px', color: '#9ca3af' }}>가격 정보 없음</span>
          )}
        </div>
        {station.distance_km != null && (
          <span style={{ fontSize: '12px', color: '#6b7280' }} data-testid="fuel-distance">
            📍 {station.distance_km.toFixed(1)}km
          </span>
        )}
      </div>
    </div>
  )
}

// ── 메인 페이지 ───────────────────────────────────────────────────────────────

export default function FuelStationsPage() {
  const [searchParams, setSearchParams] = useSearchParams()

  const [regions, setRegions] = useState<FuelRegions | null>(null)
  const [sigunguList, setSigunguList] = useState<string[]>([])
  const [result, setResult] = useState<FuelSearchResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [geoLoading, setGeoLoading] = useState(false)

  const [sido, setSido] = useState(searchParams.get('sido') ?? '')
  const [sigungu, setSigungu] = useState(searchParams.get('sigungu') ?? '')
  const [brand, setBrand] = useState(searchParams.get('brand') ?? '')
  const [fuelKind, setFuelKind] = useState<FuelKind>(
    (searchParams.get('fuel_kind') as FuelKind) ?? 'gasoline_regular'
  )
  const [sort, setSort] = useState(searchParams.get('sort') ?? 'price_asc')
  const [userLat, setUserLat] = useState<number | null>(null)
  const [userLng, setUserLng] = useState<number | null>(null)

  // 지역 메타 로드
  useEffect(() => {
    fetchFuelRegions()
      .then(setRegions)
      .catch(() => setRegions(null))
  }, [])

  // 시도 변경 시 시군구 목록 갱신
  useEffect(() => {
    if (!sido) {
      setSigunguList([])
      return
    }
    fetchFuelRegions(sido)
      .then(r => setSigunguList(r.sigungu_list))
      .catch(() => setSigunguList([]))
  }, [sido])

  const handleSearch = useCallback(() => {
    const params: Record<string, string> = {}
    if (sido) params.sido = sido
    if (sigungu) params.sigungu = sigungu
    if (brand) params.brand = brand
    params.fuel_kind = fuelKind
    params.sort = sort
    setSearchParams(params)

    setLoading(true)
    setError(null)

    const reqParams: Parameters<typeof searchFuelStations>[0] = {
      sido: sido || undefined,
      sigungu: sigungu || undefined,
      brand: brand || undefined,
      fuel_kind: fuelKind,
      sort,
    }
    if (userLat != null && userLng != null) {
      reqParams.lat = userLat
      reqParams.lng = userLng
      if (sort === 'distance') {
        reqParams.radius_km = 5
      }
    }

    searchFuelStations(reqParams)
      .then(data => {
        setResult(data)
        setLoading(false)
      })
      .catch(e => {
        setError(e.message)
        setLoading(false)
      })
  }, [sido, sigungu, brand, fuelKind, sort, userLat, userLng, setSearchParams])

  const handleUseMyLocation = useCallback(() => {
    if (!navigator.geolocation) {
      setError('브라우저에서 위치 정보를 지원하지 않습니다.')
      return
    }
    setGeoLoading(true)
    navigator.geolocation.getCurrentPosition(
      pos => {
        // 위치정보는 클라이언트 측 일회성 사용 — 저장 금지
        setUserLat(pos.coords.latitude)
        setUserLng(pos.coords.longitude)
        setSort('distance')
        setGeoLoading(false)
      },
      () => {
        setError('위치 정보를 가져올 수 없습니다.')
        setGeoLoading(false)
      }
    )
  }, [])

  const selectStyle = {
    padding: '8px 12px',
    border: '1px solid #d1d5db',
    borderRadius: '8px',
    fontSize: '14px',
    background: '#fff',
    cursor: 'pointer',
    minWidth: '120px',
  } as const

  const btnStyle = {
    padding: '8px 20px',
    background: '#2563eb',
    color: '#fff',
    border: 'none',
    borderRadius: '8px',
    fontWeight: 600,
    fontSize: '14px',
    cursor: 'pointer',
  } as const

  return (
    <div style={{ maxWidth: '1200px', margin: '0 auto', padding: '24px 16px' }}>
      {/* 헤더 */}
      <header style={{ marginBottom: '24px' }}>
        <h1 style={{ fontSize: '24px', fontWeight: 700, margin: '0 0 4px' }}>
          ⛽ 주유소 가격 비교
        </h1>
        <p style={{ color: '#6b7280', margin: 0, fontSize: '14px' }}>
          오피넷 기준 지역별 저가 주유소 — 실시간 가격 · 등급 확인
        </p>
      </header>

      {/* 필터 패널 */}
      <div
        style={{
          background: '#f9fafb',
          border: '1px solid #e5e7eb',
          borderRadius: '12px',
          padding: '20px',
          marginBottom: '24px',
          display: 'flex',
          flexWrap: 'wrap',
          gap: '12px',
          alignItems: 'flex-end',
        }}
      >
        {/* 시도 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          <label style={{ fontSize: '12px', color: '#374151', fontWeight: 500 }}>시도</label>
          <select
            style={selectStyle}
            value={sido}
            onChange={e => { setSido(e.target.value); setSigungu('') }}
            data-testid="sido-select"
          >
            <option value="">전체</option>
            {regions?.sido_list.map(s => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>

        {/* 시군구 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          <label style={{ fontSize: '12px', color: '#374151', fontWeight: 500 }}>시군구</label>
          <select
            style={selectStyle}
            value={sigungu}
            onChange={e => setSigungu(e.target.value)}
            disabled={!sido}
            data-testid="sigungu-select"
          >
            <option value="">전체</option>
            {sigunguList.map(sg => (
              <option key={sg} value={sg}>{sg}</option>
            ))}
          </select>
        </div>

        {/* 브랜드 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          <label style={{ fontSize: '12px', color: '#374151', fontWeight: 500 }}>브랜드</label>
          <select
            style={selectStyle}
            value={brand}
            onChange={e => setBrand(e.target.value)}
            data-testid="brand-select"
          >
            <option value="">전체</option>
            {regions?.brand_list.map(b => (
              <option key={b} value={b}>{b}</option>
            ))}
          </select>
        </div>

        {/* 유종 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          <label style={{ fontSize: '12px', color: '#374151', fontWeight: 500 }}>유종</label>
          <div style={{ display: 'flex', gap: '6px' }} role="radiogroup" aria-label="유종 선택">
            {FUEL_KIND_OPTIONS.map(opt => (
              <label
                key={opt.value}
                style={{
                  padding: '7px 14px',
                  border: `1px solid ${fuelKind === opt.value ? '#2563eb' : '#d1d5db'}`,
                  borderRadius: '8px',
                  background: fuelKind === opt.value ? '#eff6ff' : '#fff',
                  color: fuelKind === opt.value ? '#2563eb' : '#374151',
                  fontSize: '13px',
                  fontWeight: fuelKind === opt.value ? 600 : 400,
                  cursor: 'pointer',
                }}
              >
                <input
                  type="radio"
                  name="fuel_kind"
                  value={opt.value}
                  checked={fuelKind === opt.value}
                  onChange={() => setFuelKind(opt.value)}
                  style={{ display: 'none' }}
                  data-testid={`fuel-kind-${opt.value}`}
                />
                {opt.label}
              </label>
            ))}
          </div>
        </div>

        {/* 정렬 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          <label style={{ fontSize: '12px', color: '#374151', fontWeight: 500 }}>정렬</label>
          <div style={{ display: 'flex', gap: '6px' }} role="radiogroup" aria-label="정렬 방식">
            {SORT_OPTIONS.map(opt => (
              <label
                key={opt.value}
                style={{
                  padding: '7px 14px',
                  border: `1px solid ${sort === opt.value ? '#2563eb' : '#d1d5db'}`,
                  borderRadius: '8px',
                  background: sort === opt.value ? '#eff6ff' : '#fff',
                  color: sort === opt.value ? '#2563eb' : '#374151',
                  fontSize: '13px',
                  fontWeight: sort === opt.value ? 600 : 400,
                  cursor: 'pointer',
                }}
              >
                <input
                  type="radio"
                  name="sort"
                  value={opt.value}
                  checked={sort === opt.value}
                  onChange={() => setSort(opt.value)}
                  style={{ display: 'none' }}
                  data-testid={`sort-${opt.value}`}
                />
                {opt.label}
              </label>
            ))}
          </div>
        </div>

        {/* 내 위치 사용 버튼 */}
        <button
          onClick={handleUseMyLocation}
          disabled={geoLoading}
          style={{
            ...btnStyle,
            background: userLat != null ? '#059669' : '#6b7280',
          }}
          data-testid="use-my-location"
          title="내 위치 기준 반경 5km 주유소 검색"
        >
          {geoLoading ? '위치 확인 중…' : userLat != null ? '📍 위치 사용 중' : '📍 내 위치 사용'}
        </button>

        {/* 검색 버튼 */}
        <button onClick={handleSearch} style={btnStyle} data-testid="search-btn">
          검색
        </button>
      </div>

      {/* 요약 바 */}
      {result?.summary && (
        <div
          style={{
            display: 'flex',
            gap: '24px',
            flexWrap: 'wrap',
            marginBottom: '16px',
            padding: '12px 16px',
            background: '#eff6ff',
            borderRadius: '8px',
            fontSize: '14px',
          }}
          data-testid="fuel-summary"
        >
          <span>
            <strong>{result.summary.region || '전체'}</strong>{' '}
            {result.summary.fuel_kind_label}
          </span>
          {result.summary.avg_price != null && (
            <span>평균가: <strong>₩{result.summary.avg_price.toLocaleString()}/L</strong></span>
          )}
          {result.summary.min_price != null && (
            <span>최저가: <strong style={{ color: '#16a34a' }}>₩{result.summary.min_price.toLocaleString()}/L</strong></span>
          )}
          <span>총 {result.summary.station_count}개 주유소</span>
        </div>
      )}

      {/* 에러 */}
      {error && (
        <p style={{ color: '#dc2626', marginBottom: '16px' }}>⚠ {error}</p>
      )}

      {/* 로딩 */}
      {loading && (
        <p style={{ color: '#9ca3af', marginBottom: '16px' }}>로딩 중…</p>
      )}

      {/* 결과 없음 */}
      {!loading && result && result.items.length === 0 && !error && (
        <p style={{ color: '#9ca3af' }}>
          조건에 맞는 주유소가 없습니다. 지역을 선택하고 검색해 주세요.
        </p>
      )}

      {/* 결과 없음 — 초기 상태 */}
      {!loading && !result && !error && (
        <p style={{ color: '#9ca3af' }}>
          지역·유종을 선택하고 검색 버튼을 눌러 주세요.
        </p>
      )}

      {/* 주유소 카드 목록 */}
      {result && result.items.length > 0 && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
            gap: '16px',
          }}
        >
          {result.items.map(station => (
            <FuelStationCard key={station.id} station={station} />
          ))}
        </div>
      )}

      {/* 범례 */}
      <div style={{ marginTop: '32px', padding: '16px', background: '#f9fafb', borderRadius: '8px', fontSize: '12px', color: '#6b7280' }}>
        <strong>등급 기준</strong>: 시군구 내 동일 유종 가격 기준 하위 25% 이하 = 💚 저렴 / 상위 25% 초과 = 🔴 비쌈 / 그 외 = 보통
        <span style={{ marginLeft: '16px' }}>출처: 오피넷(한국석유공사)</span>
      </div>
    </div>
  )
}
