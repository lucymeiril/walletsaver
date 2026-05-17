import { useState, useEffect } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { CategoryTree } from '../components/CategoryTree'
import { ProductCard } from '../components/ProductCard'
import { fetchCategories, searchProducts } from '../api/client'
import type { CategoryNode, ProductSummary } from '../types'

export default function CategoryPage() {
  const { slug } = useParams<{ slug: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const sortParam = searchParams.get('sort') ?? 'recent'
  const pageParam = parseInt(searchParams.get('page') ?? '1', 10)

  const [allCategories, setAllCategories] = useState<CategoryNode[]>([])
  const [products, setProducts] = useState<ProductSummary[]>([])
  const [total, setTotal] = useState(0)
  const [totalPages, setTotalPages] = useState(1)
  const [loading, setLoading] = useState(false)
  const [activeId, setActiveId] = useState<string | undefined>()

  useEffect(() => {
    fetchCategories()
      .then((data) => {
        setAllCategories(data.categories as CategoryNode[])
        // Find category id by slug
        const findBySlug = (nodes: CategoryNode[]): CategoryNode | undefined => {
          for (const n of nodes) {
            if (n.name_slug === slug) return n
            const found = findBySlug(n.children ?? [])
            if (found) return found
          }
        }
        const cat = findBySlug(data.categories)
        setActiveId(cat?.id)
      })
      .catch(() => {})
  }, [slug])

  useEffect(() => {
    setLoading(true)
    searchProducts({ category: activeId, sort: sortParam, page: pageParam })
      .then((data) => {
        setProducts(data.items)
        setTotal(data.total)
        setTotalPages(data.total_pages)
        setLoading(false)
      })
      .catch(() => {
        setProducts([])
        setLoading(false)
      })
  }, [activeId, sortParam, pageParam])

  return (
    <div style={{ display: 'flex', maxWidth: '1200px', margin: '0 auto', padding: '24px 16px', gap: '24px' }}>
      {/* Sidebar */}
      <aside style={{ width: '220px', flexShrink: 0 }}>
        <h2 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '12px' }}>카테고리</h2>
        <CategoryTree nodes={allCategories} activeId={activeId} />
      </aside>

      {/* Main */}
      <main style={{ flex: 1 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <h1 style={{ fontSize: '20px', fontWeight: 700, margin: 0 }}>
            {slug ?? '전체'} ({total}건)
          </h1>
          <select
            value={sortParam}
            onChange={(e) => setSearchParams({ sort: e.target.value, page: '1' })}
            style={{ padding: '6px 10px', borderRadius: '6px', border: '1px solid #e5e7eb' }}
          >
            <option value="recent">최신순</option>
            <option value="hot_deal">핫딜 순</option>
            <option value="price_asc">낮은 가격순</option>
            <option value="price_desc">높은 가격순</option>
          </select>
        </div>

        {loading && <p style={{ color: '#9ca3af' }}>로딩 중...</p>}
        {!loading && products.length === 0 && (
          <p style={{ color: '#9ca3af' }}>이 카테고리에 상품이 없습니다.</p>
        )}

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))',
            gap: '16px',
          }}
        >
          {products.map((p) => (
            <ProductCard key={p.canonical_id} product={p} />
          ))}
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div style={{ display: 'flex', gap: '8px', marginTop: '24px', justifyContent: 'center' }}>
            {Array.from({ length: totalPages }, (_, i) => i + 1).map((pg) => (
              <button
                key={pg}
                onClick={() => setSearchParams({ sort: sortParam, page: String(pg) })}
                style={{
                  padding: '6px 12px',
                  borderRadius: '6px',
                  border: '1px solid #e5e7eb',
                  background: pg === pageParam ? '#2563eb' : '#fff',
                  color: pg === pageParam ? '#fff' : '#374151',
                  cursor: 'pointer',
                }}
              >
                {pg}
              </button>
            ))}
          </div>
        )}
      </main>
    </div>
  )
}
