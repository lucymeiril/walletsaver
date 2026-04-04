import { useState, useRef } from 'react';
import { X, ImagePlus, Send, MessageSquare, Eye, Clock } from 'lucide-react';
import { fmt } from '../../utils/helpers';
import SafeImage from '../common/SafeImage';
import s from './DetailModal.module.css';

export default function DetailModal({ item, type, onClose }) {
  const [newComment, setNewComment] = useState('');
  const [comments, setComments] = useState(item?.commentData || []);

  if (!item) return null;

  const addComment = () => {
    if (!newComment.trim()) return;
    setComments(prev => [...prev, { id: Date.now(), author: '나', text: newComment, time: '방금 전' }]);
    setNewComment('');
  };

  return (
    <div className={s.overlay} onClick={onClose} role="presentation">
      <div className={s.modal} onClick={e => e.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="detail-modal-title">
        <button className={s.close} onClick={onClose} aria-label="닫기"><X size={20} /></button>

        {/* 핫딜 상세 */}
        {type === 'hotdeal' && (
          <>
            {item.thumb && <SafeImage src={item.thumb} alt={item.title || '핫딜 이미지'} className={s.hero} />}
            <div className={s.body}>
              <div className={s.meta}><span className={s.source}>{item.source}</span><span className={s.time}><Clock size={12} /> {item.time}</span></div>
              <h3 className={s.title}>{item.title}</h3>
              <div className={s.priceRow}>
                {item.price && <span className={s.price}>{fmt(item.price)}원</span>}
                {item.origPrice && <span className={s.orig}>{fmt(item.origPrice)}원</span>}
                {item.price && item.origPrice && <span className={s.disc}>{Math.round((1-item.price/item.origPrice)*100)}% 할인</span>}
              </div>
              <div className={s.stats}><Eye size={14} /> {item.views} <MessageSquare size={14} /> {item.comments}</div>
              {item.url && (
                <a href={item.url} target="_blank" rel="noopener noreferrer" className={s.extLink}>
                  🔗 원본 글 보기
                </a>
              )}
            </div>
          </>
        )}

        {/* 마트 상세 */}
        {type === 'mart' && (
          <div className={s.body}>
            {item.img && <SafeImage src={item.img} alt={item.name || '마트 상품'} className={s.martImg} />}
            <h3 id="detail-modal-title" className={s.title}>{item.name}</h3>
            <div className={s.priceRow}>
              <span className={s.price}>{fmt(item.sale)}원</span>
              <span className={s.orig}>{fmt(item.orig)}원</span>
              <span className={s.disc}>-{item.disc}%</span>
            </div>
            {item.event && <span className={s.eventTag}>{item.event}</span>}
            {item.dbAvg !== undefined && (
              <div className={s.dbCompare}>
                DB 평균 대비 <strong style={{color: item.sale < item.dbAvg ? 'var(--green)' : 'var(--red)'}}>
                  {item.sale < item.dbAvg ? '-' : '+'}{fmt(Math.abs(item.sale - item.dbAvg))}원
                </strong>
              </div>
            )}
          </div>
        )}

        {/* 커뮤니티 상세 */}
        {type === 'community' && (
          <div className={s.body}>
            <div className={s.meta}><span className={s.source}>{item.cat}</span><span>{item.author}</span><span className={s.time}><Clock size={12} /> {item.time}</span></div>
            <h3 className={s.title}>{item.title}</h3>
            {item.body && <p className={s.postBody}>{item.body}</p>}
            {item.images?.length > 0 && (
              <div className={s.imgGrid}>{item.images.map((url) => <SafeImage key={url} src={url} alt="게시물 이미지" className={s.postImg} />)}</div>
            )}
            {item.priceVsAvg !== null && (
              <div className={s.priceBadge} style={{color: item.priceVsAvg < -20 ? 'var(--green)' : 'var(--text3)'}}>
                DB 평균 대비 {item.priceVsAvg}%
              </div>
            )}
            <div className={s.stats}><Eye size={14} /> {item.views} <MessageSquare size={14} /> {item.comments}</div>
          </div>
        )}

        {/* 댓글 섹션 — 모든 타입 공통 */}
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
            <input value={newComment} onChange={e => setNewComment(e.target.value)} placeholder="댓글을 입력하세요..." onKeyDown={e => e.key==='Enter' && addComment()} />
            <button onClick={addComment}><Send size={16} /></button>
          </div>
        </div>
      </div>
    </div>
  );
}
