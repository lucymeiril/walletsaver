import { ExternalLink } from 'lucide-react';
import { fmt } from '../../../data/mockData';
import { parseMenuItems, getRepresentativePrice } from '../utils';
import s from '../LocalPage.module.css';

export default function NaverPlaceDetailContent({ place, onFocusMap }) {
  const { items: menuItems, rawText: menuRawText } = parseMenuItems(place.menu_info);
  const priceInfo = getRepresentativePrice(place.menu_info);

  return (
    <div className={s.modalDetail}>
      <div className={s.detailHeader}>
        <h3 className={s.detailName}>{place.name}</h3>
        {place.category && <span className={s.detailCat}>{place.category}</span>}
      </div>

      {place.image_url && (
        <div className={s.detailImageWrap}>
          <img src={place.image_url} alt={place.name} className={s.detailImage} />
        </div>
      )}

      {place.address && <p className={s.detailAddr}>📍 {place.address}</p>}
      {place.tel && (
        <p className={s.detailTel}>
          📞 <a href={`tel:${place.tel}`} className={s.telLink}>{place.tel}</a>
        </p>
      )}
      {place.distance && <p className={s.detailDist}>📏 {place.distance}</p>}
      {place.rating > 0 && <p className={s.detailRating}>⭐ 리뷰 {place.rating}개</p>}

      {priceInfo && (
        <div className={s.priceSummary}>
          <span className={s.priceSummaryLabel}>메뉴 가격</span>
          <span className={s.priceSummaryValue}>
            평균 {fmt(priceInfo.avg)}원
            {priceInfo.count > 1 && ` (${fmt(priceInfo.min)}~${fmt(priceInfo.max)}원)`}
          </span>
        </div>
      )}

      {menuItems.length > 0 && (
        <div className={s.detailSection}>
          <h4>📋 메뉴 및 가격</h4>
          <div className={s.menuTable}>
            {menuItems.map((m, i) => (
              <div key={i} className={s.menuRow}>
                <span className={s.menuName}>{m.name}</span>
                <span className={s.menuPrice}>{fmt(m.price)}원</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 파싱 실패 시 원본 텍스트 표시 */}
      {menuItems.length === 0 && menuRawText && (
        <div className={s.detailSection}>
          <h4>📋 메뉴 정보</h4>
          <pre className={s.menuRawText}>{menuRawText}</pre>
        </div>
      )}

      {/* 파싱 성공했지만 일부 파싱 못한 텍스트가 있는 경우 */}
      {menuItems.length > 0 && menuRawText && (
        <div className={s.menuRawHint}>
          <details>
            <summary>기타 메뉴 정보</summary>
            <pre className={s.menuRawText}>{menuRawText}</pre>
          </details>
        </div>
      )}

      <div className={s.btnGroup}>
        <button className={s.mapFocusBtn} onClick={() => onFocusMap(place.name, place.url)}>
          🗺️ 지도에서 위치 보기
        </button>
        {place.url && (
          <a href={place.url} target="_blank" rel="noopener noreferrer" className={s.naverLinkBtn}>
            <ExternalLink size={14} /> 네이버 지도에서 보기
          </a>
        )}
      </div>
    </div>
  );
}
