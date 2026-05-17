import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { createPost, fetchBoardCategories } from '../api/client'
import type { BoardCategory } from '../types'

export default function NewPostPage() {
  const { slug = '' } = useParams()
  const nav = useNavigate()
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [cats, setCats] = useState<BoardCategory[]>([])
  const [categoryId, setCategoryId] = useState('')
  const [freeform, setFreeform] = useState('')
  const [canonicalId, setCanonicalId] = useState('')
  const [dealPrice, setDealPrice] = useState('')
  const [martName, setMartName] = useState('')
  const [dealUrl, setDealUrl] = useState('')
  const [images, setImages] = useState<File[]>([])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    fetchBoardCategories(slug).then(setCats).catch(() => {})
  }, [slug])

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setErr(null)
    setBusy(true)
    try {
      const fd = new FormData()
      fd.append('title', title)
      fd.append('body_markdown', body)
      if (categoryId) fd.append('category_id', categoryId)
      if (freeform) fd.append('freeform_category', freeform)
      if (slug === 'hotdeal') {
        if (canonicalId) fd.append('canonical_id', canonicalId)
        if (dealPrice) fd.append('deal_price', dealPrice)
        if (martName) fd.append('mart_name', martName)
        if (dealUrl) fd.append('deal_url', dealUrl)
      }
      for (const f of images) fd.append('images', f)
      const post = await createPost(slug, fd)
      nav(`/post/${post.id}`)
    } catch (e: any) {
      setErr('작성 실패. 로그인 상태를 확인해 주세요.')
    } finally {
      setBusy(false)
    }
  }

  const input: React.CSSProperties = {
    padding: 10,
    borderRadius: 8,
    border: '1px solid #d1d5db',
  }

  return (
    <div style={{ maxWidth: 800, margin: '20px auto', padding: 20 }}>
      <h2>새 글 쓰기 — {slug}</h2>
      <form onSubmit={onSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <input
          aria-label="title"
          placeholder="제목"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          required
          style={input}
        />
        <textarea
          aria-label="body"
          placeholder="본문 (마크다운). 이미지 참조: [[img:0]]"
          value={body}
          onChange={(e) => setBody(e.target.value)}
          required
          rows={10}
          style={input}
        />
        <div style={{ display: 'flex', gap: 8 }}>
          <select value={categoryId} onChange={(e) => setCategoryId(e.target.value)} style={input}>
            <option value="">카테고리 선택</option>
            {cats.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
          <input
            placeholder="자유 카테고리"
            value={freeform}
            onChange={(e) => setFreeform(e.target.value)}
            style={{ ...input, flex: 1 }}
          />
        </div>

        {slug === 'hotdeal' && (
          <fieldset style={{ border: '1px solid #e5e7eb', borderRadius: 12, padding: 12 }}>
            <legend>핫딜 정보</legend>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <input placeholder="canonical_id (DB 상품 ID)" value={canonicalId} onChange={(e) => setCanonicalId(e.target.value)} style={input} />
              <input placeholder="가격 (원)" type="number" value={dealPrice} onChange={(e) => setDealPrice(e.target.value)} style={input} />
              <input placeholder="마트명" value={martName} onChange={(e) => setMartName(e.target.value)} style={input} />
              <input placeholder="딜 URL" value={dealUrl} onChange={(e) => setDealUrl(e.target.value)} style={input} />
            </div>
          </fieldset>
        )}

        <input
          type="file"
          multiple
          accept="image/*"
          onChange={(e) => setImages(Array.from(e.target.files || []))}
        />
        {images.length > 0 && (
          <div style={{ fontSize: 13, color: '#6b7280' }}>
            첨부 이미지: {images.length}개
          </div>
        )}

        {err && <div style={{ color: '#b91c1c' }}>{err}</div>}

        <button
          type="submit"
          disabled={busy || !title.trim() || !body.trim()}
          style={{
            padding: 12,
            borderRadius: 8,
            background: '#ef4444',
            color: 'white',
            border: 'none',
            cursor: 'pointer',
            opacity: !title.trim() || !body.trim() ? 0.5 : 1,
          }}
        >
          {busy ? '게시 중...' : '게시'}
        </button>
      </form>
    </div>
  )
}
