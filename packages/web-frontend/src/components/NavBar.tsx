import { Link, useNavigate } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { fetchMe, logout } from '../api/client'
import type { AuthUser } from '../types'

export default function NavBar() {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loaded, setLoaded] = useState(false)
  const nav = useNavigate()

  useEffect(() => {
    fetchMe().then((u) => {
      setUser(u)
      setLoaded(true)
    }).catch(() => setLoaded(true))
  }, [])

  async function onLogout() {
    await logout()
    setUser(null)
    nav('/')
  }

  const linkStyle: React.CSSProperties = {
    color: '#374151',
    textDecoration: 'none',
    padding: '6px 10px',
    borderRadius: 8,
  }

  return (
    <nav
      style={{
        display: 'flex',
        gap: 4,
        alignItems: 'center',
        padding: '10px 20px',
        background: '#f9fafb',
        borderBottom: '1px solid #e5e7eb',
        marginBottom: 16,
      }}
    >
      <Link to="/" style={{ ...linkStyle, fontWeight: 700 }}>WalletSavior</Link>
      <Link to="/boards" style={linkStyle}>게시판</Link>
      <Link to="/board/hotdeal" style={linkStyle}>핫딜</Link>
      <Link to="/board/free" style={linkStyle}>자유</Link>
      <span style={{ flex: 1 }} />
      {loaded && !user && (
        <>
          <Link to="/login" style={linkStyle}>로그인</Link>
          <Link to="/register" style={linkStyle}>회원가입</Link>
        </>
      )}
      {loaded && user && (
        <>
          {(user.role === 'admin' || user.role === 'moderator') && (
            <Link to="/admin" style={{ ...linkStyle, color: '#b91c1c' }}>관리자</Link>
          )}
          <Link to="/account" style={linkStyle}>{user.display_name}</Link>
          <button
            onClick={onLogout}
            style={{
              ...linkStyle,
              background: 'transparent',
              border: '1px solid #d1d5db',
              cursor: 'pointer',
            }}
          >
            로그아웃
          </button>
        </>
      )}
    </nav>
  )
}
