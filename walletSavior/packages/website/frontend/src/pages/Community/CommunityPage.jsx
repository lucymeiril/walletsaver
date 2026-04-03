import { useState, useRef, useEffect, useMemo } from 'react';
import { useLocation } from 'react-router-dom';
import { Pencil, ImagePlus, X, Send, Eye, MessageSquare, Clock, Search, Trash2, Edit3 } from 'lucide-react';
import { fmt, verifyPrice } from '../../utils/helpers';
import useStore from '../../stores/appStore';
import Spinner from '../../components/common/Spinner';
import RichTextEditor from '../../components/community/RichTextEditor';
import ProductPicker from '../../components/community/ProductPicker';
import s from './CommunityPage.module.css';

const BOARD_TABS = [
  { id: 'hotdeal', label: '🔥 핫딜 게시판' },
  { id: 'free', label: '💬 자유 게시판' },
];
const CATS = ['전체', '마트', '온라인', '외식', '기타'];
const FREE_TAGS = ['질문', '정보', '후기', '잡담'];
const WRITE_CATS = ['마트', '온라인', '외식', '기타'];
const POSTS_PER_PAGE = 10;
const PINNED_COUNT = 3;

const VERIFY_STYLES = {
  great_deal: { bg: 'rgba(52,211,153,.1)', color: 'var(--green)', icon: '🔥', border: 'var(--green)' },
  verified:   { bg: 'rgba(56,189,248,.08)', color: 'var(--accent)', icon: '✅', border: 'var(--accent)' },
  sus_low:    { bg: 'rgba(248,113,113,.1)', color: 'var(--red)', icon: '⚠️', border: 'var(--red)' },
  sus_high:   { bg: 'rgba(248,113,113,.1)', color: 'var(--red)', icon: '🚨', border: 'var(--red)' },
};


function formatRelativeTime(isoString) {
  if (!isoString) return '';
  const date = new Date(isoString);
  const now = new Date();
  const diff = Math.floor((now - date) / 1000);
  if (diff < 60) return '방금 전';
  if (diff < 3600) return `${Math.floor(diff / 60)}분 전`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}시간 전`;
  if (diff < 604800) return `${Math.floor(diff / 86400)}일 전`;
  return date.toLocaleDateString('ko-KR');
}

function stripHtml(html) {
  if (!html) return '';
  return html.replace(/<[^>]*>/g, '').replace(/&nbsp;/g, ' ').trim();
}

function mapApiPost(raw, products = []) {
  const matched = products.find(p => raw.title?.includes(p.name));
  const priceVal = raw.price ?? raw.deal_price;
  const priceVsAvg = (priceVal && matched?.avg)
    ? Math.round(((priceVal - matched.avg) / matched.avg) * 100)
    : null;
  const verification = (priceVal && matched) ? verifyPrice(priceVal, matched.avg) : null;
  return {
    ...raw,
    body: raw.content,
    cat: raw.category || '',
    tag: raw.tag || '',
    author: raw.author_nickname || `user${raw.author_id}`,
    time: formatRelativeTime(raw.created_at),
    hotVotes: raw.hot_votes || 0,
    coldVotes: raw.not_votes || 0,
    comments: raw.comments_count || 0,
    images: raw.images || [],
    priceVsAvg,
    verified: verification?.status || null,
  };
}


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
  const { isLoggedIn, user, addToast } = useStore();

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
  const refreshPosts = () => {
    setLoading(true);
    const params = new URLSearchParams({ post_type: board, per_page: '50' });
    fetch(`/api/posts?${params}`).then(r => r.json())
      .then(res => setPosts((res.data || []).map(p => mapApiPost(p, products))))
      .catch(err => {
        console.error(err);
        addToast('게시글을 불러오는데 실패했습니다', 'error');
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    refreshPosts();
  }, [board, products]);

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
  const [wSelectedProducts, setWSelectedProducts] = useState([]);
  const [wPrice, setWPrice] = useState('');
  const [wLink, setWLink] = useState('');
  const [wTag, setWTag] = useState('잡담');
  const [wImages, setWImages] = useState([]);
  const [editPostId, setEditPostId] = useState(null);
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

  // 인기 게시글 상단 고정 — 핫딜 게시판에서 투표 수 상위 3개
  const pinnedPosts = useMemo(() => {
    if (board !== 'hotdeal') return [];
    const scored = posts
      .filter(p => (p.hotVotes || 0) > 0)
      .map(p => ({ ...p, score: (p.hotVotes || 0) - (p.coldVotes || 0) }))
      .sort((a, b) => b.score - a.score)
      .slice(0, PINNED_COUNT);
    return scored;
  }, [posts, board]);

  const pinnedIds = new Set(pinnedPosts.map(p => p.id));
  const nonPinnedPosts = filteredAndSorted.filter(p => !pinnedIds.has(p.id));
  const totalPages = Math.max(1, Math.ceil(nonPinnedPosts.length / POSTS_PER_PAGE));
  const safePage = Math.min(page, totalPages);
  const paginatedPosts = nonPinnedPosts.slice((safePage - 1) * POSTS_PER_PAGE, safePage * POSTS_PER_PAGE);

  const matchedProduct = wSelectedProducts.length > 0
    ? wSelectedProducts[0]
    : products.find(p => wProduct.includes(p.name));
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
    if (!wTitle.trim()) { addToast('제목을 입력해주세요.', 'error'); return; }
    if (board === 'hotdeal') {
      if (!wProduct.trim() && wSelectedProducts.length === 0) { addToast('품목명을 입력해주세요.', 'error'); return; }
      if (!wPrice.trim()) { addToast('가격을 입력해주세요.', 'error'); return; }
      if (!wLink.trim()) { addToast('핫딜 링크를 입력해주세요.', 'error'); return; }
    }
    if (verification && !verification.canPost) {
      addToast('허위 가격이 의심되어 등록할 수 없습니다.', 'error');
      return;
    }
    try {
      const headers = { 'Content-Type': 'application/json' };
      const token = localStorage.getItem('access_token');
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const isEdit = !!editPostId;
      const url = isEdit ? `/api/posts/${editPostId}` : '/api/posts';
      const method = isEdit ? 'PUT' : 'POST';

      const payload = {
        title: wTitle,
        content: wBody,
        ...(isEdit ? {} : { post_type: board === 'hotdeal' ? 'hotdeal' : 'free' }),
        category: board === 'hotdeal' ? wCat : undefined,
        price: wPrice ? Number(wPrice) : undefined,
        url: wLink || undefined,
        ...(isEdit ? {} : { images: wImages.length > 0 ? wImages : undefined }),
      };

      const resp = await fetch(url, { method, headers, body: JSON.stringify(payload) });
      if (resp.ok) {
        addToast(isEdit ? '게시글이 수정되었습니다!' : '게시글이 등록되었습니다!', 'success');
        setShowWrite(false);
        setEditPostId(null);
        refreshPosts();
      } else {
        const errData = await resp.json().catch(() => ({}));
        addToast(`${isEdit ? '수정' : '등록'} 실패: ${errData.detail || resp.statusText}`, 'error');
      }
    } catch (err) {
      console.error(err);
      addToast('처리 중 오류가 발생했습니다.', 'error');
    }
    setWTitle(''); setWBody(''); setWProduct(''); setWSelectedProducts([]); setWPrice(''); setWLink(''); setWImages([]);
  };

  const handleWriteBtn = () => {
    if (showWrite && editPostId) {
      setEditPostId(null);
      setWTitle(''); setWBody(''); setWProduct(''); setWSelectedProducts([]); setWPrice(''); setWLink(''); setWImages([]);
    }
    setShowWrite(!showWrite);
  };

  const handleEdit = (post) => {
    setEditPostId(post.id);
    setWTitle(post.title || '');
    setWBody(post.body || post.content || '');
    setWCat(post.cat || post.category || '마트');
    setWProduct(post.product_name || '');
    setWSelectedProducts([]);
    setWPrice(post.price ? String(post.price) : '');
    setWLink(post.url || '');
    setWImages(post.images || []);
    setShowWrite(true);
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
            <h4>{editPostId ? '✏️ 게시글 수정' : `📝 ${board === 'hotdeal' ? '핫딜 공유' : '자유 게시글'}`}</h4>
            <button className={s.closeWrite} onClick={() => { setShowWrite(false); setEditPostId(null); }}><X size={16} /></button>
          </div>

          <input
            className={s.titleInput}
            placeholder="제목을 입력하세요"
            value={wTitle}
            onChange={e => setWTitle(e.target.value)}
          />
          <RichTextEditor
            content={wBody}
            onChange={setWBody}
            placeholder={board === 'hotdeal'
              ? '내용을 입력하세요 (가격, 매장 위치, 수량 제한 등)'
              : '자유롭게 내용을 입력하세요'}
          />

          {board === 'hotdeal' ? (
            <>
              <div className={s.writeRow}>
                <select value={wCat} onChange={e => setWCat(e.target.value)}>
                  {WRITE_CATS.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
                <input
                  type="number"
                  placeholder="가격 (원, 필수)"
                  value={wPrice}
                  onChange={e => setWPrice(e.target.value)}
                />
              </div>
              <ProductPicker
                selected={wSelectedProducts}
                onChange={setWSelectedProducts}
              />
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
            {editPostId ? '수정' : '등록'}
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

      {/* 인기 핫딜 상단 고정 */}
      {board === 'hotdeal' && pinnedPosts.length > 0 && !searchQuery.trim() && (
        <div className={s.pinnedSection}>
          <h4 className={s.pinnedTitle}>📌 인기 핫딜 TOP {pinnedPosts.length}</h4>
          {pinnedPosts.map(p => (
            <div
              key={`pin-${p.id}`}
              className={`${s.post} ${s.hotdealPost} ${s.pinnedPost}`}
              style={{ borderLeftColor: 'var(--orange, #f59e0b)' }}
              onClick={() => setDetail(p)}
            >
              <div className={s.hotdealVoteCol}>
                <span className={s.hotdealVoteHot}>🔥 {p.hotVotes || 0}</span>
                <span className={s.hotdealVoteCold}>❄️ {p.coldVotes || 0}</span>
              </div>
              <div className={s.postBody}>
                <div className={s.postTitle}>
                  <span className={s.pinnedBadge}>📌 인기</span>
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
                {p.body && <p className={s.postExcerpt}>{stripHtml(p.body).slice(0, 60)}...</p>}
                <div className={s.postMeta}>
                  <span className={s.postCatInline}>{p.cat}</span>
                  <span>{p.author}</span>
                  <span>{p.time}</span>
                  <span>조회 {p.views}</span>
                  <span>💬 {p.comments}</span>
                </div>
              </div>
              {p.priceVsAvg !== null && (
                <span className={`${s.priceBadge} ${p.priceVsAvg < -20 ? s.cheap : s.avgBadge}`}>
                  평균 대비 {p.priceVsAvg}%
                </span>
              )}
            </div>
          ))}
        </div>
      )}

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
                {p.body && <p className={s.postExcerpt}>{stripHtml(p.body).slice(0, 60)}...</p>}
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
                {p.body && <p className={s.postExcerpt}>{stripHtml(p.body).slice(0, 80)}...</p>}
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
        {paginatedPosts.length === 0 && pinnedPosts.length === 0 && !loading && (
          <div className={s.emptyState}>
            <div className={s.emptyIcon}>{board === 'hotdeal' ? '🔥' : '💬'}</div>
            <p className={s.emptyText}>
              {board === 'hotdeal'
                ? '아직 게시글이 없습니다. 첫 핫딜 정보를 공유해주세요!'
                : '아직 게시글이 없습니다. 자유롭게 이야기를 시작해보세요!'}
            </p>
            <button className={s.emptyWriteBtn} onClick={handleWriteBtn}>
              <Pencil size={14} /> 첫 글 작성하기
            </button>
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
      {detail && (
        <PostDetailModal
          post={detail}
          onClose={() => setDetail(null)}
          board={board}
          products={products}
          user={user}
          onRefresh={refreshPosts}
          onEdit={handleEdit}
        />
      )}
    </div>
  );
}

function PostDetailModal({ post, onClose, board, products, user, onRefresh, onEdit }) {
  const [newComment, setNewComment] = useState('');
  const [comments, setComments] = useState([]);
  const [loadingComments, setLoadingComments] = useState(true);
  const [vote, setVote] = useState(null);
  const [hotVotes, setHotVotes] = useState(post.hotVotes || post.hot_votes || 0);
  const [coldVotes, setColdVotes] = useState(post.coldVotes || post.not_votes || 0);
  const { isLoggedIn, addToast } = useStore();

  useEffect(() => {
    setLoadingComments(true);
    fetch(`/api/posts/${post.id}/comments`)
      .then(r => r.json())
      .then(res => {
        const data = res.data || [];
        setComments(data.map(c => ({
          id: c.id,
          author: c.author_nickname,
          author_id: c.author_id,
          text: c.content,
          time: formatRelativeTime(c.created_at),
        })));
      })
      .catch(console.error)
      .finally(() => setLoadingComments(false));
  }, [post.id]);

  const addComment = async () => {
    if (!newComment.trim()) return;
    if (!isLoggedIn) {
      addToast('댓글을 작성하려면 로그인이 필요합니다.', 'error');
      return;
    }
    try {
      const token = localStorage.getItem('access_token');
      const resp = await fetch(`/api/posts/${post.id}/comments`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ content: newComment }),
      });
      if (resp.ok) {
        const res = await resp.json();
        const c = res.data;
        setComments(prev => [...prev, {
          id: c.id,
          author: c.author_nickname,
          author_id: c.author_id,
          text: c.content,
          time: '방금 전',
        }]);
        setNewComment('');
      } else {
        addToast('댓글 작성에 실패했습니다.', 'error');
      }
    } catch {
      addToast('댓글 작성 중 오류가 발생했습니다.', 'error');
    }
  };

  const handleVote = async (type) => {
    if (!isLoggedIn) {
      addToast('투표하려면 로그인이 필요합니다.', 'error');
      return;
    }
    const voteType = type === 'hot' ? 'hot' : 'not';
    try {
      const token = localStorage.getItem('access_token');
      const resp = await fetch(`/api/posts/${post.id}/vote`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ vote_type: voteType }),
      });
      if (resp.ok) {
        const res = await resp.json();
        setHotVotes(res.data.hot_votes);
        setColdVotes(res.data.not_votes);
        setVote(res.data.user_vote);
      }
    } catch {
      addToast('투표 중 오류가 발생했습니다.', 'error');
    }
  };

  const handleDelete = async () => {
    if (!window.confirm('정말 삭제하시겠습니까?')) return;
    try {
      const token = localStorage.getItem('access_token');
      const resp = await fetch(`/api/posts/${post.id}`, {
        method: 'DELETE',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (resp.ok) {
        addToast('게시글이 삭제되었습니다.', 'success');
        onClose();
        onRefresh();
      } else {
        addToast('삭제에 실패했습니다.', 'error');
      }
    } catch {
      addToast('삭제 중 오류가 발생했습니다.', 'error');
    }
  };

  const matchedProduct = products.find(p => post.title?.includes(p.name));
  const isAuthor = user && (post.author_id === user.id);

  return (
    <div className={s.modalOverlay} onClick={onClose}>
      <div className={s.modal} onClick={e => e.stopPropagation()}>
        <button className={s.modalClose} onClick={onClose}><X size={20} /></button>

        <div className={s.modalBody}>
          <div className={s.modalMeta}>
            {post.cat && <span className={s.modalCat}>{post.cat}</span>}
            {post.tag && <span className={`${s.tagLabel} ${s[`tag_${post.tag}`] || ''}`}>#{post.tag}</span>}
            <span className={s.modalAuthor}>{post.author}</span>
            <span className={s.modalTime}><Clock size={12} /> {post.time}</span>
          </div>

          <h3 className={s.modalTitle}>{post.title}</h3>

          {isAuthor && (
            <div className={s.authorActions}>
              <button className={s.editBtn} onClick={() => { onEdit(post); onClose(); }}>
                <Edit3 size={14} /> 수정
              </button>
              <button className={s.deleteBtn} onClick={handleDelete}>
                <Trash2 size={14} /> 삭제
              </button>
            </div>
          )}

          {post.body && <div className={`${s.modalContent} ${s.richContent}`} dangerouslySetInnerHTML={{ __html: post.body }} />}

          {post.url && (
            <a href={post.url} target="_blank" rel="noopener noreferrer" className={s.dealLink}>
              🔗 핫딜 링크로 이동
            </a>
          )}

          {post.images?.length > 0 && (
            <div className={s.modalImages}>
              {post.images.map((url, i) => <img key={i} src={url} alt="" />)}
            </div>
          )}

          <div className={s.modalStats}>
            <Eye size={14} /> {post.views}
            <MessageSquare size={14} /> {comments.length}
            {board === 'hotdeal' && <span>🔥 {hotVotes} / ❄️ {coldVotes}</span>}
          </div>

          {board === 'hotdeal' && matchedProduct && post.priceVsAvg !== null && (
            <div className={`${s.dbBadge} ${post.priceVsAvg < -20 ? s.dbBadgeDeal : s.dbBadgeOk}`}>
              🎯 평균 시세: {fmt(matchedProduct.avg)}원 · 현재 평균 대비 {post.priceVsAvg}%
            </div>
          )}

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
                className={`${s.voteBtn} ${s.voteCold} ${vote === 'not' ? s.voteActive : ''}`}
                onClick={() => handleVote('cold')}
                style={vote === 'not' ? { background: 'rgba(56,189,248,.12)' } : {}}
              >
                ❄️ 아니다
              </button>
            </div>
          )}
        </div>

        <div className={s.commentSec}>
          <h4>💬 댓글 {comments.length}개</h4>
          <div className={s.commentList}>
            {loadingComments && <p className={s.noComment}>댓글을 불러오는 중...</p>}
            {!loadingComments && comments.length === 0 && <p className={s.noComment}>아직 댓글이 없습니다.</p>}
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
              placeholder={isLoggedIn ? '댓글을 입력하세요...' : '로그인 후 댓글을 작성할 수 있습니다'}
              onKeyDown={e => e.key === 'Enter' && addComment()}
              disabled={!isLoggedIn}
            />
            <button onClick={addComment} disabled={!isLoggedIn}><Send size={16} /></button>
          </div>
        </div>
      </div>
    </div>
  );
}
