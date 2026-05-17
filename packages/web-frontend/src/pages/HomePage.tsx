import { useState, useEffect, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { SearchBar } from '../components/SearchBar'
import { ProductCard } from '../components/ProductCard'
import { fetchCategories, searchProducts } from '../api/client'
import type { CategoryNode, ProductSummary } from '../types'

const TOP_CATEGORIES = ['신선식품', '가공식품', '유제품', '조미료', '음료', '생활용품']

export default function HomePage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const q = searchParams.get('q') ?? ''

  const [hotDeals, setHotDeals] = useState<ProductSummary[]>([])
  const [searchResults, setSearchResults] = useState<ProductSummary[]>([])
  const [rootCategories, setRootCategories] = useState<CategoryNode[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchCategories()
      .then((data) => setRootCategories((data.categories as CategoryNode[]).filter((c) => c.level === 1)))
      .catch(() => setRootCategories([]))
  }, [])

  useEffect(() => {
    if (q) {
      setLoading(true)
      setError(null)
      searchProducts({ q, sort: 'recent' })
        .then((data) => {
          setSearchResults(data.items)
          setLoading(false)
        })
        .catch((e) => {
          setError(e.message)
          setLoading(false)
        })
    } else {
      setSearchResults([])
      setLoading(true)
      searchProducts({ sort: 'hot_deal', page_size: 12 } as Parameters<typeof searchProducts>[0])
        .then((data) => {
          setHotDeals(data.items)
          setLoading(false)
        })
        .catch(() => {
          setHotDeals([])
          setLoading(false)
        })
    }
  }, [q])

  const handleSearch = useCallback(
    (newQ: string) => {
      setSearchParams(newQ ? { q: newQ } : {})
    },
    [setSearchParams]
  )

  const displayProducts = q ? searchResults : hotDeals

  return (
    <div style={{ maxWidth: '1200px', margin: '0 auto', padding: '24px 16px' }}>
      {/* Hero */}
      <header style={{ textAlign: 'center', marginBottom: '32px' }}>
        <h1 style={{ fontSize: '28px', fontWeight: 700, margin: '0 0 8px' }}>
          💰 WalletSavior
        </h1>
        <p style={{ color: '#6b7280', margin: '0 0 20px' }}>
          마트 4사 데이터 기반 <strong>진짜 핫딜</strong>을 한눈에
        </p>
        <div style={{ display: 'flex', justifyContent: 'center' }}>
          <SearchBar onSearch={handleSearch} initialQuery={q} />
        </div>
      </header>

      {/* Category tiles */}
      {!q && (
        <section aria-label="카테고리">
          <h2 style={{ fontSize: '18px', fontWeight: 600, marginBottom: '12px' }}>카테고리</h2>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))',
              gap: '12px',
              marginBottom: '32px',
            }}
          >
            {rootCategories.length > 0
              ? rootCategories.map((cat) => (
                  <a
                    key={cat.id}
                    href={`/c/${cat.name_slug}`}
                    style={{
                      padding: '16px',
                      textAlign: 'center',
                      border: '1px solid #e5e7eb',
                      borderRadius: '12px',
                      textDecoration: 'none',
                      color: '#374151',
                      background: '#f9fafb',
                      fontWeight: 500,
                    }}
                  >
                    {cat.name_kr}
                  </a>
                ))
              : TOP_CATEGORIES.map((name) => (
                  <div
                    key={name}
                    style={{
                      padding: '16px',
                      textAlign: 'center',
                      border: '1px solid #e5e7eb',
                      borderRadius: '12px',
                      background: '#f9fafb',
                      fontWeight: 500,
                      color: '#9ca3af',
                    }}
                  >
                    {name}
                  </div>
                ))}
          </div>
        </section>
      )}

      {/* Products section */}
      <section aria-label={q ? '검색 결과' : '오늘의 핫딜'}>
        <h2 style={{ fontSize: '18px', fontWeight: 600, marginBottom: '12px' }}>
          {q ? `"${q}" 검색 결과` : '오늘의 핫딜 TOP 12'}
        </h2>
        {error && (
          <p style={{ color: '#dc2626' }}>오류: {error}</p>
        )}
        {loading && <p style={{ color: '#9ca3af' }}>로딩 중...</p>}
        {!loading && displayProducts.length === 0 && !error && (
          <p style={{ color: '#9ca3af' }}>
            {q ? '검색 결과가 없습니다.' : '스냅샷이 없거나 핫딜 상품이 없습니다.'}
          </p>
        )}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
            gap: '16px',
          }}
        >
          {displayProducts.map((p) => (
            <ProductCard key={p.canonical_id} product={p} />
          ))}
        </div>
      </section>
    </div>
  )
}
