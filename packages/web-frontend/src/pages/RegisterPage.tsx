import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { register, login } from '../api/client'

export default function RegisterPage() {
  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const nav = useNavigate()

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setErr(null)
    setBusy(true)
    try {
      await register(email, displayName, password)
      await login(email, password)
      nav('/')
    } catch (e: any) {
      setErr('회원가입 실패. 이미 사용 중인 이메일일 수 있습니다.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ maxWidth: 400, margin: '40px auto', padding: 24 }}>
      <h2>회원가입</h2>
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
          placeholder="닉네임"
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          required
          style={{ padding: 10, borderRadius: 8, border: '1px solid #d1d5db' }}
        />
        <input
          type="password"
          placeholder="비밀번호 (6자 이상)"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          minLength={6}
          style={{ padding: 10, borderRadius: 8, border: '1px solid #d1d5db' }}
        />
        {err && <div style={{ color: '#b91c1c' }}>{err}</div>}
        <button
          type="submit"
          disabled={busy}
          style={{ padding: 10, borderRadius: 8, background: '#374151', color: 'white', border: 'none', cursor: 'pointer' }}
        >
          {busy ? '...' : '회원가입'}
        </button>
      </form>
      <p style={{ marginTop: 12 }}>
        이미 계정이 있으신가요? <Link to="/login">로그인</Link>
      </p>
    </div>
  )
}
