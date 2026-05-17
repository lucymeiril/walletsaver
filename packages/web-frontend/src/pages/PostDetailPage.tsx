import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import {
  createComment,
  deletePost,
  fetchMe,
  fetchPost,
  fetchVerdictSummary,
  reportComment,
  reportPost,
} from '../api/client'
import type { AuthUser, Comment, PostDetail, VerdictSummary } from '../types'
import VerdictBar from '../components/VerdictBar'
import GradeBadge2 from '../components/GradeBadge2'

function preprocessBody(body: string, images: PostDetail['images']) {
  return body.replace(/\[\[img:(\d+)\]\]/g, (_m, idx) => {
    const i = parseInt(idx, 10)
    const img = images[i]
    if (!img) return ''
    return `![${img.alt || ''}](${img.image_url})`
  })
}

function VerdictBadge({ v }: { v: Comment['verdict'] }) {
  if (v === 'hot_deal') return <span data-testid="verdict-badge" style={{ background: '#fee2e2', color: '#b91c1c', padding: '2px 6px', borderRadius: 6, fontSize: 12 }}>🔥 핫딜</span>
  if (v === 'not_hot_deal') return <span data-testid="verdict-badge" style={{ background: '#dbeafe', color: '#1d4ed8', padding: '2px 6px', borderRadius: 6, fontSize: 12 }}>❌ 비핫딜</span>
  return <span data-testid="verdict-badge" style={{ background: '#f3f4f6', color: '#6b7280', padding: '2px 6px', borderRadius: 6, fontSize: 12 }}>😐 보통</span>
}

export default function PostDetailPage() {
  const { id = '' } = useParams()
  const nav = useNavigate()
  const [post, setPost] = useState<PostDetail | null>(null)
  const [user, setUser] = useState<AuthUser | null>(null)
  const [summary, setSummary] = useState<VerdictSummary>({ hot_deal: 0, not_hot_deal: 0, neutral: 0 })
  const [cmtBody, setCmtBody] = useState('')
  const [cmtVerdict, setCmtVerdict] = useState<Comment['verdict']>('neutral')

  useEffect(() => { fetchMe().then(setUser).catch(() => {}) }, [])
  useEffect(() => { fetchPost(id).then(setPost) }, [id])
  useEffect(() => {
    if (post) fetchVerdictSummary(post.id).then(setSummary).catch(() => {})
  }, [post?.id, post?.comments.length])

  const rendered = useMemo(
    () => post ? preprocessBody(post.body_markdown, post.images) : '',
    [post]
  )

  if (!post) return <div style={{ padding: 20 }}>로딩 중...</div>

  async function onAddComment(e: React.FormEvent) {
    e.preventDefault()
    if (!cmtBody.trim()) return
    try {
      const c = await createComment(post!.id, cmtBody, cmtVerdict)
      setPost({ ...post!, comments: [...post!.comments, c] })
      setCmtBody('')
    } catch {
      alert('댓글 등록 실패. 로그인 상태를 확인해 주세요.')
    }
  }

  async function onDelete() {
    if (!confirm('삭제하시겠습니까?')) return
    await deletePost(post!.id)
    nav(`/board/${post!.board_slug}`)
  }

  async function onReport() {
    const reason = prompt('신고 사유?')
    if (!reason) return
    try { await reportPost(post!.id, reason); alert('신고되었습니다') } catch { alert('실패') }
  }

  return (
    <div style={{ maxWidth: 800, margin: '20px auto', padding: 20 }}>
      <h2 style={{ marginBottom: 4 }}>{post.title}</h2>
      <div style={{ color: '#6b7280', fontSize: 13 }}>
        {post.user.display_name} · {post.created_at}
      </div>

      {post.board_slug === 'hotdeal' && (
        <div style={{ marginTop: 12 }}>
          <GradeBadge2 dealPrice={post.deal_price} grade={post.grade_summary} />
          {post.deal_url && (
            <div style={{ marginTop: 8 }}>
              <a href={post.deal_url} target="_blank" rel="noreferrer">{post.mart_name || '딜 페이지'} →</a>
            </div>
          )}
        </div>
      )}

      <div style={{ marginTop: 16, lineHeight: 1.6, color: '#374151' }}>
        <ReactMarkdown>{rendered}</ReactMarkdown>
      </div>

      <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
        {user && user.user_id === post.user.id && (
          <button onClick={onDelete} style={{ padding: '6px 12px', borderRadius: 8, border: '1px solid #d1d5db', cursor: 'pointer' }}>삭제</button>
        )}
        {user && (
          <button onClick={onReport} style={{ padding: '6px 12px', borderRadius: 8, border: '1px solid #d1d5db', cursor: 'pointer' }}>신고</button>
        )}
      </div>

      <hr style={{ margin: '20px 0' }} />

      <h3>의견</h3>
      <VerdictBar summary={summary} />

      <div style={{ marginTop: 16, display: 'flex', flexDirection: 'column', gap: 8 }}>
        {post.comments.map((c) => (
          <div key={c.id} style={{ padding: 10, background: '#f9fafb', borderRadius: 12, border: '1px solid #e5e7eb' }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 4 }}>
              <strong style={{ fontSize: 13 }}>{c.user.display_name}</strong>
              <VerdictBadge v={c.verdict} />
              <span style={{ flex: 1 }} />
              {user && (
                <button
                  onClick={async () => {
                    const r = prompt('사유?')
                    if (r) { await reportComment(c.id, r); alert('신고되었습니다') }
                  }}
                  style={{ fontSize: 12, background: 'transparent', border: 'none', color: '#9ca3af', cursor: 'pointer' }}
                >
                  신고
                </button>
              )}
            </div>
            <div style={{ fontSize: 14 }}>{c.body}</div>
          </div>
        ))}
      </div>

      {user ? (
        <form onSubmit={onAddComment} style={{ marginTop: 16, display: 'flex', flexDirection: 'column', gap: 8 }}>
          <textarea
            placeholder="댓글"
            value={cmtBody}
            onChange={(e) => setCmtBody(e.target.value)}
            rows={3}
            style={{ padding: 10, borderRadius: 8, border: '1px solid #d1d5db' }}
          />
          <div style={{ display: 'flex', gap: 12, fontSize: 14 }}>
            <label><input type="radio" checked={cmtVerdict === 'hot_deal'} onChange={() => setCmtVerdict('hot_deal')} /> 🔥 핫딜</label>
            <label><input type="radio" checked={cmtVerdict === 'neutral'} onChange={() => setCmtVerdict('neutral')} /> 😐 보통</label>
            <label><input type="radio" checked={cmtVerdict === 'not_hot_deal'} onChange={() => setCmtVerdict('not_hot_deal')} /> ❌ 비핫딜</label>
            <span style={{ flex: 1 }} />
            <button type="submit" style={{ padding: '6px 12px', borderRadius: 8, background: '#374151', color: 'white', border: 'none', cursor: 'pointer' }}>댓글 작성</button>
          </div>
        </form>
      ) : (
        <div style={{ marginTop: 16, color: '#6b7280' }}>댓글을 작성하려면 로그인하세요.</div>
      )}
    </div>
  )
}
