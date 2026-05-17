import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchBoards } from '../api/client'
import type { Board } from '../types'

export default function BoardListPage() {
  const [boards, setBoards] = useState<Board[]>([])
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    fetchBoards().then((b) => {
      setBoards(b)
      setLoading(false)
    })
  }, [])
  if (loading) return <div style={{ padding: 20 }}>로딩 중...</div>
  return (
    <div style={{ maxWidth: 800, margin: '20px auto', padding: 20 }}>
      <h2>게시판</h2>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {boards.map((b) => (
          <Link
            to={`/board/${b.slug}`}
            key={b.slug}
            style={{
              padding: 16,
              borderRadius: 12,
              background: '#f9fafb',
              color: '#374151',
              textDecoration: 'none',
              border: '1px solid #e5e7eb',
            }}
          >
            <div style={{ fontWeight: 700, fontSize: 18 }}>{b.name}</div>
            <div style={{ color: '#6b7280', fontSize: 14 }}>{b.description}</div>
            <div style={{ color: '#9ca3af', fontSize: 12, marginTop: 4 }}>
              카테고리 {b.category_count}개
            </div>
          </Link>
        ))}
      </div>
    </div>
  )
}
