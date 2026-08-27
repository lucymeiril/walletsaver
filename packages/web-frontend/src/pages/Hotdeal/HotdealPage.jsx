import React, { useState, useCallback, useMemo, useEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';
import { X, Info, Eye, MessageSquare, Clock, Send } from 'lucide-react';
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { HOTDEAL_FILTERS } from '../../utils/constants';
import { fmt } from '../../utils/helpers';
import useInfiniteScroll from '../../hooks/useInfiniteScroll';
import useAbortController from '../../hooks/useAbortController';
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
  if (!price || !origPrice) return null;
  const ratio = price / origPrice;
  if (ratio <= 0.4) return { label: '역대급', cls: 'tierUltra', color: 'success' };
  if (ratio <= 0.6) return { label: '대박', cls: 'tierGreat', color: 'info' };
  if (ratio <= 0.8) return { label: '괜찮은', cls: 'tierGood', color: 'warning' };
  return { label: '보통', cls: 'tierWait', color: 'neutral' };
}

export default function HotdealPage() {
  const location = useLocation();
  const { addToast } = useStore();
  const [filter, setFilter] = useState('all');
  const [source, setSource] = useState('전체');
  const [sort, setSort] = useState('discount');
  const [detail, setDetail] = useState(null);
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const [votes, setVotes] = useState({});

  const [allDeals, setAllDeals] = useState([]);
  const [products, setProducts] = useState([]);
  const [sources, setSources] = useState(['전체']);
  const [loading, setLoading] = useState(true);
  const [newDealCount, setNewDealCount] = useState(0);
  const lastDealIdsRef = useRef(null);
  const [voteLoading, setVoteLoading] = useState({});
  const voteLoadingRef = useRef({});
  const getSignal = useAbortController();

  useEffect(() => {
    voteLoadingRef.current = voteLoading;
  }, [voteLoading]);

  // 핫딜 출처 목록 API에서 조회
  useEffect(() => {
    const signal = getSignal();
    fetch('/api/hotdeals/sources', { signal }).then(r => r.json())
      .then(res => setSources(res.data || ['전체']))
      .catch(err => {
        if (err.name !== 'AbortError') setSources(['전체']);
      });
  }, [getSignal]);

  useEffect(() => {
    const signal = getSignal();
    fetch('/api/products/search?per_page=50', { signal }).then(r => r.json())
      .then(res => setProducts(res.data || []))
      .catch(err => { if (err.name !== 'AbortError') console.error(err); });
  }, [getSignal]);

  useEffect(() => {
    setLoading(true);
    setVisibleCount(PAGE_SIZE);
    const controller = new AbortController();

    fetchAllHotdeals(filter, controller.signal)
      .then(setAllDeals)
      .catch(err => {
        if (err.name === 'AbortError') return;
        console.error(err);
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
      const deal = allDeals.find((d) => d.id === openDealId);
      if (deal) setDetail(deal);
      window.history.replaceState({}, '');
    }
  }, [location.state, allDeals]);

  // 새 핫딜 감지
  useEffect(() => {
    if (allDeals.length === 0) return;
    const currentIds = new Set(allDeals.map(d => d.id));
    if (lastDealIdsRef.current !== null) {
      const fresh = [...currentIds].filter(id => !lastDealIdsRef.current.has(id));
      if (fresh.length > 0) setNewDealCount(prev => prev + fresh.length);
    }
    lastDealIdsRef.current = currentIds;
  }, [allDeals]);

  // 60초마다 최신 페이지를 확인하고, 기존 전체 목록을 유지한 채 새/갱신 항목만 병합한다.
  useEffect(() => {
    let currentController = null;
    const interval = setInterval(() => {
      if (currentController) currentController.abort();
      currentController = new AbortController();
      fetchHotdealPage(filter, 1, currentController.signal)
        .then(({ deals }) => {
          if (!deals.length) return;
          setAllDeals(current => {
            const freshIds = new Set(deals.map(deal => deal.id));
            return [...deals, ...current.filter(deal => !freshIds.has(deal.id))];
          });
        })
        .catch(() => {});
    }, 60000);
    return () => {
      clearInterval(interval);
      if (currentController) currentController.abort();
    };
  }, [filter]);

  const allItems = useMemo(() => {
    let items = [...allDeals];
    if (source !== '전체') items = items.filter(d => d.source === source);
    if (sort === 'discount') items.sort((a, b) => {
      const ra = a.price && a.origPrice ? a.price / a.origPrice : 1;
      const rb = b.price && b.origPrice ? b.price / b.origPrice : 1;
      return ra - rb;
    });
    if (sort === 'popular') items.sort((a, b) => {
      const scoreA = (a.hotVotes || 0) - (a.coldVotes || 0);
      const scoreB = (b.hotVotes || 0) - (b.coldVotes || 0);
      return scoreB - scoreA || (b.views || 0) - (a.views || 0);
    });
    if (sort === 'priceAsc') items.sort((a, b) => (a.price || Infinity) - (b.price || Infinity));
    return items;
  }, [allDeals, source, sort]);

  const items = allItems.slice(0, visibleCount);
  const hasMore = visibleCount < allItems.length;

  const loadMore = useCallback(() => {
    if (hasMore) setVisibleCount(prev => Math.min(prev + PAGE_SIZE, allItems.length));
  }, [hasMore, allItems.length]);

  const sentinelRef = useInfiniteScroll(loadMore, { enabled: hasMore });

  const handleVote = useCallback(async (id, type) => {
    if (voteLoadingRef.current[id]) return;
    setVoteLoading(prev => ({ ...prev, [id]: true }));
    const prev = votes[id];
    const newType = prev === type ? null : type;
    setVotes(p => ({ ...p, [id]: newType }));
    let toastShown = false;
    try {
      const res = await fetch(`/api/hotdeals/${id}/vote`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ vote_type: voteTypeForApi(newType) }),
      });
      if (!res.ok) {
        if (res.status === 401) {
          addToast('로그인 후 투표할 수 있습니다', 'error');
        } else if (res.status === 429) {
          addToast('투표 요청이 너무 많습니다. 잠시 후 다시 시도해주세요.', 'error');
        } else if (res.status === 400) {
          addToast('투표 요청을 처리할 수 없습니다. 새로고침 후 다시 시도해주세요.', 'error');
        } else {
          addToast('투표 처리에 실패했습니다', 'error');
        }
        toastShown = true;
        throw new Error(`vote failed: ${res.status}`);
      }
      const data = await res.json();
      if (data.data) {
        const serverVote = voteTypeFromApi(data.data.user_vote);
        setVotes(p => ({ ...p, [id]: serverVote }));
        setAllDeals(ds => ds.map(d =>
          d.id === id ? { ...d, hotVotes: data.data.votes_hot, coldVotes: data.data.votes_not } : d
        ));
        setDetail(prev => prev && prev.id === id
          ? { ...prev, hotVotes: data.data.votes_hot, coldVotes: data.data.votes_not }
          : prev
        );
      }
    } catch {
      if (!toastShown) addToast('투표 처리에 실패했습니다', 'error');
      setVotes(p => ({ ...p, [id]: prev }));
    } finally {
      setVoteLoading(prev => ({ ...prev, [id]: false }));
    }
  }, [votes, addToast]);

  const throttledVote = useThrottledCallback(handleVote, 1000);

  const handleCommentCountChange = useCallback((dealId, count) => {
    setAllDeals(ds => ds.map(d => d.id === dealId ? { ...d, comments: count } : d));
    setDetail(prev => prev && prev.id === dealId ? { ...prev, comments: count } : prev);
  }, []);

  return (
    <div>
      <div className={s.hdr}>
        <h2>핫딜 모아보기</h2>
        <p>뽐뿌 · 어미새 · 루리웹 · 에펨코리아 · 무신사 핫딜과 자동 가격 판단</p>
      </div>

      {loading && <div style={{ display: 'flex', justifyContent: 'center', padding: '2rem 0' }}><Spinner /></div>}

      {newDealCount > 0 && (
        <div className={s.newDealToast} onClick={() => { setNewDealCount(0); setVisibleCount(PAGE_SIZE); window.scrollTo({ top: 0, behavior: 'smooth' }); }}>
          🔔 새 핫딜 {newDealCount}개가 등록되었습니다 — 클릭하여 확인
        </div>
      )}

      <div className={s.controls}>
        <div className={s.filterRow}>
          <div className={s.filters}>
            {HOTDEAL_FILTERS.map(f => (
              <button
                key={f.key}
                className={`${s.fbtn} ${filter === f.key ? s.fbtnActive : ''}`}
                onClick={() => { setFilter(f.key); setVisibleCount(PAGE_SIZE); }}
              >
                {f.label}
              </button>
            ))}
          </div>
          <select className={s.sortSel} value={sort} onChange={e => setSort(e.target.value)}>
            <option value="time">최신순</option>
            <option value="discount">할인율순</option>
            <option value="priceAsc">가격순</option>
            <option value="popular">인기순</option>
          </select>
        </div>
        <div className={s.sourceRow}>
          <span className={s.sourceLabel}>출처:</span>
          {sources.map(src => (
            <button
              key={src}
              className={`${s.sourceBtn} ${source === src ? s.sourceBtnActive : ''}`}
              onClick={() => { setSource(src); setVisibleCount(PAGE_SIZE); }}
            >
              {src}
            </button>
          ))}
        </div>
      </div>

      <div className={s.grid}>
        {!loading && items.length === 0 && (
          <EmptyState
            title="핫딜이 없습니다"
            description="다른 카테고리나 필터를 선택해 보세요."
          />
        )}
        {items.map(d => {
          const tier = getTier(d.price, d.origPrice);
          const matchedProduct = products.find(p => d.title?.includes(p.name));
          const vsAvg = matchedProduct && d.price
            ? Math.round((1 - d.price / matchedProduct.avg) * 100)
            : null;
          const vote = votes[d.id];

          return (
            <div key={d.id} className={s.card} onClick={() => setDetail(d)}>
              {d.thumb && <SafeImage src={d.thumb} alt={d.title} className={s.thumb} />}
              <div className={s.cardBody}>
                <div className={s.cardHead}>
                  <span className={s.source}>{d.source}</span>
                  <span className={s.time}>{d.time}</span>
                </div>
                <div className={s.cardTitle}>{d.title}</div>
                <div className={s.cardBottom}>
                  <span className={s.price}>{d.price ? `${fmt(d.price)}원` : ''}</span>
                  <div className={s.badges}>
                    {tier && (
                      <Badge variant="solid" color={tier.color} size="sm">{tier.label}</Badge>
                    )}
                    {d.price && d.origPrice && (
                      <span className={`${s.discBadge} ${d.price / d.origPrice <= 0.5 ? s.ultra : d.price / d.origPrice <= 0.75 ? s.great : s.ok}`}>
                        {Math.round((1 - d.price / d.origPrice) * 100)}% 할인
                      </span>
                    )}
                    {vsAvg !== null && (
                      <span className={`${s.dbBadge} ${vsAvg > 20 ? s.dbGreat : vsAvg > 0 ? s.dbOk : s.dbWarn}`}
                        title="수집된 평균 시세와 비교한 결과">
                        시세 대비 {vsAvg > 0 ? '-' : '+'}{Math.abs(vsAvg)}%
                        <span className={s.dbInfo}><Info size={11} /></span>
                      </span>
                    )}
                    {(d.hotVotes || 0) + (d.coldVotes || 0) >= 10 && (
                      <span className={s.verifiedBadge}>✅ 커뮤니티 검증</span>
                    )}
                  </div>
                </div>
                <div className={s.cardMeta}>👁️ {d.views} · 💬 {d.comments} · 🔥 {d.hotVotes || 0} / ❄️ {d.coldVotes || 0}</div>
                <div className={s.voteRow} onClick={e => e.stopPropagation()}>
                  <button
                    className={`${s.voteBtn} ${vote === 'hot' ? s.voteBtnHot : ''}`}
                    onClick={() => throttledVote(d.id, 'hot')}
                    disabled={voteLoading[d.id]}
                    aria-busy={voteLoading[d.id]}
                  >{voteLoading[d.id] ? '⏳' : '🔥'} 핫딜</button>
                  <button
                    className={`${s.voteBtn} ${vote === 'cold' ? s.voteBtnCold : ''}`}
                    onClick={() => throttledVote(d.id, 'cold')}
                    disabled={voteLoading[d.id]}
                    aria-busy={voteLoading[d.id]}
                  >{voteLoading[d.id] ? '⏳' : '❄️'} 아니다</button>
                </div>
                {d.url && (
                  <a href={d.url} target="_blank" rel="noopener noreferrer" className={s.ctaBtn} onClick={e => e.stopPropagation()}>
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

      {detail && <HotdealDetailModal item={detail} votes={votes} voteLoading={voteLoading} onVote={handleVote} onClose={() => setDetail(null)} products={products} addToast={addToast} onCommentCountChange={handleCommentCountChange} />}
    </div>
  );
}

const HotdealDetailModal = React.memo(function HotdealDetailModal({ item, votes, voteLoading, onVote, onClose, products, addToast, onCommentCountChange }) {
  const [newComment, setNewComment] = useState('');
  const [comments, setComments] = useState([]);
  const [commentsLoading, setCommentsLoading] = useState(true);
  const vote = votes[item.id];
  const isVotePending = Boolean(voteLoading[item.id]);

  const matchedProduct = products.find(p => item.title?.includes(p.name));
  const totalVotes = (item.hotVotes || 0) + (item.coldVotes || 0);

  // 댓글 API 조회
  useEffect(() => {
    setCommentsLoading(true);
    fetch(`/api/hotdeals/${item.id}/comments`)
      .then(r => r.json())
      .then(res => setComments(res.data || []))
      .catch(() => setComments(item?.commentData || []))
      .finally(() => setCommentsLoading(false));
  }, [item.id]);

  useEffect(() => {
    if (!commentsLoading && onCommentCountChange) {
      onCommentCountChange(item.id, comments.length);
    }
  }, [comments.length, commentsLoading, item.id, onCommentCountChange]);

  const [chartData, setChartData] = useState([]);
  const [chartLoading, setChartLoading] = useState(false);
  useEffect(() => {
    if (!matchedProduct) return;
    setChartLoading(true);
    fetch(`/api/products/${matchedProduct.id}/price-history?days=30`)
      .then(r => r.json())
      .then(res => setChartData(res.data || []))
      .catch(console.error)
      .finally(() => setChartLoading(false));
  }, [matchedProduct?.id]);

  // 댓글 서버 저장
  const addComment = async () => {
    if (!newComment.trim()) return;
    try {
      const res = await fetch(`/api/hotdeals/${item.id}/comments`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: newComment, author: '나' }),
        credentials: 'include',
      });
      if (!res.ok) {
        addToast('댓글 작성에 실패했습니다', 'error');
        return;
      }
      const data = await res.json();
      if (data.data) {
        setComments(prev => [...prev, data.data]);
      }
      setNewComment('');
      addToast('댓글이 등록되었습니다', 'success');
    } catch {
      addToast('댓글 작성에 실패했습니다', 'error');
    }
  };

  const deleteComment = async (commentId) => {
    try {
      const res = await fetch(`/api/hotdeals/${item.id}/comments/${commentId}`, {
        method: 'DELETE',
        credentials: 'include',
      });
      if (!res.ok) {
        addToast('댓글 삭제에 실패했습니다', 'error');
        return;
      }
      setComments(prev => prev.filter(c => c.id !== commentId));
    } catch {
      addToast('댓글 삭제에 실패했습니다', 'error');
    }
  };

  // Escape 키로 모달 닫기
  useEffect(() => {
    const handleKeyDown = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  return (
    <div className={s.modalOverlay} onClick={onClose} role="presentation">
      <div className={s.modal} onClick={e => e.stopPropagation()} role="dialog" aria-modal="true" aria-label="핫딜 상세">
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
            {item.price && item.origPrice && (
              <span className={s.modalDisc}>{Math.round((1 - item.price / item.origPrice) * 100)}% 할인</span>
            )}
          </div>

          {/* 원본 사이트 CTA */}
          {item.url && (
            <a href={item.url} target="_blank" rel="noopener noreferrer" className={s.ctaBtnLg} onClick={e => e.stopPropagation()}>
              🔗 원본 사이트로 이동
            </a>
          )}

          <div className={s.modalStats}>
            <Eye size={14} /> {item.views}
            <MessageSquare size={14} /> {item.comments}
            <span>🔥 {item.hotVotes || 0} / ❄️ {item.coldVotes || 0}</span>
          </div>

          {/* 투표 */}
          <div className={s.modalVote}>
            <button
              className={`${s.modalVoteBtn} ${vote === 'hot' ? s.modalVoteHot : ''}`}
              onClick={() => onVote(item.id, 'hot')}
              disabled={isVotePending}
              aria-busy={isVotePending}
            >{isVotePending ? '⏳' : '🔥'} 핫딜이다</button>
            <button
              className={`${s.modalVoteBtn} ${vote === 'cold' ? s.modalVoteCold : ''}`}
              onClick={() => onVote(item.id, 'cold')}
              disabled={isVotePending}
              aria-busy={isVotePending}
            >{isVotePending ? '⏳' : '❄️'} 아니다</button>
          </div>

          {/* 가격 이력 차트 또는 빈 상태 */}
          {matchedProduct ? (
            chartLoading ? (
              <div className={s.emptyChart}><p>가격 데이터 로딩 중...</p></div>
            ) : chartData.length > 0 ? (
              <div className={s.chartBox}>
                <h4>📈 {matchedProduct.name} 30일 가격 추이</h4>
                <ResponsiveContainer width="100%" height={180}>
                  <AreaChart data={chartData}>
                    <defs>
                      <linearGradient id="colorDealPrice" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#38bdf8" stopOpacity={0.2} />
                        <stop offset="95%" stopColor="#38bdf8" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <XAxis dataKey="date" tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} width={50} tickFormatter={v => fmt(v)} />
                    <Tooltip
                      contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, fontSize: '.85rem' }}
                      formatter={v => [`${fmt(v)}원`, '가격']}
                    />
                    <Area type="monotone" dataKey="price" stroke="#38bdf8" strokeWidth={2} fill="url(#colorDealPrice)" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <div className={s.emptyChart}>
                <div className={s.emptyChartIcon}>📊</div>
                <p>가격 데이터를 수집 중입니다</p>
                <span>곧 {matchedProduct.name}의 가격 추이를 확인할 수 있습니다</span>
              </div>
            )
          ) : (
            products.length > 0 && (
              <div className={s.similarBox}>
                <h4>🔍 유사 상품 추천</h4>
                <div className={s.similarList}>
                  {products.slice(0, 3).map(p => (
                    <div key={p.id} className={s.similarItem}>
                      <span>{p.name}</span>
                      {p.avg && <span className={s.similarPrice}>평균 {fmt(p.avg)}원</span>}
                    </div>
                  ))}
                </div>
              </div>
            )
          )}
        </div>

        {/* 댓글 */}
        <div className={s.commentSec}>
          <h4>💬 댓글 {comments.length}개</h4>
          <div className={s.commentList}>
            {commentsLoading && <p className={s.noComment}>댓글 불러오는 중...</p>}
            {!commentsLoading && comments.length === 0 && <p className={s.noComment}>아직 댓글이 없습니다.</p>}
            {comments.map(c => (
              <div key={c.id} className={s.comment}>
                <div className={s.commentHeader}>
                  <div>
                    <strong>{c.author}</strong>
                    <span className={s.commentTime}>{c.time}</span>
                  </div>
                  {c.author === '나' && (
                    <button className={s.deleteCommentBtn} onClick={() => deleteComment(c.id)} title="삭제">🗑️</button>
                  )}
                </div>
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
});