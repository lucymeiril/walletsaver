import { useState, useRef, useEffect, useMemo } from 'react';
import { useLocation } from 'react-router-dom';
import { Pencil, ImagePlus, X, Send, Eye, MessageSquare, Clock, Search } from 'lucide-react';
import { COMMUNITY_POSTS, PRODUCTS, fmt, verifyPrice } from '../../data/mockData';
import useStore from '../../stores/appStore';
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

const FREE_POSTS_MOCK = [
  { id: 101, title: '물가 절약 팁 공유합니다', cat: '정보', tag: '정보', author: '절약러', time: '10분 전', views: 156, comments: 12, body: '장 볼 때 전단지 먼저 확인하고 가면 평균 15% 절약 가능해요. 특히 이마트 에브리데이 앱은 필수!', commentData: [{ id: 1, author: '살림꾼', text: '좋은 정보 감사합니다!', time: '5분 전' }] },
  { id: 102, title: '요즘 장보기 너무 비싸지 않나요?', cat: '질문', tag: '질문', author: '주부9단', time: '30분 전', views: 234, comments: 28, body: '2인 가족인데 한 달에 식비가 80만원이 넘어가요. 다들 얼마나 쓰시나요?', commentData: [{ id: 1, author: '먹보', text: '저도 비슷해요...', time: '20분 전' }, { id: 2, author: '절약왕', text: '저는 60만원 정도 쓰는데 마트 세일 기간 맞춰서 장봐요', time: '15분 전' }] },
  { id: 103, title: '코스트코 회원권 가성비 후기', cat: '후기', tag: '후기', author: '코스트코러버', time: '1시간 전', views: 445, comments: 34, body: '연회비 38,500원인데 한 달에 2번만 가도 비회원 대비 5만원은 절약됩니다. 특히 고기/계란은 확실히 저렴해요.', commentData: [] },
  { id: 104, title: '배달 vs 포장 vs 직접 조리 뭐가 나을까', cat: '잡담', tag: '잡담', author: '먹보', time: '2시간 전', views: 178, comments: 19, body: '치킨 기준으로 배달 21,000원, 포장 18,000원, 직접 만들면 8,000원 정도... 근데 시간도 비용이잖아요.', commentData: [{ id: 1, author: '치킨매니아', text: '포장이 답이죠', time: '1시간 전' }] },
  { id: 105, title: '1인가구 식비 줄이는 현실적인 방법', cat: '정보', tag: '정보', author: '자취생', time: '3시간 전', views: 567, comments: 42, body: '1. 밑반찬 주말에 몰아서 만들기\n2. 마트 마감 할인 노리기\n3. 냉동실 적극 활용\n4. 계절 채소 위주로 구매', commentData: [] },
  { id: 106, title: '편의점 도시락 가성비 순위', cat: '후기', tag: '후기', author: '편의점마스터', time: '4시간 전', views: 321, comments: 15, body: 'CU > GS25 > 세븐일레븐 순으로 가성비가 좋은 것 같아요. CU는 양이 제일 많고요.', commentData: [] },
  { id: 107, title: '장보기 앱 추천 좀 해주세요', cat: '질문', tag: '질문', author: '앱덕후', time: '5시간 전', views: 189, comments: 23, body: '물가 비교 앱이나 마트 할인 정보 앱 중에 좋은 거 있으면 추천 부탁드려요!', commentData: [] },
  { id: 108, title: '오늘 저녁 뭐 해먹을지 고민', cat: '잡담', tag: '잡담', author: '요리초보', time: '6시간 전', views: 98, comments: 8, body: '냉장고에 양파, 계란, 김치밖에 없는데 뭘 만들 수 있을까요?', commentData: [{ id: 1, author: '절약러', text: '김치볶음밥이 답입니다', time: '5시간 전' }] },
];

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

  useEffect(() => {
    const openPostId = location.state?.openPostId;
    if (openPostId) {
      const post = COMMUNITY_POSTS.find((p) => p.id === openPostId);
      if (post) setDetail(post);
      window.history.replaceState({}, '');
    }
  }, [location.state]);

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
    let posts;

    if (board === 'hotdeal') {
      posts = filter === '전체' ? [...COMMUNITY_POSTS] : COMMUNITY_POSTS.filter(p => p.cat === filter);
    } else {
      posts = freeTag === '전체' ? [...FREE_POSTS_MOCK] : FREE_POSTS_MOCK.filter(p => p.tag === freeTag);
    }

    if (searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase();
      posts = posts.filter(p =>
        p.title.toLowerCase().includes(q) || (p.body && p.body.toLowerCase().includes(q))
      );
    }

    if (sortBy === 'popular') {
      posts.sort((a, b) => ((b.hotVotes || 0) - (b.coldVotes || 0)) - ((a.hotVotes || 0) - (a.coldVotes || 0)));
    } else if (sortBy === 'comments') {
      posts.sort((a, b) => (b.commentData?.length || b.comments || 0) - (a.commentData?.length || a.comments || 0));
    }

    return posts;
  }, [board, filter, freeTag, searchQuery, sortBy]);

  const totalPages = Math.max(1, Math.ceil(filteredAndSorted.length / POSTS_PER_PAGE));
  const safePage = Math.min(page, totalPages);
  const paginatedPosts = filteredAndSorted.slice((safePage - 1) * POSTS_PER_PAGE, safePage * POSTS_PER_PAGE);

  const matchedProduct = PRODUCTS.find(p => wProduct.includes(p.name));
  const verification = wPrice && matchedProduct ? verifyPrice(Number(wPrice), matchedProduct.avg) : null;

  const handleImageAdd = (e) => {
    const files = Array.from(e.target.files);
    files.forEach(f => {
      const reader = new FileReader();
      reader.onload = (ev) => setWImages(prev => [...prev, ev.target.result]);
      reader.readAsDataURL(f);
    });
  };

  const handleWrite = () => {
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
    addToast('게시글이 등록되었습니다! (데모)', 'success');
    setShowWrite(false);
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
                  {PRODUCTS.map(p => <option key={p.id} value={p.name} />)}
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
      {detail && <PostDetailModal post={detail} onClose={() => setDetail(null)} board={board} />}
    </div>
  );
}

function PostDetailModal({ post, onClose, board }) {
  const [newComment, setNewComment] = useState('');
  const [comments, setComments] = useState(post?.commentData || []);
  const [vote, setVote] = useState(null);

  const matchedProduct = PRODUCTS.find(p => post.title?.includes(p.name));

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
