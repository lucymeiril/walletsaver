import { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import { MapPin, Search, RefreshCw, X, ExternalLink, ChevronRight, ArrowLeft, Filter, ArrowUpDown } from 'lucide-react';
import { GAS_STATIONS, RESTAURANTS, LOCAL_AVGS, RECIPES, fmt, calcRecipeCost } from '../../data/mockData';
import Modal from '../../components/common/Modal';
import useStore from '../../stores/appStore';
import s from './LocalPage.module.css';

/* ── Category config ── */
const CATEGORY_ICONS = {
  '주유소': '⛽', '음식': '🍽️', '카페': '☕', '병원': '🏥',
  '미용': '💇', '편의시설': '🏪', '숙박': '🏨', '문화': '🎭',
  '교육': '📚', '쇼핑': '🛍️', '스포츠': '🏋️', '금융': '🏦',
};
const EXPLORE_CATEGORIES = '주유소,음식,카페,병원,미용,편의시설';
const CATEGORY_SEARCH_MAP = {
  '주유소': '주유소', '음식': '맛집', '카페': '카페', '병원': '병원',
  '미용': '미용실', '편의시설': '편의점',
};
const RADIUS_OPTIONS = [
  { label: '500m', value: 500 }, { label: '1km', value: 1000 },
  { label: '2km', value: 2000 }, { label: '3km', value: 3000 },
  { label: '5km', value: 5000 },
];

/** Extract representative price from menu_info (string or array) */
function getRepresentativePrice(menuInfo) {
  if (!menuInfo) return null;
  let prices = [];
  if (Array.isArray(menuInfo)) {
    prices = menuInfo
      .map(m => {
        if (typeof m.price === 'number') return m.price;
        const str = String(m.price || '').replace(/[,원\s]/g, '');
        return parseInt(str, 10);
      })
      .filter(p => !isNaN(p) && p > 0);
  } else if (typeof menuInfo === 'string' && menuInfo.trim()) {
    const matches = menuInfo.match(/[\d,]+/g);
    if (matches) {
      prices = matches.map(m => parseInt(m.replace(/,/g, ''), 10)).filter(p => !isNaN(p) && p >= 1000);
    }
  }
  if (prices.length === 0) return null;
  const avg = Math.round(prices.reduce((a, b) => a + b, 0) / prices.length);
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  return { avg, min, max, count: prices.length };
}

/** Parse menu_info into structured [{name, price}] array */
function parseMenuItems(menuInfo) {
  if (!menuInfo) return [];
  if (Array.isArray(menuInfo)) {
    return menuInfo
      .map(m => ({
        name: m.name || m.menu || '메뉴',
        price: typeof m.price === 'number' ? m.price
          : parseInt(String(m.price || '').replace(/[,원\s]/g, ''), 10) || 0,
      }))
      .filter(m => m.price > 0);
  }
  if (typeof menuInfo === 'string' && menuInfo.trim()) {
    return menuInfo.split(/\n/).map(line => {
      const match = line.trim().match(/^(.+?)\s+([\d,]+)\s*원?$/);
      if (match) return { name: match[1].trim(), price: parseInt(match[2].replace(/,/g, ''), 10) };
      return null;
    }).filter(Boolean);
  }
  return [];
}

/** Build subcategory map from items' classifications */
function buildSubcategories(items) {
  const map = {};
  items.forEach(item => {
    if (item.classifications) {
      item.classifications.forEach(cls => {
        (cls.subcategories || []).forEach(sub => {
          if (!map[sub]) map[sub] = [];
          map[sub].push(item);
        });
      });
    }
    if (item.category) {
      const cat = item.category;
      if (!map[cat]) map[cat] = [];
      if (!map[cat].includes(item)) map[cat].push(item);
    }
  });
  return map;
}

/** Sort items by given criteria */
function sortItems(items, sortBy, sortDir) {
  const sorted = [...items];
  sorted.sort((a, b) => {
    let va, vb;
    switch (sortBy) {
      case 'gasoline':
        va = a.petrol_info?.gasoline ?? Infinity;
        vb = b.petrol_info?.gasoline ?? Infinity;
        break;
      case 'diesel':
        va = a.petrol_info?.diesel ?? Infinity;
        vb = b.petrol_info?.diesel ?? Infinity;
        break;
      case 'price': {
        const pa = getRepresentativePrice(a.menu_info);
        const pb = getRepresentativePrice(b.menu_info);
        va = pa?.avg ?? (a.petrol_info?.gasoline ?? Infinity);
        vb = pb?.avg ?? (b.petrol_info?.gasoline ?? Infinity);
        break;
      }
      case 'rating':
        va = -(a.rating || 0);
        vb = -(b.rating || 0);
        break;
      case 'distance': {
        const da = typeof a.distance === 'string'
          ? parseFloat(a.distance.replace(/[^\d.]/g, '')) || Infinity
          : (a.distance ?? Infinity);
        const db = typeof b.distance === 'string'
          ? parseFloat(b.distance.replace(/[^\d.]/g, '')) || Infinity
          : (b.distance ?? Infinity);
        va = da; vb = db;
        break;
      }
      default:
        va = 0; vb = 0;
    }
    return sortDir === 'asc' ? va - vb : vb - va;
  });
  return sorted;
}

/** Detect if items are gas-station-heavy */
function isGasCategory(items) {
  if (!items || items.length === 0) return false;
  return items.filter(i => i.petrol_info).length > items.length * 0.3;
}

export default function LocalPage() {
  // Phase: idle | locating | exploring | categories | subcategory | items | search
  const [phase, setPhase] = useState('idle');
  const [locationInput, setLocationInput] = useState('');
  const [locationName, setLocationName] = useState('');
  const [lat, setLat] = useState(37.4979);
  const [lng, setLng] = useState(127.0276);
  const [radius, setRadius] = useState(2000);
  const [customRadius, setCustomRadius] = useState('');
  const [loading, setLoading] = useState(false);

  // Area-explore data
  const [exploreData, setExploreData] = useState(null);
  const [selectedCategoryName, setSelectedCategoryName] = useState('');
  const [selectedCategoryItems, setSelectedCategoryItems] = useState([]);
  const [subcategoryMap, setSubcategoryMap] = useState({});
  const [selectedSubcategory, setSelectedSubcategory] = useState('');

  // Item list & sorting
  const [displayItems, setDisplayItems] = useState([]);
  const [sortBy, setSortBy] = useState('price');
  const [sortDir, setSortDir] = useState('asc');

  // Direct search
  const [searchQuery, setSearchQuery] = useState('');
  const [searchLabel, setSearchLabel] = useState('');

  // iframe
  const [iframeUrl, setIframeUrl] = useState('');
  const [mapFocusUrl, setMapFocusUrl] = useState(null);

  // Modals
  const [selectedGas, setSelectedGas] = useState(null);
  const [selectedRest, setSelectedRest] = useState(null);
  const [selectedNaverPlace, setSelectedNaverPlace] = useState(null);

  // Cook vs eat
  const cookExample = RECIPES.find(r => r.name === '짜장면');
  const cookCost = cookExample ? calcRecipeCost(cookExample) : null;

  const { addToast } = useStore();
  const searchInputRef = useRef(null);

  const currentMapUrl = mapFocusUrl || iframeUrl || `https://map.naver.com/p?c=${lng},${lat},15,0,0,0,dh`;

  // Sorted items for display
  const sortedItems = useMemo(() => sortItems(displayItems, sortBy, sortDir), [displayItems, sortBy, sortDir]);
  const isGas = useMemo(() => isGasCategory(displayItems), [displayItems]);

  // Avg prices for gas modals
  const avgGasoline = useMemo(() => {
    const gs = displayItems.filter(i => i.petrol_info?.gasoline);
    return gs.length ? Math.round(gs.reduce((s, i) => s + i.petrol_info.gasoline, 0) / gs.length) : 0;
  }, [displayItems]);
  const avgDiesel = useMemo(() => {
    const gs = displayItems.filter(i => i.petrol_info?.diesel);
    return gs.length ? Math.round(gs.reduce((s, i) => s + i.petrol_info.diesel, 0) / gs.length) : 0;
  }, [displayItems]);

  /* ── API calls ── */
  const geocodeLocation = useCallback(async (query) => {
    const res = await fetch(`/api/local/geocode?query=${encodeURIComponent(query)}`);
    const data = await res.json();
    if (data.success && data.data) return data.data;
    throw new Error(data.message || '위치를 찾을 수 없습니다');
  }, []);

  const areaExplore = useCallback(async (locName) => {
    const res = await fetch(
      `/api/local/area-explore?location_name=${encodeURIComponent(locName)}&categories=${encodeURIComponent(EXPLORE_CATEGORIES)}&max_items=15`
    );
    const data = await res.json();
    if (data.success && data.data) return data.data;
    throw new Error(data.message || '탐색 실패');
  }, []);

  const naverSearch = useCallback(async (query) => {
    const res = await fetch(
      `/api/local/naver-search?query=${encodeURIComponent(query)}&lat=${lat}&lng=${lng}&max_items=20`
    );
    const data = await res.json();
    if (data.success && data.data?.items) return data.data.items;
    return [];
  }, [lat, lng]);

  /* ── Handlers ── */
  const handleLocationSearch = useCallback(async (locQuery) => {
    if (!locQuery.trim()) return;
    setPhase('locating');
    setLoading(true);
    setMapFocusUrl(null);
    try {
      const geo = await geocodeLocation(locQuery);
      setLat(geo.lat);
      setLng(geo.lng);
      setLocationName(geo.name || locQuery);
      setIframeUrl(`https://map.naver.com/p/search/${encodeURIComponent(locQuery)}`);
      addToast(`📍 ${geo.name || locQuery} 위치 설정 완료`, 'success');

      // Auto-trigger area explore
      setPhase('exploring');
      try {
        const explore = await areaExplore(geo.name || locQuery);
        setExploreData(explore);
        setPhase('categories');
      } catch {
        addToast('주변 탐색에 실패했습니다. 직접 검색해 주세요.', 'warning');
        setPhase('categories');
        setExploreData({ categories: [] });
      }
    } catch (err) {
      addToast(err.message || '위치 검색 실패', 'error');
      setPhase('idle');
    } finally {
      setLoading(false);
    }
  }, [geocodeLocation, areaExplore, addToast]);

  const handleLocationSubmit = (e) => {
    e.preventDefault();
    handleLocationSearch(locationInput);
  };

  const handleCurrentLocation = () => {
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          setLat(pos.coords.latitude);
          setLng(pos.coords.longitude);
          setLocationName('현재 위치');
          setLocationInput('현재 위치');
          setIframeUrl(`https://map.naver.com/p?c=${pos.coords.longitude},${pos.coords.latitude},15,0,0,0,dh`);
          addToast('현재 위치를 가져왔습니다', 'success');
          // Auto explore
          (async () => {
            setPhase('exploring');
            setLoading(true);
            try {
              const explore = await areaExplore('현재 위치');
              setExploreData(explore);
              setPhase('categories');
            } catch {
              setPhase('categories');
              setExploreData({ categories: [] });
            } finally {
              setLoading(false);
            }
          })();
        },
        () => {
          addToast('위치 권한이 거부되었습니다', 'warning');
        }
      );
    }
  };

  const handleCategoryClick = (cat) => {
    setSelectedCategoryName(cat.name);
    const items = cat.items || [];
    setSelectedCategoryItems(items);
    const subMap = buildSubcategories(items);
    setSubcategoryMap(subMap);
    setSelectedSubcategory('');
    // Default sort for gas stations
    if (isGasCategory(items)) {
      setSortBy('gasoline');
    } else {
      setSortBy('price');
    }
    setSortDir('asc');

    const subKeys = Object.keys(subMap);
    if (subKeys.length > 1) {
      setPhase('subcategory');
      setDisplayItems([]);
    } else {
      setDisplayItems(items);
      setPhase('items');
    }
    const keyword = CATEGORY_SEARCH_MAP[cat.name] || cat.name;
    setIframeUrl(`https://map.naver.com/p/search/${encodeURIComponent(locationName + ' ' + keyword)}`);
    setMapFocusUrl(null);
  };

  const handleSubcategoryClick = (subName) => {
    setSelectedSubcategory(subName);
    const items = subName === '전체' ? selectedCategoryItems : (subcategoryMap[subName] || []);
    setDisplayItems(items);
    setPhase('items');
    setIframeUrl(`https://map.naver.com/p/search/${encodeURIComponent(locationName + ' ' + subName)}`);
    setMapFocusUrl(null);
  };

  const handleDirectSearch = useCallback(async (e) => {
    e.preventDefault();
    if (!searchQuery.trim()) return;
    setLoading(true);
    setPhase('search');
    setSearchLabel(searchQuery);
    setMapFocusUrl(null);
    const fullQuery = locationName ? `${locationName} ${searchQuery}` : searchQuery;
    setIframeUrl(`https://map.naver.com/p/search/${encodeURIComponent(fullQuery)}`);
    try {
      const items = await naverSearch(fullQuery);
      setDisplayItems(items);
      if (items.length > 0) {
        addToast(`'${searchQuery}' 검색: ${items.length}건 발견`, 'success');
      } else {
        addToast('검색 결과 없음', 'warning');
      }
      if (isGasCategory(items)) setSortBy('gasoline');
      else setSortBy('price');
      setSortDir('asc');
    } catch {
      setDisplayItems([]);
      addToast('검색에 실패했습니다', 'error');
    } finally {
      setLoading(false);
    }
  }, [searchQuery, locationName, naverSearch, addToast]);

  const handleBreadcrumbNav = (target) => {
    setMapFocusUrl(null);
    if (target === 'location') {
      setPhase('categories');
      setSelectedCategoryName('');
      setSelectedSubcategory('');
      setDisplayItems([]);
      setIframeUrl(`https://map.naver.com/p/search/${encodeURIComponent(locationName)}`);
    } else if (target === 'category') {
      const cat = exploreData?.categories?.find(c => c.name === selectedCategoryName);
      if (cat) {
        const items = cat.items || [];
        setSelectedCategoryItems(items);
        const subMap = buildSubcategories(items);
        setSubcategoryMap(subMap);
        setSelectedSubcategory('');
        if (Object.keys(subMap).length > 1) {
          setPhase('subcategory');
          setDisplayItems([]);
        } else {
          setDisplayItems(items);
          setPhase('items');
        }
        const keyword = CATEGORY_SEARCH_MAP[selectedCategoryName] || selectedCategoryName;
        setIframeUrl(`https://map.naver.com/p/search/${encodeURIComponent(locationName + ' ' + keyword)}`);
      }
    }
  };

  const focusMapOnPlace = useCallback((name, placeUrl) => {
    if (placeUrl) {
      setMapFocusUrl(placeUrl);
    } else if (name) {
      setMapFocusUrl(`https://map.naver.com/p/search/${encodeURIComponent(name)}`);
    }
  }, []);

  const handleItemClick = (item) => {
    const petrol = item.petrol_info;
    if (petrol) {
      setSelectedGas({
        name: item.name, addr: item.address, brand: petrol.brand,
        gasoline: petrol.gasoline, diesel: petrol.diesel, lpg: petrol.lpg,
        is_self: petrol.is_self, is_24h: petrol.is_24h, has_car_wash: petrol.has_car_wash,
        premium_gasoline: petrol.premium_gasoline, naverUrl: item.url,
        image_url: item.image_url, tel: item.tel, distance: item.distance,
      });
    } else {
      setSelectedNaverPlace(item);
    }
  };

  const handleMapReset = () => {
    setMapFocusUrl(null);
    if (locationName) {
      setIframeUrl(`https://map.naver.com/p/search/${encodeURIComponent(locationName)}`);
    }
  };

  /* ── Sort options based on current items ── */
  const sortOptions = useMemo(() => {
    if (isGas) {
      return [['gasoline', '휘발유'], ['diesel', '경유'], ['distance', '거리']];
    }
    return [['price', '가격'], ['distance', '거리'], ['rating', '평점']];
  }, [isGas]);

  /* ── Breadcrumb ── */
  const breadcrumb = useMemo(() => {
    const crumbs = [];
    if (!locationName) return crumbs;
    crumbs.push({ label: locationName, action: () => handleBreadcrumbNav('location') });
    if (phase === 'search') {
      crumbs.push({ label: `"${searchLabel}"`, action: null });
    } else if (selectedCategoryName && (phase === 'subcategory' || phase === 'items')) {
      crumbs.push({ label: selectedCategoryName, action: () => handleBreadcrumbNav('category') });
      if (selectedSubcategory && phase === 'items') {
        crumbs.push({ label: selectedSubcategory, action: null });
      }
    }
    return crumbs;
  }, [locationName, phase, selectedCategoryName, selectedSubcategory, searchLabel]);

  /* ── Render ── */
  return (
    <div>
      <div className={s.hdr}>
        <h2>우리 동네 물가 지도</h2>
        <p>위치를 입력하고, 주변 카테고리별 가격을 탐색하세요</p>
      </div>

      <div className={s.layout}>
        {/* 네이버 지도 iframe */}
        <div className={s.map}>
          {currentMapUrl ? (
            <iframe
              src={currentMapUrl}
              className={s.naverIframe}
              title="네이버 지도"
              allow="geolocation"
              loading="lazy"
            />
          ) : (
            <div className={s.mapPlaceholder}>
              <MapPin size={48} />
              <p>위치를 입력하면 지도가 표시됩니다</p>
            </div>
          )}
          <div className={s.mapOverlay}>
            <span className={s.mapTag}>🗺️ 네이버 지도</span>
          </div>
          {mapFocusUrl && (
            <button className={s.mapResetBtn} onClick={handleMapReset}>
              ↩️ 기본 지도로 돌아가기
            </button>
          )}
        </div>

        {/* Sidebar */}
        <div className={s.sidebar}>
          {/* Step 1: Location + Radius */}
          <form onSubmit={handleLocationSubmit} className={s.locationRow}>
            <input
              ref={searchInputRef}
              className={s.locationInput}
              value={locationInput}
              onChange={e => setLocationInput(e.target.value)}
              placeholder="위치를 입력하세요 (예: 정자역, 강남역)"
            />
            <button type="button" className={s.locationBtn} onClick={handleCurrentLocation}>📍 현위치</button>
            <button type="submit" className={s.searchBtn} disabled={loading || !locationInput.trim()}>
              {loading && phase === 'locating' ? <RefreshCw size={16} className={s.spin} /> : <Search size={16} />}
            </button>
          </form>

          {/* Radius selector */}
          <div className={s.radiusRow}>
            <span className={s.radiusLabel}>반경</span>
            <div className={s.radiusOptions}>
              {RADIUS_OPTIONS.map(opt => (
                <button
                  key={opt.value}
                  className={`${s.radiusBtn} ${radius === opt.value && !customRadius ? s.radiusActive : ''}`}
                  onClick={() => { setRadius(opt.value); setCustomRadius(''); }}
                >
                  {opt.label}
                </button>
              ))}
              <input
                className={s.radiusInput}
                value={customRadius}
                onChange={e => {
                  setCustomRadius(e.target.value);
                  const v = parseInt(e.target.value, 10);
                  if (v > 0) setRadius(v);
                }}
                placeholder="직접 입력(m)"
              />
            </div>
          </div>

          {/* Direct search */}
          {locationName && (
            <form onSubmit={handleDirectSearch} className={s.directSearchRow}>
              <input
                className={s.directSearchInput}
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                placeholder={`${locationName} 주변 검색 (예: 삼겹살, 카페)`}
              />
              <button type="submit" className={s.directSearchBtn} disabled={loading}>
                {loading && phase === 'search' ? <RefreshCw size={14} className={s.spin} /> : <Search size={14} />}
              </button>
            </form>
          )}

          {/* Breadcrumb */}
          {breadcrumb.length > 0 && (
            <div className={s.breadcrumb}>
              {breadcrumb.map((c, i) => (
                <span key={i} className={s.breadcrumbItem}>
                  {i > 0 && <ChevronRight size={12} className={s.breadcrumbSep} />}
                  {c.action ? (
                    <button className={s.breadcrumbLink} onClick={c.action}>{c.label}</button>
                  ) : (
                    <span className={s.breadcrumbCurrent}>{c.label}</span>
                  )}
                </span>
              ))}
            </div>
          )}

          {/* Loading */}
          {loading && (phase === 'exploring' || phase === 'locating') && (
            <div className={s.loadingBox}>
              <RefreshCw size={20} className={s.spin} />
              <span>{phase === 'locating' ? '위치 검색 중...' : '주변 탐색 중...'}</span>
            </div>
          )}

          {/* IDLE state */}
          {phase === 'idle' && !loading && (
            <div className={s.idleBox}>
              <MapPin size={36} />
              <p>위치를 입력하고 검색하면<br/>주변 가게 정보를 탐색할 수 있어요</p>
            </div>
          )}

          {/* Step 2: Category grid */}
          {phase === 'categories' && exploreData && (
            <div className={s.categoryGrid}>
              {exploreData.categories && exploreData.categories.length > 0 ? (
                exploreData.categories.map(cat => (
                  <button
                    key={cat.name}
                    className={s.categoryCard}
                    onClick={() => handleCategoryClick(cat)}
                  >
                    <span className={s.categoryIcon}>{CATEGORY_ICONS[cat.name] || '📌'}</span>
                    <span className={s.categoryName}>{cat.name}</span>
                    <span className={s.categoryCount}>({cat.count || cat.items?.length || 0})</span>
                  </button>
                ))
              ) : (
                <div className={s.emptyMsg}>
                  카테고리 결과가 없습니다. 직접 검색해 보세요.
                </div>
              )}
            </div>
          )}

          {/* Step 3: Subcategory buttons */}
          {phase === 'subcategory' && (
            <div className={s.subcategorySection}>
              <button className={s.allItemsBtn} onClick={() => handleSubcategoryClick('전체')}>
                📋 전체 보기 ({selectedCategoryItems.length})
              </button>
              <div className={s.subcategoryGrid}>
                {Object.entries(subcategoryMap).map(([name, items]) => (
                  <button
                    key={name}
                    className={s.subcategoryBtn}
                    onClick={() => handleSubcategoryClick(name)}
                  >
                    {name} <span className={s.subcategoryCount}>({items.length})</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Step 4 / Direct Search: Item list */}
          {(phase === 'items' || phase === 'search') && (
            <>
              {/* Sort controls */}
              <div className={s.sortControls}>
                <div className={s.sortByGroup}>
                  {sortOptions.map(([k, l]) => (
                    <button
                      key={k}
                      className={`${s.sortByBtn} ${sortBy === k ? s.sortByActive : ''}`}
                      onClick={() => setSortBy(k)}
                    >
                      {l}순
                    </button>
                  ))}
                </div>
                <button
                  className={s.sortDirBtn}
                  onClick={() => setSortDir(d => d === 'asc' ? 'desc' : 'asc')}
                >
                  {sortDir === 'asc' ? '↑ 낮은순' : '↓ 높은순'}
                </button>
              </div>

              {/* Cook vs eat (shown when viewing restaurant category) */}
              {selectedCategoryName === '음식' && cookCost && phase === 'items' && (
                <div className={s.cookBanner}>
                  <div className={s.cookTitle}>🍳 외식 vs 직접 해먹기</div>
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

              {/* Results count */}
              <div className={s.resultCount}>
                {sortedItems.length}건의 결과
              </div>

              {/* Item list */}
              <div className={s.list}>
                {sortedItems.length === 0 && !loading && (
                  <div className={s.emptyMsg}>검색 결과가 없습니다</div>
                )}
                {sortedItems.map((item, i) => {
                  const priceInfo = getRepresentativePrice(item.menu_info);
                  const petrol = item.petrol_info;
                  return (
                    <div key={i} className={s.item} onClick={() => handleItemClick(item)}>
                      <span className={`${s.rank} ${i === 0 ? s.rank1 : i === 1 ? s.rank2 : i === 2 ? s.rank3 : ''}`}>
                        {i + 1}
                      </span>
                      <div className={s.itemBody}>
                        <div className={s.itemName}>
                          {item.name}
                          {petrol?.brand && <span className={s.itemBrand}>{petrol.brand}</span>}
                          {item.category && !petrol && <span className={s.itemBrand}>{item.category}</span>}
                        </div>
                        <div className={s.itemAddr}>
                          {petrol?.is_self && <span className={s.selfTag}>셀프</span>}
                          {petrol?.is_24h && <span className={s.selfTag}>24h</span>}
                          {item.rating > 0 && <span className={s.rating}>⭐ {item.rating}</span>}
                        </div>
                        {item.address && <div className={s.itemAddr}>{item.address}</div>}
                      </div>
                      <div className={s.itemRight}>
                        {petrol ? (
                          <div className={s.petrolPrices}>
                            {petrol.gasoline && (
                              <div className={s.petrolLine}>
                                <span className={s.petrolLabel}>휘발유</span>
                                <span className={s.petrolVal}>{fmt(petrol.gasoline)}</span>
                              </div>
                            )}
                            {petrol.diesel && (
                              <div className={s.petrolLine}>
                                <span className={s.petrolLabel}>경유</span>
                                <span className={s.petrolVal}>{fmt(petrol.diesel)}</span>
                              </div>
                            )}
                            {petrol.lpg && (
                              <div className={s.petrolLineSub}>
                                <span className={s.petrolLabel}>LPG</span>
                                <span>{fmt(petrol.lpg)}</span>
                              </div>
                            )}
                          </div>
                        ) : priceInfo ? (
                          <>
                            <span className={s.itemPrice}>평균 {fmt(priceInfo.avg)}원</span>
                            {priceInfo.count > 1 && (
                              <div className={s.priceRange}>
                                {fmt(priceInfo.min)}~{fmt(priceInfo.max)}원
                              </div>
                            )}
                          </>
                        ) : item.price > 0 ? (
                          <span className={s.itemPrice}>{fmt(item.price)}원</span>
                        ) : null}
                        {item.distance && (
                          <div className={s.itemDist}>
                            📏 {typeof item.distance === 'number'
                              ? (item.distance >= 1000 ? `${(item.distance / 1000).toFixed(1)}km` : `${item.distance}m`)
                              : item.distance}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </div>
      </div>

      {/* Gas Station Detail Modal */}
      <Modal isOpen={!!selectedGas} onClose={() => setSelectedGas(null)} title="⛽ 주유소 상세 정보" size="md">
        {selectedGas && (
          <GasDetailContent
            station={selectedGas}
            avgGas={avgGasoline || 0}
            avgGasoline={avgGasoline}
            avgDiesel={avgDiesel}
            onFocusMap={(name) => { focusMapOnPlace(name); setSelectedGas(null); }}
          />
        )}
      </Modal>

      {/* Restaurant Detail Modal */}
      <Modal isOpen={!!selectedRest} onClose={() => setSelectedRest(null)} title="🍽️ 식당 상세 정보" size="md">
        {selectedRest && (
          <RestDetailContent
            restaurant={selectedRest}
            onFocusMap={(name) => { focusMapOnPlace(name); setSelectedRest(null); }}
          />
        )}
      </Modal>

      {/* Naver Place Detail Modal */}
      <Modal isOpen={!!selectedNaverPlace} onClose={() => setSelectedNaverPlace(null)} title="📍 가게 상세 정보" size="md">
        {selectedNaverPlace && (
          <NaverPlaceDetailContent
            place={selectedNaverPlace}
            onFocusMap={(name, url) => { focusMapOnPlace(name, url); setSelectedNaverPlace(null); }}
          />
        )}
      </Modal>
    </div>
  );
}

function GasDetailContent({ station, avgGas, avgGasoline, avgDiesel, onFocusMap }) {
  const isSelf = station.is_self || station.name.includes('셀프');
  const dist = station.distance != null ? (parseFloat(station.distance) > 100 ? (parseFloat(station.distance) / 1000).toFixed(1) : parseFloat(station.distance).toFixed(1)) : (station.idx != null ? (0.5 + station.idx * 0.3).toFixed(1) : '?');

  const fuelRows = [
    { label: '휘발유', key: 'gasoline', avg: avgGasoline || avgGas },
    { label: '고급 휘발유', key: 'premium_gasoline', avg: Math.round((avgGasoline || avgGas) * 1.15) },
    { label: '경유', key: 'diesel', avg: avgDiesel || Math.round(avgGas * 0.9) },
    { label: 'LPG', key: 'lpg', avg: Math.round((avgGasoline || avgGas) * 0.62) },
  ];

  return (
    <div className={s.modalDetail}>
      <div className={s.detailHeader}>
        <h3 className={s.detailName}>{station.name}</h3>
        {station.brand && <span className={s.detailBrand}>{station.brand}</span>}
        {isSelf && <span className={s.selfTag}>셀프</span>}
        {station.is_24h && <span className={s.selfTag}>24h</span>}
      </div>
      <p className={s.detailAddr}>📍 {station.addr || station.address}</p>
      {station.tel && <p className={s.detailDist}>📞 {station.tel}</p>}
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
                {f.avg > 0 && (
                  <span className={s.fuelDiff} style={{ color: diff <= 0 ? 'var(--green)' : 'var(--red)' }}>
                    지역 평균 대비 {diff <= 0 ? fmt(diff) : `+${fmt(diff)}`}원
                  </span>
                )}
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
            <span className={s.infoValue}>{station.is_24h ? '24시간' : '06:00 ~ 23:00'}</span>
          </div>
          {station.has_car_wash && (
            <div className={s.infoItem}>
              <span className={s.infoLabel}>세차장</span>
              <span className={s.infoValue}>✅ 있음</span>
            </div>
          )}
          {station.brand && (
            <div className={s.infoItem}>
              <span className={s.infoLabel}>브랜드</span>
              <span className={s.infoValue}>{station.brand}</span>
            </div>
          )}
        </div>
      </div>

      <div className={s.btnGroup}>
        <button className={s.mapFocusBtn} onClick={() => onFocusMap(station.name)}>
          🗺️ 지도에서 위치 보기
        </button>
        {station.naverUrl && (
          <a href={station.naverUrl} target="_blank" rel="noopener noreferrer" className={s.externalLink}>
            📍 네이버 지도에서 보기 →
          </a>
        )}
      </div>
    </div>
  );
}

function RestDetailContent({ restaurant, onFocusMap }) {
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

      <div className={s.btnGroup}>
        <button className={s.mapFocusBtn} onClick={() => onFocusMap(restaurant.name)}>
          🗺️ 지도에서 위치 보기
        </button>
      </div>
    </div>
  );
}

function NaverPlaceDetailContent({ place, onFocusMap }) {
  const menuItems = parseMenuItems(place.menu_info);
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
      {place.tel && <p className={s.detailTel}>📞 {place.tel}</p>}
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
