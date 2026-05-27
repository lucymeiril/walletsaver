import { useCallback, useEffect, useState } from 'react';
import { Eye, MessageSquareWarning, RotateCcw, Search, Trash2 } from 'lucide-react';
import { api } from '../../api/client';
import s from '../Products/Products.module.css';

const TYPE_LABELS = { hotdeal: '핫딜', free: '자유' };

export default function CommunityModeration() {
  const [posts, setPosts] = useState([]);
  const [status, setStatus] = useState('active');
  const [postType, setPostType] = useState('');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [meta, setMeta] = useState({ total: 0, total_pages: 1 });
  const [note, setNote] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const fetchPosts = useCallback(async (nextPage = page) => {
    setLoading(true); setError('');
    try {
      const data = await api.getCommunityPosts({
        status, post_type: postType, search, page: nextPage, per_page: 20,
      });
      setPosts(data.items || []);
      setMeta({ total: data.total || 0, total_pages: data.total_pages || 1 });
      setNote(data.note || '');
    } catch (err) {
      setError(`커뮤니티 게시글 로드 실패: ${err.message}`);
    } finally {
      setLoading(false);
    }
  }, [page, postType, search, status]);

  useEffect(() => { fetchPosts(1); setPage(1); }, [fetchPosts, status, postType]);

  const onSearch = () => { setPage(1); fetchPosts(1); };
  const onDelete = async (id) => {
    if (!confirm('이 게시글을 삭제 처리하시겠습니까?')) return;
    await api.deleteCommunityPost(id);
    fetchPosts(page);
  };
  const onRestore = async (id) => {
    await api.restoreCommunityPost(id);
    fetchPosts(page);
  };
  const openDetail = async (id) => {
    setDetailLoading(true); setError('');
    try {
      setDetail(await api.getCommunityPost(id));
    } catch (err) {
      setError(`게시글 상세 로드 실패: ${err.message}`);
    } finally {
      setDetailLoading(false);
    }
  };
  const toggleCommentDeleted = async (comment) => {
    if (comment.is_deleted) await api.restoreCommunityComment(comment.id);
    else if (confirm('이 댓글을 삭제 처리하시겠습니까?')) await api.deleteCommunityComment(comment.id);
    await openDetail(comment.post_id);
    fetchPosts(page);
  };

  return (
    <div className={s.page}>
      <div className={s.header}>
        <div>
          <h2 className={s.title}>커뮤니티 관리</h2>
          <p className={s.count}>게시글 검색, 삭제 처리, 복구를 관리합니다.</p>
        </div>
      </div>

      <div className={s.sourceTabs}>
        {[
          ['active', '활성'], ['reported', '신고됨'], ['deleted', '삭제됨'], ['all', '전체'],
        ].map(([key, label]) => (
          <button key={key} className={`${s.sourceTab} ${status === key ? s.sourceTabActive : ''}`} onClick={() => setStatus(key)}>
            {label}
          </button>
        ))}
      </div>

      <div className={s.filters}>
        <div className={s.searchWrap}>
          <Search size={16} className={s.searchIcon} />
          <input className={s.searchInput} value={search} onChange={e => setSearch(e.target.value)} onKeyDown={e => e.key === 'Enter' && onSearch()} placeholder="제목, 본문, 작성자 검색..." />
          <button className={s.searchBtn} onClick={onSearch}>검색</button>
        </div>
        <select className={s.select} value={postType} onChange={e => setPostType(e.target.value)}>
          <option value="">전체 유형</option>
          <option value="hotdeal">핫딜</option>
          <option value="free">자유</option>
        </select>
      </div>

      {note && <div className={s.loadingBar}>{note}</div>}
      {error && <div className={s.errorState}><MessageSquareWarning size={20} /><span>{error}</span></div>}
      {loading && <div className={s.loadingBar}>불러오는 중...</div>}

      {!loading && posts.length === 0 ? (
        <div className={s.emptyState}><MessageSquareWarning size={40} /><p>게시글 없음</p><span>조건에 맞는 커뮤니티 게시글이 없습니다.</span></div>
      ) : (
        <div className={s.tableWrap}>
          <table className={s.table}>
            <thead>
              <tr>
                <th>ID</th><th>유형</th><th>제목</th><th>작성자</th><th>댓글/투표</th><th>조회</th><th>상태</th><th>관리</th>
              </tr>
            </thead>
            <tbody>
              {posts.map(post => (
                <tr key={post.id} className={s.row}>
                  <td>{post.id}</td>
                  <td>{TYPE_LABELS[post.post_type] || post.post_type}</td>
                  <td>
                    <div className={s.nameWrap}>
                      <span>{post.title}</span>
                      {post.is_pinned && <span className={s.sourceTag}>고정</span>}
                    </div>
                    <div className={s.count}>{String(post.content || '').slice(0, 80)}</div>
                  </td>
                  <td>{post.author || `#${post.author_id}`}</td>
                  <td>{post.comment_count} / {post.vote_count}</td>
                  <td>{post.view_count}</td>
                  <td><span className={`${s.dealStatus} ${post.is_deleted ? s.statusExpired : s.statusActive}`}>{post.is_deleted ? '삭제됨' : '활성'}</span></td>
                  <td>
                    <div className={s.actions}>
                      <button className={s.iconBtn} onClick={() => openDetail(post.id)} title="내용/댓글 보기"><Eye size={14} /></button>
                      {post.is_deleted ? (
                        <button className={s.iconBtn} onClick={() => onRestore(post.id)} title="복구"><RotateCcw size={14} /></button>
                      ) : (
                        <button className={s.iconBtn} onClick={() => onDelete(post.id)} title="삭제"><Trash2 size={14} /></button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className={s.pagination}>
        <span className={s.count}>총 {meta.total.toLocaleString()}개 게시글</span>
        <div className={s.pageControls}>
          <button className={s.pageBtn} disabled={page <= 1} onClick={() => { const p = page - 1; setPage(p); fetchPosts(p); }}>‹</button>
          <span className={s.pageInfo}>{page} / {meta.total_pages}</span>
          <button className={s.pageBtn} disabled={page >= meta.total_pages} onClick={() => { const p = page + 1; setPage(p); fetchPosts(p); }}>›</button>
        </div>
      </div>

      {detail && (
        <div className={s.overlay} onClick={() => setDetail(null)}>
          <div className={s.modal} onClick={e => e.stopPropagation()}>
            <div className={s.modalHeader}>
              <div>
                <h3>{detail.post?.title}</h3>
                <p className={s.count}>작성자 {detail.post?.author || `#${detail.post?.author_id}`} · 댓글 {detail.comments?.length || 0}개</p>
              </div>
              <button className={s.iconBtn} onClick={() => setDetail(null)}>×</button>
            </div>
            <div className={s.detail}>
              <pre className={s.preWrap}>{detail.post?.content}</pre>
              <h4>댓글 관리</h4>
              {detailLoading && <div className={s.loadingBar}>댓글 불러오는 중...</div>}
              {(detail.comments || []).length === 0 ? (
                <p className={s.count}>댓글이 없습니다.</p>
              ) : (
                <div className={s.commentList}>
                  {detail.comments.map(comment => (
                    <div key={comment.id} className={s.commentItem}>
                      <div>
                        <strong>{comment.author || `#${comment.author_id}`}</strong>
                        <p className={comment.is_deleted ? s.deletedText : ''}>{comment.content}</p>
                      </div>
                      <button className={s.iconBtn} onClick={() => toggleCommentDeleted(comment)} title={comment.is_deleted ? '댓글 복구' : '댓글 삭제'}>
                        {comment.is_deleted ? <RotateCcw size={14} /> : <Trash2 size={14} />}
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
