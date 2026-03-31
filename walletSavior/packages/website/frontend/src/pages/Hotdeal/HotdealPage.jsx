import { useState, useCallback, useMemo, useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { X, Info, Eye, MessageSquare, Clock, Send } from 'lucide-react';
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { HOTDEAL_FILTERS, PRODUCTS, fmt, genPriceHistory } from '../../data/mockData';
import { HOTDEALS, HOTDEAL_SOURCES } from '../../data/seedData';
import useInfiniteScroll from '../../hooks/useInfiniteScroll';
import Badge from '../../components/common/Badge';
import s from './HotdealPage.module.css';

const SOURCES = HOTDEAL_SOURCES;
const PAGE_SIZE = 8;

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
  const [filter, setFilter] = useState('all');
  const [source, setSource] = useState('전체');
  const [sort, setSort] = useState('time');
  const [detail, setDetail] = useState(null);
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const [votes, setVotes] = useState({});

  useEffect(() => {
    const openDealId = location.state?.openDealId;
    if (openDealId) {
      const deal = HOTDEALS.find((d) => d.id === openDealId);
      if (deal) setDetail(deal);
      window.history.replaceState({}, '');
    }
  }, [location.state]);

  const allItems = useMemo(() => {
    let items = filter === 'all' ? [...HOTDEALS] : HOTDEALS.filter(d => d.cat === filter);
    if (source !== '전체') items = items.filter(d => d.source === source);
    if (sort === 'discount') items.sort((a, b) => {
      const ra = a.price && a.origPrice ? a.price / a.origPrice : 1;
      const rb = b.price && b.origPrice ? b.price / b.origPrice : 1;
      return ra - rb;
    });
    if (sort === 'popular') items.sort((a, b) => b.views - a.views);
    if (sort === 'priceAsc') items.sort((a, b) => (a.price || Infinity) - (b.price || Infinity));
    return items;
  }, [filter, source, sort]);

  const items = allItems.slice(0, visibleCount);
  const hasMore = visibleCount < allItems.length;

  const loadMore = useCallback(() => {
    if (hasMore) setVisibleCount(prev => Math.min(prev + PAGE_SIZE, allItems.length));
  }, [hasMore, allItems.length]);

  const sentinelRef = useInfiniteScroll(loadMore, { enabled: hasMore });

  const handleVote = (id, type) => {
    setVotes(prev => {
      const current = prev[id];
      if (current === type) return { ...prev, [id]: null };
      return { ...prev, [id]: type };
    });
  };

  return (
    <div>
      <div className={s.hdr}>
        <h2>핫딜 모아보기</h2>
        <p>뽐뿌 · 어미새 · 루리웹 · 에펨코리아 · 무신사 핫딜과 자동 가격 판단</p>
      </div>

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
          {SOURCES.map(src => (
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
        {items.map(d => {
          const tier = getTier(d.price, d.origPrice);
          const matchedProduct = PRODUCTS.find(p => d.title.includes(p.name));
          const vsAvg = matchedProduct && d.price
            ? Math.round((1 - d.price / matchedProduct.avg) * 100)
            : null;
          const vote = votes[d.id];

          return (
            <div key={d.id} className={s.card} onClick={() => setDetail(d)}>
              {d.thumb && <img src={d.thumb} alt={d.title} className={s.thumb} loading="lazy" />}
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
                  </div>
                </div>
                <div className={s.cardMeta}>👁️ {d.views} · 💬 {d.comments} · 🔥 {d.hotVotes || 0} / ❄️ {d.coldVotes || 0}</div>
                <div className={s.voteRow} onClick={e => e.stopPropagation()}>
                  <button
                    className={`${s.voteBtn} ${vote === 'hot' ? s.voteBtnHot : ''}`}
                    onClick={() => handleVote(d.id, 'hot')}
                  >🔥 핫딜</button>
                  <button
                    className={`${s.voteBtn} ${vote === 'cold' ? s.voteBtnCold : ''}`}
                    onClick={() => handleVote(d.id, 'cold')}
                  >❄️ 아니다</button>
                </div>
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

      {detail && <HotdealDetailModal item={detail} votes={votes} onVote={handleVote} onClose={() => setDetail(null)} />}
    </div>
  );
}

function HotdealDetailModal({ item, votes, onVote, onClose }) {
  const [newComment, setNewComment] = useState('');
  const [comments, setComments] = useState(item?.commentData || []);
  const vote = votes[item.id];

  const matchedProduct = PRODUCTS.find(p => item.title.includes(p.name));
  const chartData = useMemo(
    () => matchedProduct ? genPriceHistory(matchedProduct, 30) : [],
    [matchedProduct]
  );

  const addComment = () => {
    if (!newComment.trim()) return;
    setComments(prev => [...prev, { id: Date.now(), author: '나', text: newComment, time: '방금 전' }]);
    setNewComment('');
  };

  return (
    <div className={s.modalOverlay} onClick={onClose}>
      <div className={s.modal} onClick={e => e.stopPropagation()}>
        <button className={s.modalClose} onClick={onClose}><X size={20} /></button>

        {item.thumb && <img src={item.thumb} alt="" className={s.modalHero} />}

        <div className={s.modalBody}>
          <div className={s.modalMeta}>
            <span className={s.source}>{item.source}</span>
            <span className={s.time}><Clock size={12} /> {item.time}</span>
            {item.url && (
              <a href={item.url} target="_blank" rel="noopener noreferrer" className={s.sourceLink} onClick={e => e.stopPropagation()}>
                🔗 원본 보기
              </a>
            )}
          </div>
          <h3 className={s.modalTitle}>{item.title}</h3>

          <div className={s.modalPriceRow}>
            {item.price && <span className={s.modalPrice}>{fmt(item.price)}원</span>}
            {item.origPrice && <span className={s.modalOrig}>{fmt(item.origPrice)}원</span>}
            {item.price && item.origPrice && (
              <span className={s.modalDisc}>{Math.round((1 - item.price / item.origPrice) * 100)}% 할인</span>
            )}
          </div>

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
            >🔥 핫딜이다</button>
            <button
              className={`${s.modalVoteBtn} ${vote === 'cold' ? s.modalVoteCold : ''}`}
              onClick={() => onVote(item.id, 'cold')}
            >❄️ 아니다</button>
          </div>

          {/* 가격 이력 차트 */}
          {matchedProduct && chartData.length > 0 && (
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
          )}
        </div>

        {/* 댓글 */}
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
