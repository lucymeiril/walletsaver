import { LOCAL_AVGS, RECIPES, fmt, calcRecipeCost } from '../../../data/mockData';
import s from '../LocalPage.module.css';

export default function RestDetailContent({ restaurant, onFocusMap }) {
  const avg = LOCAL_AVGS[restaurant.menu];
  const dist = (0.3 + restaurant.idx * 0.25).toFixed(1);

  const matchedRecipe = RECIPES.find(r =>
    restaurant.menu.includes(r.name) || r.name.includes(restaurant.menu.replace('(1인분)', '').trim())
  );
  const recipeCost = matchedRecipe ? calcRecipeCost(matchedRecipe) : null;

  const mockMenuItems = [
    { name: restaurant.menu, price: restaurant.price },
    { name: restaurant.cat === '카페' ? '카페라떼' : '공기밥', price: restaurant.cat === '카페' ? restaurant.price + 1000 : 1000 },
    { name: restaurant.cat === '카페' ? '녹차라떼' : restaurant.cat === '중식' ? '짬뽕' : '된장찌개', price: restaurant.price + (restaurant.cat === '카페' ? 500 : 1500) },
  ];

  return (
    <div className={s.modalDetail}>
      <div className={s.detailHeader}>
        <h3 className={s.detailName}>{restaurant.name}</h3>
        <span className={s.detailCat}>{restaurant.cat}</span>
      </div>
      <p className={s.detailAddr}>📍 {restaurant.addr}</p>
      {restaurant.tel && (
        <p className={s.detailTel}>
          📞 <a href={`tel:${restaurant.tel}`} className={s.telLink}>{restaurant.tel}</a>
        </p>
      )}
      <p className={s.detailDist}>📏 현재 위치에서 ~{dist}km</p>
      <p className={s.detailRating}>⭐ {restaurant.rating} / 5.0</p>

      <div className={s.detailSection}>
        <h4>📋 메뉴 및 가격</h4>
        <div className={s.menuTable}>
          {mockMenuItems.map((m, i) => {
            const menuAvg = LOCAL_AVGS[m.name];
            const menuDiff = menuAvg ? m.price - menuAvg : null;
            return (
              <div key={i} className={s.menuRow}>
                <span className={s.menuName}>{m.name}</span>
                <span className={s.menuPrice}>{fmt(m.price)}원</span>
                {menuDiff !== null && (
                  <span className={s.menuDiff} style={{ color: menuDiff <= 0 ? 'var(--green)' : 'var(--red)' }}>
                    시세 대비 {menuDiff <= 0 ? fmt(menuDiff) : `+${fmt(menuDiff)}`}원
                  </span>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {recipeCost && (
        <div className={s.detailSection}>
          <h4>🍳 외식 vs 직접 조리</h4>
          <div className={s.cookCompareModal}>
            <div className={s.cookCompareItem}>
              <span className={s.cookCompareLabel}>🍽️ 외식 (이 식당)</span>
              <span className={s.cookComparePrice}>{fmt(restaurant.price)}원</span>
            </div>
            <span className={s.cookVs}>vs</span>
            <div className={s.cookCompareItem}>
              <span className={s.cookCompareLabel}>🏠 직접 조리</span>
              <span className={s.cookComparePrice} style={{ color: 'var(--green)' }}>{fmt(recipeCost.total)}원</span>
            </div>
          </div>
          <p className={s.cookSavingsModal}>
            💰 직접 해먹으면 {fmt(recipeCost.savings)}원 절약 ({recipeCost.pct}%)
          </p>
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
