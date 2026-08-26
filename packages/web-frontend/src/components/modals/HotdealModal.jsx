import { ExternalLink, Heart } from 'lucide-react';
import Modal from '../common/Modal';
import useStore from '../../stores/appStore';
import useCartStore from '../../stores/cartStore';
import { api } from '../../services/api';
import { fmt } from '../../utils/helpers';
import { buildCartPayload, buildWishlistPayload, normalizeProduct } from '../../utils/productActions';
import s from './HotdealModal.module.css';

export default function HotdealModal({ data, onClose }) {
  const isLoggedIn = useStore((st) => st.isLoggedIn);
  const favorites = useStore((st) => st.favorites);
  const favoriteItems = useStore((st) => st.favoriteItems);
  const addFavorite = useStore((st) => st.addFavorite);
  const removeFavorite = useStore((st) => st.removeFavorite);
  const setFavoriteRemoteId = useStore((st) => st.setFavoriteRemoteId);
  const addToast = useStore((st) => st.addToast);
  const addCartItem = useCartStore((st) => st.addItem);

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

  const normalized = normalizeProduct(data);
  const productId = normalized.favoriteId;
  const isFav = favorites.includes(productId);

  const resolveRemoteWishlistId = async () => {
    const cached = favoriteItems?.[productId]?.remote_id;
    if (cached) return cached;

    const result = await api.getJson('/api/wishlist');
    const rows = result?.data || result?.items || result || [];
    const match = (Array.isArray(rows) ? rows : []).find((row) => {
      if (normalized.numericProductId && row.product_id) {
        return Number(row.product_id) === Number(normalized.numericProductId);
      }
      return (
        (row.item_name || '') === normalized.name
        && (row.store_name || '') === normalized.storeName
      );
    });
    if (!match?.id) return null;
    setFavoriteRemoteId(productId, match.id);
    return match.id;
  };

  const handleToggleWishlist = async () => {
    if (!isLoggedIn) {
      addToast('로그인이 필요합니다', 'warning');
      return;
    }

    try {
      if (isFav) {
        const remoteId = await resolveRemoteWishlistId();
        if (!remoteId) throw new Error('서버 찜 항목을 찾을 수 없습니다.');
        await api.delete(`/api/wishlist/${remoteId}`);
        removeFavorite(productId);
        addToast('찜 목록에서 제거했어요', 'info');
        return;
      }

      const payload = buildWishlistPayload(data);
      const res = await api.post('/api/wishlist', payload);
      const json = await res.json();
      const saved = json?.data || json;
      addFavorite(productId, payload);
      if (saved?.id) setFavoriteRemoteId(productId, saved.id);
      addToast(`${title} 찜했어요 ❤️`, 'success');
    } catch {
      addToast(isFav ? '찜 해제에 실패했습니다.' : '찜 추가에 실패했습니다.', 'error');
    }
  };

  const handleAddToCart = async () => {
    try {
      await addCartItem(buildCartPayload(data));
      addToast(`${title}을(를) 장바구니에 추가했어요`, 'success');
      onClose();
    } catch {
      addToast('장바구니 저장에 실패했습니다. 다시 시도해주세요.', 'error');
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
          <button className={s.cartBtn} onClick={handleAddToCart}>
            🛒 장바구니 담기
          </button>
          <button className={s.closeBtn} onClick={onClose}>
            닫기
          </button>
        </div>
      </div>
    </Modal>
  );
}
