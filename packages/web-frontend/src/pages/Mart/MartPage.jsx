import { useState, useMemo, useEffect, useCallback, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { ChevronLeft, ChevronRight, ExternalLink, Heart, RefreshCw, ZoomIn, ZoomOut, Maximize, Minimize2 } from 'lucide-react';
import { MARTS } from '../../utils/constants';
import { fmt } from '../../utils/helpers';
import useStore from '../../stores/appStore';
import { api } from '../../services/api';
import { buildWishlistPayload, normalizeProduct } from '../../utils/productActions';
import Spinner from '../../components/common/Spinner';
import EmptyState from '../../components/common/EmptyState';
import ProductDetailModal from '../../components/ProductDetailModal';
import s from './MartPage.module.css';

const COMPARE_MARTS = ['emart', 'homeplus', 'lotte'];

const MART_CATEGORIES = {
  '육류': ['돼지', '소고기', '한우', '삼겹', '갈비', '목심', '등심', '닭', '오리고기'],
  '수산물': ['생선', '연어', '참치', '새우', '오징어', '조개', '굴', '게', '랍스터', '멸치'],
  '채소': ['양파', '감자', '당근', '배추', '상추', '시금치', '파', '마늘', '고추', '토마토'],
  '과일': ['사과', '배', '포도', '딸기', '수박', '참외', '바나나', '귤', '오렌지', '망고'],
  '유제품': ['우유', '치즈', '요거트', '버터', '크림'],
  '음료': ['커피', '주스', '콜라', '사이다', '물', '차', '맥주', '소주'],
  '과자/간식': ['과자', '초콜릿', '젤리', '쿠키', '빵', '떡', '아이스크림'],
  '가공식품': ['라면', '통조림', '소시지', '햄', '만두', '김치', '두부'],
  '생활용품': ['세제', '휴지', '샴푸', '치약', '비누', '마스크'],
};

function inferCategory(name) {
  if (!name) return '기타';
  for (const [cat, keywords] of Object.entries(MART_CATEGORIES)) {
    if (keywords.some(kw => name.includes(kw))) return cat;
  }
  return '기타';
}

const MART_ONLINE_URLS = {
  emart: { name: 'SSG.COM', url: 'https://www.ssg.com', searchUrl: 'https://www.ssg.com/search.ssg?query=' },
  homeplus: { name: '홈플러스몰', url: 'https://mfront.homeplus.co.kr', searchUrl: 'https://mfront.homeplus.co.kr/search?keyword=' },
  lotte: { name: '롯데온', url: 'https://www.lottemart.com', searchUrl: 'https://www.lottemart.com/search/search/search.do?keyword=' },
  costco: { name: '코스트코', url: 'https://www.costco.co.kr', searchUrl: 'https://www.costco.co.kr/search?text=' },
};

function getOnlineMallUrl(martKey, productName) {
  const mall = MART_ONLINE_URLS[martKey];
  if (!mall) return null;
  return productName ? `${mall.searchUrl}${encodeURIComponent(productName)}` : mall.url;
}

function safePrice(val) {
  if (val == null) return 0;
  const n = typeof val === 'string' ? parseInt(val.replace(/[^0-9]/g, ''), 10) : Number(val);
  return isNaN(n) ? 0 : n;
}

function safeDiscount(val) {
  if (val == null) return 0;
  const n = typeof val === 'string' ? parseFloat(val.replace(/[^0-9.]/g, '')) : Number(val);
  return isNaN(n) ? 0 : n;
}

function formatPeriodDate(value) {
  if (!value) return '';
  const text = String(value).trim();
  const iso = text.match(/^\d{4}-(\d{2})-(\d{2})/);
  if (iso) return `${Number(iso[1])}/${Number(iso[2])}`;
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) return '';
  return `${parsed.getMonth() + 1}/${parsed.getDate()}`;
}

function formatItemPeriod(item) {
  const start = formatPeriodDate(item?.validFrom);
  const end = formatPeriodDate(item?.validTo);
  if (start && end) return `${start} ~ ${end}`;
  if (start) return `${start} ~`;
  if (end) return `~ ${end}`;
  return '';
}

function normalizeItem(d) {
  if (!d) return null;
  const priceObservationOnly = Boolean(d.price_observation_only);
  const hasDiscountMetadata = Boolean(d.has_discount_metadata)
    || (!priceObservationOnly && d.original_price != null && (d.discount_rate ?? d.disc ?? d.discount) != null);
  const orig = hasDiscountMetadata ? safePrice(d.original_price ?? d.orig ?? d.regular_price) : 0;
  const disc = hasDiscountMetadata ? safeDiscount(d.discount_rate ?? d.disc ?? d.discount) : 0;
  return {
    name: d.name || d.product_name || '상품명 없음',
    sale: safePrice(d.price ?? d.sale ?? d.sale_price),
    orig,
    disc,
    event: d.event_name ?? d.event ?? d.promotion ?? d.record_label ?? '관측 가격',
    img: d.image_url ?? d.img ?? d.thumbnail ?? '',
    detailUrl: d.source_url ?? d.detail_url ?? d.url ?? '',
    unit: d.display_unit ?? d.unit ?? d.spec ?? '',
    store: d.store ?? d.branch ?? '',
    crawledAt: d.crawled_at ?? d.updated_at ?? '',
    validFrom: d.valid_from ?? d.validFrom ?? '',
    validTo: d.valid_to ?? d.valid_until ?? d.validTo ?? '',
    recordKind: d.record_kind ?? 'price_observation',
    publicationKind: d.publication_kind ?? 'price_observation',
    priceObservationOnly,
    discountClaimStatus: d.discount_claim_status ?? 'unknown',
    claimBasis: d.claim_basis ?? '',
    hasDiscountMetadata,
    recordLabel: d.record_label ?? (priceObservationOnly ? '관측 가격' : '가격 정보'),
    claimStatusLabel: d.claim_status_label ?? (priceObservationOnly ? '할인 여부 미확인' : ''),
  };
}

function getCategories(items) {
  if (!Array.isArray(items) || items.length === 0) return ['전체'];
  const events = new Set(items.map(i => i.event).filter(Boolean));
  return ['전체', ...events];
}

function normalizeProductName(name) {
  if (!name) return '';
  return name
    .replace(/\s+\d+.*$/, '')
    .replace(/\s+(1kg|100g|1L|5P|2입|24입|30구|12|21포|500g|1통|1포기|2마리|1망|793g|1\.5kg|2\.3L|600g).*$/i, '')
    .trim();
}

function findCommonProducts(martDeals, targetMarts = COMPARE_MARTS) {
  const productNames = {};
  for (const martKey of targetMarts) {
    const items = martDeals[martKey];
    if (!Array.isArray(items)) continue;
    const martInfo = MARTS.find(m => m.key === martKey);
    for (const item of items) {
      if (!item?.name) continue;
      const base = normalizeProductName(item.name);
      if (!base) continue;
      if (!productNames[base]) productNames[base] = {};
      productNames[base][martKey] = {
        ...item,
        mart: martInfo?.name || martKey,
        color: martInfo?.color || '#666',
      };
    }
  }
  return Object.entries(productNames)
    .filter(([, marts]) => Object.keys(marts).length >= 2)
    .map(([name, marts]) => ({ name, marts }))
    .sort((a, b) => Object.keys(b.marts).length - Object.keys(a.marts).length);
}

function formatLastUpdate(dateStr) {
  if (!dateStr) return null;
  try {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return null;
    return `${d.getMonth()+1}/${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2,'0')}`;
  } catch { return null; }
}

export default function MartPage() {
  const [searchParams] = useSearchParams();
  const urlMart = searchParams.get('mart');
  const urlProduct = searchParams.get('product');

  const [activeMart, setActiveMart] = useState(() => {
    if (urlMart && MARTS.some(m => m.key === urlMart)) return urlMart;
    return 'emart';
  });
  const [mode, setMode] = useState('sale');
  const [catFilter, setCatFilter] = useState('전체');
  const [searchText, setSearchText] = useState('');
  const [productCat, setProductCat] = useState('전체');
  const [flyerIdx, setFlyerIdx] = useState(0);
  const [flyerZoom, setFlyerZoom] = useState(1);
  const [flyerPan, setFlyerPan] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const dragStart = useRef({ x: 0, y: 0, panX: 0, panY: 0 });
  const flyerViewerRef = useRef(null);
  const flyerImgRef = useRef(null);
  const [saleDetail, setSaleDetail] = useState(null);

  const {
    addToShoppingList, addToast, isLoggedIn, favorites, favoriteItems,
    addFavorite, removeFavorite, setFavoriteRemoteId,
  } = useStore();
  const favoriteIds = Array.isArray(favorites) ? favorites : [];

  const [martDeals, setMartDeals] = useState({});
  const [martMeta, setMartMeta] = useState({});
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(true);

  const [flyerData, setFlyerData] = useState({});
  const [flyerLoading, setFlyerLoading] = useState(false);
  const [flyerError, setFlyerError] = useState(null);
  const [flyerMart, setFlyerMart] = useState('emart');

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    const martKeys = MARTS.map(m => m.key);
    Promise.allSettled(
      martKeys.map(key =>
        fetch(`/api/marts/${key}/promotions`, { signal }).then(r => r.json())
          .then(res => {
            const rawItems = Array.isArray(res?.data) ? res.data : (res?.data?.items || []);
            return {
              key,
              lastCrawledAt: res?.data?.last_crawled_at || '',
              items: rawItems.map(normalizeItem).filter(Boolean),
            };
          })
      )
    ).then(results => {
      const deals = {};
      const meta = {};
      results.forEach(r => {
        if (r.status === 'fulfilled' && r.value) {
          deals[r.value.key] = r.value.items;
          meta[r.value.key] = { lastCrawledAt: r.value.lastCrawledAt };
        }
      });
      setMartDeals(deals);
      setMartMeta(meta);
    }).catch(err => {
      if (err.name === 'AbortError') return;
      console.error(err);
      addToast('마트 데이터를 불러오는데 실패했습니다', 'error');
    }).finally(() => setLoading(false));

    fetch('/api/products/search?per_page=50', { signal })
      .then(r => r.json())
      .then(res => setProducts(Array.isArray(res?.data) ? res.data : []))
      .catch(err => { if (err.name !== 'AbortError') console.error(err); });

    return () => controller.abort();
  }, [addToast]);

  const flyerDataRef = useRef(flyerData);
  flyerDataRef.current = flyerData;

  const martInfo = useMemo(() => MARTS.find(m => m.key === activeMart), [activeMart]);
  const martItems = useMemo(() => Array.isArray(martDeals[activeMart]) ? martDeals[activeMart] : [], [martDeals, activeMart]);

  // Auto-open product from URL param (e.g., navigated from Home → Mart)
  useEffect(() => {
    if (!urlProduct || loading || martItems.length === 0) return;
    const match = martItems.find(item => (item.id || item.name) === urlProduct || item.name === decodeURIComponent(urlProduct));
    if (match) {
      const mInfo = MARTS.find(m => m.key === activeMart);
      setSaleDetail({
        ...match,
        martKey: activeMart,
        martName: mInfo?.name,
        period: formatItemPeriod(match) || '기간 미제공 · 최근 가격 관측',
      });
    }
  }, [urlProduct, loading, martItems, activeMart]);

  const fetchFlyerData = useCallback((store, signal) => {
    if (flyerDataRef.current[store]) return;
    setFlyerLoading(true);
    setFlyerError(null);
    fetch(`/api/marts/${store}/flyers`, { signal })
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(res => { if (res?.data) setFlyerData(prev => ({ ...prev, [store]: res.data })); })
      .catch(err => {
        if (err.name === 'AbortError') return;
        console.error('Flyer fetch error:', err);
        setFlyerError(`${store} 전단지를 불러올 수 없습니다`);
      })
      .finally(() => setFlyerLoading(false));
  }, []);

  useEffect(() => {
    if (mode !== 'flyer') return;
    const controller = new AbortController();
    const { signal } = controller;

    fetchFlyerData(flyerMart, signal);
    MARTS.forEach(m => {
      if (m.key !== flyerMart && !flyerDataRef.current[m.key]) {
        fetch(`/api/marts/${m.key}/flyers`, { signal })
          .then(r => r.ok ? r.json() : null)
          .then(res => { if (res?.data) setFlyerData(prev => ({ ...prev, [m.key]: res.data })); })
          .catch(() => {});
      }
    });

    return () => controller.abort();
  }, [mode, flyerMart, fetchFlyerData]);

  const categories = useMemo(() => getCategories(martItems), [martItems]);
  const filteredItems = useMemo(() => {
    let items = catFilter === '전체' ? martItems : martItems.filter(i => i.event === catFilter);
    if (productCat !== '전체') {
      items = items.filter(i => inferCategory(i.name) === productCat);
    }
    if (searchText.trim()) {
      const q = searchText.trim().toLowerCase();
      items = items.filter(i => i.name?.toLowerCase().includes(q));
    }
    return items;
  }, [martItems, catFilter, productCat, searchText]);
  const productCatCounts = useMemo(() => {
    const base = catFilter === '전체' ? martItems : martItems.filter(i => i.event === catFilter);
    const counts = {};
    for (const item of base) {
      const cat = inferCategory(item.name);
      counts[cat] = (counts[cat] || 0) + 1;
    }
    return counts;
  }, [martItems, catFilter]);
  const commonProducts = useMemo(() => findCommonProducts(martDeals), [martDeals]);

  const martPeriod = useMemo(() => {
    const periods = Array.from(new Set(martItems.map(formatItemPeriod).filter(Boolean)));
    if (periods.length === 0) return '행사 기간 미제공 · 최근 가격 관측';
    if (periods.length === 1) return periods[0];
    return `상품별 기간 상이 (${periods.length}개 기간)`;
  }, [martItems]);

  const toggleWishlist = useCallback((product) => {
    const normalized = normalizeProduct(product);
    const favoriteId = normalized.favoriteId;
    const isFav = favoriteIds.includes(favoriteId);
    if (!isLoggedIn) {
      addToast('로그인이 필요합니다', 'warning');
      return;
    }
    if (isFav) {
      const remoteId = favoriteItems?.[favoriteId]?.remote_id;
      removeFavorite(favoriteId);
      if (remoteId) api.delete(`/api/wishlist/${remoteId}`).catch(() => {});
      addToast('찜 목록에서 제거했어요', 'info');
      return;
    }
    const payload = buildWishlistPayload(product);
    addFavorite(favoriteId, payload);
    api.post('/api/wishlist', payload).then(async (res) => {
      const json = res?.json ? await res.json().catch(() => null) : null;
      const remoteId = json?.data?.id || json?.id;
      if (remoteId) setFavoriteRemoteId(favoriteId, remoteId);
    }).catch(() => {
      removeFavorite(favoriteId);
      addToast('찜 추가에 실패했어요. 잠시 후 다시 시도해주세요.', 'error');
    });
    addToast(`${normalized.name} 찜했어요 ❤️`, 'success');
  }, [isLoggedIn, favoriteIds, favoriteItems, addFavorite, removeFavorite, setFavoriteRemoteId, addToast]);

  const currentFlyer = useMemo(() => flyerData[flyerMart], [flyerData, flyerMart]);
  const flyerPages = useMemo(() => currentFlyer?.flyer_pages || [], [currentFlyer]);
  const flyerHasImages = flyerPages.length > 0;

  const resetFlyerView = useCallback(() => {
    setFlyerZoom(1);
    setFlyerPan({ x: 0, y: 0 });
  }, []);

  const clampPan = useCallback((px, py, z) => {
    if (z <= 1) return { x: 0, y: 0 };
    const viewer = flyerViewerRef.current;
    const img = flyerImgRef.current;
    if (!viewer || !img) return { x: px, y: py };
    const vw = viewer.clientWidth;
    const vh = viewer.clientHeight;
    const iw = img.clientWidth;
    const ih = img.clientHeight;
    // pan is applied inside the scale, so effective pixel shift = pan * zoom
    // max pan so the image edge doesn't go past the viewer edge
    const maxPanX = Math.max(0, (iw * z - vw) / (2 * z));
    const maxPanY = Math.max(0, (ih * z - vh) / (2 * z));
    return {
      x: Math.max(-maxPanX, Math.min(maxPanX, px)),
      y: Math.max(-maxPanY, Math.min(maxPanY, py)),
    };
  }, []);

  const handleFlyerMouseDown = useCallback((e) => {
    if (flyerZoom <= 1) return;
    e.preventDefault();
    setIsDragging(true);
    dragStart.current = { x: e.clientX, y: e.clientY, panX: flyerPan.x, panY: flyerPan.y };
  }, [flyerZoom, flyerPan]);

  const handleFlyerMouseMove = useCallback((e) => {
    if (!isDragging) return;
    const dx = (e.clientX - dragStart.current.x) / flyerZoom;
    const dy = (e.clientY - dragStart.current.y) / flyerZoom;
    setFlyerPan(clampPan(dragStart.current.panX + dx, dragStart.current.panY + dy, flyerZoom));
  }, [isDragging, flyerZoom, clampPan]);

  const handleFlyerMouseUp = useCallback(() => {
    setIsDragging(false);
  }, []);

  const handleFlyerWheel = useCallback((e) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? -0.1 : 0.1;
    setFlyerZoom(prev => {
      const next = Math.min(3, Math.max(0.5, +(prev + delta).toFixed(2)));
      if (next <= 1) {
        setFlyerPan({ x: 0, y: 0 });
      } else {
        setFlyerPan(p => clampPan(p.x, p.y, next));
      }
      return next;
    });
  }, [clampPan]);

  const handleFlyerDoubleClick = useCallback((e) => {
    e.preventDefault();
    if (flyerZoom > 1) {
      resetFlyerView();
    } else {
      setFlyerZoom(2);
      // pan toward click position
      const viewer = flyerViewerRef.current;
      if (viewer) {
        const rect = viewer.getBoundingClientRect();
        const cx = (e.clientX - rect.left - rect.width / 2) / 2;
        const cy = (e.clientY - rect.top - rect.height / 2) / 2;
        setFlyerPan(clampPan(-cx, -cy, 2));
      }
    }
  }, [flyerZoom, resetFlyerView, clampPan]);

  // attach wheel listener with { passive: false } so preventDefault works
  useEffect(() => {
    const el = flyerViewerRef.current;
    if (!el) return;
    el.addEventListener('wheel', handleFlyerWheel, { passive: false });
    return () => el.removeEventListener('wheel', handleFlyerWheel);
  }, [handleFlyerWheel]);

  return (
    <div>
      <div className={s.hdr}>
        <h2>마트 가격/행사 전단</h2>
        <p>이마트 · 홈플러스 · 롯데마트 · 코스트코 관측 가격과 확인된 행사</p>
      </div>

      <div className={s.tabs}>
        {MARTS.map(m => (
          <button
            key={m.key}
            className={`${s.tab} ${activeMart === m.key ? s.tabActive : ''}`}
            onClick={() => { setActiveMart(m.key); setCatFilter('전체'); setProductCat('전체'); setSearchText(''); }}
          >
            <span className={s.dot} style={{ background: m.color }} />{m.name}
          </button>
        ))}
      </div>

      {loading && <div style={{ display: 'flex', justifyContent: 'center', padding: '2rem 0' }}><Spinner /></div>}

      <div className={s.info}>
        <span>기간 정보: {martPeriod}</span>
        <span>총 {martItems.length}개 상품</span>
        {martMeta[activeMart]?.lastCrawledAt && (
          <span className={s.crawlBadge} title="크롤링된 실제 데이터">
            🔄 {formatLastUpdate(martMeta[activeMart].lastCrawledAt)} 수집
          </span>
        )}
      </div>

      <div className={s.modeRow}>
        <button className={`${s.modeBtn} ${mode === 'sale' ? s.modeBtnActive : ''}`} onClick={() => setMode('sale')}>
          📋 가격/행사 상품
        </button>
        <button className={`${s.modeBtn} ${mode === 'flyer' ? s.modeBtnActive : ''}`} onClick={() => setMode('flyer')}>
          📰 전단지 보기
        </button>
        <button className={`${s.modeBtn} ${mode === 'compare' ? s.modeBtnActive : ''}`} onClick={() => setMode('compare')}>
          ⚖️ 마트별 비교
        </button>
      </div>

      {/* ===== FLYER VIEWER ===== */}
      {mode === 'flyer' && (
        <div className={s.flyerSection}>
          <div className={s.flyerMartTabs}>
            {MARTS.map(m => (
              <button
                key={m.key}
                className={`${s.flyerMartTab} ${flyerMart === m.key ? s.flyerMartTabActive : ''}`}
                style={flyerMart === m.key ? { borderColor: m.color, color: m.color } : {}}
                onClick={() => { setFlyerMart(m.key); setFlyerIdx(0); resetFlyerView(); }}
              >
                <span className={s.dot} style={{ background: m.color }} />{m.name}
              </button>
            ))}
          </div>

          {currentFlyer && (
            <div className={s.flyerPeriod}>
              <span>📅 행사 기간: {currentFlyer.display_period || '정보 없음'}</span>
              {currentFlyer.web_url && (
                <a href={currentFlyer.web_url} target="_blank" rel="noopener noreferrer" className={s.flyerWebLink}>
                  원본 사이트에서 보기 <ExternalLink size={14} />
                </a>
              )}
            </div>
          )}

          {flyerLoading && (
            <div className={s.flyerLoading}>
              <Spinner />
              <span>전단지를 불러오는 중...</span>
            </div>
          )}

          {flyerError && !flyerLoading && (
            <div className={s.flyerError}>
              <p>⚠️ {flyerError}</p>
              <button
                className={s.flyerRetryBtn}
                onClick={() => {
                  setFlyerData(prev => { const next = { ...prev }; delete next[flyerMart]; return next; });
                  fetchFlyerData(flyerMart);
                }}
              >
                <RefreshCw size={14} /> 다시 시도
              </button>
            </div>
          )}

          {!flyerLoading && !flyerError && flyerHasImages && (
            <>
              <div
                className={s.flyerViewer}
                ref={flyerViewerRef}
                onMouseDown={handleFlyerMouseDown}
                onMouseMove={handleFlyerMouseMove}
                onMouseUp={handleFlyerMouseUp}
                onMouseLeave={handleFlyerMouseUp}
                onDoubleClick={handleFlyerDoubleClick}
              >
                <img
                  src={flyerPages[flyerIdx]?.image_url}
                  alt={`${currentFlyer?.name || flyerMart} 전단지 ${flyerIdx + 1}페이지`}
                  className={s.flyerImg}
                  ref={flyerImgRef}
                  draggable={false}
                  onError={(e) => { e.target.style.opacity = '0.3'; }}
                  style={{
                    transform: `scale(${flyerZoom}) translate(${flyerPan.x}px, ${flyerPan.y}px)`,
                    cursor: flyerZoom > 1 ? (isDragging ? 'grabbing' : 'grab') : 'default',
                    userSelect: 'none',
                    transition: isDragging ? 'none' : 'transform .3s var(--ease)',
                  }}
                />
                {flyerPages.length > 1 && (
                  <>
                    <button
                      className={`${s.flyerNav} ${s.flyerPrev}`}
                      onClick={() => { setFlyerIdx(prev => (prev - 1 + flyerPages.length) % flyerPages.length); resetFlyerView(); }}
                    >
                      <ChevronLeft size={20} />
                    </button>
                    <button
                      className={`${s.flyerNav} ${s.flyerNext}`}
                      onClick={() => { setFlyerIdx(prev => (prev + 1) % flyerPages.length); resetFlyerView(); }}
                    >
                      <ChevronRight size={20} />
                    </button>
                  </>
                )}
                <div className={s.flyerPageBadge}>
                  {flyerIdx + 1} / {flyerPages.length}
                </div>
                <div className={s.flyerZoomControls}>
                  <button
                    className={s.flyerZoomBtn}
                    onClick={e => { e.stopPropagation(); setFlyerZoom(z => { const next = Math.max(0.5, z - 0.25); if (next <= 1) setFlyerPan({ x: 0, y: 0 }); return next; }); }}
                    title="축소"
                  >
                    <ZoomOut size={16} />
                  </button>
                  <span className={s.flyerZoomLevel}>{Math.round(flyerZoom * 100)}%</span>
                  <button
                    className={s.flyerZoomBtn}
                    onClick={e => { e.stopPropagation(); setFlyerZoom(z => Math.min(3, z + 0.25)); }}
                    title="확대"
                  >
                    <ZoomIn size={16} />
                  </button>
                  <button
                    className={s.flyerZoomBtn}
                    onClick={e => { e.stopPropagation(); resetFlyerView(); }}
                    title="맞춤"
                  >
                    <Maximize size={16} />
                  </button>
                  <button
                    className={s.flyerZoomBtn}
                    onClick={e => { e.stopPropagation(); setFlyerZoom(1); setFlyerPan({ x: 0, y: 0 }); }}
                    title="원본 (100%)"
                  >
                    <Minimize2 size={16} />
                  </button>
                </div>
              </div>
              {flyerPages.length > 1 && (
                <div className={s.flyerDots}>
                  {flyerPages.map((_, i) => (
                    <button
                      key={`dot-${i}`}
                      className={`${s.flyerDot} ${i === flyerIdx ? s.flyerDotActive : ''}`}
                      onClick={() => { setFlyerIdx(i); resetFlyerView(); }}
                      title={`${i + 1}페이지`}
                    />
                  ))}
                </div>
              )}
            </>
          )}

          {!flyerLoading && !flyerError && currentFlyer && !flyerHasImages && (
            <div className={s.flyerLinkCard}>
              <div className={s.flyerLinkIcon}>📰</div>
              <h3 className={s.flyerLinkTitle}>{currentFlyer.name || '전단지'}</h3>
              <p className={s.flyerLinkDesc}>{currentFlyer.description || '최신 전단지를 확인하세요'}</p>
              {currentFlyer.display_period && (
                <p className={s.flyerLinkPeriod}>📅 {currentFlyer.display_period}</p>
              )}
              {currentFlyer.web_url ? (
                <a href={currentFlyer.web_url} target="_blank" rel="noopener noreferrer" className={s.flyerLinkBtn}>
                  전단지 보러가기 <ExternalLink size={16} />
                </a>
              ) : (
                <p className={s.emptyHint}>전단지가 아직 등록되지 않았습니다</p>
              )}
              <p className={s.flyerLinkNote}>
                {currentFlyer.name || MARTS.find(m => m.key === flyerMart)?.name} 공식 사이트에서 최신 전단지를 확인하세요
              </p>
            </div>
          )}

          {!flyerLoading && !flyerError && !currentFlyer && (
            <div className={s.emptyState}>
              <div className={s.emptyIcon}>📭</div>
              <p className={s.emptyTitle}>전단지가 아직 등록되지 않았습니다</p>
              <p className={s.emptyDesc}>
                데이터가 업데이트되면 자동으로 표시됩니다.
                {formatLastUpdate(martMeta[flyerMart]?.lastCrawledAt) && (
                  <> 마지막 업데이트: {formatLastUpdate(martMeta[flyerMart]?.lastCrawledAt)}</>
                )}
              </p>
              {MART_ONLINE_URLS[flyerMart] && (
                <a
                  href={MART_ONLINE_URLS[flyerMart].url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={s.emptyLink}
                >
                  {MART_ONLINE_URLS[flyerMart].name}에서 직접 확인하기 <ExternalLink size={14} />
                </a>
              )}
            </div>
          )}

          {!flyerLoading && (
            <div className={s.flyerQuickLinks}>
              <h4 className={s.flyerQuickTitle}>🔗 마트별 전단지 바로가기</h4>
              <div className={s.flyerQuickGrid}>
                {MARTS.map(m => {
                  const data = flyerData[m.key];
                  const webUrl = data?.web_url || MART_ONLINE_URLS[m.key]?.url;
                  if (!webUrl) return null;
                  return (
                    <a key={m.key} href={webUrl} target="_blank" rel="noopener noreferrer" className={s.flyerQuickItem}>
                      <span className={s.dot} style={{ background: m.color }} />
                      <span>{m.name}</span>
                      <ExternalLink size={12} />
                    </a>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ===== SALE GRID ===== */}
      {mode === 'sale' && (
        <>
          {/* 상품명 검색 */}
          <div className={s.searchRow}>
            <div className={s.searchWrap}>
              <span className={s.searchIcon}>🔍</span>
              <input
                className={s.searchInput}
                type="text"
                placeholder="상품명 검색..."
                value={searchText}
                onChange={e => setSearchText(e.target.value)}
              />
              {searchText && (
                <button className={s.searchClear} onClick={() => setSearchText('')}>✕</button>
              )}
            </div>
            {searchText && (
              <span className={s.searchCount}>검색 결과: {filteredItems.length}건</span>
            )}
          </div>

          {/* 행사 유형 필터 */}
          <div className={s.catRow}>
            <span className={s.catLabel}>행사:</span>
            {categories.map(c => (
              <button
                key={c}
                className={`${s.catBtn} ${catFilter === c ? s.catBtnActive : ''}`}
                onClick={() => setCatFilter(c)}
              >
                {c}
              </button>
            ))}
          </div>

          {/* 상품 카테고리 필터 */}
          <div className={s.catRow}>
            <span className={s.catLabel}>상품군:</span>
            <button
              className={`${s.catBtn} ${productCat === '전체' ? s.catBtnActive : ''}`}
              onClick={() => setProductCat('전체')}
            >
              전체
            </button>
            {Object.keys(MART_CATEGORIES).map(cat => {
              const count = productCatCounts[cat] || 0;
              if (count === 0) return null;
              return (
                <button
                  key={cat}
                  className={`${s.catBtn} ${productCat === cat ? s.catBtnActive : ''}`}
                  onClick={() => setProductCat(cat)}
                >
                  {cat} <span className={s.catCount}>({count})</span>
                </button>
              );
            })}
            {(productCatCounts['기타'] || 0) > 0 && (
              <button
                className={`${s.catBtn} ${productCat === '기타' ? s.catBtnActive : ''}`}
                onClick={() => setProductCat('기타')}
              >
                기타 <span className={s.catCount}>({productCatCounts['기타']})</span>
              </button>
            )}
          </div>

          <div className={s.grid}>
            {filteredItems.length === 0 && !loading && (
              <div className={s.emptyState} style={{ gridColumn: '1 / -1' }}>
                <div className={s.emptyIcon}>📭</div>
                <p className={s.emptyTitle}>가격/행사 상품이 아직 등록되지 않았습니다</p>
                <p className={s.emptyDesc}>
                  크롤러에서 수집 → 관리자 승인 후 표시됩니다.
                  {formatLastUpdate(martMeta[activeMart]?.lastCrawledAt) && (
                    <> 마지막 업데이트: {formatLastUpdate(martMeta[activeMart]?.lastCrawledAt)}</>
                  )}
                </p>
                {MART_ONLINE_URLS[activeMart] && (
                  <a
                    href={MART_ONLINE_URLS[activeMart].url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={s.emptyLink}
                  >
                    {MART_ONLINE_URLS[activeMart].name}에서 직접 확인하기 <ExternalLink size={14} />
                  </a>
                )}
              </div>
            )}
            {!loading && filteredItems.length === 0 && (
              <EmptyState
                title="가격/행사 상품이 없습니다"
                description="다른 마트나 카테고리를 선택해 보세요."
              />
            )}
            {filteredItems.map((item, i) => {
              const matched = products.find(p => item.name?.includes(p.name));
              const diff = matched ? item.sale - matched.avg : null;
              const onlineUrl = getOnlineMallUrl(activeMart, item.name);
              const common = commonProducts.find(cp => cp.name === normalizeProductName(item.name));
              const itemPeriod = formatItemPeriod(item);
              const comparableOffers = common
                ? Object.entries(common.marts).map(([key, offer]) => ({
                  ...offer,
                  source_name: offer.mart || key,
                  store_name: offer.mart || key,
                  price: offer.sale || offer.price,
                  original_price: offer.orig,
                  source_type: 'mart',
                  period: formatItemPeriod(offer) || '기간 미제공 · 최근 가격 관측',
                  price_observation_only: offer.priceObservationOnly,
                  has_discount_metadata: offer.hasDiscountMetadata,
                  record_label: offer.recordLabel,
                  discount_claim_status: offer.discountClaimStatus,
                }))
                : [];
              const productData = {
                ...item,
                martKey: activeMart,
                martName: martInfo?.name,
                period: itemPeriod || '기간 미제공 · 최근 가격 관측',
                comparable_offers: comparableOffers,
                  price_history_summary: matched ? { average_price: matched.avg, count: 1 } : null,
                  price_observation_only: item.priceObservationOnly,
                  has_discount_metadata: item.hasDiscountMetadata,
                  record_label: item.recordLabel,
                  claim_status_label: item.claimStatusLabel,
                  discount_claim_status: item.discountClaimStatus,
                  claim_basis: item.claimBasis,
                };
              const fav = favoriteIds.includes(normalizeProduct(productData).favoriteId);
              return (
                <div key={item.id || item.name || `sale-${i}`} className={s.card} onClick={() => setSaleDetail(productData)}>
                  <div className={s.cardName}>{item.name}</div>
                  <div className={s.cardPrices}>
                    <span className={s.sale}>{fmt(item.sale)}원</span>
                    {item.hasDiscountMetadata && item.orig > 0 && <span className={s.orig}>{fmt(item.orig)}원</span>}
                    {item.hasDiscountMetadata && item.disc > 0 && <span className={s.disc}>-{item.disc}%</span>}
                  </div>
                  <div className={s.observationMeta}>
                    <span className={item.hasDiscountMetadata ? s.claimVerified : s.observedOnly}>
                      {item.recordLabel}
                    </span>
                    {item.unit && <span>{item.unit}</span>}
                    {formatLastUpdate(item.crawledAt) && <span>{formatLastUpdate(item.crawledAt)} 수집</span>}
                  </div>
                  {diff !== null && (
                    <div className={s.vs}>
                      시세 평균 대비 <em className={diff <= 0 ? s.cheap : s.expensive}>{diff <= 0 ? fmt(diff) : `+${fmt(diff)}`}원</em>
                    </div>
                  )}
                  <div className={s.cardBottom}>
                    <span className={s.event}>{item.event}</span>
                    <div className={s.cardActions}>
                      {onlineUrl && (
                        <a
                          href={onlineUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          className={s.mallMini}
                          onClick={e => e.stopPropagation()}
                          title={`${MART_ONLINE_URLS[activeMart]?.name}에서 보기`}
                        >
                          🛍️
                        </a>
                      )}
                       <button
                         className={s.cartMini}
                         onClick={(e) => {
                           e.stopPropagation();
                           addToShoppingList({ ...productData, icon: '🏪' });
                           addToast(`${item.name}을(를) 장보기 리스트에 추가했어요`, 'success');
                         }}
                         title="장보기에 추가"
                       >
                         🛒
                       </button>
                       <button
                         className={s.cartMini}
                         onClick={(e) => {
                           e.stopPropagation();
                           toggleWishlist(productData);
                         }}
                         title={fav ? '찜 해제' : '찜하기'}
                       >
                         <Heart size={14} fill={fav ? 'currentColor' : 'none'} />
                       </button>
                     </div>
                   </div>
                  <div className={s.validity}>{itemPeriod || '기간 정보 없음'}</div>
                </div>
              );
            })}
          </div>
        </>
      )}

      {/* ===== COMPARE TABLE ===== */}
      {mode === 'compare' && (
        <div className={s.compareSection}>
          <h3 className={s.compareTitle}>⚖️ 이마트 · 홈플러스 · 롯데마트 가격 비교</h3>
          <p className={s.compareDesc}>동일 상품을 한눈에 비교하세요. 최저가 마트가 강조 표시됩니다.</p>

          {commonProducts.length > 0 ? (
            <div className={s.compareTableWrap}>
              <table className={s.compareTable}>
                <thead>
                  <tr>
                    <th className={s.compareThProduct}>상품명</th>
                    {COMPARE_MARTS.map(key => {
                      const m = MARTS.find(mart => mart.key === key);
                      return (
                        <th key={key} className={s.compareTh}>
                          <span className={s.compareMartDot} style={{ background: m?.color }} />
                          {m?.name || key}
                        </th>
                      );
                    })}
                    <th className={s.compareTh}>최저가</th>
                  </tr>
                </thead>
                <tbody>
                  {commonProducts.map(({ name, marts: martPrices }) => {
                    const prices = COMPARE_MARTS
                      .filter(key => martPrices[key])
                      .map(key => ({ key, sale: safePrice(martPrices[key]?.sale) }))
                      .filter(p => p.sale > 0);
                    const lowestPrice = prices.length > 0 ? Math.min(...prices.map(p => p.sale)) : 0;
                    const lowestMartInfo = prices.length > 0
                      ? MARTS.find(m => m.key === prices.find(p => p.sale === lowestPrice)?.key)
                      : null;
                    return (
                      <tr key={name} className={s.compareTr}>
                        <td className={s.compareTdProduct}>{name}</td>
                        {COMPARE_MARTS.map(key => {
                          const item = martPrices[key];
                          const price = item ? safePrice(item.sale) : 0;
                          const isLowest = item && price > 0 && price === lowestPrice;
                          return (
                            <td
                              key={key}
                              className={`${s.compareTd} ${isLowest ? s.compareTdLowest : ''} ${item ? s.compareTdClickable : ''}`}
                              onClick={() => {
                                if (item) {
                                  const mInfo = MARTS.find(m => m.key === key);
                                  setSaleDetail({
                                    ...item,
                                    martKey: key,
                                    martName: mInfo?.name || item.mart,
                                    period: formatItemPeriod(item) || '기간 미제공 · 최근 가격 관측',
                                  });
                                }
                              }}
                            >
                              {item && price > 0 ? (
                                <>
                                  <span className={s.compareCellPrice}>{fmt(price)}원</span>
                                  {isLowest && <span className={s.compareCellBadge}>🏆</span>}
                                </>
                              ) : (
                                <span className={s.compareCellEmpty}>—</span>
                              )}
                            </td>
                          );
                        })}
                        <td className={s.compareTdBest}>
                          {lowestMartInfo && (
                            <span className={s.compareBestMart} style={{ color: lowestMartInfo.color }}>
                              {lowestMartInfo.name}
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className={s.emptyState}>
              <div className={s.emptyIcon}>⚖️</div>
              <p className={s.emptyTitle}>비교 가능한 동일 상품이 없습니다</p>
              <p className={s.emptyDesc}>
                각 마트에서 동일한 상품이 세일 중일 때 비교 결과가 표시됩니다.
              </p>
            </div>
          )}
        </div>
      )}

      {saleDetail && (
        <ProductDetailModal
          product={saleDetail}
          onClose={() => setSaleDetail(null)}
          mode="preview"
        />
      )}
    </div>
  );
}
