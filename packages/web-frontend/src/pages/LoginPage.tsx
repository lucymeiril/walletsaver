import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { login } from '../api/client'

export default function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const nav = useNavigate()

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setErr(null)
    setBusy(true)
    try {
      await login(email, password)
      nav('/')
    } catch (e: any) {
      setErr('로그인 실패: 이메일/비밀번호를 확인해 주세요.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ maxWidth: 400, margin: '40px auto', padding: 24 }}>
      <h2>로그인</h2>
      <form onSubmit={onSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <input
          type="email"
          placeholder="이메일"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          style={{ padding: 10, borderRadius: 8, border: '1px solid #d1d5db' }}
        />
        <input
          type="password"
          placeholder="비밀번호"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          style={{ padding: 10, borderRadius: 8, border: '1px solid #d1d5db' }}
        />
        {err && <div style={{ color: '#b91c1c' }}>{err}</div>}
        <button
          type="submit"
          disabled={busy}
          style={{ padding: 10, borderRadius: 8, background: '#374151', color: 'white', border: 'none', cursor: 'pointer' }}
        >
          {busy ? '...' : '로그인'}
        </button>
      </form>
      <p style={{ marginTop: 12 }}>
        계정이 없으신가요? <Link to="/register">회원가입</Link>
      </p>
    </div>
  )
}
