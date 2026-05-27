import { useState, useEffect, useCallback, memo } from 'react';
import { useNavigate } from 'react-router-dom';
import { Heart } from 'lucide-react';
import Modal from '../common/Modal';
import SafeImage from '../common/SafeImage';
import useStore from '../../stores/appStore';
import { productService } from '../../services/productService';
import { api } from '../../services/api';
import { fmt } from '../../utils/helpers';
import { buildWishlistPayload, normalizeProduct } from '../../utils/productActions';
import s from './ProductQuickView.module.css';

const SOURCE_LABELS = {
  mart_crawl: { label: '마트 할인', icon: '🏪', cls: 'srcMart' },
  community_deal: { label: '커뮤니티 핫딜', icon: '🔥', cls: 'srcDeal' },
  baseline: { label: '기준가', icon: '📏', cls: 'srcBase' },
  unknown: { label: '일반 상품', icon: '📦', cls: 'srcDefault' },
};

function getSourceInfo(type) {
  return SOURCE_LABELS[type] || SOURCE_LABELS.unknown;
}

function ProductQuickViewContent({ data, onClose }) {
  const navigate = useNavigate();
  const addToShoppingList = useStore((st) => st.addToShoppingList);
  const addToast = useStore((st) => st.addToast);
  const isLoggedIn = useStore((st) => st.isLoggedIn);
  const favorites = useStore((st) => st.favorites);
  const favoriteItems = useStore((st) => st.favoriteItems);
  const addFavorite = useStore((st) => st.addFavorite);
  const removeFavorite = useStore((st) => st.removeFavorite);
  const setFavoriteRemoteId = useStore((st) => st.setFavoriteRemoteId);

  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);

  const productId = data?.id ?? null;

  useEffect(() => {
    if (!productId) return;
    let cancelled = false;
    setLoading(true);
    productService
      .getProduct(productId)
      .then((res) => {
        if (!cancelled) setDetail(res.data ?? res);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [productId]);

  // Merge autocomplete data with full detail (detail takes precedence for richer fields)
  const d = detail || {};
  const name = d.name || data.name || data.product_name || '상품';
  const salePrice = d.current_price ?? data.current_price ?? data.price ?? null;
  const origPrice = d.original_price ?? data.original_price ?? null;
  const discountPct = d.discount_pct ?? data.discount_pct ?? null;
  const unit = d.unit ?? data.unit ?? '';
  const sourceType = d.source_type ?? data.source_type ?? 'unknown';
  const image = d.image_url ?? data.image_url ?? data.image ?? '';
  const categoryPath = d.category_path ?? data.category_path ?? '';
  const categoryId = d.category_id ?? data.category_id ?? null;
  const description = d.description ?? data.description ?? '';

  const src = getSourceInfo(sourceType);
  const hasDiscount = discountPct != null && discountPct > 0;
  const hasOrigPrice = origPrice != null && origPrice > 0;
  const wishlistProduct = { ...data, ...d, name, price: salePrice, original_price: origPrice, unit, source_type: sourceType, image_url: image, category_path: categoryPath, category_id: categoryId };
  const favoriteId = normalizeProduct(wishlistProduct).favoriteId;
  const isFav = favorites.includes(favoriteId);

  const handlePriceCompare = useCallback(() => {
    onClose();
    if (productId) navigate(`/price/${productId}`);
  }, [onClose, productId, navigate]);

  const handleCategoryCompare = useCallback(() => {
    if (categoryId) {
      onClose();
      navigate(`/price/category/${categoryId}`);
    }
  }, [onClose, categoryId, navigate]);

  const handleAddToCart = useCallback(() => {
    addToShoppingList({
      productId,
      name,
      price: salePrice,
      unit,
      icon: src.icon,
    });
    addToast(`${name}을(를) 장보기 리스트에 추가했어요`, 'success');
    onClose();
  }, [addToShoppingList, productId, name, salePrice, unit, src.icon, addToast, onClose]);

  const handleToggleWishlist = useCallback(() => {
    if (!isLoggedIn) {
      addToast('로그인이 필요합니다', 'warning');
      return;
    }
    if (isFav) {
      const remoteId = favoriteItems?.[favoriteId]?.remote_id;
      removeFavorite(favoriteId);
      if (remoteId) api.delete(`/api/wishlist/${remoteId}`).catch(() => {});
      addToast('찜 목록에서 제거했어요', 'info');
      return;
    }
    const payload = buildWishlistPayload(wishlistProduct);
    addFavorite(favoriteId, payload);
    api.post('/api/wishlist', payload).then(async (res) => {
      const json = res?.json ? await res.json().catch(() => null) : null;
      const remoteId = json?.data?.id || json?.id;
      if (remoteId) setFavoriteRemoteId(favoriteId, remoteId);
    }).catch(() => {
      removeFavorite(favoriteId);
      addToast('찜 추가에 실패했어요. 잠시 후 다시 시도해주세요.', 'error');
    });
    addToast(`${name} 찜했어요 ❤️`, 'success');
  }, [isLoggedIn, isFav, favoriteItems, favoriteId, wishlistProduct, name, addFavorite, removeFavorite, setFavoriteRemoteId, addToast]);

  return (
    <Modal isOpen onClose={onClose} title={name} size="sm">
      <div className={s.body}>
        {/* Source badge */}
        <span className={`${s.srcBadge} ${s[src.cls]}`}>
          {src.icon} {src.label}
        </span>

        {/* Image area */}
        <div className={s.imgWrap}>
          {image ? (
            <SafeImage src={image} alt={name} className={s.img} />
          ) : (
            <div className={s.imgPlaceholder}>📷</div>
          )}
          {hasDiscount && (
            <span className={s.discBadge}>-{discountPct}%</span>
          )}
        </div>

        {/* Category breadcrumb */}
        {categoryPath && (
          <span className={s.category}>📁 {categoryPath}</span>
        )}

        {/* Price section */}
        {salePrice != null && (
          <div className={s.priceSection}>
            <div className={s.priceRow}>
              <span className={s.label}>판매가</span>
              <span className={s.sale}>{fmt(salePrice)}원</span>
            </div>
            {hasOrigPrice && (
              <div className={s.priceRow}>
                <span className={s.label}>정가</span>
                <span className={s.orig}>{fmt(origPrice)}원</span>
              </div>
            )}
            {hasDiscount && (
              <div className={s.priceRow}>
                <span className={s.label}>할인율</span>
                <span className={s.disc}>-{discountPct}%</span>
              </div>
            )}
          </div>
        )}

        {/* Detail rows */}
        {unit && (
          <div className={s.row}>
            <span className={s.label}>규격/단위</span>
            <span>{unit}</span>
          </div>
        )}

        <div className={s.row}>
          <span className={s.label}>소스</span>
          <span className={s[src.cls]}>{src.icon} {src.label}</span>
        </div>

        {description && (
          <div className={s.descWrap}>
            <span className={s.label}>상품 설명</span>
            <p className={s.desc}>{description}</p>
          </div>
        )}

        {loading && <p className={s.loading}>상세 정보 불러오는 중…</p>}

        {/* Actions */}
        <div className={s.actions}>
          {productId && (
            <button className={s.compareBtn} onClick={handlePriceCompare}>
              📊 물가비교 상세
            </button>
          )}
          {categoryId && (
            <button className={s.categoryBtn} onClick={handleCategoryCompare}>
              📁 카테고리 비교
            </button>
          )}
          <button className={s.cartBtn} onClick={handleAddToCart}>
            🛒 장보기에 추가
          </button>
          <button className={s.closeBtn} onClick={handleToggleWishlist}>
            <Heart size={16} fill={isFav ? 'currentColor' : 'none'} />
            {isFav ? ' 찜 해제' : ' 찜하기'}
          </button>
          <button className={s.closeBtn} onClick={onClose}>
            닫기
          </button>
        </div>
      </div>
    </Modal>
  );
}

const ProductQuickView = memo(function ProductQuickView({ data, onClose }) {
  // Lazy render: skip all content when there's no data
  if (!data) return null;
  return <ProductQuickViewContent data={data} onClose={onClose} />;
});

export default ProductQuickView;
