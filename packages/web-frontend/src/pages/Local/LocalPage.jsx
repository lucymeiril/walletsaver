import { useState, useMemo, useCallback, useRef, useEffect } from 'react';
import { MapPin, Search, RefreshCw, ChevronRight } from 'lucide-react';
import { fmt } from '../../utils/helpers';
import Modal from '../../components/common/Modal';
import EmptyState from '../../components/common/EmptyState';
import useStore from '../../stores/appStore';
import { getRepresentativePrice, buildSubcategories, sortItems, isGasCategory, fuelStationItem, itemsWithinRadius, distanceKm } from './utils';
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
const FUEL_TYPES = ['gasoline', 'diesel', 'premium', 'lpg'];
const PLACE_STATUS_TEXT = {
  disabled: '장소 검색이 꺼져 있습니다. 브라우저 검색 사용을 직접 켜주세요.',
  unavailable: '장소 검색 결과를 확인할 수 없습니다. 잠시 후 다시 시도해 주세요.',
  not_queried: '장소 검색 결과가 아직 확인되지 않았습니다.',
  querying: '장소 검색 결과를 확인하고 있습니다.',
};

function savedManualRegion(location) {
  if (!location || typeof location !== 'object' || Array.isArray(location)
    || 'lat' in location || 'lng' in location) return null;
  const sido = typeof location.sido === 'string' ? location.sido.trim() : '';
  const sigungu = typeof location.sigungu === 'string' ? location.sigungu.trim() : '';
  if (!sido && !sigungu) return null;
  return { sido, sigungu, fuelType: FUEL_TYPES.includes(location.fuelType) ? location.fuelType : null };
}

export default function LocalPage() {
  const { addToast, setSavedLocation, savedLocation } = useStore();
  const initialRegion = useRef(savedManualRegion(savedLocation)).current;
  const [phase, setPhase] = useState('idle');
  const [locationInput, setLocationInput] = useState('');
  const [locationName, setLocationName] = useState(initialRegion
    ? [initialRegion.sido, initialRegion.sigungu].filter(Boolean).join(' ') : '');
  const [lat, setLat] = useState(37.4979);
  const [lng, setLng] = useState(127.0276);
  const [radius, setRadius] = useState(3000);
  const [loading, setLoading] = useState(false);
  const [gpsStatus, setGpsStatus] = useState('idle'); // idle | requesting | success | denied
  const [browserSearchEnabled, setBrowserSearchEnabled] = useState(false);
  const [manualRegion, setManualRegion] = useState(initialRegion);
  const [regionSido, setRegionSido] = useState(initialRegion?.sido || '');
  const [regionSigungu, setRegionSigungu] = useState(initialRegion?.sigungu || '');
  const [fuelType, setFuelType] = useState(initialRegion?.fuelType || 'gasoline');
  const fuelTypeRef = useRef(fuelType);
  const radiusRef = useRef(radius);
  const browserSearchRef = useRef(browserSearchEnabled);

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
  const [directSearchResult, setDirectSearchResult] = useState(null);

  const [iframeUrl, setIframeUrl] = useState('');
  const [mapFocusUrl, setMapFocusUrl] = useState(null);

  const [selectedGas, setSelectedGas] = useState(null);
  const [selectedRest, setSelectedRest] = useState(null);
  const [selectedNaverPlace, setSelectedNaverPlace] = useState(null);

  const searchInputRef = useRef(null);
  const streamAbortRef = useRef(null);
  const locationRequestRef = useRef(0);

  // Cleanup stream on unmount
  useEffect(() => {
    return () => {
      locationRequestRef.current += 1;
      if (streamAbortRef.current) streamAbortRef.current.abort();
    };
  }, []);

  const currentMapUrl = useMemo(() => mapFocusUrl || iframeUrl || (manualRegion
    ? `https://map.naver.com/p/search/${encodeURIComponent(locationName)}`
    : `https://map.naver.com/p?c=${lng},${lat},15,0,0,0,dh`), [mapFocusUrl, iframeUrl, manualRegion, locationName, lng, lat]);

  const sortedItems = useMemo(() => sortItems(displayItems, sortBy, sortDir), [displayItems, sortBy, sortDir]);
  const fuelStatus = exploreData?.categories?.find(category => category.name === '주유소');
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
      `/api/local/geocode?query=${encodeURIComponent(query)}&browser_search=${browserSearchRef.current}`
    );
    const data = await res.json();
    if (res.ok && data.success && data.data
      && Number.isFinite(data.data.lat) && Number.isFinite(data.data.lng)
      && Math.abs(data.data.lat) <= 90 && Math.abs(data.data.lng) <= 180) return data.data;
    throw new Error(data.message || '위치를 찾을 수 없습니다');
  }, []);

  const naverSearch = useCallback(async (query, signal) => {
    if (manualRegion || !browserSearchEnabled) return { source: 'disabled', items: [] };
    const res = await fetch(
      `/api/local/naver-search?query=${encodeURIComponent(query)}&lat=${lat}&lng=${lng}&max_items=20&browser_search=${browserSearchEnabled}`,
      { signal },
    );
    const data = await res.json();
    if (res.ok && data.success && data.data?.source === 'naver' && Array.isArray(data.data.items)) {
      return { source: 'naver', items: itemsWithinRadius(data.data.items, lat, lng, radiusRef.current) };
    }
    return { source: 'unavailable', items: [] };
  }, [lat, lng, browserSearchEnabled, manualRegion]);

  /* ── Handlers ── */
  const runAreaExplore = useCallback(async (
    locName,
    latVal,
    lngVal,
    browserSearchOverride = browserSearchRef.current,
    radiusOverride = radiusRef.current,
  ) => {
    if (streamAbortRef.current) streamAbortRef.current.abort();
    const controller = new AbortController();
    streamAbortRef.current = controller;

    setPhase('exploring');
    setSelectedGas(null);
    setDisplayItems([]);
    setExploreData({ categories: [] });
    setStreamingCats(new Set(EXPLORE_CATEGORIES.split(',')));

    const params = new URLSearchParams({ max_items: '30' });
    params.set('categories', EXPLORE_CATEGORIES.split(',').filter(category => category !== '주유소').join(','));
    if (locName) params.set('location_name', locName);
    if (latVal != null) params.set('lat', String(latVal));
    if (lngVal != null) params.set('lng', String(lngVal));
    params.set('browser_search', String(browserSearchOverride));
    const url = `/api/local/area-explore-stream?${params}`;
    const active = () => streamAbortRef.current === controller && !controller.signal.aborted;
    const publishCategory = (data) => {
      if (!active()) return;
      const items = itemsWithinRadius(data.items, latVal, lngVal, radiusOverride);
      const sourceItems = Array.isArray(data.items) ? data.items : [];
      const unlocatedItems = sourceItems.filter(item => {
        const y = item.y ?? item.lat, x = item.x ?? item.lng;
        return y == null || x == null || y === '' || x === ''
          || !Number.isFinite(Number(y)) || !Number.isFinite(Number(x))
          || Math.abs(Number(y)) > 90 || Math.abs(Number(x)) > 180;
      }).map(item => ({ ...item, source_distance: item.source_distance ?? item.distance,
        distance: null, distance_m: null }));
      const category = { ...data, items, count: items.length,
        received_count: sourceItems.length, unlocated_items: unlocatedItems };
      setExploreData(prev => ({ ...prev, categories: [
        ...(prev?.categories || []).filter(existing => existing.name !== data.name), category,
      ] }));
      setStreamingCats(prev => { const next = new Set(prev); next.delete(data.name); return next; });
    };
    const fuelParams = new URLSearchParams({ lat: String(latVal), lng: String(lngVal),
      radius: String(radiusOverride), fuel_type: fuelTypeRef.current, limit: '1000' });
    const fuelRequest = (async () => {
      try {
        const response = await fetch(`/api/gas/nearby?${fuelParams}`, { signal: controller.signal });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || '오피넷 가격 정보를 불러올 수 없습니다');
        publishCategory({ name: '주유소', source: 'opinet', items: (payload.data || []).map(fuelStationItem), message: payload.message });
      } catch (error) {
        if (error.name !== 'AbortError') publishCategory({ name: '주유소', source: 'unavailable', items: [], error: error.message });
      }
    })();

    try {
      const response = await fetch(url, { signal: controller.signal });
      if (!response.ok) throw new Error('주변 탐색 응답 오류');
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      try {
        while (true) {
          const { done, value } = await reader.read();
          if (!active()) return;
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
                await fuelRequest;
                if (!active()) return;
                setPhase(current => current === 'exploring' ? 'categories' : current);
                setStreamingCats(new Set());
                return;
              }
              if (data.error && !data.name) continue;
              publishCategory(data);
            } catch { /* skip malformed */ }
          }
        }
      } finally {
        reader.releaseLock();
      }
      await fuelRequest;
      if (!active()) return;
      setPhase(current => current === 'exploring' ? 'categories' : current);
      setStreamingCats(new Set());
    } catch (err) {
      if (err.name === 'AbortError' || !active()) return;
      await fuelRequest;
      if (!active()) return;
      setExploreData(prev => ({ ...prev, source: 'unavailable' }));
      addToast('주변 탐색에 실패했습니다. 직접 검색해 주세요.', 'warning');
      setPhase(current => current === 'exploring' ? 'categories' : current);
      setStreamingCats(new Set());
    }
  }, [addToast]);

  const handleBrowserSearchToggle = useCallback(async (event) => {
    const enabled = event.target.checked;
    browserSearchRef.current = enabled;
    setBrowserSearchEnabled(enabled);

    if (locationName && !manualRegion) {
      await runAreaExplore(locationName, lat, lng, enabled);
    }
  }, [locationName, lat, lng, runAreaExplore, manualRegion]);

  const runRegionFuel = useCallback(async (sido, sigungu) => {
    const request = ++locationRequestRef.current;
    streamAbortRef.current?.abort();
    const controller = new AbortController();
    streamAbortRef.current = controller;
    const region = { sido: sido.trim(), sigungu: sigungu.trim() };
    const name = [region.sido, region.sigungu].filter(Boolean).join(' ');
    setManualRegion(region);
    setGpsStatus('idle');
    setLocationName(name);
    setMapFocusUrl(null);
    setIframeUrl(`https://map.naver.com/p/search/${encodeURIComponent(name)}`);
    setSavedLocation({ ...region, locationName: name, fuelType: fuelTypeRef.current });
    setSelectedGas(null);
    setDisplayItems([]);
    setExploreData({ categories: [] });
    setStreamingCats(new Set(['주유소']));
    setPhase('exploring');
    setLoading(true);
    const params = new URLSearchParams({ ...region, fuel_type: fuelTypeRef.current, limit: '1000' });
    try {
      const response = await fetch(`/api/gas/nearby?${params}`, { signal: controller.signal });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || '오피넷 가격 정보를 불러올 수 없습니다');
      if (request !== locationRequestRef.current || controller.signal.aborted) return;
      setExploreData({ categories: [{ name: '주유소', source: 'opinet',
        items: (payload.data || []).map(fuelStationItem), message: payload.message }] });
    } catch (error) {
      if (request !== locationRequestRef.current || controller.signal.aborted) return;
      setExploreData({ categories: [{ name: '주유소', source: 'unavailable', items: [], error: error.message }] });
    } finally {
      if (request === locationRequestRef.current) {
        setLoading(false); setStreamingCats(new Set()); setPhase('categories');
      }
    }
  }, [setSavedLocation]);

  useEffect(() => {
    // Restore only an explicit manual region and known fuel, never a stored GPS position.
    if (initialRegion?.fuelType) runRegionFuel(initialRegion.sido, initialRegion.sigungu);
  }, [initialRegion, runRegionFuel]);

  const handleLocationSearch = useCallback(async (locQuery) => {
    if (!locQuery.trim()) return;
    const request = ++locationRequestRef.current;
    streamAbortRef.current?.abort();
    setGpsStatus('idle');
    setPhase('locating');
    setLoading(true);
    setMapFocusUrl(null);
    try {
      const geo = await geocodeLocation(locQuery);
      if (request !== locationRequestRef.current) return;
      setManualRegion(null);
      setLat(geo.lat);
      setLng(geo.lng);
      setLocationName(geo.name || locQuery);
      setSavedLocation({ lat: geo.lat, lng: geo.lng, locationName: geo.name || locQuery });
      setIframeUrl(`https://map.naver.com/p/search/${encodeURIComponent(locQuery)}`);
      addToast(`📍 ${geo.name || locQuery} 위치 설정 완료`, 'success');
      await runAreaExplore(geo.name || locQuery, geo.lat, geo.lng);
    } catch (err) {
      if (request !== locationRequestRef.current) return;
      addToast(err.message || '위치 검색 실패', 'error');
      setPhase('idle');
    } finally {
      if (request === locationRequestRef.current) setLoading(false);
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
    const request = ++locationRequestRef.current;
    addToast('📡 GPS 위치를 가져오는 중...', 'info');

    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        if (request !== locationRequestRef.current) return;
        const newLat = pos.coords.latitude;
        const newLng = pos.coords.longitude;
        setManualRegion(null);
        setLat(newLat);
        setLng(newLng);
        setGpsStatus('success');
        setIframeUrl(`https://map.naver.com/p?c=${newLng},${newLat},15,0,0,0,dh`);
        addToast('✅ 현재 위치를 가져왔습니다', 'success');

        // 역 geocode로 위치명 가져오기
        setLoading(true);
        try {
          const geo = await geocodeLocation(`${newLat},${newLng}`);
          if (request !== locationRequestRef.current) return;
          const locLabel = geo?.name || '현재 위치';
          setLocationName(locLabel);
          setLocationInput(locLabel);
          setSavedLocation({ lat: newLat, lng: newLng, locationName: locLabel });
          await runAreaExplore(locLabel, newLat, newLng);
        } catch {
          if (request !== locationRequestRef.current) return;
          setLocationName('현재 위치');
          setLocationInput('현재 위치');
          setSavedLocation({ lat: newLat, lng: newLng, locationName: '현재 위치' });
          await runAreaExplore(null, newLat, newLng);
        } finally {
          if (request === locationRequestRef.current) setLoading(false);
        }
      },
      (err) => {
        if (request !== locationRequestRef.current) return;
        setGpsStatus('denied');
        setLoading(false);
        setPhase(locationName ? 'categories' : 'idle');
        const msg = err.code === 1
          ? '위치 권한이 거부되었습니다. 위치를 직접 입력해 주세요.'
          : '위치를 가져올 수 없습니다. 위치를 직접 입력해 주세요.';
        addToast(msg, 'warning');
        searchInputRef.current?.focus();
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
    );
  }, [geocodeLocation, runAreaExplore, addToast, setSavedLocation, locationName]);

  const fetchSubcategoryResults = useCallback(async (location, subcategory, latVal, lngVal) => {
    const params = new URLSearchParams({
      location, subcategory,
      ...(latVal != null && { lat: latVal }),
      ...(lngVal != null && { lng: lngVal }),
      max_items: 30,
      browser_search: String(browserSearchEnabled),
    });
    const res = await fetch(`/api/local/subcategory-search?${params}`);
    const data = await res.json();
    return itemsWithinRadius(data.data?.items || data.items || [], latVal, lngVal, radiusRef.current);
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
      setSortBy(fuelTypeRef.current === 'premium' ? 'premium_gasoline' : fuelTypeRef.current);
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

    if (locationName && !manualRegion && subName !== '전체') {
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
    const request = ++locationRequestRef.current;
    streamAbortRef.current?.abort();
    const controller = new AbortController();
    streamAbortRef.current = controller;
    const active = () => request === locationRequestRef.current
      && streamAbortRef.current === controller && !controller.signal.aborted;
    setLoading(true);
    setPhase('search');
    setDirectSearchResult(null);
    setSearchLabel(searchQuery);
    setMapFocusUrl(null);
    const fullQuery = locationName ? `${locationName} ${searchQuery}` : searchQuery;
    setIframeUrl(`https://map.naver.com/p/search/${encodeURIComponent(fullQuery)}`);
    try {
      const result = await naverSearch(fullQuery, controller.signal);
      if (!active()) return;
      const { items } = result;
      setDirectSearchResult(result);
      setDisplayItems(items);
      if (result.source !== 'naver') {
        addToast(PLACE_STATUS_TEXT[result.source], 'warning');
      } else if (items.length > 0) {
        addToast(`'${searchQuery}' 검색: ${items.length}건 발견`, 'success');
      } else {
        addToast('검색 결과 없음', 'warning');
      }
      if (isGasCategory(items)) setSortBy('gasoline');
      else setSortBy('price');
      setSortDir('asc');
    } catch (error) {
      if (!active() || error.name === 'AbortError') return;
      setDirectSearchResult({ source: 'unavailable', items: [] });
      setDisplayItems([]);
      addToast(PLACE_STATUS_TEXT.unavailable, 'error');
    } finally {
      if (active()) setLoading(false);
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
    locationRequestRef.current += 1;
    setGpsStatus('idle');
    setLoading(false);
    if (placeUrl) {
      setMapFocusUrl(placeUrl);
    } else if (name) {
      setMapFocusUrl(`https://map.naver.com/p/search/${encodeURIComponent(name)}`);
    }
  }, []);

  const handleItemClick = useCallback((item) => {
    locationRequestRef.current += 1;
    setGpsStatus('idle');
    setLoading(false);
    const petrol = item.petrol_info;
    if (petrol) {
      setSelectedGas({
        name: item.name, addr: item.address, brand: petrol.brand,
        gasoline: petrol.gasoline, diesel: petrol.diesel, lpg: petrol.lpg,
        is_self: petrol.is_self, is_24h: petrol.is_24h, has_car_wash: petrol.has_car_wash,
        premium_gasoline: petrol.premium_gasoline, naverUrl: item.url,
        image_url: item.image_url, tel: item.tel, distance: item.distance, distance_m: item.distance_m,
        updated_at: petrol.updated_at || item.updated_at,
        source: petrol.source || item.source,
        price_observed_at: petrol.price_observed_at,
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
      return [['gasoline', '휘발유'], ['diesel', '경유'], ['premium_gasoline', '고급 휘발유'], ['lpg', 'LPG'], ['distance', '거리']];
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
  const placeCategories = exploreData?.categories?.filter(category => category.name !== '주유소') || [];
  const areaPlaceSource = !browserSearchEnabled ? 'disabled'
    : streamingCats.size > 0 ? 'querying'
    : exploreData?.source === 'unavailable' ? 'unavailable'
    : !placeCategories.length ? 'not_queried'
    : placeCategories.every(category => category.source === 'naver') ? 'naver' : 'unavailable';
  const placeSearchSource = phase === 'search'
    ? (loading ? 'querying' : directSearchResult?.source || 'not_queried') : areaPlaceSource;
  const placeSearchMessage = PLACE_STATUS_TEXT[placeSearchSource];
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
              {manualRegion ? '선택한 지역의 저장된 유종별 가격 정보를 확인할 수 있습니다.' : locationName
                ? '주변 검색 결과는 이 화면에서 바로 확인할 수 있습니다.'
                : '위치를 입력하거나 브라우저 위치 권한을 사용해 시작하세요.'}
            </p>

            {locationName && (
              <div className={s.mapStatusGrid}>
                <div>
                  <span>{manualRegion ? '선택 지역' : '탐색 반경'}</span>
                  <strong>{manualRegion ? locationName : `${radius / 1000}km`}</strong>
                </div>
                <div>
                  <span>장소 검색</span>
                  <strong>{manualRegion ? '위치 선택 후 사용' : placeSearchSource === 'naver'
                    ? '조회됨' : placeSearchSource === 'disabled' ? '사용 안 함'
                      : placeSearchSource === 'unavailable' ? '결과 미확인'
                        : placeSearchSource === 'querying' ? '조회 중' : '조회 대기'}</strong>
                </div>
                <div>
                  <span>카테고리</span>
                  <strong>{visibleCategories.length}개</strong>
                </div>
                <div>
                  <span>{!manualRegion && placeSearchMessage && !visibleCategories.length ? '장소 결과' : '현재 결과'}</span>
                  <strong>{!manualRegion && placeSearchMessage && !visibleCategories.length
                    ? (placeSearchSource === 'disabled' ? '미조회' : '미확인') : `${sortedItems.length}건`}</strong>
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

            {locationName && !manualRegion && !browserSearchEnabled && (
              <small className={s.mapConsentHint}>
                장소 목록이 필요하면 오른쪽의 브라우저 검색을 직접 켜주세요.
              </small>
            )}
            {locationName && !manualRegion && browserSearchEnabled && placeSearchMessage && (
              <small className={s.mapConsentHint}>{placeSearchMessage}</small>
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
            <button type="submit" className={s.searchBtn} disabled={!locationInput.trim()}>
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
          {!manualRegion && <div className={s.radiusRow}>
            <span className={s.radiusLabel}>반경</span>
            <div className={s.radiusOptions}>
              {RADIUS_OPTIONS.map(opt => (
                <button
                  key={opt.value}
                  className={`${s.radiusBtn} ${radius === opt.value ? s.radiusActive : ''}`}
                  onClick={() => {
                    setRadius(opt.value);
                    radiusRef.current = opt.value;
                    if (locationName) runAreaExplore(locationName, lat, lng, browserSearchEnabled, opt.value);
                  }}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>}

          <form className={s.locationRow} onSubmit={event => {
            event.preventDefault();
            if (regionSido.trim() || regionSigungu.trim()) runRegionFuel(regionSido, regionSigungu);
          }}>
            <input className={s.locationInput} aria-label="시/도" placeholder="시/도 (예: 서울특별시)"
              value={regionSido} onChange={event => setRegionSido(event.target.value)} />
            <input className={s.locationInput} aria-label="시/군/구" placeholder="시/군/구 (예: 강서구)"
              value={regionSigungu} onChange={event => setRegionSigungu(event.target.value)} />
            <button type="submit" disabled={!regionSido.trim() && !regionSigungu.trim()}>지역 가격 조회</button>
          </form>
          <label>조회 유종{' '}
            <select aria-label="조회 유종" value={fuelType} onChange={event => {
              setFuelType(event.target.value); fuelTypeRef.current = event.target.value;
              if (manualRegion) runRegionFuel(manualRegion.sido, manualRegion.sigungu);
              else if (locationName) runAreaExplore(locationName, lat, lng);
            }}>
              <option value="gasoline">휘발유</option><option value="diesel">경유</option>
              <option value="premium">고급 휘발유</option><option value="lpg">LPG</option>
            </select>
          </label>
          {manualRegion && <p>선택 지역의 가격 정보입니다. 거리와 반경은 위치가 확인된 뒤 조회할 수 있습니다.</p>}

          {(fuelStatus?.error || (!fuelStatus?.items?.length && fuelStatus?.message)) && (
            <p role="status">{fuelStatus.error || fuelStatus.message}</p>
          )}

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
          {locationName && !manualRegion && (
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
              {(exploreData?.categories || []).filter(cat => cat.unlocated_items?.length > 0).map(cat => <button key={`unlocated-${cat.name}`} className={s.categoryCard} onClick={() => handleCategoryClick({...cat, items:cat.unlocated_items})}>
                <span>{cat.name} · 원문 결과 {cat.unlocated_items.length}건</span>
                <small>좌표·거리·반경 미확인</small>
              </button>)}
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
                  {manualRegion ? (fuelStatus?.error || fuelStatus?.message || '선택한 지역의 가격 정보가 없습니다')
                    : (exploreData?.categories || []).some(cat => cat.received_count > 0)
                      ? `출처 결과 ${(exploreData?.categories || []).reduce((n, cat) => n + (cat.received_count || 0), 0)}건을 받았으나 선택한 위치·반경에서 확인되는 장소가 없습니다. 검색 지역과 출처 좌표를 확인해 주세요.`
                      : placeSearchMessage || '브라우저 검색 결과가 없습니다. 검색어를 바꿔 다시 시도해 주세요.'}
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
                {phase === 'search' && placeSearchMessage ? placeSearchMessage : `${sortedItems.length}건의 결과`}
              </div>

              {/* 검색 중 스켈레톤 (항목 없을 때) */}
              {loading && sortedItems.length === 0 && (
                <SkeletonLoader count={5} message="검색 결과를 불러오고 있습니다..." />
              )}

              {/* Item list */}
              <div className={s.list}>
                {sortedItems.length === 0 && !loading && (
                  <div className={s.emptyMsg} role={phase === 'search' ? 'status' : undefined}
                    aria-label={phase === 'search' ? '장소 검색 상태' : undefined}>
                    {phase === 'search' && placeSearchMessage ? placeSearchMessage : '검색 결과가 없습니다'}
                  </div>
                )}
                {sortedItems.map((item, i) => {
                  const priceInfo = getRepresentativePrice(item.menu_info);
                  const petrol = item.petrol_info;
                  const distance = distanceKm(item.distance, item.distance_m);
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
                            {petrol.premium_gasoline && (
                              <div className={s.petrolLine}>
                                <span className={s.petrolLabel}>고급 휘발유</span>
                                <span className={s.petrolVal}>{fmt(petrol.premium_gasoline)}</span>
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
                                <span>가격 관측</span>
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
                        <div className={s.itemDist}>
                          {distance == null ? '거리 미확인' : `📏 ${distance.toFixed(1)}km`}
                        </div>
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
