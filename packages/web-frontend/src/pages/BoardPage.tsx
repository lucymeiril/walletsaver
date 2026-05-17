import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { fetchBoardCategories, fetchBoardPosts, fetchMe } from '../api/client'
import type { AuthUser, BoardCategory, PaginatedPosts } from '../types'

export default function BoardPage() {
  const { slug = '' } = useParams()
  const [posts, setPosts] = useState<PaginatedPosts | null>(null)
  const [cats, setCats] = useState<BoardCategory[]>([])
  const [user, setUser] = useState<AuthUser | null>(null)
  const [cat, setCat] = useState<string>('')
  const [q, setQ] = useState('')
  const [sort, setSort] = useState('recent')
  const [page, setPage] = useState(1)

  useEffect(() => {
    fetchMe().then(setUser).catch(() => {})
  }, [])

  useEffect(() => {
    setCats([])
    fetchBoardCategories(slug).then(setCats).catch(() => {})
  }, [slug])

  useEffect(() => {
    fetchBoardPosts(slug, { category: cat || undefined, q: q || undefined, sort, page })
      .then(setPosts)
      .catch(() => setPosts(null))
  }, [slug, cat, q, sort, page])

  return (
    <div style={{ maxWidth: 900, margin: '20px auto', padding: 20 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <h2 style={{ margin: 0 }}>{slug === 'hotdeal' ? '핫딜 게시판' : slug === 'free' ? '자유 게시판' : slug}</h2>
        <span style={{ flex: 1 }} />
        {user && (
          <Link
            to={`/board/${slug}/new`}
            style={{
              padding: '8px 14px',
              borderRadius: 8,
              background: '#ef4444',
              color: 'white',
              textDecoration: 'none',
            }}
          >
            새 글 쓰기
          </Link>
        )}
      </div>

      <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
        <select value={cat} onChange={(e) => { setCat(e.target.value); setPage(1) }} style={{ padding: 8, borderRadius: 8 }}>
          <option value="">전체</option>
          {cats.map((c) => (
            <option key={c.id} value={c.slug}>{c.name}</option>
          ))}
        </select>
        <select value={sort} onChange={(e) => setSort(e.target.value)} style={{ padding: 8, borderRadius: 8 }}>
          <option value="recent">최신순</option>
          <option value="comments">댓글많은순</option>
          <option value="popular">인기순</option>
        </select>
        <input
          placeholder="검색"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          style={{ padding: 8, borderRadius: 8, border: '1px solid #d1d5db', flex: 1, minWidth: 200 }}
        />
      </div>

      <div style={{ marginTop: 16, display: 'flex', flexDirection: 'column', gap: 8 }}>
        {posts && posts.items.length === 0 && (
          <div style={{ padding: 24, color: '#6b7280', textAlign: 'center' }}>게시글이 없습니다.</div>
        )}
        {posts?.items.map((p) => (
          <Link
            key={p.id}
            to={`/post/${p.id}`}
            style={{
              padding: 12,
              borderRadius: 12,
              background: '#f9fafb',
              border: '1px solid #e5e7eb',
              color: '#374151',
              textDecoration: 'none',
              display: 'flex',
              gap: 12,
              alignItems: 'center',
            }}
          >
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 600 }}>{p.title}</div>
              <div style={{ fontSize: 12, color: '#6b7280' }}>
                {p.user.display_name} · 댓글 {p.comment_count}
                {p.freeform_category && <> · #{p.freeform_category}</>}
              </div>
            </div>
            {slug === 'hotdeal' && p.deal_price != null && (
              <div style={{ fontWeight: 700, color: '#ef4444' }}>
                ₩{Math.round(p.deal_price).toLocaleString()}
              </div>
            )}
          </Link>
        ))}
      </div>

      {posts && posts.total_pages > 1 && (
        <div style={{ marginTop: 16, display: 'flex', gap: 8, justifyContent: 'center' }}>
          <button disabled={page <= 1} onClick={() => setPage(page - 1)}>이전</button>
          <span>{page} / {posts.total_pages}</span>
          <button disabled={page >= posts.total_pages} onClick={() => setPage(page + 1)}>다음</button>
        </div>
      )}
    </div>
  )
}
