import { useState, useMemo } from 'react';
import { MapPin } from 'lucide-react';
import { GAS_STATIONS, RESTAURANTS, LOCAL_AVGS, RECIPES, fmt, calcRecipeCost } from '../../data/mockData';
import useStore from '../../stores/appStore';
import s from './LocalPage.module.css';

export default function LocalPage() {
  const [tab, setTab] = useState('gas');
  const [fuel, setFuel] = useState('gasoline');
  const [restCat, setRestCat] = useState('all');
  const [selfOnly, setSelfOnly] = useState(false);
  const [location, setLocation] = useState('');
  const { addToast } = useStore();

  const gasStations = useMemo(() => {
    let stations = [...GAS_STATIONS].filter(g => g[fuel]);
    if (selfOnly) stations = stations.filter(g => g.name.includes('셀프'));
    stations.sort((a, b) => a[fuel] - b[fuel]);
    return stations;
  }, [fuel, selfOnly]);

  const avgGas = gasStations.length
    ? Math.round(gasStations.reduce((sum, g) => sum + g[fuel], 0) / gasStations.length)
    : 0;

  const filteredRest = restCat === 'all' ? RESTAURANTS : RESTAURANTS.filter(r => r.cat === restCat);

  const cookExample = RECIPES.find(r => r.name === '짜장면');
  const cookCost = cookExample ? calcRecipeCost(cookExample) : null;

  const handleLocation = () => {
    addToast('현재 위치를 사용합니다. (데모)', 'info');
    setLocation('서울 강남구 역삼동');
  };

  return (
    <div>
      <div className={s.hdr}>
        <h2>우리 동네 물가 지도</h2>
        <p>주유소 및 식당/카페 평균 가격을 비교하세요</p>
      </div>

      <div className={s.layout}>
        {/* Map area */}
        <div className={s.map}>
          <div className={s.mapPlaceholder}>
            <MapPin size={48} strokeWidth={1.2} />
            <p>지도 API 연결 시 위치가 표시됩니다</p>
            <span className={s.mapTag}>Kakao Maps / Naver Maps API 연동 예정</span>
          </div>
        </div>

        {/* Sidebar */}
        <div className={s.sidebar}>
          {/* Main Toggle */}
          <div className={s.mainToggle}>
            <button className={`${s.toggleBtn} ${tab === 'gas' ? s.toggleActive : ''}`} onClick={() => setTab('gas')}>
              ⛽ 주유소
            </button>
            <button className={`${s.toggleBtn} ${tab === 'rest' ? s.toggleActive : ''}`} onClick={() => setTab('rest')}>
              🍽️ 동네 식당
            </button>
          </div>

          {/* Location Input */}
          <div className={s.locationRow}>
            <input
              className={s.locationInput}
              value={location}
              onChange={e => setLocation(e.target.value)}
              placeholder="위치를 입력하세요"
            />
            <button className={s.locationBtn} onClick={handleLocation}>📍 현위치</button>
          </div>

          {tab === 'gas' ? (
            <>
              {/* Fuel type */}
              <div className={s.fuelToggle}>
                {[['gasoline', '휘발유'], ['diesel', '경유'], ['lpg', 'LPG']].map(([k, l]) => (
                  <button key={k} className={`${s.fuelBtn} ${fuel === k ? s.fuelActive : ''}`} onClick={() => setFuel(k)}>
                    {l}
                  </button>
                ))}
              </div>

              {/* Self filter */}
              <div className={s.filterRow}>
                <button
                  className={`${s.filterCheck} ${selfOnly ? s.filterCheckActive : ''}`}
                  onClick={() => setSelfOnly(!selfOnly)}
                >
                  {selfOnly ? '✅' : '⬜'} 셀프 주유소만
                </button>
              </div>

              {/* Station list */}
              <div className={s.list}>
                {gasStations.map((g, i) => {
                  const isSelf = g.name.includes('셀프');
                  return (
                    <div key={i} className={s.item}>
                      <span className={`${s.rank} ${i === 0 ? s.rank1 : i === 1 ? s.rank2 : i === 2 ? s.rank3 : ''}`}>
                        {i + 1}
                      </span>
                      <div className={s.itemBody}>
                        <div className={s.itemName}>
                          {g.name}
                          <span className={s.itemBrand}>{g.brand}</span>
                        </div>
                        <div className={s.itemAddr}>{g.addr}</div>
                        {isSelf && <span className={s.selfTag}>셀프</span>}
                      </div>
                      <div className={s.itemRight}>
                        <span className={s.itemPrice}>{fmt(g[fuel])}원</span>
                        <div className={s.itemDist}>~{(0.5 + i * 0.3).toFixed(1)}km</div>
                      </div>
                    </div>
                  );
                })}
              </div>

              <div className={s.avg}>
                <span>전국 평균</span>
                <strong>{fmt(avgGas)}원/L</strong>
              </div>
            </>
          ) : (
            <>
              {/* Restaurant category */}
              <div className={s.fuelToggle}>
                {['all', '한식', '중식', '카페'].map(c => (
                  <button key={c} className={`${s.fuelBtn} ${restCat === c ? s.fuelActive : ''}`} onClick={() => setRestCat(c)}>
                    {c === 'all' ? '전체' : c}
                  </button>
                ))}
              </div>

              {/* Restaurant list */}
              <div className={s.list}>
                {filteredRest.map((r, i) => {
                  const avg = LOCAL_AVGS[r.menu];
                  const diff = avg ? r.price - avg : null;
                  return (
                    <div key={i} className={s.item}>
                      <div className={s.itemBody}>
                        <div className={s.itemName}>{r.name}</div>
                        <div className={s.itemAddr}>
                          {r.menu} · <span className={s.rating}>⭐ {r.rating}</span>
                        </div>
                      </div>
                      <div className={s.itemRight}>
                        <span className={s.itemPrice}>{fmt(r.price)}원</span>
                        {diff !== null && (
                          <div className={s.itemVs} style={{ color: diff <= 0 ? 'var(--green)' : 'var(--red)' }}>
                            시세 대비 {diff <= 0 ? fmt(diff) : `+${fmt(diff)}`}원
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Cook vs Eat banner */}
              {cookCost && (
                <div className={s.cookBanner}>
                  <div className={s.cookTitle}>🍳 메뉴 가격 vs 직접 해먹기</div>
                  <div className={s.cookCompare}>
                    <div className={`${s.cookItem} ${s.cookEat}`}>
                      <span className={s.cookLabel}>🍽️ 외식 평균</span>
                      <span className={s.cookPrice}>{fmt(cookExample.eatingOut)}원</span>
                    </div>
                    <div className={`${s.cookItem} ${s.cookHome}`}>
                      <span className={s.cookLabel}>🏠 직접 조리</span>
                      <span className={s.cookPrice}>{fmt(cookCost.total)}원</span>
                    </div>
                  </div>
                  <div className={s.cookSavings}>
                    💰 직접 해먹으면 {fmt(cookCost.savings)}원 절약 ({cookCost.pct}%)
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
