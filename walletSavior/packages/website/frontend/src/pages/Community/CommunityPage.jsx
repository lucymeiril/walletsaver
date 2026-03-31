import { useState, useRef, useEffect, useMemo } from 'react';
import { useLocation } from 'react-router-dom';
import { Pencil, ImagePlus, X, Send, Eye, MessageSquare, Clock, Search } from 'lucide-react';
import { fmt, verifyPrice } from '../../data/mockData';
import useStore from '../../stores/appStore';
import Spinner from '../../components/common/Spinner';
import s from './CommunityPage.module.css';

const BOARD_TABS = [
  { id: 'hotdeal', label: '🔥 핫딜 게시판' },
  { id: 'free', label: '💬 자유 게시판' },
];
const CATS = ['전체', '마트', '온라인', '외식', '기타'];
const FREE_TAGS = ['질문', '정보', '후기', '잡담'];
const WRITE_CATS = ['마트', '온라인', '외식', '기타'];
const POSTS_PER_PAGE = 10;

const VERIFY_STYLES = {
  great_deal: { bg: 'rgba(52,211,153,.1)', color: 'var(--green)', icon: '🔥', border: 'var(--green)' },
  verified:   { bg: 'rgba(56,189,248,.08)', color: 'var(--accent)', icon: '✅', border: 'var(--accent)' },
  sus_low:    { bg: 'rgba(248,113,113,.1)', color: 'var(--red)', icon: '⚠️', border: 'var(--red)' },
  sus_high:   { bg: 'rgba(248,113,113,.1)', color: 'var(--red)', icon: '🚨', border: 'var(--red)' },
};


export default function CommunityPage() {
  const location = useLocation();
  const [board, setBoard] = useState('hotdeal');
  const [filter, setFilter] = useState('전체');
  const [freeTag, setFreeTag] = useState('전체');
  const [showWrite, setShowWrite] = useState(false);
  const [detail, setDetail] = useState(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [sortBy, setSortBy] = useState('popular');
  const [page, setPage] = useState(1);
  const { isLoggedIn, addToast } = useStore();

  const [posts, setPosts] = useState([]);
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(true);

  // Fetch products for price verification
  useEffect(() => {
    fetch('/api/products/search?per_page=50').then(r => r.json())
      .then(res => setProducts(res.data || []))
      .catch(console.error);
  }, []);

  // Fetch posts from API when board changes
  useEffect(() => {
    setLoading(true);
    const params = new URLSearchParams({ board, per_page: '50' });
    fetch(`/api/posts?${params}`).then(r => r.json())
      .then(res => setPosts(res.data || []))
      .catch(err => {
        console.error(err);
        addToast('게시글을 불러오는데 실패했습니다', 'error');
      })
      .finally(() => setLoading(false));
  }, [board]);

  useEffect(() => {
    const openPostId = location.state?.openPostId;
    if (openPostId && posts.length > 0) {
      const post = posts.find((p) => p.id === openPostId);
      if (post) setDetail(post);
      window.history.replaceState({}, '');
    }
  }, [location.state, posts]);

  useEffect(() => {
    setSortBy(board === 'hotdeal' ? 'popular' : 'latest');
    setFilter('전체');
    setFreeTag('전체');
    setPage(1);
    setSearchQuery('');
  }, [board]);

  // Write form state
  const [wTitle, setWTitle] = useState('');
  const [wBody, setWBody] = useState('');
  const [wCat, setWCat] = useState('마트');
  const [wProduct, setWProduct] = useState('');
  const [wPrice, setWPrice] = useState('');
  const [wLink, setWLink] = useState('');
  const [wTag, setWTag] = useState('잡담');
  const [wImages, setWImages] = useState([]);
  const fileRef = useRef(null);

  const filteredAndSorted = useMemo(() => {
    let items = [...posts];

    if (board === 'hotdeal') {
      if (filter !== '전체') items = items.filter(p => p.cat === filter);
    } else {
      if (freeTag !== '전체') items = items.filter(p => p.tag === freeTag);
    }

    if (searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase();
      items = items.filter(p =>
        p.title?.toLowerCase().includes(q) || (p.body && p.body.toLowerCase().includes(q))
      );
    }

    if (sortBy === 'popular') {
      items.sort((a, b) => ((b.hotVotes || 0) - (b.coldVotes || 0)) - ((a.hotVotes || 0) - (a.coldVotes || 0)));
    } else if (sortBy === 'comments') {
      items.sort((a, b) => (b.commentData?.length || b.comments || 0) - (a.commentData?.length || a.comments || 0));
    }

    return items;
  }, [posts, board, filter, freeTag, searchQuery, sortBy]);

  const totalPages = Math.max(1, Math.ceil(filteredAndSorted.length / POSTS_PER_PAGE));
  const safePage = Math.min(page, totalPages);
  const paginatedPosts = filteredAndSorted.slice((safePage - 1) * POSTS_PER_PAGE, safePage * POSTS_PER_PAGE);

  const matchedProduct = products.find(p => wProduct.includes(p.name));
  const verification = wPrice && matchedProduct ? verifyPrice(Number(wPrice), matchedProduct.avg) : null;

  const handleImageAdd = (e) => {
    const files = Array.from(e.target.files);
    files.forEach(f => {
      const reader = new FileReader();
      reader.onload = (ev) => setWImages(prev => [...prev, ev.target.result]);
      reader.readAsDataURL(f);
    });
  };

  const handleWrite = async () => {
    if (!isLoggedIn) {
      addToast('로그인이 필요합니다.', 'error');
      return;
    }
    if (!wTitle.trim()) { addToast('제목을 입력해주세요.', 'error'); return; }
    if (board === 'hotdeal') {
      if (!wProduct.trim()) { addToast('품목명을 입력해주세요.', 'error'); return; }
      if (!wPrice.trim()) { addToast('가격을 입력해주세요.', 'error'); return; }
      if (!wLink.trim()) { addToast('핫딜 링크를 입력해주세요.', 'error'); return; }
    }
    if (verification && !verification.canPost) {
      addToast('허위 가격이 의심되어 등록할 수 없습니다.', 'error');
      return;
    }
    try {
      const resp = await fetch('/api/posts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: wTitle,
          content: wBody,
          board,
          product_name: wProduct || undefined,
          price: wPrice ? Number(wPrice) : undefined,
          category: board === 'hotdeal' ? wCat : undefined,
          link: wLink || undefined,
          tag: board === 'free' ? wTag : undefined,
        }),
      });
      if (resp.ok) {
        addToast('게시글이 등록되었습니다!', 'success');
        setShowWrite(false);
        // Re-fetch posts
        const params = new URLSearchParams({ board, per_page: '50' });
        fetch(`/api/posts?${params}`).then(r => r.json())
          .then(res => setPosts(res.data || []))
          .catch(console.error);
      } else {
        addToast('등록에 실패했습니다.', 'error');
      }
    } catch (err) {
      console.error(err);
      addToast('등록 중 오류가 발생했습니다.', 'error');
    }
    setWTitle(''); setWBody(''); setWProduct(''); setWPrice(''); setWLink(''); setWImages([]);
  };

  const handleWriteBtn = () => {
    if (!isLoggedIn) {
      addToast('로그인이 필요합니다', 'error');
      return;
    }
    setShowWrite(!showWrite);
  };

  const handleFilterChange = (f) => {
    setFilter(f);
    setPage(1);
  };

  const handleTagChange = (t) => {
    setFreeTag(t);
    setPage(1);
  };

  const handleSearchChange = (e) => {
    setSearchQuery(e.target.value);
    setPage(1);
  };

  const handleSortChange = (e) => {
    setSortBy(e.target.value);
    setPage(1);
  };

  const getVerifyBorderColor = (verified) => {
    if (!verified) return 'var(--border)';
    return VERIFY_STYLES[verified]?.border || 'var(--border)';
  };

  return (
    <div>
      <div className={`${s.hdr} ${board === 'hotdeal' ? s.hdrHotdeal : s.hdrFree}`}>
        <div>
          <h2>{board === 'hotdeal' ? '🔥 핫딜 정보를 공유하고 검증하세요' : '💬 자유롭게 이야기를 나눠보세요'}</h2>
          <p>{board === 'hotdeal'
            ? '직접 발견한 할인을 공유하고, 자동으로 시세 비교를 해드립니다'
            : '물가, 절약, 살림에 대해 자유롭게 이야기하세요'}</p>
        </div>
        <button className={s.writeBtn} onClick={handleWriteBtn}>
          <Pencil size={16} /> {isLoggedIn ? '글쓰기' : '로그인 후 글쓰기'}
        </button>
      </div>

      {/* Board Tabs */}
      <div className={s.tabRow}>
        {BOARD_TABS.map(t => (
          <button
            key={t.id}
            className={`${s.mainTab} ${board === t.id ? (t.id === 'hotdeal' ? s.mainTabHotdeal : s.mainTabFree) : ''}`}
            onClick={() => setBoard(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Write Form */}
      {showWrite && (
        <div className={s.writeForm}>
          <div className={s.writeHeader}>
            <h4>📝 {board === 'hotdeal' ? '핫딜 공유' : '자유 게시글'}</h4>
            <button className={s.closeWrite} onClick={() => setShowWrite(false)}><X size={16} /></button>
          </div>

          <input
            className={s.titleInput}
            placeholder="제목을 입력하세요"
            value={wTitle}
            onChange={e => setWTitle(e.target.value)}
          />
          <textarea
            className={s.bodyInput}
            placeholder={board === 'hotdeal'
              ? '내용을 입력하세요 (가격, 매장 위치, 수량 제한 등)'
              : '자유롭게 내용을 입력하세요'}
            rows={5}
            value={wBody}
            onChange={e => setWBody(e.target.value)}
          />

          {board === 'hotdeal' ? (
            <>
              <div className={s.writeRow}>
                <select value={wCat} onChange={e => setWCat(e.target.value)}>
                  {WRITE_CATS.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
                <input
                  placeholder="품목명 (필수 — 자동 시세 비교)"
                  value={wProduct}
                  onChange={e => setWProduct(e.target.value)}
                  list="product-list"
                />
                <datalist id="product-list">
                  {products.map(p => <option key={p.id} value={p.name} />)}
                </datalist>
                <input
                  type="number"
                  placeholder="가격 (원, 필수)"
                  value={wPrice}
                  onChange={e => setWPrice(e.target.value)}
                />
              </div>
              <input
                className={s.linkInput}
                placeholder="핫딜 링크 (필수)"
                value={wLink}
                onChange={e => setWLink(e.target.value)}
              />
            </>
          ) : (
            <div className={s.writeTagRow}>
              <span className={s.writeTagLabel}>태그:</span>
              {FREE_TAGS.map(t => (
                <button
                  key={t}
                  className={`${s.writeTagBtn} ${wTag === t ? s.writeTagActive : ''}`}
                  onClick={() => setWTag(t)}
                >
                  {t}
                </button>
              ))}
            </div>
          )}

          {/* Image Upload */}
          <div className={s.imgUpload}>
            <button className={s.imgBtn} onClick={() => fileRef.current?.click()}>
              <ImagePlus size={18} /> 사진 추가 {board === 'free' && <span className={s.optionalLabel}>(선택)</span>}
            </button>
            <input ref={fileRef} type="file" accept="image/*" multiple hidden onChange={handleImageAdd} />
            {wImages.length > 0 && (
              <div className={s.imgPreview}>
                {wImages.map((src, i) => (
                  <div key={i} className={s.previewWrap}>
                    <img src={src} alt="" />
                    <button className={s.removeImg} onClick={() => setWImages(prev => prev.filter((_, j) => j !== i))}>×</button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Verification (hotdeal only) */}
          {board === 'hotdeal' && verification && (
            <div className={s.verifyResult} style={{
              background: VERIFY_STYLES[verification.status]?.bg || 'var(--glass)',
              color: VERIFY_STYLES[verification.status]?.color || 'var(--text)'
            }}>
              <span>{verification.emoji}</span>
              <span>{verification.label}</span>
              {matchedProduct && <span className={s.verifyDetail}>평균 시세: {fmt(matchedProduct.avg)}원</span>}
            </div>
          )}
          {board === 'hotdeal' && !matchedProduct && wProduct && (
            <div className={s.noMatch}>ℹ️ 시세 데이터에 없는 품목입니다. 검증 없이 등록됩니다.</div>
          )}
          {board === 'hotdeal' && verification && !verification.canPost && (
            <div className={s.blocked}>⛔ 등록 차단됨 — 허위 가격이 의심됩니다.</div>
          )}

          <button className={s.submitBtn} onClick={handleWrite} disabled={board === 'hotdeal' && verification?.canPost === false}>
            등록
          </button>
        </div>
      )}

      {/* Search & Sort */}
      <div className={s.searchSortRow}>
        <div className={s.searchWrap}>
          <Search size={16} className={s.searchIcon} />
          <input
            className={s.searchInput}
            value={searchQuery}
            onChange={handleSearchChange}
            placeholder="게시글 검색..."
            autoComplete="off"
          />
        </div>
        <select className={s.sortSel} value={sortBy} onChange={handleSortChange}>
          {board === 'hotdeal' ? (
            <>
              <option value="popular">인기순</option>
              <option value="latest">최신순</option>
              <option value="comments">댓글순</option>
            </>
          ) : (
            <>
              <option value="latest">최신순</option>
              <option value="comments">댓글순</option>
              <option value="popular">인기순</option>
            </>
          )}
        </select>
      </div>

      {/* Category / Tag Filter */}
      <div className={s.filterRow}>
        {board === 'hotdeal' ? (
          CATS.map(t => (
            <button
              key={t}
              className={`${s.tab} ${filter === t ? s.tabActive : ''}`}
              onClick={() => handleFilterChange(t)}
            >
              {t}
            </button>
          ))
        ) : (
          ['전체', ...FREE_TAGS].map(t => (
            <button
              key={t}
              className={`${s.freeTagBtn} ${freeTag === t ? s.freeTagActive : ''}`}
              onClick={() => handleTagChange(t)}
            >
              {t === '전체' ? '전체' : `#${t}`}
            </button>
          ))
        )}
      </div>

      {loading && <div style={{ display: 'flex', justifyContent: 'center', padding: '2rem 0' }}><Spinner /></div>}

      {/* Post List */}
      <div className={s.list}>
        {board === 'hotdeal' ? (
          paginatedPosts.map(p => (
            <div
              key={p.id}
              className={`${s.post} ${s.hotdealPost}`}
              style={{ borderLeftColor: getVerifyBorderColor(p.verified) }}
              onClick={() => setDetail(p)}
            >
              <div className={s.hotdealVoteCol}>
                <span className={s.hotdealVoteHot}>🔥 {p.hotVotes || 0}</span>
                <span className={s.hotdealVoteCold}>❄️ {p.coldVotes || 0}</span>
              </div>
              <div className={s.postBody}>
                <div className={s.postTitle}>
                  {p.verified && (
                    <span className={s.verifyBadge} style={{
                      background: VERIFY_STYLES[p.verified]?.bg,
                      color: VERIFY_STYLES[p.verified]?.color
                    }}>
                      {VERIFY_STYLES[p.verified]?.icon} 시세 검증
                    </span>
                  )}
                  {p.title}
                </div>
                {p.body && <p className={s.postExcerpt}>{p.body.slice(0, 60)}...</p>}
                <div className={s.postMeta}>
                  <span className={s.postCatInline}>{p.cat}</span>
                  <span>{p.author}</span>
                  <span>{p.time}</span>
                  <span>조회 {p.views}</span>
                  <span>💬 {p.commentData?.length || p.comments}</span>
                </div>
              </div>
              {p.priceVsAvg !== null && (
                <span className={`${s.priceBadge} ${p.priceVsAvg < -20 ? s.cheap : s.avgBadge}`}>
                  평균 대비 {p.priceVsAvg}%
                </span>
              )}
            </div>
          ))
        ) : (
          paginatedPosts.map(p => (
            <div key={p.id} className={`${s.post} ${s.freePost}`} onClick={() => setDetail(p)}>
              <div className={s.postBody}>
                <div className={s.postTitle}>
                  {p.tag && <span className={`${s.tagLabel} ${s[`tag_${p.tag}`] || ''}`}>#{p.tag}</span>}
                  {p.title}
                </div>
                {p.body && <p className={s.postExcerpt}>{p.body.slice(0, 80)}...</p>}
                <div className={s.postMeta}>
                  <span>{p.author}</span>
                  <span>{p.time}</span>
                  <span>👁️ {p.views}</span>
                  <span>💬 {p.commentData?.length || p.comments}</span>
                </div>
              </div>
            </div>
          ))
        )}
        {paginatedPosts.length === 0 && (
          <div className={s.emptyState}>
            {board === 'hotdeal'
              ? '🔥 아직 핫딜이 없습니다. 첫 번째 핫딜을 공유해보세요!'
              : '💬 아직 게시글이 없습니다. 자유롭게 이야기를 시작해보세요!'}
          </div>
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className={s.pagination}>
          <button
            className={s.pageBtn}
            disabled={safePage <= 1}
            onClick={() => setPage(p => Math.max(1, p - 1))}
          >
            ← 이전
          </button>
          <span className={s.pageInfo}>{safePage} / {totalPages}</span>
          <button
            className={s.pageBtn}
            disabled={safePage >= totalPages}
            onClick={() => setPage(p => Math.min(totalPages, p + 1))}
          >
            다음 →
          </button>
        </div>
      )}

      {/* Detail Modal */}
      {detail && <PostDetailModal post={detail} onClose={() => setDetail(null)} board={board} products={products} />}
    </div>
  );
}

function PostDetailModal({ post, onClose, board, products }) {
  const [newComment, setNewComment] = useState('');
  const [comments, setComments] = useState(post?.commentData || []);
  const [vote, setVote] = useState(null);

  const matchedProduct = products.find(p => post.title?.includes(p.name));

  const addComment = () => {
    if (!newComment.trim()) return;
    setComments(prev => [...prev, { id: Date.now(), author: '나', text: newComment, time: '방금 전' }]);
    setNewComment('');
  };

  const handleVote = (type) => {
    setVote(prev => prev === type ? null : type);
  };

  return (
    <div className={s.modalOverlay} onClick={onClose}>
      <div className={s.modal} onClick={e => e.stopPropagation()}>
        <button className={s.modalClose} onClick={onClose}><X size={20} /></button>

        <div className={s.modalBody}>
          <div className={s.modalMeta}>
            <span className={s.modalCat}>{post.cat}</span>
            {post.tag && <span className={`${s.tagLabel} ${s[`tag_${post.tag}`] || ''}`}>#{post.tag}</span>}
            <span className={s.modalAuthor}>{post.author}</span>
            <span className={s.modalTime}><Clock size={12} /> {post.time}</span>
          </div>

          <h3 className={s.modalTitle}>{post.title}</h3>

          {post.body && <div className={s.modalContent}>{post.body}</div>}

          {post.images?.length > 0 && (
            <div className={s.modalImages}>
              {post.images.map((url, i) => <img key={i} src={url} alt="" />)}
            </div>
          )}

          <div className={s.modalStats}>
            <Eye size={14} /> {post.views}
            <MessageSquare size={14} /> {comments.length}
            {board === 'hotdeal' && <span>🔥 {post.hotVotes || 0} / ❄️ {post.coldVotes || 0}</span>}
          </div>

          {/* Price Badge (hotdeal only) */}
          {board === 'hotdeal' && matchedProduct && post.priceVsAvg !== null && (
            <div className={`${s.dbBadge} ${post.priceVsAvg < -20 ? s.dbBadgeDeal : s.dbBadgeOk}`}>
              🎯 평균 시세: {fmt(matchedProduct.avg)}원 · 현재 평균 대비 {post.priceVsAvg}%
            </div>
          )}

          {/* Vote (hotdeal only) */}
          {board === 'hotdeal' && (
            <div className={s.voteSection}>
              <button
                className={`${s.voteBtn} ${s.voteHot} ${vote === 'hot' ? s.voteActive : ''}`}
                onClick={() => handleVote('hot')}
                style={vote === 'hot' ? { background: 'rgba(248,113,113,.12)' } : {}}
              >
                🔥 핫딜이다
              </button>
              <button
                className={`${s.voteBtn} ${s.voteCold} ${vote === 'cold' ? s.voteActive : ''}`}
                onClick={() => handleVote('cold')}
                style={vote === 'cold' ? { background: 'rgba(56,189,248,.12)' } : {}}
              >
                ❄️ 아니다
              </button>
            </div>
          )}
        </div>

        {/* Comments */}
        <div className={s.commentSec}>
          <h4>💬 댓글 {comments.length}개</h4>
          <div className={s.commentList}>
            {comments.length === 0 && <p className={s.noComment}>아직 댓글이 없습니다.</p>}
            {comments.map(c => (
              <div key={c.id} className={s.comment}>
                <strong>{c.author}</strong>
                <span className={s.commentTime}>{c.time}</span>
                <p>{c.text}</p>
              </div>
            ))}
          </div>
          <div className={s.commentInput}>
            <input
              value={newComment}
              onChange={e => setNewComment(e.target.value)}
              placeholder="댓글을 입력하세요..."
              onKeyDown={e => e.key === 'Enter' && addComment()}
            />
            <button onClick={addComment}><Send size={16} /></button>
          </div>
        </div>
      </div>
    </div>
  );
}
