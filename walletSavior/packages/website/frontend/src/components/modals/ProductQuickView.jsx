import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import Modal from '../common/Modal';
import useStore from '../../stores/appStore';
import { productService } from '../../services/productService';
import { fmt } from '../../utils/helpers';
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

export default function ProductQuickView({ data, onClose }) {
  const navigate = useNavigate();
  const addToShoppingList = useStore((st) => st.addToShoppingList);
  const addToast = useStore((st) => st.addToast);

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

  if (!data) return null;

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

  const handlePriceCompare = () => {
    onClose();
    if (productId) navigate(`/price/${productId}`);
  };

  const handleCategoryCompare = () => {
    if (categoryId) {
      onClose();
      navigate(`/price/category/${categoryId}`);
    }
  };

  const handleAddToCart = () => {
    addToShoppingList({
      productId,
      name,
      price: salePrice,
      unit,
      icon: src.icon,
    });
    addToast(`${name}을(를) 장보기 리스트에 추가했어요`, 'success');
    onClose();
  };

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
            <img src={image} alt={name} className={s.img} />
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
          <button className={s.closeBtn} onClick={onClose}>
            닫기
          </button>
        </div>
      </div>
    </Modal>
  );
}
