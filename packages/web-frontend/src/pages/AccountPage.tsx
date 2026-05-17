import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchMe, logout } from '../api/client'
import type { AuthUser } from '../types'

export default function AccountPage() {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)
  const nav = useNavigate()
  useEffect(() => {
    fetchMe().then((u) => {
      setUser(u)
      setLoading(false)
    })
  }, [])
  if (loading) return <div style={{ padding: 20 }}>로딩 중...</div>
  if (!user) {
    return (
      <div style={{ padding: 20 }}>
        <p>로그인이 필요합니다.</p>
      </div>
    )
  }
  return (
    <div style={{ maxWidth: 500, margin: '20px auto', padding: 20 }}>
      <h2>내 계정</h2>
      <div style={{ padding: 16, background: '#f9fafb', borderRadius: 12, color: '#374151' }}>
        <div><strong>닉네임:</strong> {user.display_name}</div>
        <div><strong>이메일:</strong> {user.email}</div>
        <div><strong>역할:</strong> {user.role}</div>
      </div>
      <button
        onClick={async () => { await logout(); nav('/') }}
        style={{ marginTop: 16, padding: 10, borderRadius: 8, background: '#374151', color: 'white', border: 'none', cursor: 'pointer' }}
      >
        로그아웃
      </button>
    </div>
  )
}
