import { useNavigate } from 'react-router-dom';
import { ExternalLink } from 'lucide-react';
import Modal from '../common/Modal';
import useStore from '../../stores/appStore';
import { fmt } from '../../utils/helpers';
import s from './MartProductModal.module.css';

const MART_ONLINE_URLS = {
  emart: { name: 'SSG.COM', searchUrl: 'https://www.ssg.com/search.ssg?query=' },
  homeplus: { name: '홈플러스몰', searchUrl: 'https://mfront.homeplus.co.kr/search?keyword=' },
  lotte: { name: '롯데온', searchUrl: 'https://www.lottemart.com/search/search/search.do?keyword=' },
  costco: { name: '코스트코', searchUrl: 'https://www.costco.co.kr/search?text=' },
};

function getOnlineMallUrl(martKey, productName) {
  const mall = MART_ONLINE_URLS[martKey];
  if (!mall) return null;
  return productName ? `${mall.searchUrl}${encodeURIComponent(productName)}` : null;
}

export default function MartProductModal({ data, onClose }) {
  const navigate = useNavigate();
  const addToShoppingList = useStore((st) => st.addToShoppingList);
  const addToast = useStore((st) => st.addToast);

  if (!data) return null;

  // Support both autocomplete data shape and MartPage normalizeItem shape
  const name = data.name || data.product_name || '상품명 없음';
  const salePrice = data.sale ?? data.current_price ?? data.price ?? 0;
  const origPrice = data.orig ?? data.original_price ?? 0;
  const discountPct = data.disc ?? data.discount_pct ?? data.discount ?? 0;
  const eventType = data.event ?? data.event_name ?? '할인';
  const image = data.img ?? data.image_url ?? data.image ?? '';
  const unit = data.unit ?? data.spec ?? '';
  const store = data.store ?? data.branch ?? '';
  const martKey = data.martKey ?? data.source ?? null;
  const martName = data.martName ?? data.source_name ?? martKey ?? '';
  const period = data.period ?? '';
  const detailUrl = data.detailUrl ?? data.source_url ?? data.detail_url ?? '';
  const categoryId = data.category_id ?? null;

  const periodParts = period.split('~');
  const mallInfo = martKey ? MART_ONLINE_URLS[martKey] : null;
  const onlineUrl = getOnlineMallUrl(martKey, name);

  const handleCategoryCompare = () => {
    if (categoryId) {
      onClose();
      navigate(`/price/category/${categoryId}`);
    }
  };

  const handleAddToCart = () => {
    addToShoppingList({ name, price: salePrice, icon: '🏪' });
    addToast(`${name}을(를) 장보기 리스트에 추가했어요`, 'success');
    onClose();
  };

  return (
    <Modal isOpen onClose={onClose} title={name} size="sm">
      <div className={s.body}>
        {image && (
          <div className={s.imgWrap}>
            <img src={image} alt={name} className={s.img} />
            {discountPct > 0 && (
              <span className={s.discBadge}>-{discountPct}%</span>
            )}
          </div>
        )}

        <div className={s.row}>
          <span className={s.label}>판매가</span>
          <span className={s.sale}>{fmt(salePrice)}원</span>
        </div>
        {origPrice > 0 && (
          <div className={s.row}>
            <span className={s.label}>정가</span>
            <span className={s.orig}>{fmt(origPrice)}원</span>
          </div>
        )}
        {discountPct > 0 && (
          <div className={s.row}>
            <span className={s.label}>할인율</span>
            <span className={s.disc}>-{discountPct}%</span>
          </div>
        )}
        <div className={s.row}>
          <span className={s.label}>행사 유형</span>
          <span className={s.event}>{eventType}</span>
        </div>
        {unit && (
          <div className={s.row}>
            <span className={s.label}>규격/단위</span>
            <span>{unit}</span>
          </div>
        )}
        {store && (
          <div className={s.row}>
            <span className={s.label}>판매 매장</span>
            <span>{store}</span>
          </div>
        )}
        {martName && (
          <div className={s.row}>
            <span className={s.label}>마트</span>
            <span>{martName}</span>
          </div>
        )}
        {period && (
          <div className={s.row}>
            <span className={s.label}>행사 기간</span>
            <span>{periodParts[0]?.trim() || ''} ~ {periodParts[1]?.trim() || ''}</span>
          </div>
        )}

        <div className={s.actions}>
          {detailUrl && (
            <a href={detailUrl} target="_blank" rel="noopener noreferrer" className={s.linkBtn}>
              <ExternalLink size={16} />
              상품 페이지로 이동
            </a>
          )}
          {onlineUrl && mallInfo && (
            <a href={onlineUrl} target="_blank" rel="noopener noreferrer" className={s.mallBtn}>
              🛒 {mallInfo.name}에서 검색
            </a>
          )}
          {categoryId && (
            <button className={s.categoryBtn} onClick={handleCategoryCompare}>
              📊 카테고리 비교
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
