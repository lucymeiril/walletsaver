import { useState, useMemo, useCallback, useRef, useEffect } from 'react';
import { MapPin, Search, RefreshCw, ChevronRight } from 'lucide-react';
import { fmt } from '../../utils/helpers';
import Modal from '../../components/common/Modal';
import EmptyState from '../../components/common/EmptyState';
import useStore from '../../stores/appStore';
import { getRepresentativePrice, buildSubcategories, sortItems, isGasCategory } from './utils';
import GasDetailContent from './components/GasDetailContent';
import RestDetailContent from './components/RestDetailContent';
import NaverPlaceDetailContent from './components/NaverPlaceDetailContent';
import SkeletonLoader from './components/SkeletonLoader';
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
  { label: '1km', value: 1000 },
  { label: '3km', value: 3000 },
  { label: '5km', value: 5000 },
  { label: '10km', value: 10000 },
];

export default function LocalPage() {
  const [phase, setPhase] = useState('idle');
  const [locationInput, setLocationInput] = useState('');
  const [locationName, setLocationName] = useState('');
  const [lat, setLat] = useState(37.4979);
  const [lng, setLng] = useState(127.0276);
  const [radius, setRadius] = useState(3000);
  const [loading, setLoading] = useState(false);
  const [gpsStatus, setGpsStatus] = useState('idle'); // idle | requesting | success | denied
  const [browserSearchEnabled, setBrowserSearchEnabled] = useState(false);

  const [exploreData, setExploreData] = useState(null);
  const [selectedCategoryName, setSelectedCategoryName] = useState('');
  const [selectedCategoryItems, setSelectedCategoryItems] = useState([]);
  const [subcategoryMap, setSubcategoryMap] = useState({});
  const [selectedSubcategory, setSelectedSubcategory] = useState('');

  const [displayItems, setDisplayItems] = useState([]);
  const [sortBy, setSortBy] = useState('price');
  const [sortDir, setSortDir] = useState('asc');

  const [searchQuery, setSearchQuery] = useState('');
  const [searchLabel, setSearchLabel] = useState('');

  const [iframeUrl, setIframeUrl] = useState('');
  const [mapFocusUrl, setMapFocusUrl] = useState(null);

  const [selectedGas, setSelectedGas] = useState(null);
  const [selectedRest, setSelectedRest] = useState(null);
  const [selectedNaverPlace, setSelectedNaverPlace] = useState(null);

  const { addToast, setSavedLocation } = useStore();
  const searchInputRef = useRef(null);
  const streamAbortRef = useRef(null);

  // Cleanup stream on unmount
  useEffect(() => {
    return () => {
      if (streamAbortRef.current) streamAbortRef.current.abort();
    };
  }, []);

  const currentMapUrl = useMemo(() => mapFocusUrl || iframeUrl || `https://map.naver.com/p?c=${lng},${lat},15,0,0,0,dh`, [mapFocusUrl, iframeUrl, lng, lat]);

  const sortedItems = useMemo(() => sortItems(displayItems, sortBy, sortDir), [displayItems, sortBy, sortDir]);
  const isGas = useMemo(() => isGasCategory(displayItems), [displayItems]);

  const avgGasoline = useMemo(() => {
    const gs = displayItems.filter(i => i.petrol_info?.gasoline);
    return gs.length ? Math.round(gs.reduce((s, i) => s + i.petrol_info.gasoline, 0) / gs.length) : 0;
  }, [displayItems]);
  const avgDiesel = useMemo(() => {
    const gs = displayItems.filter(i => i.petrol_info?.diesel);
    return gs.length ? Math.round(gs.reduce((s, i) => s + i.petrol_info.diesel, 0) / gs.length) : 0;
  }, [displayItems]);

  const [streamingCats, setStreamingCats] = useState(new Set());

  /* ── API calls ── */
  const geocodeLocation = useCallback(async (query) => {
    const res = await fetch(
      `/api/local/geocode?query=${encodeURIComponent(query)}&browser_search=${browserSearchEnabled}`
    );
    const data = await res.json();
    if (data.success && data.data) return data.data;
    throw new Error(data.message || '위치를 찾을 수 없습니다');
  }, [browserSearchEnabled]);

  const naverSearch = useCallback(async (query) => {
    const res = await fetch(
      `/api/local/naver-search?query=${encodeURIComponent(query)}&lat=${lat}&lng=${lng}&max_items=20&browser_search=${browserSearchEnabled}`
    );
    const data = await res.json();
    if (data.success && data.data?.items) return data.data.items;
    return [];
  }, [lat, lng, browserSearchEnabled]);

  /* ── Handlers ── */
  const runAreaExplore = useCallback(async (
    locName,
    latVal,
    lngVal,
    browserSearchOverride = browserSearchEnabled,
  ) => {
    if (streamAbortRef.current) streamAbortRef.current.abort();
    const controller = new AbortController();
    streamAbortRef.current = controller;

    setPhase('exploring');
    setExploreData({ categories: [] });
    setStreamingCats(new Set(EXPLORE_CATEGORIES.split(',')));

    const params = new URLSearchParams({ max_items: '30' });
    params.set('categories', EXPLORE_CATEGORIES);
    if (locName) params.set('location_name', locName);
    if (latVal != null) params.set('lat', String(latVal));
    if (lngVal != null) params.set('lng', String(lngVal));
    params.set('browser_search', String(browserSearchOverride));
    const url = `/api/local/area-explore-stream?${params}`;

    try {
      const response = await fetch(url, { signal: controller.signal });
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            const jsonStr = line.slice(6).trim();
            if (!jsonStr) continue;
            try {
              const data = JSON.parse(jsonStr);
              if (data.done) {
                setPhase('categories');
                setStreamingCats(new Set());
                return;
              }
              if (data.error && !data.name) continue;
              setExploreData(prev => ({
                ...prev,
                categories: [...(prev?.categories || []), data],
              }));
              setStreamingCats(prev => {
                const next = new Set(prev);
                next.delete(data.name);
                return next;
              });
            } catch { /* skip malformed */ }
          }
        }
      } finally {
        reader.releaseLock();
      }
      setPhase('categories');
      setStreamingCats(new Set());
    } catch (err) {
      if (err.name === 'AbortError') return;
      addToast('주변 탐색에 실패했습니다. 직접 검색해 주세요.', 'warning');
      setPhase('categories');
      setExploreData({ categories: [] });
      setStreamingCats(new Set());
    }
  }, [addToast, browserSearchEnabled]);

  const handleBrowserSearchToggle = useCallback(async (event) => {
    const enabled = event.target.checked;
    setBrowserSearchEnabled(enabled);

    if (locationName) {
      await runAreaExplore(locationName, lat, lng, enabled);
    }
  }, [locationName, lat, lng, runAreaExplore]);

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
      setSavedLocation({ lat: geo.lat, lng: geo.lng, locationName: geo.name || locQuery });
      setIframeUrl(`https://map.naver.com/p/search/${encodeURIComponent(locQuery)}`);
      addToast(`📍 ${geo.name || locQuery} 위치 설정 완료`, 'success');
      await runAreaExplore(geo.name || locQuery, geo.lat, geo.lng);
    } catch (err) {
      addToast(err.message || '위치 검색 실패', 'error');
      setPhase('idle');
    } finally {
      setLoading(false);
    }
  }, [geocodeLocation, runAreaExplore, addToast, setSavedLocation]);

  const handleLocationSubmit = (e) => {
    e.preventDefault();
    handleLocationSearch(locationInput);
  };

  const handleCurrentLocation = useCallback(() => {
    if (!navigator.geolocation) {
      addToast('이 브라우저에서는 GPS를 지원하지 않습니다. 위치를 직접 입력해 주세요.', 'warning');
      searchInputRef.current?.focus();
      return;
    }
    setGpsStatus('requesting');
    addToast('📡 GPS 위치를 가져오는 중...', 'info');

    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        const newLat = pos.coords.latitude;
        const newLng = pos.coords.longitude;
        setLat(newLat);
        setLng(newLng);
        setGpsStatus('success');
        setIframeUrl(`https://map.naver.com/p?c=${newLng},${newLat},15,0,0,0,dh`);
        addToast('✅ 현재 위치를 가져왔습니다', 'success');

        // 역 geocode로 위치명 가져오기
        setLoading(true);
        try {
          const geo = await geocodeLocation(`${newLat},${newLng}`);
          const locLabel = geo?.name || '현재 위치';
          setLocationName(locLabel);
          setLocationInput(locLabel);
          setSavedLocation({ lat: newLat, lng: newLng, locationName: locLabel });
          await runAreaExplore(locLabel, newLat, newLng);
        } catch {
          setLocationName('현재 위치');
          setLocationInput('현재 위치');
          setSavedLocation({ lat: newLat, lng: newLng, locationName: '현재 위치' });
          await runAreaExplore(null, newLat, newLng);
        } finally {
          setLoading(false);
        }
      },
      (err) => {
        setGpsStatus('denied');
        const msg = err.code === 1
          ? '위치 권한이 거부되었습니다. 위치를 직접 입력해 주세요.'
          : '위치를 가져올 수 없습니다. 위치를 직접 입력해 주세요.';
        addToast(msg, 'warning');
        searchInputRef.current?.focus();
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
    );
  }, [geocodeLocation, runAreaExplore, addToast, setSavedLocation]);

  const fetchSubcategoryResults = useCallback(async (location, subcategory, latVal, lngVal) => {
    const params = new URLSearchParams({
      location, subcategory,
      ...(latVal && { lat: latVal }),
      ...(lngVal && { lng: lngVal }),
      max_items: 30,
      browser_search: String(browserSearchEnabled),
    });
    const res = await fetch(`/api/local/subcategory-search?${params}`);
    const data = await res.json();
    return data.data?.items || data.items || [];
  }, [browserSearchEnabled]);

  const handleCategoryClick = (cat) => {
    setSelectedCategoryName(cat.name);
    let items = [...(cat.items || [])];

    if (cat.name === '음식' && exploreData?.categories) {
      const cafeCategory = exploreData.categories.find(c => c.name === '카페');
      if (cafeCategory?.items) {
        const existingNames = new Set(items.map(i => i.name));
        cafeCategory.items.forEach(i => {
          if (!existingNames.has(i.name)) items.push(i);
        });
      }
    }

    setSelectedCategoryItems(items);
    const subMap = buildSubcategories(items);
    setSubcategoryMap(subMap);
    setSelectedSubcategory('');
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

  const handleSubcategoryClick = async (subName) => {
    setSelectedSubcategory(subName);

    if (subName === '전체') {
      setDisplayItems(selectedCategoryItems);
      setPhase('items');
      setMapFocusUrl(null);
      setIframeUrl(`https://map.naver.com/p/search/${encodeURIComponent(locationName + ' ' + (CATEGORY_SEARCH_MAP[selectedCategoryName] || selectedCategoryName))}`);
      return;
    }

    const filtered = subcategoryMap[subName] || [];
    setDisplayItems(filtered);
    setPhase('items');
    setIframeUrl(`https://map.naver.com/p/search/${encodeURIComponent(`${locationName} ${subName}`)}`);
    setMapFocusUrl(null);

    if (locationName && subName !== '전체') {
      setLoading(true);
      try {
        const moreItems = await fetchSubcategoryResults(locationName, subName, lat, lng);
        if (moreItems.length > 0) {
          const existingNames = new Set(filtered.map(i => i.name));
          const newItems = moreItems.filter(i => !existingNames.has(i.name));
          if (newItems.length > 0) {
            setDisplayItems(prev => [...prev, ...newItems]);
          }
        }
      } catch (e) {
        console.warn('서브카테고리 추가 검색 실패:', e);
      } finally {
        setLoading(false);
      }
    }
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
        let items = [...(cat.items || [])];
        if (selectedCategoryName === '음식' && exploreData?.categories) {
          const cafeCategory = exploreData.categories.find(c => c.name === '카페');
          if (cafeCategory?.items) {
            const existingNames = new Set(items.map(i => i.name));
            cafeCategory.items.forEach(i => {
              if (!existingNames.has(i.name)) items.push(i);
            });
          }
        }
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

  const handleItemClick = useCallback((item) => {
    const petrol = item.petrol_info;
    if (petrol) {
      setSelectedGas({
        name: item.name, addr: item.address, brand: petrol.brand,
        gasoline: petrol.gasoline, diesel: petrol.diesel, lpg: petrol.lpg,
        is_self: petrol.is_self, is_24h: petrol.is_24h, has_car_wash: petrol.has_car_wash,
        premium_gasoline: petrol.premium_gasoline, naverUrl: item.url,
        image_url: item.image_url, tel: item.tel, distance: item.distance,
        updated_at: petrol.updated_at || item.updated_at,
        source: petrol.source || item.source,
      });
    } else {
      setSelectedNaverPlace(item);
    }
  }, []);

  const handleMapReset = useCallback(() => {
    setMapFocusUrl(null);
    if (locationName) {
      setIframeUrl(`https://map.naver.com/p/search/${encodeURIComponent(locationName)}`);
    }
  }, [locationName]);

  /* ── Sort options ── */
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

  // 빈 카테고리 제외한 목록
  const visibleCategories = useMemo(() => {
    if (!exploreData?.categories) return [];
    return exploreData.categories.filter(cat => (cat.count || cat.items?.length || 0) > 0);
  }, [exploreData]);
  /* ── Render ── */
  return (
    <div>
      <div className={s.hdr}>
        <h2>우리 동네 물가 지도</h2>
        <p>위치를 입력하고, 주변 카테고리별 가격을 탐색하세요</p>
      </div>

      <div className={s.layout}>
        {/* 지도 임베딩 없이도 동작하는 지역 탐색 요약 */}
        <div className={s.map}>
          <div className={s.mapPlaceholder}>
            <MapPin size={48} />
            <strong>{mapFocusUrl ? '선택한 장소' : (locationName || '탐색 위치를 정해주세요')}</strong>
            <p>
              {locationName
                ? '주변 검색 결과는 이 화면에서 바로 확인할 수 있습니다.'
                : '위치를 입력하거나 브라우저 위치 권한을 사용해 시작하세요.'}
            </p>

            {locationName && (
              <div className={s.mapStatusGrid}>
                <div>
                  <span>탐색 반경</span>
                  <strong>{radius / 1000}km</strong>
                </div>
                <div>
                  <span>장소 검색</span>
                  <strong>{browserSearchEnabled ? '사용 중' : '사용 안 함'}</strong>
                </div>
                <div>
                  <span>카테고리</span>
                  <strong>{visibleCategories.length}개</strong>
                </div>
                <div>
                  <span>현재 결과</span>
                  <strong>{sortedItems.length}건</strong>
                </div>
              </div>
            )}

            {visibleCategories.length > 0 && (
              <div className={s.mapCategorySummary} aria-label="주변 카테고리 결과 요약">
                {visibleCategories.slice(0, 6).map(category => (
                  <button key={category.name} onClick={() => handleCategoryClick(category)}>
                    <span>{CATEGORY_ICONS[category.name] || '📌'}</span>
                    {category.name}
                    <small>{category.count || category.items?.length || 0}건</small>
                  </button>
                ))}
              </div>
            )}

            {locationName && currentMapUrl && (
              <a
                className={s.mapExternalLink}
                href={currentMapUrl}
                target="_blank"
                rel="noopener noreferrer"
              >
                선택한 위치를 네이버 지도에서 확인
              </a>
            )}

            {locationName && !browserSearchEnabled && (
              <small className={s.mapConsentHint}>
                장소 목록이 필요하면 오른쪽의 브라우저 검색을 직접 켜주세요.
              </small>
            )}
          </div>
          {mapFocusUrl && (
            <button className={s.mapResetBtn} onClick={handleMapReset}>
              ↩️ 위치 요약으로 돌아가기
            </button>
          )}
        </div>

        {/* Sidebar */}
        <div className={s.sidebar}>
          {/* Location + GPS */}
          <form onSubmit={handleLocationSubmit} className={s.locationRow}>
            <input
              ref={searchInputRef}
              className={s.locationInput}
              value={locationInput}
              onChange={e => setLocationInput(e.target.value)}
              placeholder="위치를 입력하세요 (예: 정자역, 강남역)"
            />
            <button
              type="button"
              className={`${s.locationBtn} ${gpsStatus === 'requesting' ? s.spin : ''}`}
              onClick={handleCurrentLocation}
              disabled={gpsStatus === 'requesting'}
            >
              {gpsStatus === 'requesting' ? '📡' : '📍'} 현위치
            </button>
            <button type="submit" className={s.searchBtn} disabled={loading || !locationInput.trim()}>
              {loading && phase === 'locating' ? <RefreshCw size={16} className={s.spin} /> : <Search size={16} />}
            </button>
          </form>

          {/* GPS 실패 안내 */}
          {gpsStatus === 'denied' && (
            <div className={s.gpsHint}>
              📍 위치 권한이 거부되었습니다. 위치를 직접 입력해 주세요.
            </div>
          )}

          {/* Radius selector */}
          <div className={s.radiusRow}>
            <span className={s.radiusLabel}>반경</span>
            <div className={s.radiusOptions}>
              {RADIUS_OPTIONS.map(opt => (
                <button
                  key={opt.value}
                  className={`${s.radiusBtn} ${radius === opt.value ? s.radiusActive : ''}`}
                  onClick={() => setRadius(opt.value)}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          <label className={s.browserSearchOptIn}>
            <input
              type="checkbox"
              checked={browserSearchEnabled}
              onChange={handleBrowserSearchToggle}
            />
            <span>
              네이버 공개 페이지 브라우저 검색 사용
              <small>체크한 검색에만 실행되며 결과가 늦게 표시될 수 있습니다.</small>
            </span>
          </label>

          {/* Direct search */}
          {locationName && (
            <form onSubmit={handleDirectSearch} className={s.directSearchRow}>
              <input
                className={s.directSearchInput}
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                placeholder={`🔍 ${locationName} 주변 검색 (예: 삼겹살, 카페)`}
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
                <span key={c.label || `bc-${i}`} className={s.breadcrumbItem}>
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

          {/* 스켈레톤 로딩 */}
          {loading && phase === 'locating' && (
            <SkeletonLoader
              count={4}
              message="위치를 검색하고 있습니다..."
            />
          )}

          {/* IDLE state */}
          {phase === 'idle' && !loading && (
            <div className={s.idleBox}>
              <MapPin size={36} />
              <p>위치를 입력하고 검색하면<br/>주변 가게 정보를 탐색할 수 있어요</p>
              <button className={s.gpsStartBtn} onClick={handleCurrentLocation}>
                📍 현재 위치로 시작하기
              </button>
            </div>
          )}

          {/* Category grid — 스트리밍 중에도 카테고리 점진 표시 */}
          {(phase === 'categories' || phase === 'exploring') && exploreData && (
            <div className={s.categoryGrid}>
              {visibleCategories.length > 0 && visibleCategories.map(cat => (
                <button
                  key={cat.name}
                  className={s.categoryCard}
                  onClick={() => handleCategoryClick(cat)}
                >
                  <span className={s.categoryIcon}>{CATEGORY_ICONS[cat.name] || '📌'}</span>
                  <span className={s.categoryName}>{cat.name}</span>
                  <span className={s.categoryCount}>({cat.count || cat.items?.length || 0})</span>
                </button>
              ))}
              {/* 아직 로딩 중인 카테고리 스피너 */}
              {streamingCats.size > 0 && [...streamingCats].map(catName => (
                <div key={catName} className={`${s.categoryCard} ${s.categoryLoading}`}>
                  <span className={s.categoryIcon}>
                    <RefreshCw size={20} className={s.spin} />
                  </span>
                  <span className={s.categoryName}>{catName}</span>
                  <span className={s.categoryCount}>검색 중...</span>
                </div>
              ))}
              {visibleCategories.length === 0 && streamingCats.size === 0 && (
                <div className={s.emptyMsg}>
                  {browserSearchEnabled
                    ? '브라우저 검색 결과가 없습니다. 검색어를 바꿔 다시 시도해 주세요.'
                    : '네이버 장소 결과가 필요하면 위의 브라우저 검색 사용을 명시적으로 체크해 주세요.'}
                </div>
              )}
            </div>
          )}

          {/* Subcategory buttons */}
          {phase === 'subcategory' && (
            <div className={s.subcategorySection}>
              <button className={s.allItemsBtn} onClick={() => handleSubcategoryClick('전체')}>
                📋 전체 보기 ({selectedCategoryItems.length})
              </button>
              <div className={s.subcategoryGrid}>
                {Object.entries(subcategoryMap)
                  .filter(([name]) => name !== '전체')
                  .map(([name, items]) => (
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

          {/* Item list */}
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

              {/* Results count */}
              <div className={s.resultCount}>
                {sortedItems.length}건의 결과
              </div>

              {/* 검색 중 스켈레톤 (항목 없을 때) */}
              {loading && sortedItems.length === 0 && (
                <SkeletonLoader count={5} message="검색 결과를 불러오고 있습니다..." />
              )}

              {/* Item list */}
              <div className={s.list}>
                {sortedItems.length === 0 && !loading && (
                  <div className={s.emptyMsg}>검색 결과가 없습니다</div>
                )}
                {sortedItems.map((item, i) => {
                  const priceInfo = getRepresentativePrice(item.menu_info);
                  const petrol = item.petrol_info;
                  return (
                    <div key={item.id || item.place_id || item.name || `item-${i}`} className={s.item} onClick={() => handleItemClick(item)}>
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
                            {petrol.updated_at && (
                              <div className={s.petrolLineSub}>
                                <span>갱신</span>
                                <span>{String(petrol.updated_at).slice(0, 16)}</span>
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

              {/* 추가 검색 중 로딩 */}
              {loading && displayItems.length > 0 && (
                <div className={s.loadingMore}>추가 검색 중...</div>
              )}
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
