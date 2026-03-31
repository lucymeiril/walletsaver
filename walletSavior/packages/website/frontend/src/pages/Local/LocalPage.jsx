import { useState, useMemo, useCallback, useEffect } from 'react';
import { MapPin, Search, RefreshCw, X } from 'lucide-react';
import { GAS_STATIONS, RESTAURANTS, LOCAL_AVGS, RECIPES, fmt, calcRecipeCost } from '../../data/mockData';
import Modal from '../../components/common/Modal';
import useStore from '../../stores/appStore';
import s from './LocalPage.module.css';

/**
 * LocalPage — 우리 동네 물가 지도.
 *
 * 네이버 지도를 iframe으로 삽입하고, 사용자의 검색/위치 이동에 따라
 * 백엔드에서 네이버 플레이스를 실시간 크롤링하여 주변 가게 정보를 표시한다.
 *
 * 구조:
 *   - 좌측: 네이버 지도 iframe (사용자가 직접 조작)
 *   - 우측: 실시간 크롤링 결과 + 기존 mock 데이터 (주유소/식당)
 *   - 하단: 외식 vs 직접 조리 비교
 */
export default function LocalPage() {
  const [tab, setTab] = useState('gas');
  const [fuel, setFuel] = useState('gasoline');
  const [restCat, setRestCat] = useState('all');
  const [selfOnly, setSelfOnly] = useState(false);
  const [location, setLocation] = useState('');
  const [selectedGas, setSelectedGas] = useState(null);
  const [selectedRest, setSelectedRest] = useState(null);
  const [naverQuery, setNaverQuery] = useState('');
  const [naverResults, setNaverResults] = useState([]);
  const [naverLoading, setNaverLoading] = useState(false);
  const [mapLat, setMapLat] = useState(37.4979);
  const [mapLng, setMapLng] = useState(127.0276);
  const { addToast } = useStore();

  // 네이버 지도 iframe URL — 사용자 위치 기반
  const naverMapUrl = useMemo(() => {
    return `https://map.naver.com/p?c=${mapLng},${mapLat},15,0,0,0,dh`;
  }, [mapLat, mapLng]);

  // 네이버 플레이스 실시간 검색 — 백엔드 API 호출
  const searchNaverPlaces = useCallback(async (query) => {
    if (!query || query.length < 1) return;
    setNaverLoading(true);
    try {
      const res = await fetch(
        `/api/local/naver-search?query=${encodeURIComponent(query)}&lat=${mapLat}&lng=${mapLng}&max_items=20`
      );
      const data = await res.json();
      if (data.success && data.data?.items) {
        setNaverResults(data.data.items);
        addToast(`'${query}' 검색: ${data.data.count}건 발견`, 'success');
      } else {
        setNaverResults([]);
        addToast(data.message || '검색 결과 없음', 'warning');
      }
    } catch (err) {
      console.error('네이버 검색 실패:', err);
      setNaverResults([]);
    } finally {
      setNaverLoading(false);
    }
  }, [mapLat, mapLng, addToast]);

  const handleNaverSearch = (e) => {
    e.preventDefault();
    const q = tab === 'gas' ? (naverQuery || '주유소') : (naverQuery || '맛집');
    searchNaverPlaces(q);
  };

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
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          setMapLat(pos.coords.latitude);
          setMapLng(pos.coords.longitude);
          setLocation('현재 위치');
          addToast('현재 위치를 가져왔습니다', 'success');
        },
        () => {
          setLocation('서울 강남구 역삼동');
          addToast('위치 권한이 거부되어 기본 위치를 사용합니다', 'info');
        }
      );
    } else {
      setLocation('서울 강남구 역삼동');
      addToast('브라우저가 위치 서비스를 지원하지 않습니다', 'warning');
    }
  };

  return (
    <div>
      <div className={s.hdr}>
        <h2>우리 동네 물가 지도</h2>
        <p>네이버 지도에서 검색하고, 주변 가게 가격을 실시간으로 비교하세요</p>
      </div>

      <div className={s.layout}>
        {/* 네이버 지도 iframe */}
        <div className={s.map}>
          <iframe
            src={naverMapUrl}
            className={s.naverIframe}
            title="네이버 지도"
            allow="geolocation"
            loading="lazy"
          />
          <div className={s.mapOverlay}>
            <span className={s.mapTag}>🗺️ 네이버 지도 — 지도에서 직접 검색/이동 가능</span>
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

          {/* 네이버 플레이스 실시간 검색 */}
          <form onSubmit={handleNaverSearch} className={s.naverSearchRow}>
            <input
              className={s.naverSearchInput}
              value={naverQuery}
              onChange={e => setNaverQuery(e.target.value)}
              placeholder={tab === 'gas' ? '주유소 검색...' : '맛집, 카페 검색...'}
            />
            <button type="submit" className={s.naverSearchBtn} disabled={naverLoading}>
              {naverLoading ? <RefreshCw size={16} className={s.spin} /> : <Search size={16} />}
            </button>
          </form>

          {/* 네이버 실시간 검색 결과 */}
          {naverResults.length > 0 && (
            <div className={s.naverResults}>
              <div className={s.naverResultsHeader}>
                <span>📍 네이버 검색 결과 ({naverResults.length}건)</span>
                <button className={s.naverClearBtn} onClick={() => setNaverResults([])}>
                  <X size={14} />
                </button>
              </div>
              <div className={s.list}>
                {naverResults.map((r, i) => (
                  <div key={i} className={s.item}>
                    <span className={`${s.rank} ${i === 0 ? s.rank1 : i === 1 ? s.rank2 : i === 2 ? s.rank3 : ''}`}>
                      {i + 1}
                    </span>
                    <div className={s.itemBody}>
                      <div className={s.itemName}>{r.name}</div>
                      <div className={s.itemAddr}>
                        {r.addr || r.category}
                        {r.rating > 0 && <span className={s.rating}> ⭐ {r.rating}</span>}
                      </div>
                    </div>
                    <div className={s.itemRight}>
                      {r.price > 0 && <span className={s.itemPrice}>{fmt(r.price)}원</span>}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

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
                    <div key={i} className={s.item} onClick={() => setSelectedGas({ ...g, idx: i })}>
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
                    <div key={i} className={s.item} onClick={() => setSelectedRest({ ...r, idx: i })}>
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

      {/* Gas Station Detail Modal */}
      <Modal isOpen={!!selectedGas} onClose={() => setSelectedGas(null)} title="⛽ 주유소 상세 정보" size="md">
        {selectedGas && <GasDetailContent station={selectedGas} avgGas={avgGas} />}
      </Modal>

      {/* Restaurant Detail Modal */}
      <Modal isOpen={!!selectedRest} onClose={() => setSelectedRest(null)} title="🍽️ 식당 상세 정보" size="md">
        {selectedRest && <RestDetailContent restaurant={selectedRest} />}
      </Modal>
    </div>
  );
}

function GasDetailContent({ station, avgGas }) {
  const isSelf = station.name.includes('셀프');
  const dist = (0.5 + station.idx * 0.3).toFixed(1);

  const fuelRows = [
    { label: '휘발유', key: 'gasoline', avg: avgGas },
    { label: '경유', key: 'diesel', avg: Math.round(avgGas * 0.9) },
    { label: 'LPG', key: 'lpg', avg: Math.round(avgGas * 0.62) },
  ];

  return (
    <div className={s.modalDetail}>
      <div className={s.detailHeader}>
        <h3 className={s.detailName}>{station.name}</h3>
        <span className={s.detailBrand}>{station.brand}</span>
        {isSelf && <span className={s.selfTag}>셀프</span>}
      </div>
      <p className={s.detailAddr}>📍 {station.addr}</p>
      <p className={s.detailDist}>📏 현재 위치에서 ~{dist}km</p>

      <div className={s.detailSection}>
        <h4>⛽ 유종별 가격</h4>
        <div className={s.fuelTable}>
          {fuelRows.map(f => {
            const price = station[f.key];
            if (!price) return (
              <div key={f.key} className={s.fuelRow}>
                <span className={s.fuelLabel}>{f.label}</span>
                <span className={s.fuelNA}>취급 안 함</span>
              </div>
            );
            const diff = price - f.avg;
            return (
              <div key={f.key} className={s.fuelRow}>
                <span className={s.fuelLabel}>{f.label}</span>
                <span className={s.fuelPrice}>{fmt(price)}원/L</span>
                <span className={s.fuelDiff} style={{ color: diff <= 0 ? 'var(--green)' : 'var(--red)' }}>
                  지역 평균 대비 {diff <= 0 ? fmt(diff) : `+${fmt(diff)}`}원
                </span>
              </div>
            );
          })}
        </div>
      </div>

      <div className={s.detailSection}>
        <h4>ℹ️ 운영 정보</h4>
        <div className={s.infoGrid}>
          <div className={s.infoItem}>
            <span className={s.infoLabel}>셀프 여부</span>
            <span className={s.infoValue}>{isSelf ? '✅ 셀프 주유' : '❌ 일반 주유'}</span>
          </div>
          <div className={s.infoItem}>
            <span className={s.infoLabel}>운영 시간</span>
            <span className={s.infoValue}>{isSelf ? '24시간' : '06:00 ~ 23:00'}</span>
          </div>
          <div className={s.infoItem}>
            <span className={s.infoLabel}>브랜드</span>
            <span className={s.infoValue}>{station.brand}</span>
          </div>
        </div>
      </div>

      <button className={s.directionBtn} onClick={() => alert('길찾기 기능은 지도 API 연동 후 제공됩니다.')}>
        🧭 길찾기
      </button>
    </div>
  );
}

function RestDetailContent({ restaurant }) {
  const avg = LOCAL_AVGS[restaurant.menu];
  const diff = avg ? restaurant.price - avg : null;
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

      <button className={s.directionBtn} onClick={() => alert('길찾기 기능은 지도 API 연동 후 제공됩니다.')}>
        🧭 길찾기
      </button>
    </div>
  );
}
