import { useState, useRef } from 'react';
import { Pencil, ImagePlus, X, Send, Eye, MessageSquare, Clock } from 'lucide-react';
import { COMMUNITY_POSTS, PRODUCTS, fmt, verifyPrice } from '../../data/mockData';
import useStore from '../../stores/appStore';
import s from './CommunityPage.module.css';

const BOARD_TABS = [
  { id: 'hotdeal', label: '🔥 핫딜 게시판' },
  { id: 'free', label: '💬 자유 게시판' },
];
const CATS = ['전체', '마트', '온라인', '외식', '기타'];
const WRITE_CATS = ['마트', '온라인', '외식', '기타'];

const VERIFY_STYLES = {
  great_deal: { bg: 'rgba(52,211,153,.1)', color: 'var(--green)', icon: '🔥' },
  verified:   { bg: 'rgba(56,189,248,.08)', color: 'var(--accent)', icon: '✅' },
  sus_low:    { bg: 'rgba(248,113,113,.1)', color: 'var(--red)', icon: '⚠️' },
  sus_high:   { bg: 'rgba(248,113,113,.1)', color: 'var(--red)', icon: '🚨' },
};

export default function CommunityPage() {
  const [board, setBoard] = useState('hotdeal');
  const [filter, setFilter] = useState('전체');
  const [showWrite, setShowWrite] = useState(false);
  const [detail, setDetail] = useState(null);
  const { isLoggedIn, addToast, login } = useStore();

  // Write form state
  const [wTitle, setWTitle] = useState('');
  const [wBody, setWBody] = useState('');
  const [wCat, setWCat] = useState('마트');
  const [wProduct, setWProduct] = useState('');
  const [wPrice, setWPrice] = useState('');
  const [wLink, setWLink] = useState('');
  const [wImages, setWImages] = useState([]);
  const fileRef = useRef(null);

  const filtered = (filter === '전체' ? COMMUNITY_POSTS : COMMUNITY_POSTS.filter(p => p.cat === filter));

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
      login({ name: '데모유저', email: 'demo@wallet.com' });
      addToast('데모 로그인 완료! 이제 글을 작성할 수 있습니다.', 'success');
    }
    setShowWrite(!showWrite);
  };

  return (
    <div>
      <div className={s.hdr}>
        <div>
          <h2>핫딜 공유 커뮤니티</h2>
          <p>직접 발견한 할인을 공유하고, 자동으로 시세 비교를 해드립니다</p>
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
            className={`${s.mainTab} ${board === t.id ? s.mainTabActive : ''}`}
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
            placeholder="내용을 입력하세요 (가격, 매장 위치, 수량 제한 등)"
            rows={5}
            value={wBody}
            onChange={e => setWBody(e.target.value)}
          />

          <div className={s.writeRow}>
            <select value={wCat} onChange={e => setWCat(e.target.value)}>
              {WRITE_CATS.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
            <input
              placeholder="품목명 (선택 — DB 자동 비교)"
              value={wProduct}
              onChange={e => setWProduct(e.target.value)}
              list="product-list"
            />
            <datalist id="product-list">
              {PRODUCTS.map(p => <option key={p.id} value={p.name} />)}
            </datalist>
            <input
              type="number"
              placeholder="가격 (원, 선택)"
              value={wPrice}
              onChange={e => setWPrice(e.target.value)}
            />
          </div>

          {/* Link input for hotdeal board */}
          {board === 'hotdeal' && (
            <input
              className={s.linkInput}
              placeholder="핫딜 링크 (선택)"
              value={wLink}
              onChange={e => setWLink(e.target.value)}
            />
          )}

          {/* Image Upload */}
          <div className={s.imgUpload}>
            <button className={s.imgBtn} onClick={() => fileRef.current?.click()}>
              <ImagePlus size={18} /> 사진 추가
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

          {/* Verification */}
          {verification && (
            <div className={s.verifyResult} style={{
              background: VERIFY_STYLES[verification.status]?.bg || 'var(--glass)',
              color: VERIFY_STYLES[verification.status]?.color || 'var(--text)'
            }}>
              <span>{verification.emoji}</span>
              <span>{verification.label}</span>
              {matchedProduct && <span className={s.verifyDetail}>DB 평균: {fmt(matchedProduct.avg)}원</span>}
            </div>
          )}
          {!matchedProduct && wProduct && (
            <div className={s.noMatch}>ℹ️ DB에 없는 품목입니다. 검증 없이 등록됩니다.</div>
          )}
          {verification && !verification.canPost && (
            <div className={s.blocked}>⛔ 등록 차단됨 — 허위 가격이 의심됩니다.</div>
          )}

          <button className={s.submitBtn} onClick={handleWrite} disabled={verification?.canPost === false}>
            등록
          </button>
        </div>
      )}

      {/* Category Filter */}
      <div className={s.filterRow}>
        {CATS.map(t => (
          <button
            key={t}
            className={`${s.tab} ${filter === t ? s.tabActive : ''}`}
            onClick={() => setFilter(t)}
          >
            {t}
          </button>
        ))}
      </div>

      {/* Post List */}
      <div className={s.list}>
        {filtered.map(p => (
          <div key={p.id} className={s.post} onClick={() => setDetail(p)}>
            <span className={s.postCat}>{p.cat}</span>
            <div className={s.postBody}>
              <div className={s.postTitle}>
                {p.verified && (
                  <span className={s.verifyBadge} style={{
                    background: VERIFY_STYLES[p.verified]?.bg,
                    color: VERIFY_STYLES[p.verified]?.color
                  }}>
                    {VERIFY_STYLES[p.verified]?.icon}
                  </span>
                )}
                {p.title}
              </div>
              {p.body && <p className={s.postExcerpt}>{p.body.slice(0, 60)}...</p>}
              <div className={s.postMeta}>
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
        ))}
      </div>

      {/* Detail Modal */}
      {detail && <PostDetailModal post={detail} onClose={() => setDetail(null)} />}
    </div>
  );
}

function PostDetailModal({ post, onClose }) {
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
          </div>

          {/* DB Price Badge */}
          {matchedProduct && post.priceVsAvg !== null && (
            <div className={`${s.dbBadge} ${post.priceVsAvg < -20 ? s.dbBadgeDeal : s.dbBadgeOk}`}>
              🎯 DB 기반 적정가: {fmt(matchedProduct.avg)}원 · 현재 평균 대비 {post.priceVsAvg}%
            </div>
          )}

          {/* Vote */}
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
