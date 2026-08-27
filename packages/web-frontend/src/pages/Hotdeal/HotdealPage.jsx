import React, { useState, useCallback, useMemo, useEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';
import { X, MessageSquare, Clock, Send } from 'lucide-react';
import { HOTDEAL_FILTERS } from '../../utils/constants';
import { fmt } from '../../utils/helpers';
import useInfiniteScroll from '../../hooks/useInfiniteScroll';
import useThrottledCallback from '../../hooks/useThrottledCallback';
import Badge from '../../components/common/Badge';
import Spinner from '../../components/common/Spinner';
import SafeImage from '../../components/common/SafeImage';
import EmptyState from '../../components/common/EmptyState';
import useStore from '../../stores/appStore';
import s from './HotdealPage.module.css';

const PAGE_SIZE = 8;
const API_PAGE_SIZE = 100;

function normalizeDeal(deal) {
  return {
    ...deal,
    hotVotes: deal.hotVotes ?? deal.votes_hot ?? 0,
    coldVotes: deal.coldVotes ?? deal.votes_not ?? 0,
  };
}

function hotdealParams(filter, page = 1) {
  const params = new URLSearchParams({
    page: String(page),
    per_page: String(API_PAGE_SIZE),
    sort: 'recent',
  });
  if (filter !== 'all') params.set('category', filter);
  return params;
}

async function fetchHotdealPage(filter, page, signal) {
  const response = await fetch(`/api/hotdeals?${hotdealParams(filter, page)}`, { signal });
  if (!response.ok) throw new Error(`hotdeal fetch failed: ${response.status}`);
  const result = await response.json();
  return {
    deals: (result.data || []).map(normalizeDeal),
    meta: result.meta || {},
  };
}

async function fetchAllHotdeals(filter, signal) {
  const all = [];
  let page = 1;
  let totalPages = 1;
  do {
    const result = await fetchHotdealPage(filter, page, signal);
    all.push(...result.deals);
    totalPages = Math.max(1, Number(result.meta.total_pages || 1));
    page += 1;
  } while (page <= totalPages);
  return all;
}

function voteTypeForApi(type) {
  if (type === 'cold') return 'not';
  return type || 'cancel';
}

function voteTypeFromApi(type) {
  if (type === 'not') return 'cold';
  return type || null;
}

function getTier(price, origPrice) {
  if (!price || !origPrice || origPrice <= price) return null;
  const ratio = price / origPrice;
  if (ratio <= 0.4) return { label: '역대급', color: 'success' };
  if (ratio <= 0.6) return { label: '대박', color: 'info' };
  if (ratio <= 0.8) return { label: '괜찮은', color: 'warning' };
  return { label: '보통', color: 'neutral' };
}

export default function HotdealPage() {
  const location = useLocation();
  const addToast = useStore((state) => state.addToast);
  const [filter, setFilter] = useState('all');
  const [source, setSource] = useState('전체');
  const [sort, setSort] = useState('discount');
  const [detail, setDetail] = useState(null);
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const [votes, setVotes] = useState({});
  const [allDeals, setAllDeals] = useState([]);
  const [sources, setSources] = useState(['전체']);
  const [loading, setLoading] = useState(true);
  const [newDealCount, setNewDealCount] = useState(0);
  const [voteLoading, setVoteLoading] = useState({});
  const voteLoadingRef = useRef({});
  const lastDealIdsRef = useRef(null);

  useEffect(() => {
    voteLoadingRef.current = voteLoading;
  }, [voteLoading]);

  useEffect(() => {
    const controller = new AbortController();
    fetch('/api/hotdeals/sources', { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`source fetch failed: ${response.status}`);
        return response.json();
      })
      .then((result) => setSources(result.data || ['전체']))
      .catch((error) => {
        if (error.name !== 'AbortError') setSources(['전체']);
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    setLoading(true);
    setVisibleCount(PAGE_SIZE);
    const controller = new AbortController();

    fetchAllHotdeals(filter, controller.signal)
      .then(setAllDeals)
      .catch((error) => {
        if (error.name === 'AbortError') return;
        console.error(error);
        addToast('핫딜 데이터를 불러오는데 실패했습니다', 'error');
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });

    return () => controller.abort();
  }, [filter, addToast]);

  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
  }, [sort, source]);

  useEffect(() => {
    lastDealIdsRef.current = null;
    setNewDealCount(0);
  }, [filter]);

  useEffect(() => {
    const openDealId = location.state?.openDealId;
    if (openDealId && allDeals.length > 0) {
      const deal = allDeals.find((item) => item.id === openDealId);
      if (deal) setDetail(deal);
      window.history.replaceState({}, '');
    }
  }, [location.state, allDeals]);

  useEffect(() => {
    if (allDeals.length === 0) return;
    const currentIds = new Set(allDeals.map((deal) => deal.id));
    if (lastDealIdsRef.current !== null) {
      const fresh = [...currentIds].filter((id) => !lastDealIdsRef.current.has(id));
      if (fresh.length > 0) setNewDealCount((count) => count + fresh.length);
    }
    lastDealIdsRef.current = currentIds;
  }, [allDeals]);

  useEffect(() => {
    let currentController = null;
    const interval = setInterval(() => {
      currentController?.abort();
      currentController = new AbortController();
      fetchHotdealPage(filter, 1, currentController.signal)
        .then(({ deals }) => {
          if (!deals.length) return;
          setAllDeals((current) => {
            const refreshedIds = new Set(deals.map((deal) => deal.id));
            return [...deals, ...current.filter((deal) => !refreshedIds.has(deal.id))];
          });
        })
        .catch(() => {});
    }, 60000);

    return () => {
      clearInterval(interval);
      currentController?.abort();
    };
  }, [filter]);

  const allItems = useMemo(() => {
    let items = [...allDeals];
    if (source !== '전체') items = items.filter((deal) => deal.source === source);

    if (sort === 'discount') {
      items.sort((a, b) => {
        const aRatio = a.price && a.origPrice ? a.price / a.origPrice : 1;
        const bRatio = b.price && b.origPrice ? b.price / b.origPrice : 1;
        return aRatio - bRatio;
      });
    } else if (sort === 'popular') {
      items.sort((a, b) => {
        const aScore = (a.hotVotes || 0) - (a.coldVotes || 0);
        const bScore = (b.hotVotes || 0) - (b.coldVotes || 0);
        return bScore - aScore;
      });
    } else if (sort === 'priceAsc') {
      items.sort((a, b) => (a.price || Infinity) - (b.price || Infinity));
    }

    return items;
  }, [allDeals, source, sort]);

  const items = allItems.slice(0, visibleCount);
  const hasMore = visibleCount < allItems.length;
  const loadMore = useCallback(() => {
    if (hasMore) {
      setVisibleCount((count) => Math.min(count + PAGE_SIZE, allItems.length));
    }
  }, [hasMore, allItems.length]);
  const sentinelRef = useInfiniteScroll(loadMore, { enabled: hasMore });

  const handleVote = useCallback(async (id, type) => {
    if (voteLoadingRef.current[id]) return;
    setVoteLoading((current) => ({ ...current, [id]: true }));
    const previousVote = votes[id];
    const nextVote = previousVote === type ? null : type;
    setVotes((current) => ({ ...current, [id]: nextVote }));

    let toastShown = false;
    try {
      const response = await fetch(`/api/hotdeals/${id}/vote`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ vote_type: voteTypeForApi(nextVote) }),
      });
      if (!response.ok) {
        if (response.status === 401) {
          addToast('로그인 후 투표할 수 있습니다', 'error');
        } else if (response.status === 429) {
          addToast('투표 요청이 너무 많습니다. 잠시 후 다시 시도해주세요.', 'error');
        } else {
          const errorData = await response.json().catch(() => ({}));
          addToast(errorData.detail || '투표 처리에 실패했습니다', 'error');
        }
        toastShown = true;
        throw new Error(`vote failed: ${response.status}`);
      }

      const result = await response.json();
      if (result.data) {
        const serverVote = voteTypeFromApi(result.data.user_vote);
        setVotes((current) => ({ ...current, [id]: serverVote }));
        setAllDeals((current) => current.map((deal) =>
          deal.id === id
            ? { ...deal, hotVotes: result.data.votes_hot, coldVotes: result.data.votes_not }
            : deal
        ));
        setDetail((current) => current?.id === id
          ? { ...current, hotVotes: result.data.votes_hot, coldVotes: result.data.votes_not }
          : current
        );
      }
    } catch {
      if (!toastShown) addToast('투표 처리에 실패했습니다', 'error');
      setVotes((current) => ({ ...current, [id]: previousVote }));
    } finally {
      setVoteLoading((current) => ({ ...current, [id]: false }));
    }
  }, [votes, addToast]);

  const throttledVote = useThrottledCallback(handleVote, 1000);

  const handleCommentCountChange = useCallback((dealId, count) => {
    setAllDeals((current) => current.map((deal) =>
      deal.id === dealId ? { ...deal, comments: count } : deal
    ));
    setDetail((current) => current?.id === dealId ? { ...current, comments: count } : current);
  }, []);

  return (
    <div>
      <div className={s.hdr}>
        <h2>핫딜 모아보기</h2>
        <p>수집된 핫딜의 가격·할인율과 커뮤니티 반응을 한곳에서 확인합니다</p>
      </div>

      {loading && (
        <div style={{ display: 'flex', justifyContent: 'center', padding: '2rem 0' }}>
          <Spinner />
        </div>
      )}

      {newDealCount > 0 && (
        <div
          className={s.newDealToast}
          onClick={() => {
            setNewDealCount(0);
            setVisibleCount(PAGE_SIZE);
            window.scrollTo({ top: 0, behavior: 'smooth' });
          }}
        >
          🔔 새 핫딜 {newDealCount}개가 등록되었습니다 — 클릭하여 확인
        </div>
      )}

      <div className={s.controls}>
        <div className={s.filterRow}>
          <div className={s.filters}>
            {HOTDEAL_FILTERS.map((item) => (
              <button
                key={item.key}
                className={`${s.fbtn} ${filter === item.key ? s.fbtnActive : ''}`}
                onClick={() => setFilter(item.key)}
              >
                {item.label}
              </button>
            ))}
          </div>
          <select className={s.sortSel} value={sort} onChange={(event) => setSort(event.target.value)}>
            <option value="time">최신순</option>
            <option value="discount">할인율순</option>
            <option value="priceAsc">가격순</option>
            <option value="popular">인기순</option>
          </select>
        </div>
        <div className={s.sourceRow}>
          <span className={s.sourceLabel}>출처:</span>
          {sources.map((item) => (
            <button
              key={item}
              className={`${s.sourceBtn} ${source === item ? s.sourceBtnActive : ''}`}
              onClick={() => setSource(item)}
            >
              {item}
            </button>
          ))}
        </div>
      </div>

      <div className={s.grid}>
        {!loading && items.length === 0 && (
          <EmptyState
            title="핫딜이 없습니다"
            description="다른 카테고리나 출처를 선택해 보세요."
          />
        )}

        {items.map((deal) => {
          const tier = getTier(deal.price, deal.origPrice);
          const vote = votes[deal.id];
          return (
            <div key={deal.id} className={s.card} onClick={() => setDetail(deal)}>
              {deal.thumb && <SafeImage src={deal.thumb} alt={deal.title} className={s.thumb} />}
              <div className={s.cardBody}>
                <div className={s.cardHead}>
                  <span className={s.source}>{deal.source}</span>
                  <span className={s.time}>{deal.time}</span>
                </div>
                <div className={s.cardTitle}>{deal.title}</div>
                <div className={s.cardBottom}>
                  <span className={s.price}>{deal.price ? `${fmt(deal.price)}원` : ''}</span>
                  <div className={s.badges}>
                    {tier && <Badge variant="solid" color={tier.color} size="sm">{tier.label}</Badge>}
                    {deal.price && deal.origPrice && deal.origPrice > deal.price && (
                      <span className={`${s.discBadge} ${deal.price / deal.origPrice <= 0.5 ? s.ultra : deal.price / deal.origPrice <= 0.75 ? s.great : s.ok}`}>
                        {Math.round((1 - deal.price / deal.origPrice) * 100)}% 할인
                      </span>
                    )}
                    {(deal.hotVotes || 0) + (deal.coldVotes || 0) >= 10 && (
                      <span className={s.verifiedBadge}>✅ 커뮤니티 검증</span>
                    )}
                  </div>
                </div>
                <div className={s.cardMeta}>
                  💬 {deal.comments || 0} · 🔥 {deal.hotVotes || 0} / ❄️ {deal.coldVotes || 0}
                </div>
                <div className={s.voteRow} onClick={(event) => event.stopPropagation()}>
                  <button
                    className={`${s.voteBtn} ${vote === 'hot' ? s.voteBtnHot : ''}`}
                    onClick={() => throttledVote(deal.id, 'hot')}
                    disabled={voteLoading[deal.id]}
                    aria-busy={voteLoading[deal.id]}
                  >
                    {voteLoading[deal.id] ? '⏳' : '🔥'} 핫딜
                  </button>
                  <button
                    className={`${s.voteBtn} ${vote === 'cold' ? s.voteBtnCold : ''}`}
                    onClick={() => throttledVote(deal.id, 'cold')}
                    disabled={voteLoading[deal.id]}
                    aria-busy={voteLoading[deal.id]}
                  >
                    {voteLoading[deal.id] ? '⏳' : '❄️'} 아니다
                  </button>
                </div>
                {deal.url && (
                  <a
                    href={deal.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={s.ctaBtn}
                    onClick={(event) => event.stopPropagation()}
                  >
                    🔗 원본 사이트로 이동
                  </a>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {hasMore && (
        <div ref={sentinelRef} className={s.loadMore}>
          불러오는 중...
        </div>
      )}

      {detail && (
        <HotdealDetailModal
          item={detail}
          votes={votes}
          voteLoading={voteLoading}
          onVote={handleVote}
          onClose={() => setDetail(null)}
          onCommentCountChange={handleCommentCountChange}
        />
      )}
    </div>
  );
}

const HotdealDetailModal = React.memo(function HotdealDetailModal({
  item,
  votes,
  voteLoading,
  onVote,
  onClose,
  onCommentCountChange,
}) {
  const [newComment, setNewComment] = useState('');
  const [comments, setComments] = useState([]);
  const [commentsLoading, setCommentsLoading] = useState(true);
  const { isLoggedIn, addToast } = useStore();
  const vote = votes[item.id];
  const isVotePending = Boolean(voteLoading[item.id]);
  const totalVotes = (item.hotVotes || 0) + (item.coldVotes || 0);

  useEffect(() => {
    const controller = new AbortController();
    setCommentsLoading(true);
    fetch(`/api/hotdeals/${item.id}/comments`, {
      signal: controller.signal,
      credentials: 'include',
    })
      .then((response) => {
        if (!response.ok) throw new Error(`comment fetch failed: ${response.status}`);
        return response.json();
      })
      .then((result) => setComments(result.data || []))
      .catch((error) => {
        if (error.name !== 'AbortError') console.error(error);
      })
      .finally(() => {
        if (!controller.signal.aborted) setCommentsLoading(false);
      });
    return () => controller.abort();
  }, [item.id]);

  useEffect(() => {
    if (!commentsLoading) onCommentCountChange?.(item.id, comments.length);
  }, [comments.length, commentsLoading, item.id, onCommentCountChange]);

  useEffect(() => {
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  const addComment = async () => {
    const content = newComment.trim();
    if (!content) return;
    if (!isLoggedIn) {
      addToast('로그인 후 댓글을 작성할 수 있습니다', 'warning');
      return;
    }

    try {
      const response = await fetch(`/api/hotdeals/${item.id}/comments`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
        credentials: 'include',
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        addToast(errorData.detail || '댓글 작성에 실패했습니다', 'error');
        return;
      }
      const result = await response.json();
      setComments((current) => [...current, result.data]);
      setNewComment('');
      addToast('댓글이 등록되었습니다', 'success');
    } catch {
      addToast('댓글 작성에 실패했습니다', 'error');
    }
  };

  const deleteComment = async (commentId) => {
    try {
      const response = await fetch(`/api/hotdeals/${item.id}/comments/${commentId}`, {
        method: 'DELETE',
        credentials: 'include',
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        addToast(errorData.detail || '댓글 삭제에 실패했습니다', 'error');
        return;
      }
      setComments((current) => current.filter((comment) => comment.id !== commentId));
    } catch {
      addToast('댓글 삭제에 실패했습니다', 'error');
    }
  };

  return (
    <div className={s.modalOverlay} onClick={onClose} role="presentation">
      <div className={s.modal} onClick={(event) => event.stopPropagation()} role="dialog" aria-modal="true" aria-label="핫딜 상세">
        <button className={s.modalClose} onClick={onClose} aria-label="닫기"><X size={20} /></button>

        {item.thumb && <SafeImage src={item.thumb} alt={item.title || '핫딜 이미지'} className={s.modalHero} />}

        <div className={s.modalBody}>
          <div className={s.modalMeta}>
            <span className={s.source}>{item.source}</span>
            <span className={s.time}><Clock size={12} /> {item.time}</span>
            {totalVotes >= 10 && <span className={s.verifiedBadge}>✅ 커뮤니티 검증</span>}
          </div>
          <h3 className={s.modalTitle}>{item.title}</h3>

          <div className={s.modalPriceRow}>
            {item.price && <span className={s.modalPrice}>{fmt(item.price)}원</span>}
            {item.origPrice && <span className={s.modalOrig}>{fmt(item.origPrice)}원</span>}
            {item.price && item.origPrice && item.origPrice > item.price && (
              <span className={s.modalDisc}>{Math.round((1 - item.price / item.origPrice) * 100)}% 할인</span>
            )}
          </div>

          {item.url && (
            <a
              href={item.url}
              target="_blank"
              rel="noopener noreferrer"
              className={s.ctaBtnLg}
              onClick={(event) => event.stopPropagation()}
            >
              🔗 원본 사이트로 이동
            </a>
          )}

          <div className={s.modalStats}>
            <MessageSquare size={14} /> {comments.length}
            <span>🔥 {item.hotVotes || 0} / ❄️ {item.coldVotes || 0}</span>
          </div>

          <div className={s.modalVote}>
            <button
              className={`${s.modalVoteBtn} ${vote === 'hot' ? s.modalVoteHot : ''}`}
              onClick={() => onVote(item.id, 'hot')}
              disabled={isVotePending}
              aria-busy={isVotePending}
            >
              {isVotePending ? '⏳' : '🔥'} 핫딜이다
            </button>
            <button
              className={`${s.modalVoteBtn} ${vote === 'cold' ? s.modalVoteCold : ''}`}
              onClick={() => onVote(item.id, 'cold')}
              disabled={isVotePending}
              aria-busy={isVotePending}
            >
              {isVotePending ? '⏳' : '❄️'} 아니다
            </button>
          </div>

          <div className={s.emptyChart}>
            <p>상품 가격 이력은 정확한 상품 연결 정보가 있을 때만 제공합니다.</p>
          </div>
        </div>

        <div className={s.commentSec}>
          <h4>💬 댓글 {comments.length}개</h4>
          <div className={s.commentList}>
            {commentsLoading && <p className={s.noComment}>댓글 불러오는 중...</p>}
            {!commentsLoading && comments.length === 0 && <p className={s.noComment}>아직 댓글이 없습니다.</p>}
            {comments.map((comment) => (
              <div key={comment.id} className={s.comment}>
                <div className={s.commentHeader}>
                  <div>
                    <strong>{comment.author}</strong>
                    <span className={s.commentTime}>{comment.time}</span>
                  </div>
                  {comment.is_mine && (
                    <button
                      className={s.deleteCommentBtn}
                      onClick={() => deleteComment(comment.id)}
                      title="삭제"
                    >
                      🗑️
                    </button>
                  )}
                </div>
                <p>{comment.text}</p>
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
