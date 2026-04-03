import { useNavigate } from 'react-router-dom';
import Modal from '../common/Modal';
import { fmt } from '../../utils/helpers';
import s from './ProductQuickView.module.css';

export default function ProductQuickView({ data, onClose }) {
  const navigate = useNavigate();

  if (!data) return null;

  const name = data.name || data.product_name || '상품';
  const price = data.current_price ?? data.price ?? null;
  const unit = data.unit ?? '';
  const categoryPath = data.category_path || '';
  const categoryId = data.category_id || null;
  const productId = data.id ?? null;
  const sourceType = data.source_type || '';

  const handlePriceCompare = () => {
    onClose();
    if (productId) {
      navigate(`/price/${productId}`);
    }
  };

  const handleCategoryCompare = () => {
    if (categoryId) {
      onClose();
      navigate(`/price/category/${categoryId}`);
    }
  };

  return (
    <Modal isOpen onClose={onClose} title={name} size="sm">
      <div className={s.body}>
        {categoryPath && (
          <span className={s.category}>📁 {categoryPath}</span>
        )}

        {price != null && (
          <div className={s.priceRow}>
            <span className={s.price}>{fmt(price)}원</span>
            {unit && <span className={s.unit}>/ {unit}</span>}
          </div>
        )}

        {sourceType && (
          <div className={s.row}>
            <span className={s.label}>소스</span>
            <span>{sourceType}</span>
          </div>
        )}

        {categoryPath && (
          <div className={s.row}>
            <span className={s.label}>카테고리</span>
            <span>{categoryPath}</span>
          </div>
        )}

        <div className={s.actions}>
          {productId && (
            <button className={s.compareBtn} onClick={handlePriceCompare}>
              📊 물가비교 상세 보기
            </button>
          )}
          {categoryId && (
            <button className={s.compareBtn} onClick={handleCategoryCompare}>
              📁 카테고리 비교 보기
            </button>
          )}
          <button className={s.closeBtn} onClick={onClose}>
            닫기
          </button>
        </div>
      </div>
    </Modal>
  );
}
