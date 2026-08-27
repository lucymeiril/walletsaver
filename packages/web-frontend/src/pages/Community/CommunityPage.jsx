import React, { useState, useRef, useEffect, useMemo, useCallback } from 'react';
import { useLocation } from 'react-router-dom';
import { Pencil, X, Send, Eye, MessageSquare, Clock, Search, Trash2, Edit3 } from 'lucide-react';
import { fmt, verifyPrice } from '../../utils/helpers';
import { sanitizeHTML, sanitizeURL } from '../../utils/sanitize';
import useStore from '../../stores/appStore';
import useDebounce from '../../hooks/useDebounce';
import Spinner from '../../components/common/Spinner';
import EmptyState from '../../components/common/EmptyState';
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
const API_PAGE_SIZE = 100;
const PINNED_COUNT = 3;

const VERIFY_STYLES = {
  great_deal: { bg: 'rgba(52,211,153,.1)', color: 'var(--green)', icon: '🔥', border: 'var(--green)' },
  verified: { bg: 'rgba(56,189,248,.08)', color: 'var(--accent)', icon: '✅', border: 'var(--accent)' },
  sus_low: { bg: 'rgba(248,113,113,.1)', color: 'var(--red)', icon: '⚠️', border: 'var(--red)' },
  sus_high: { bg: 'rgba(248,113,113,.1)', color: 'var(--red)', icon: '🚨', border: 'var(--red)' },
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

function mapApiPost(raw) {
  return {
    ...raw,
    body: raw.content,
    cat: raw.category || '',
    tag: raw.tags?.[0] || raw.tag || '',
    author: raw.author_nickname || `user${raw.author_id}`,
    time: formatRelativeTime(raw.created_at),
    hotVotes: raw.hot_votes || 0,
    coldVotes: raw.not_votes || 0,
    comments: raw.comments_count || 0,
    priceVsAvg: null,
    verified: null,
  };
}

async function fetchPostPage(board, page, signal) {
  const params = new URLSearchParams({
    post_type: board,
    page: String(page),
    per_page: String(API_PAGE_SIZE),
    sort: 'recent',
  });
  const response = await fetch(`/api/posts?${params}`, { signal });
  if (!response.ok) throw new Error(`community fetch failed: ${response.status}`);
  const result = await response.json();
  return {
    posts: (result.data || []).map(mapApiPost),
    totalPages: Math.max(1, Number(result.meta?.total_pages || 1)),
  };
}

async function fetchAllPosts(board, signal) {
  const all = [];
  let page = 1;
  let totalPages = 1;
  do {
    const result = await fetchPostPage(board, page, signal);
    all.push(...result.posts);
    totalPages = result.totalPages;
    page += 1;
  } while (page <= totalPages);
  return all;
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
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const postsControllerRef = useRef(null);

  const refreshPosts = useCallback(() => {
    postsControllerRef.current?.abort();
    const controller = new AbortController();
    postsControllerRef.current = controller;
    setLoading(true);
    setFetchError(false);

    fetchAllPosts(board, controller.signal)
      .then(setPosts)
      .catch((error) => {
        if (error.name === 'AbortError') return;
        console.error(error);
        setFetchError(true);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
  }, [board]);

  useEffect(() => {
    refreshPosts();
    return () => postsControllerRef.current?.abort();
  }, [refreshPosts]);

  useEffect(() => {
    const openPostId = location.state?.openPostId;
    if (openPostId && posts.length > 0) {
      const post = posts.find((item) => item.id === openPostId);
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
    setShowWrite(false);
    setDetail(null);
  }, [board]);

  const [wTitle, setWTitle] = useState('');
  const [wBody, setWBody] = useState('');
  const [wCat, setWCat] = useState('마트');
  const [wSelectedProducts, setWSelectedProducts] = useState([]);
  const [wPrice, setWPrice] = useState('');
  const [wLink, setWLink] = useState('');
  const [wTag, setWTag] = useState('잡담');
  const [editPostId, setEditPostId] = useState(null);
  const debouncedSearch = useDebounce(searchQuery, 200);

  const resetWriteForm = useCallback(() => {
    setEditPostId(null);
    setWTitle('');
    setWBody('');
    setWCat('마트');
    setWSelectedProducts([]);
    setWPrice('');
    setWLink('');
    setWTag('잡담');
  }, []);

  const matchedProduct = wSelectedProducts[0] || null;
  const verification = wPrice && matchedProduct?.avg
    ? verifyPrice(Number(wPrice), matchedProduct.avg)
    : null;

  const filteredAndSorted = useMemo(() => {
    let items = [...posts];

    if (board === 'hotdeal') {
      if (filter !== '전체') items = items.filter((post) => post.cat === filter);
    } else if (freeTag !== '전체') {
      items = items.filter((post) => post.tag === freeTag);
    }

    if (debouncedSearch.trim()) {
      const query = debouncedSearch.trim().toLowerCase();
      items = items.filter((post) =>
        post.title?.toLowerCase().includes(query)
        || post.body?.toLowerCase().includes(query)
      );
    }

    if (sortBy === 'popular') {
      if (board === 'hotdeal') {
        items.sort((a, b) =>
          ((b.hotVotes || 0) - (b.coldVotes || 0))
          - ((a.hotVotes || 0) - (a.coldVotes || 0))
        );
      } else {
        items.sort((a, b) => (b.views || 0) - (a.views || 0));
      }
    } else if (sortBy === 'comments') {
      items.sort((a, b) => (b.comments || 0) - (a.comments || 0));
    }

    return items;
  }, [posts, board, filter, freeTag, debouncedSearch, sortBy]);

  const pinnedPosts = useMemo(() => {
    if (board !== 'hotdeal' || searchQuery.trim()) return [];
    return filteredAndSorted
      .filter((post) => (post.hotVotes || 0) > 0)
      .map((post) => ({
        ...post,
        score: (post.hotVotes || 0) - (post.coldVotes || 0),
      }))
      .sort((a, b) => b.score - a.score)
      .slice(0, PINNED_COUNT);
  }, [filteredAndSorted, board, searchQuery]);

  const pinnedIds = useMemo(() => new Set(pinnedPosts.map((post) => post.id)), [pinnedPosts]);
  const nonPinnedPosts = useMemo(
    () => filteredAndSorted.filter((post) => !pinnedIds.has(post.id)),
    [filteredAndSorted, pinnedIds],
  );
  const totalPages = useMemo(
    () => Math.max(1, Math.ceil(nonPinnedPosts.length / POSTS_PER_PAGE)),
    [nonPinnedPosts.length],
  );
  const safePage = Math.min(page, totalPages);
  const paginatedPosts = useMemo(
    () => nonPinnedPosts.slice((safePage - 1) * POSTS_PER_PAGE, safePage * POSTS_PER_PAGE),
    [nonPinnedPosts, safePage],
  );

  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  const handleWrite = async () => {
    if (submitting) return;
    if (!isLoggedIn) {
      addToast('로그인 후 게시글을 작성할 수 있습니다.', 'warning');
      return;
    }
    if (!wTitle.trim()) {
      addToast('제목을 입력해주세요.', 'error');
      return;
    }
    if (board === 'hotdeal') {
      if (!wPrice.trim()) {
        addToast('가격을 입력해주세요.', 'error');
        return;
      }
      if (!wLink.trim()) {
        addToast('핫딜 링크를 입력해주세요.', 'error');
        return;
      }
    }
    if (verification && !verification.canPost) {
      addToast('허위 가격이 의심되어 등록할 수 없습니다.', 'error');
      return;
    }

    try {
      setSubmitting(true);
      const isEdit = Boolean(editPostId);
      const url = isEdit ? `/api/posts/${editPostId}` : '/api/posts';
      const method = isEdit ? 'PUT' : 'POST';
      const payload = {
        title: wTitle,
        content: wBody,
        ...(isEdit ? {} : { post_type: board }),
        category: board === 'hotdeal' ? wCat : undefined,
        tags: board === 'free' && wTag ? [wTag] : undefined,
        price: board === 'hotdeal' && wPrice ? Number(wPrice) : undefined,
        url: board === 'hotdeal' ? (wLink || undefined) : undefined,
      };

      const response = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        credentials: 'include',
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        addToast(`${isEdit ? '수정' : '등록'} 실패: ${errorData.detail || response.statusText}`, 'error');
        return;
      }

      addToast(isEdit ? '게시글이 수정되었습니다!' : '게시글이 등록되었습니다!', 'success');
      setShowWrite(false);
      resetWriteForm();
      refreshPosts();
      setPage(1);
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (error) {
      console.error(error);
      addToast('처리 중 오류가 발생했습니다.', 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const handleWriteBtn = () => {
    if (!isLoggedIn && !showWrite) {
      addToast('로그인 후 게시글을 작성할 수 있습니다.', 'warning');
      return;
    }
    if (showWrite) resetWriteForm();
    setShowWrite((value) => !value);
  };

  const handleEdit = (post) => {
    setEditPostId(post.id);
    setWTitle(post.title || '');
    setWBody(post.body || post.content || '');
    setWCat(post.cat || post.category || '마트');
    setWSelectedProducts([]);
    setWPrice(post.price ? String(post.price) : '');
    setWLink(post.url || '');
    setWTag(post.tag || '잡담');
    setShowWrite(true);
  };

  const handleFilterChange = useCallback((value) => {
    setFilter(value);
    setPage(1);
  }, []);

  const handleTagChange = useCallback((value) => {
    setFreeTag(value);
    setPage(1);
  }, []);

  const handleSearchChange = useCallback((event) => {
    setSearchQuery(event.target.value);
    setPage(1);
  }, []);

  const handleSortChange = useCallback((event) => {
    setSortBy(event.target.value);
    setPage(1);
  }, []);

  const getVerifyBorderColor = useCallback((verified) => {
    if (!verified) return 'var(--border)';
    return VERIFY_STYLES[verified]?.border || 'var(--border)';
  }, []);

  const handlePostUpdate = useCallback((postId, updates) => {
    setPosts((current) => current.map((post) =>
      post.id === postId ? { ...post, ...updates } : post
    ));
  }, []);

  return (
    <div>
      <div className={`${s.hdr} ${board === 'hotdeal' ? s.hdrHotdeal : s.hdrFree}`}>
        <div>
          <h2>{board === 'hotdeal' ? '🔥 핫딜 정보를 공유하고 검증하세요' : '💬 자유롭게 이야기를 나눠보세요'}</h2>
          <p>{board === 'hotdeal'
            ? '직접 발견한 할인을 공유하고, 품목을 선택하면 시세와 비교합니다'
            : '물가, 절약, 살림에 대해 자유롭게 이야기하세요'}</p>
        </div>
        <button className={s.writeBtn} onClick={handleWriteBtn}>
          <Pencil size={16} /> {isLoggedIn ? '글쓰기' : '로그인 후 글쓰기'}
        </button>
      </div>

      <div className={s.tabRow}>
        {BOARD_TABS.map((tab) => (
          <button
            key={tab.id}
            className={`${s.mainTab} ${board === tab.id ? (tab.id === 'hotdeal' ? s.mainTabHotdeal : s.mainTabFree) : ''}`}
            onClick={() => setBoard(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {showWrite && (
        <div className={s.writeForm}>
          <div className={s.writeHeader}>
            <h4>{editPostId ? '✏️ 게시글 수정' : `📝 ${board === 'hotdeal' ? '핫딜 공유' : '자유 게시글'}`}</h4>
            <button
              className={s.closeWrite}
              onClick={() => { setShowWrite(false); resetWriteForm(); }}
            >
              <X size={16} />
            </button>
          </div>

          <input
            className={s.titleInput}
            placeholder="제목을 입력하세요"
            value={wTitle}
            onChange={(event) => setWTitle(event.target.value)}
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
                <select value={wCat} onChange={(event) => setWCat(event.target.value)}>
                  {WRITE_CATS.map((category) => <option key={category} value={category}>{category}</option>)}
                </select>
                <input
                  type="number"
                  placeholder="가격 (원, 필수)"
                  value={wPrice}
                  onChange={(event) => setWPrice(event.target.value)}
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
                onChange={(event) => setWLink(event.target.value)}
              />
              {!matchedProduct && (
                <div className={s.noMatch}>ℹ️ 품목 선택은 선택사항입니다. 선택하면 현재 시세와 비교해 등록 가격을 검증합니다.</div>
              )}
            </>
          ) : (
            <div className={s.writeTagRow}>
              <span className={s.writeTagLabel}>태그:</span>
              {FREE_TAGS.map((tag) => (
                <button
                  key={tag}
                  type="button"
                  className={`${s.writeTagBtn} ${wTag === tag ? s.writeTagActive : ''}`}
                  onClick={() => setWTag(tag)}
                >
                  {tag}
                </button>
              ))}
            </div>
          )}

          {board === 'hotdeal' && verification && (
            <div className={s.verifyResult} style={{
              background: VERIFY_STYLES[verification.status]?.bg || 'var(--glass)',
              color: VERIFY_STYLES[verification.status]?.color || 'var(--text)',
            }}>
              <span>{verification.emoji}</span>
              <span>{verification.label}</span>
              <span className={s.verifyDetail}>평균 시세: {fmt(matchedProduct.avg)}원</span>
            </div>
          )}
          {board === 'hotdeal' && verification && !verification.canPost && (
            <div className={s.blocked}>⛔ 등록 차단됨 — 허위 가격이 의심됩니다.</div>
          )}

          <button
            className={s.submitBtn}
            onClick={handleWrite}
            disabled={submitting || (board === 'hotdeal' && verification?.canPost === false)}
            aria-busy={submitting}
          >
            {submitting ? '게시 중...' : (editPostId ? '수정' : '등록')}
          </button>
        </div>
      )}

      <div className={s.searchSortRow}>
        <div className={s.searchWrap}>
          <Search size={16} className={s.searchIcon} />
          <input
            className={s.searchInput}
            value={searchQuery}
            onChange={handleSearchChange}
            placeholder="게시글 검색..."
            autoComplete="off"
            aria-label="게시글 검색"
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

      <div className={s.filterRow}>
        {board === 'hotdeal' ? (
          CATS.map((category) => (
            <button
              key={category}
              className={`${s.tab} ${filter === category ? s.tabActive : ''}`}
              onClick={() => handleFilterChange(category)}
            >
              {category}
            </button>
          ))
        ) : (
          ['전체', ...FREE_TAGS].map((tag) => (
            <button
              key={tag}
              className={`${s.freeTagBtn} ${freeTag === tag ? s.freeTagActive : ''}`}
              onClick={() => handleTagChange(tag)}
            >
              {tag === '전체' ? '전체' : `#${tag}`}
            </button>
          ))
        )}
      </div>

      {loading && (
        <div style={{ display: 'flex', justifyContent: 'center', padding: '2rem 0' }}>
          <Spinner />
        </div>
      )}

      {board === 'hotdeal' && pinnedPosts.length > 0 && !searchQuery.trim() && (
        <div className={s.pinnedSection}>
          <h4 className={s.pinnedTitle}>📌 인기 핫딜 TOP {pinnedPosts.length}</h4>
          {pinnedPosts.map((post) => (
            <div
              key={`pin-${post.id}`}
              className={`${s.post} ${s.hotdealPost} ${s.pinnedPost}`}
              style={{ borderLeftColor: 'var(--orange, #f59e0b)' }}
              onClick={() => setDetail(post)}
            >
              <div className={s.hotdealVoteCol}>
                <span className={s.hotdealVoteHot}>🔥 {post.hotVotes || 0}</span>
                <span className={s.hotdealVoteCold}>❄️ {post.coldVotes || 0}</span>
              </div>
              <div className={s.postBody}>
                <div className={s.postTitle}>
                  <span className={s.pinnedBadge}>📌 인기</span>
                  {post.title}
                </div>
                {post.body && <p className={s.postExcerpt}>{stripHtml(post.body).slice(0, 60)}...</p>}
                <div className={s.postMeta}>
                  <span className={s.postCatInline}>{post.cat}</span>
                  <span>{post.author}</span>
                  <span>{post.time}</span>
                  <span>조회 {post.views}</span>
                  <span>💬 {post.comments}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className={s.list}>
        {!loading && fetchError && (
          <div style={{ textAlign: 'center', padding: '2rem 0' }}>
            <p style={{ color: 'var(--red, #ef4444)', marginBottom: '0.75rem' }}>⚠️ 게시글을 불러오는 데 실패했습니다</p>
            <button
              className={s.submitBtn}
              onClick={refreshPosts}
              style={{ display: 'inline-flex', width: 'auto', padding: '0.5rem 1.2rem' }}
            >
              다시 시도
            </button>
          </div>
        )}

        {!loading && !fetchError && paginatedPosts.length === 0 && pinnedPosts.length === 0 && (
          <EmptyState
            title="게시글이 없습니다"
            description="첫 번째 게시글을 작성해 보세요!"
          />
        )}

        {board === 'hotdeal' ? (
          paginatedPosts.map((post) => (
            <div
              key={post.id}
              className={`${s.post} ${s.hotdealPost}`}
              style={{ borderLeftColor: getVerifyBorderColor(post.verified) }}
              onClick={() => setDetail(post)}
            >
              <div className={s.hotdealVoteCol}>
                <span className={s.hotdealVoteHot}>🔥 {post.hotVotes || 0}</span>
                <span className={s.hotdealVoteCold}>❄️ {post.coldVotes || 0}</span>
              </div>
              <div className={s.postBody}>
                <div className={s.postTitle}>{post.title}</div>
                {post.body && <p className={s.postExcerpt}>{stripHtml(post.body).slice(0, 60)}...</p>}
                <div className={s.postMeta}>
                  <span className={s.postCatInline}>{post.cat}</span>
                  <span>{post.author}</span>
                  <span>{post.time}</span>
                  <span>조회 {post.views}</span>
                  <span>💬 {post.comments}</span>
                </div>
              </div>
            </div>
          ))
        ) : (
          paginatedPosts.map((post) => (
            <div key={post.id} className={`${s.post} ${s.freePost}`} onClick={() => setDetail(post)}>
              <div className={s.postBody}>
                <div className={s.postTitle}>
                  {post.tag && <span className={`${s.tagLabel} ${s[`tag_${post.tag}`] || ''}`}>#{post.tag}</span>}
                  {post.title}
                </div>
                {post.body && <p className={s.postExcerpt}>{stripHtml(post.body).slice(0, 80)}...</p>}
                <div className={s.postMeta}>
                  <span>{post.author}</span>
                  <span>{post.time}</span>
                  <span>👁️ {post.views}</span>
                  <span>💬 {post.comments}</span>
                </div>
              </div>
            </div>
          ))
        )}
      </div>

      {totalPages > 1 && (
        <div className={s.pagination}>
          <button
            className={s.pageBtn}
            disabled={safePage <= 1}
            onClick={() => setPage((current) => Math.max(1, current - 1))}
          >
            ← 이전
          </button>
          <span className={s.pageInfo}>{safePage} / {totalPages}</span>
          <button
            className={s.pageBtn}
            disabled={safePage >= totalPages}
            onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
          >
            다음 →
          </button>
        </div>
      )}

      {detail && (
        <PostDetailModal
          post={detail}
          onClose={() => setDetail(null)}
          board={board}
          user={user}
          onRefresh={refreshPosts}
          onEdit={handleEdit}
          onPostUpdate={handlePostUpdate}
        />
      )}
    </div>
  );
}

const PostDetailModal = React.memo(function PostDetailModal({
  post,
  onClose,
  board,
  user,
  onRefresh,
  onEdit,
  onPostUpdate,
}) {
  const [newComment, setNewComment] = useState('');
  const [comments, setComments] = useState([]);
  const [loadingComments, setLoadingComments] = useState(true);
  const [vote, setVote] = useState(null);
  const [hotVotes, setHotVotes] = useState(post.hotVotes || post.hot_votes || 0);
  const [coldVotes, setColdVotes] = useState(post.coldVotes || post.not_votes || 0);
  const { isLoggedIn, addToast } = useStore();

  useEffect(() => {
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  useEffect(() => {
    const controller = new AbortController();
    setLoadingComments(true);
    fetch(`/api/posts/${post.id}/comments`, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`comment fetch failed: ${response.status}`);
        return response.json();
      })
      .then((result) => setComments(result.data || []))
      .catch((error) => {
        if (error.name !== 'AbortError') console.error(error);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingComments(false);
      });
    return () => controller.abort();
  }, [post.id]);

  const addComment = async () => {
    const content = newComment.trim();
    if (!content) return;
    if (!isLoggedIn) {
      addToast('댓글을 작성하려면 로그인이 필요합니다.', 'error');
      return;
    }

    try {
      const response = await fetch(`/api/posts/${post.id}/comments`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
        credentials: 'include',
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        addToast(errorData.detail || '댓글 작성에 실패했습니다.', 'error');
        return;
      }
      const result = await response.json();
      setComments((current) => [...current, result.data]);
      setNewComment('');
      addToast('댓글이 등록되었습니다', 'success');
      onPostUpdate?.(post.id, { comments: comments.length + 1 });
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
      const response = await fetch(`/api/posts/${post.id}/vote`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ vote_type: voteType }),
        credentials: 'include',
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        addToast(errorData.detail || '투표 처리에 실패했습니다.', 'error');
        return;
      }
      const result = await response.json();
      setHotVotes(result.data.hot_votes);
      setColdVotes(result.data.not_votes);
      setVote(result.data.user_vote);
      onPostUpdate?.(post.id, {
        hotVotes: result.data.hot_votes,
        coldVotes: result.data.not_votes,
      });
    } catch {
      addToast('투표 중 오류가 발생했습니다.', 'error');
    }
  };

  const handleDelete = async () => {
    if (!window.confirm('정말 삭제하시겠습니까?')) return;
    try {
      const response = await fetch(`/api/posts/${post.id}`, {
        method: 'DELETE',
        credentials: 'include',
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        addToast(errorData.detail || '삭제에 실패했습니다.', 'error');
        return;
      }
      addToast('게시글이 삭제되었습니다.', 'success');
      onClose();
      onRefresh();
    } catch {
      addToast('삭제 중 오류가 발생했습니다.', 'error');
    }
  };

  const isAuthor = user && Number(post.author_id) === Number(user.id);

  return (
    <div className={s.modalOverlay} onClick={onClose} role="presentation">
      <div className={s.modal} onClick={(event) => event.stopPropagation()} role="dialog" aria-modal="true" aria-label="게시글 상세">
        <button className={s.modalClose} onClick={onClose} aria-label="닫기"><X size={20} /></button>

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

          {post.body && (
            <div
              className={`${s.modalContent} ${s.richContent}`}
              dangerouslySetInnerHTML={{ __html: sanitizeHTML(post.body) }}
            />
          )}

          {post.url && sanitizeURL(post.url) && (
            <a href={sanitizeURL(post.url)} target="_blank" rel="noopener noreferrer" className={s.dealLink}>
              🔗 핫딜 링크로 이동
            </a>
          )}

          <div className={s.modalStats}>
            <Eye size={14} /> {post.views}
            <MessageSquare size={14} /> {comments.length}
            {board === 'hotdeal' && <span>🔥 {hotVotes} / ❄️ {coldVotes}</span>}
          </div>

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
            {comments.map((comment) => (
              <div key={comment.id} className={s.comment}>
                <strong>{comment.author_nickname || comment.author}</strong>
                <span className={s.commentTime}>
                  {comment.created_at ? formatRelativeTime(comment.created_at) : comment.time}
                </span>
                <p>{comment.content || comment.text}</p>
              </div>
            ))}
          </div>
          <div className={s.commentInput}>
            <input
              value={newComment}
              onChange={(event) => setNewComment(event.target.value)}
              placeholder={isLoggedIn ? '댓글을 입력하세요...' : '로그인 후 댓글을 작성할 수 있습니다'}
              onKeyDown={(event) => event.key === 'Enter' && addComment()}
              disabled={!isLoggedIn}
            />
            <button onClick={addComment} disabled={!isLoggedIn}><Send size={16} /></button>
          </div>
        </div>
      </div>
    </div>
  );
});
