import { ExternalLink, Heart } from 'lucide-react';
import Modal from '../common/Modal';
import useStore from '../../stores/appStore';
import { api } from '../../services/api';
import { fmt } from '../../utils/helpers';
import s from './HotdealModal.module.css';

export default function HotdealModal({ data, onClose }) {
  const isLoggedIn = useStore((st) => st.isLoggedIn);
  const favorites = useStore((st) => st.favorites);
  const addFavorite = useStore((st) => st.addFavorite);
  const removeFavorite = useStore((st) => st.removeFavorite);
  const addToast = useStore((st) => st.addToast);

  if (!data) return null;

  const title = data.title || data.name || '핫딜';
  const price = data.price ?? data.current_price ?? null;
  const originalPrice = data.original_price ?? null;
  const source = data.source || data.source_name || '';
  const sourceUrl = data.source_url || data.link || data.url || '';
  const description = data.description || data.content || '';
  const likes = data.likes ?? data.recommend ?? 0;
  const comments = data.comment_count ?? data.comments ?? 0;
  const views = data.views ?? data.view_count ?? 0;
  const postedAt = data.posted_at || data.created_at || '';

  const productId = data.product_id || data.id || title;
  const isFav = favorites.includes(productId);

  const handleToggleWishlist = () => {
    if (!isLoggedIn) {
      addToast('로그인이 필요합니다', 'warning');
      return;
    }
    if (isFav) {
      removeFavorite(productId);
      addToast('찜 목록에서 제거했어요', 'info');
    } else {
      addFavorite(productId);
      api.post('/api/wishlist', {
        product_id: data.product_id || null,
        item_name: title,
        item_price: price,
        source: source,
        source_url: sourceUrl,
      }).catch(() => {});
      addToast(`${title} 찜했어요 ❤️`, 'success');
    }
  };

  const sourceLabel =
    source === 'ppomppu' ? '뽐뿌' :
    source === 'fmkorea' ? '에펨코리아' :
    source === 'ruliweb' ? '루리웹' :
    source || '커뮤니티';

  return (
    <Modal isOpen onClose={onClose} title={title} size="sm">
      <div className={s.body}>
        <span className={s.source}>🔥 {sourceLabel}</span>

        {price != null && (
          <div className={s.priceRow}>
            <span className={s.price}>{fmt(price)}원</span>
            {originalPrice != null && originalPrice > 0 && (
              <span className={s.origPrice}>{fmt(originalPrice)}원</span>
            )}
          </div>
        )}

        {postedAt && (
          <div className={s.row}>
            <span className={s.label}>등록일</span>
            <span>{postedAt}</span>
          </div>
        )}

        {(likes > 0 || comments > 0 || views > 0) && (
          <div className={s.reactions}>
            {likes > 0 && <span className={s.reaction}>👍 {likes}</span>}
            {comments > 0 && <span className={s.reaction}>💬 {comments}</span>}
            {views > 0 && <span className={s.reaction}>👀 {views}</span>}
          </div>
        )}

        {description && (
          <div className={s.desc}>{description}</div>
        )}

        <div className={s.actions}>
          {sourceUrl && (
            <a href={sourceUrl} target="_blank" rel="noopener noreferrer" className={s.linkBtn}>
              <ExternalLink size={16} />
              원문 보기 ({sourceLabel})
            </a>
          )}
          <button className={`${s.wishBtn} ${isFav ? s.wishActive : ''}`} onClick={handleToggleWishlist}>
            <Heart size={16} fill={isFav ? 'currentColor' : 'none'} />
            {isFav ? '찜 해제' : '찜하기'}
          </button>
          <button className={s.closeBtn} onClick={onClose}>
            닫기
          </button>
        </div>
      </div>
    </Modal>
  );
}
