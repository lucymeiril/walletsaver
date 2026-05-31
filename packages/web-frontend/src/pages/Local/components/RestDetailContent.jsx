import { fmt } from '../../../utils/helpers';
import s from '../LocalPage.module.css';

export default function RestDetailContent({ restaurant, onFocusMap }) {
  const dist = restaurant.distance != null
    ? (parseFloat(restaurant.distance) > 100 ? (parseFloat(restaurant.distance) / 1000).toFixed(1) : parseFloat(restaurant.distance).toFixed(1))
    : '?';
  const menuItems = Array.isArray(restaurant.menu_items) ? restaurant.menu_items : [];

  return (
    <div className={s.modalDetail}>
      <div className={s.detailHeader}>
        <h3 className={s.detailName}>{restaurant.name}</h3>
        <span className={s.detailCat}>{restaurant.cat || restaurant.category || '음식'}</span>
      </div>
      <p className={s.detailAddr}>📍 {restaurant.addr || restaurant.address}</p>
      {restaurant.tel && (
        <p className={s.detailTel}>
          📞 <a href={`tel:${restaurant.tel}`} className={s.telLink}>{restaurant.tel}</a>
        </p>
      )}
      <p className={s.detailDist}>📏 현재 위치에서 ~{dist}km</p>
      {restaurant.rating > 0 && <p className={s.detailRating}>⭐ {restaurant.rating} / 5.0</p>}

      {menuItems.length > 0 && (
        <div className={s.detailSection}>
        <h4>📋 메뉴 및 가격</h4>
        <div className={s.menuTable}>
          {menuItems.map((m) => (
            <div key={`${m.name}-${m.price}`} className={s.menuRow}>
              <span className={s.menuName}>{m.name}</span>
              {m.price ? <span className={s.menuPrice}>{fmt(m.price)}원</span> : <span className={s.fuelNA}>가격 정보 없음</span>}
            </div>
          ))}
        </div>
      </div>
      )}
      {menuItems.length === 0 && (
        <div className={s.detailSection}>
          <h4>📋 메뉴 및 가격</h4>
          <p className={s.menuRawText}>네이버 장소 응답에 메뉴 가격 정보가 없습니다.</p>
        </div>
      )}

      <div className={s.btnGroup}>
        <button className={s.mapFocusBtn} onClick={() => onFocusMap(restaurant.name)}>
          🗺️ 지도에서 위치 보기
        </button>
      </div>
    </div>
  );
}
