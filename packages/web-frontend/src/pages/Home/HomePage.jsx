import { useState, useRef, useCallback, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, X, TrendingUp, TrendingDown, Minus, ArrowRight, Heart, Clock, MapPin, RefreshCw } from 'lucide-react';
import { MARTS } from '../../utils/constants';
import { fmt } from '../../utils/helpers';
import { searchService } from '../../services/searchService';
import useStore from '../../stores/appStore';
import useModalStore from '../../stores/modalStore';
import useCartStore from '../../stores/cartStore';
import useAbortController from '../../hooks/useAbortController';
import EmptyState from '../../components/common/EmptyState';
import TrustBadge from '../../components/common/TrustBadge';
import PriceGauge from '../../components/common/PriceGauge';
import s from './HomePage.module.css';

const CATEGORIES = [
  { icon: '🥩', name: '식품',   path: '/price' },
  { icon: '🏪', name: '마트',   path: '/mart' },
  { icon: '⛽', name: '주유소', path: '/local' },
  { icon: '🔥', name: '핫딜',   path: '/hotdeal' },
];

const DEFAULT_COORDS = { lat: 37.4004, lng: 127.1055 };

function highlightMatch(text, query) {
  if (!query || !text) return text;
  const idx = text.toLowerCase().indexOf(query.toLowerCase());
  if (idx === -1) return text;
  return <>{text.slice(0, idx)}<strong>{text.slice(idx, idx + query.length)}</strong>{text.slice(idx + query.length)}</>;
}

function normalizeMartItems(data) {
  const raw = Array.isArray(data) ? data : data?.items || data?.data || [];
  const list = Array.isArray(raw) ? raw : [];
  return list.map(d => ({
    name: d.name || d.title || '',
    sale: d.price ?? d.sale ?? d.sale_price ?? 0,
    orig: d.original_price ?? d.orig ?? d.origin_price ?? 0,
    disc: d.discount_rate ?? d.disc ?? d.discount ?? 0,
    event: d.event || d.promotion || '할인',
  }));
}

function SectionError({ onRetry, message }) {
  return (
    <div className={s.sectionError} role="status" aria-live="polite">
      <p>{message || '백엔드 연결이 끊겼습니다. 잠시 후 다시 시도해 주세요.'}</p>
      {onRetry && (
        <button className={s.retryBtn} onClick={onRetry}>
          <RefreshCw size={14} /> 재연결
        </button>
      )}
    </div>
  );
}

function SectionEmpty({ title, hint, actionLabel, onAction }) {
  return (
    <div className={s.sectionError} role="status" aria-live="polite">
      <p><strong>{title || '아직 표시할 데이터가 없어요'}</strong></p>
      {hint && <p style={{ fontSize: '.85rem', color: 'var(--text3)', margin: 0 }}>{hint}</p>}
      {onAction && actionLabel && (
        <button className={s.retryBtn} onClick={onAction}>
          {actionLabel}
        </button>
      )}
    </div>
  );
}

function SkeletonCard({ className }) {
  return <div className={`${s.skeleton} ${className || ''}`}><div className={s.shimmer} /></div>;
}

function SkeletonRow() {
  return <div className={`${s.skeleton} ${s.skeletonRow}`}><div className={s.shimmer} /></div>;
}

export default function HomePage() {
  const navigate = useNavigate();
  const { openMartModal, openHotdealModal, openProductModal, openProductDetailModal, openGasStationModal } = useModalStore();
  const {
    setSelectedProduct,
    favorites, addFavorite, removeFavorite, isFavorite,
    recentSearches, addRecentSearch, clearRecentSearches,
    addToShoppingList, addToast, setLocation,
    savedLocation, setSavedLocation,
    hotdealerMode,
  } = useStore();
  const addCartItem = useCartStore((st) => st.addItem);

  const [query, setQuery] = useState('');
  const [acOpen, setAcOpen] = useState(false);
  const [acKeywords, setAcKeywords] = useState([]);
  const [acProducts, setAcProducts] = useState([]);
  const [totalKeywords, setTotalKeywords] = useState(0);
  const [totalProducts, setTotalProducts] = useState(0);
  const [martTab, setMartTab] = useState('emart');
  const inputRef = useRef(null);
  const debounceRef = useRef(null);

  const [products, setProducts] = useState([]);
  const [categorySummary, setCategorySummary] = useState([]);
  const [hotdeals, setHotdeals] = useState([]);
  const [fashionDeals, setFashionDeals] = useState([]);
  const [martDeals, setMartDeals] = useState({});
  const [communityPosts, setCommunityPosts] = useState([]);
  const [gasStations, setGasStations] = useState([]);
  const [trending, setTrending] = useState([]);
  const [trendingKeywords, setTrendingKeywords] = useState([]);

  // 섹션별 로딩/에러 상태
  const [sectionLoading, setSectionLoading] = useState({
    products: true, hotdeals: true, community: true, gas: true, trending: true, fashion: true,
  });
  const [sectionError, setSectionError] = useState({
    products: false, hotdeals: false, community: false, gas: false, trending: false, fashion: false,
  });

  const [coords, setCoords] = useState(null);
  const [martLoading, setMartLoading] = useState(false);
  const [martError, setMartError] = useState(false);

  const getMainSignal = useAbortController();
  const getMartSignal = useAbortController();

  // 1) GPS 위치 연동 — savedLocation 우선, 없으면 GPS
  useEffect(() => {
    if (savedLocation?.lat && savedLocation?.lng) {
      const c = { lat: savedLocation.lat, lng: savedLocation.lng };
      setCoords(c);
      setLocation(c.lat, c.lng);
      return;
    }
    if (!navigator.geolocation) {
      setCoords(DEFAULT_COORDS);
      setLocation(DEFAULT_COORDS.lat, DEFAULT_COORDS.lng);
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const c = { lat: pos.coords.latitude, lng: pos.coords.longitude };
        setCoords(c);
        setLocation(c.lat, c.lng);
      },
      () => {
        setCoords(DEFAULT_COORDS);
        setLocation(DEFAULT_COORDS.lat, DEFAULT_COORDS.lng);
      },
      { timeout: 5000, maximumAge: 300000 }
    );
  }, [setLocation, savedLocation]);

  // 2) API 병렬 최적화 — /api/dashboard 통합 + 나머지 개별 요청
  const fetchAllData = useCallback((loc, signal) => {
    const gasQuery = loc ? `lat=${loc.lat}&lng=${loc.lng}&sort=price_asc` : 'sort=price_asc';
    const readJson = async (url) => {
      const response = await fetch(url, { signal });
      const body = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(body?.detail || body?.message || `HTTP ${response.status}`);
      }
      return body;
    };

    setSectionLoading({ products: true, hotdeals: true, community: true, gas: true, trending: true, fashion: true });
    setSectionError({ products: false, hotdeals: false, community: false, gas: false, trending: false, fashion: false });

    Promise.allSettled([
      readJson('/api/dashboard'),
      readJson('/api/posts?post_type=hotdeal&per_page=5'),
      readJson(`/api/gas/nearby?${gasQuery}`),
      readJson('/api/hotdeals?category=fashion&per_page=6'),
    ]).then(([dashRes, postRes, gasRes, fashionRes]) => {
      // 대시보드 통합 응답 (hotdeals + category_summary + recent_products + trending_keywords)
      if (dashRes.status === 'fulfilled' && dashRes.value?.data) {
        const d = dashRes.value.data;
        setHotdeals(d.hotdeals || []);
        setCategorySummary(d.category_summary || []);
        setProducts(d.recent_products || []);
        setTrending(d.trending_keywords || []);
        setTrendingKeywords(d.trending_keywords || []);
      } else {
        setSectionError(prev => ({ ...prev, hotdeals: true, products: true, trending: true }));
      }
      setSectionLoading(prev => ({ ...prev, hotdeals: false, products: false, trending: false }));

      // 패션 핫딜
      if (fashionRes.status === 'fulfilled') {
        setFashionDeals(fashionRes.value.data || []);
      } else {
        setSectionError(prev => ({ ...prev, fashion: true }));
      }
      setSectionLoading(prev => ({ ...prev, fashion: false }));

      // 커뮤니티
      if (postRes.status === 'fulfilled') {
        setCommunityPosts(postRes.value.data || []);
      } else {
        setSectionError(prev => ({ ...prev, community: true }));
      }
      setSectionLoading(prev => ({ ...prev, community: false }));

      // 주유소
      if (gasRes.status === 'fulfilled') {
        setGasStations(gasRes.value.data || []);
      } else {
        setGasStations([]);
        setSectionError(prev => ({ ...prev, gas: true }));
      }
      setSectionLoading(prev => ({ ...prev, gas: false }));
    });
  }, []);

  useEffect(() => {
    if (coords) {
      const signal = getMainSignal();
      fetchAllData(coords, signal);
    }
  }, [coords, fetchAllData, getMainSignal]);

  // 5) 마트 데이터 정규화
  const fetchMart = useCallback((tab, signal) => {
    setMartLoading(true);
    setMartError(false);
    fetch(`/api/marts/${tab}/promotions`, { signal }).then(r => r.json())
      .then(res => {
        const items = normalizeMartItems(res.data ?? res);
        setMartDeals(prev => ({ ...prev, [tab]: items }));
      })
      .catch(err => {
        if (err.name !== 'AbortError') setMartError(true);
      })
      .finally(() => setMartLoading(false));
  }, []);

  useEffect(() => {
    const signal = getMartSignal();
    fetchMart(martTab, signal);
  }, [martTab, fetchMart, getMartSignal]);

  // 자동완성 API (200ms 디바운스)
  const fetchAutocomplete = useCallback((value) => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!value || value.length < 1) {
      setAcKeywords([]);
      setAcProducts([]);
      setTotalKeywords(0);
      setTotalProducts(0);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      try {
        const res = await searchService.autocomplete(value);
        const d = res.data || {};
        setAcKeywords(d.keywords || []);
        setAcProducts(d.products || []);
        setTotalKeywords(d.total_keyword_count || 0);
        setTotalProducts(d.total_product_count || 0);
      } catch {
        setAcKeywords([]);
        setAcProducts([]);
      }
    }, 200);
  }, []);

  useEffect(() => {
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, []);

  const handleKeywordClick = useCallback((kw) => {
    addRecentSearch(kw.word);
    searchService.trackKeyword(kw.id);
    setQuery('');
    setAcOpen(false);
    setAcKeywords([]);
    setAcProducts([]);

    // Prioritize product name match: if products exist in autocomplete, go to search
    if (acProducts.length > 0) {
      navigate(`/search?q=${encodeURIComponent(kw.word)}`);
    } else if (kw.suggested_action === 'category_page' && kw.category_id && kw.category_path?.toLowerCase().includes(kw.word?.toLowerCase?.().slice(0, 2))) {
      navigate(`/price/category/${kw.category_id}`);
    } else {
      navigate(`/search?q=${encodeURIComponent(kw.word)}`);
    }
  }, [navigate, addRecentSearch]);

  const handleProductClick = useCallback((p) => {
    if (p.id) searchService.trackKeyword(p.id);
    setQuery('');
    setAcOpen(false);
    setAcKeywords([]);
    setAcProducts([]);

    const action = p.suggested_action || 'price_page';
    switch (action) {
      case 'mart_modal':
        openMartModal(p);
        break;
      case 'hotdeal_modal':
        openHotdealModal(p);
        break;
      case 'product_modal':
        openProductModal(p);
        break;
      case 'price_page':
      default:
        navigate(`/price/${p.id}`);
        break;
    }
  }, [navigate, openMartModal, openHotdealModal, openProductModal]);

  const selectProduct = useCallback((p) => {
    setSelectedProduct(p);
    addRecentSearch(p.name);
    setQuery('');
    setAcOpen(false);
    navigate(`/price/${p.id}`);
  }, [navigate, setSelectedProduct, addRecentSearch]);

  const quickTags = ['양파', '삼겹살', '계란', '휘발유', '사과', '우유'];

  const activeMartInfo = useMemo(() => MARTS.find(m => m.key === martTab), [martTab]);
  const activeMartItems = useMemo(() => martDeals[martTab] || [], [martDeals, martTab]);
  const topGas = useMemo(() =>
    [...gasStations].sort((a, b) => (a.gasoline || Infinity) - (b.gasoline || Infinity)).slice(0, 4),
    [gasStations]
  );

  // 3) 오늘의 핫딜 TOP 3 — 할인율 기준
  const topHotdeals = useMemo(() =>
    [...hotdeals]
      .map(d => {
        const discountRate = d.price && d.origPrice && d.origPrice > 0
          ? Math.round((1 - d.price / d.origPrice) * 100) : 0;
        return { ...d, discountRate };
      })
      .sort((a, b) => b.discountRate - a.discountRate)
      .slice(0, 3),
    [hotdeals]
  );

  return (
    <div>
      {/* 히어로 */}
      <section className={s.hero}>
        <div className={s.heroBg} />
        <div className={s.heroContent}>
          <h1 className={s.title}>이 가격,<br />진짜 싼 건가요?</h1>
          <p className={s.sub}>정부 공식 물가 + 마트 전단 데이터로<br />지금 사도 될지 알려드립니다</p>

          {coords && (
            <div className={s.locationBadge}>
              <MapPin size={12} />
              <span>{coords === DEFAULT_COORDS ? '기본 위치 (판교)' : '내 위치 기준'}</span>
            </div>
          )}

          <div className={s.search}>
            <div className={s.searchWrap}>
              <Search size={20} className={s.searchIcon} />
              <input
                ref={inputRef}
                className={s.searchInput}
                value={query}
                onChange={(e) => { setQuery(e.target.value); setAcOpen(true); fetchAutocomplete(e.target.value); }}
                onFocus={() => setAcOpen(true)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && query.trim()) {
                    e.preventDefault();
                    addRecentSearch(query.trim());
                    setAcOpen(false);
                    navigate(`/search?q=${encodeURIComponent(query.trim())}`);
                  }
                }}
                placeholder="무엇을 찾으시나요?"
                autoComplete="off"
                aria-label="상품 검색"
              />
              {query && (
                <button className={s.searchClear} onClick={() => { setQuery(''); setAcOpen(false); setAcKeywords([]); setAcProducts([]); }}>
                  <X size={16} />
                </button>
              )}
            </div>

            {acOpen && (acKeywords.length > 0 || acProducts.length > 0) && (
              <div className={s.acList}>
                {acKeywords.length > 0 && (
                  <>
                    <div className={s.acSectionLabel}>키워드</div>
                    {acKeywords.map(kw => (
                      <div key={`kw-${kw.id}`} className={s.acItem} onClick={() => handleKeywordClick(kw)}>
                        <span className={s.acIcon}>🔍</span>
                        <div className={s.acInfo}>
                          <div className={s.acName}>{highlightMatch(kw.word, query)}</div>
                          {kw.matched_synonym && <div className={s.acHint}>← &ldquo;{kw.matched_synonym}&rdquo; 포함</div>}
                          <div className={s.acCat}>{kw.category_path}</div>
                        </div>
                      </div>
                    ))}
                  </>
                )}
                {acKeywords.length > 0 && acProducts.length > 0 && <div className={s.acDivider} />}
                {acProducts.length > 0 && (
                  <>
                    <div className={s.acSectionLabel}>상품</div>
                    {acProducts.map(p => (
                      <div key={`p-${p.id}`} className={s.acItem} onClick={() => handleProductClick(p)}>
                        <span className={s.acIcon}>{p.icon || '📦'}</span>
                        <div className={s.acInfo}>
                          <div className={s.acName}>{highlightMatch(p.name, query)}</div>
                          <div className={s.acCat}>{p.unit} {p.current_price ? `· ${fmt(p.current_price)}원` : ''}</div>
                        </div>
                      </div>
                    ))}
                  </>
                )}
                {(totalKeywords > 3 || totalProducts > 5) && (
                  <div className={s.acFooter} onClick={() => { addRecentSearch(query); navigate(`/search?q=${encodeURIComponent(query)}`); setQuery(''); setAcOpen(false); }}>
                    🔍 &ldquo;{query}&rdquo; 전체 검색 결과 보기 ({totalKeywords + totalProducts}건)
                  </div>
                )}
              </div>
            )}

            {acOpen && query.length > 0 && acKeywords.length === 0 && acProducts.length === 0 && (
              <div className={s.acList}>
                <div className={s.acEmpty}>
                  😅 &ldquo;{query}&rdquo;에 대한 결과가 없습니다.
                  {trendingKeywords.length > 0 && (
                    <div className={s.acTrending}>
                      {trendingKeywords.map(t => (
                        <button key={t.word} className={s.acTrendBtn} onClick={() => { setQuery(t.word); fetchAutocomplete(t.word); }}>
                          🔥 {t.word}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}

            {acOpen && query.length === 0 && (
              <div className={s.trending}>
                {recentSearches.length > 0 && (
                  <>
                    <div className={s.trendTitleWrap}>
                      <span className={s.trendTitle}><Clock size={12} /> 최근 검색</span>
                      <button className={s.trendClear} onClick={clearRecentSearches}>지우기</button>
                    </div>
                    <div className={s.trendList}>
                      {recentSearches.slice(0, 5).map(rs => (
                        <button key={rs.timestamp} className={s.trendItem} onClick={() => {
                          setQuery(rs.query);
                          setAcOpen(true);
                          fetchAutocomplete(rs.query);
                        }}>
                          <Clock size={12} /> {rs.query}
                        </button>
                      ))}
                    </div>
                  </>
                )}
                {trendingKeywords.length > 0 && (
                  <>
                    <span className={s.trendTitle}>🔥 인기 검색어</span>
                    <div className={s.trendList}>
                      {trendingKeywords.map((t, i) => (
                        <button key={t.word} className={s.trendItem} onClick={() => {
                          setQuery(t.word);
                          fetchAutocomplete(t.word);
                        }}>
                          <span className={s.trendRank}>{i + 1}</span> {t.icon || '🔥'} {t.word}
                        </button>
                      ))}
                    </div>
                  </>
                )}
                {trendingKeywords.length === 0 && trending.length > 0 && (
                  <>
                    <span className={s.trendTitle}>🔥 인기 검색어</span>
                    <div className={s.trendList}>
                      {trending.map((t, i) => (
                        <button key={typeof t === 'string' ? t : t.word || i} className={s.trendItem} onClick={() => {
                          const word = typeof t === 'string' ? t : t.word;
                          setQuery(word);
                          fetchAutocomplete(word);
                        }}>
                          <span className={s.trendRank}>{i + 1}</span> {typeof t === 'string' ? t : t.word}
                        </button>
                      ))}
                    </div>
                  </>
                )}
              </div>
            )}
          </div>

          <div className={s.tags}>
            {quickTags.map(t => (
              <button key={t} className={s.tag} onClick={() => {
                setQuery(t);
                setAcOpen(true);
                fetchAutocomplete(t);
              }}>{t}</button>
            ))}
          </div>

          {recentSearches.length > 0 && (
            <div className={s.recentChips}>
              {recentSearches.slice(0, 6).map(rs => (
                <button key={rs.timestamp} className={s.recentChip} onClick={() => {
                  setQuery(rs.query);
                  setAcOpen(true);
                  fetchAutocomplete(rs.query);
                }}>
                  <Clock size={11} /> {rs.query}
                </button>
              ))}
            </div>
          )}
        </div>
      </section>

      {/* 카테고리 퀵 링크 — 핵심 4개 + 더보기 */}
      <section className={s.sec}>
        <h2 className={s.secTitle}>카테고리</h2>
        <p className={s.secDesc}>원하는 정보에 3클릭 이내로 접근하세요</p>
        <div className={s.catGrid}>
          {CATEGORIES.map(cat => (
            <button key={cat.name} className={s.catLink} onClick={() => navigate(cat.path)}>
              <span className={s.catIcon}>{cat.icon}</span>
              <span className={s.catName}>{cat.name}</span>
            </button>
          ))}
          <button className={`${s.catLink} ${s.catMore}`} onClick={() => navigate('/community')}>
            <span className={s.catIcon}>➕</span>
            <span className={s.catName}>더보기</span>
          </button>
        </div>
      </section>

      {/* 오늘의 핫딜 TOP 3 — 할인율 기준 대형 카드 */}
      <section className={s.sec}>
        <div className={s.secHead}>
          <div>
            <h2 className={s.secTitle}>🔥 오늘의 핫딜 TOP 3</h2>
            <p className={s.secDesc}>할인율 기준 실시간 최고의 딜</p>
          </div>
          <button className={s.secMore} onClick={() => navigate('/hotdeal')}>전체보기 <ArrowRight size={14} /></button>
        </div>
        {sectionLoading.hotdeals ? (
          <div className={s.topDealGrid}>
            {[0, 1, 2].map(i => <SkeletonCard key={i} className={s.skeletonTopDeal} />)}
          </div>
        ) : sectionError.hotdeals ? (
          <SectionError onRetry={() => fetchAllData(coords)} message="핫딜 백엔드 연결이 끊겼습니다." />
        ) : topHotdeals.length === 0 ? (
          <SectionEmpty
            title="오늘 표시할 핫딜이 아직 모이지 않았어요"
            hint="크롤러가 첫 데이터를 적재 중일 수 있어요. 잠시 후 새로고침해 주세요."
            actionLabel="전체 핫딜 보기"
            onAction={() => navigate('/hotdeal')}
          />
        ) : (
          <div className={s.topDealGrid}>
            {topHotdeals.map((d, i) => {
              const ratio = d.price && d.origPrice ? d.price / d.origPrice : null;
              let tierClass = '';
              if (ratio !== null) {
                if (ratio <= 0.5) tierClass = s.ultra;
                else if (ratio <= 0.65) tierClass = s.great;
                else if (ratio <= 0.8) tierClass = s.good;
                else tierClass = s.ok;
              }
              return (
                <div key={d.id} className={s.topDealCard} onClick={() => {
                  navigate(`/hotdeal?id=${encodeURIComponent(d.id)}&modal=true`);
                  openProductDetailModal({
                    id: d.id,
                    name: d.title,
                    price: d.price,
                    original_price: d.origPrice,
                    source: d.source,
                    source_type: 'hotdeal',
                    image: d.thumb,
                    source_url: d.url,
                    period: d.time,
                    hotVotes: d.hotVotes,
                    coldVotes: d.coldVotes,
                    comments: d.comments,
                    views: d.views,
                    discountRate: d.discountRate,
                  });
                }}>
                  <span className={s.topDealRank}>TOP {i + 1}</span>
                  <div className={s.dealHead}>
                    <span className={s.dealSource}>{d.source}</span>
                    <span className={s.dealTime}>{d.time}</span>
                  </div>
                  <div className={s.topDealTitle}>{d.title}</div>
                  <div className={s.dealBottom}>
                    <span className={s.dealPrice}>{d.price ? `${fmt(d.price)}원` : ''}</span>
                    {d.discountRate > 0 && (
                      <span className={`${s.dealBadge} ${tierClass}`}>
                        {d.discountRate}% 할인
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* 오늘의 물가 — 카테고리별 집계 */}
      <section className={s.sec}>
        <div className={s.secHead}>
          <div>
            <h2 className={s.secTitle}>오늘의 물가</h2>
            <p className={s.secDesc}>카테고리별 평균 · 최저가 비교</p>
          </div>
          <button className={s.secMore} onClick={() => navigate('/price')}>전체보기 <ArrowRight size={14} /></button>
        </div>
        {sectionLoading.products ? (
          <div className={s.priceGrid}>
            {[...Array(8)].map((_, i) => <SkeletonCard key={i} className={s.skeletonPrice} />)}
          </div>
        ) : sectionError.products ? (
          <SectionError onRetry={() => fetchAllData(coords)} message="물가 백엔드 연결이 끊겼습니다." />
        ) : categorySummary.length > 0 && categorySummary.some(c => c.avg_price > 0) ? (
          <div className={s.priceGrid}>
            {categorySummary.slice(0, 8).map(cat => (
              <div key={cat.category_id} className={s.priceCard} onClick={() => navigate(`/price/category/${cat.category_id}`)}>
                <div className={s.priceCardTop}>
                  <span className={s.priceCardIcon}>{cat.icon}</span>
                  {cat.count > 0 && (
                    <span className={s.catCount}>{cat.count}개 품목</span>
                  )}
                </div>
                <div className={s.priceCardName}>{cat.name}</div>
                <div className={s.priceCardPrice}>
                  {cat.avg_price > 0 ? `평균 ${fmt(cat.avg_price)}원` : '아직 적재 전'}
                </div>
                {cat.min_price > 0 && (
                  <div className={s.catMinPrice}>
                    최저 {fmt(cat.min_price)}원
                    {cat.min_source && <span className={s.catMinSource}> ({cat.min_source})</span>}
                  </div>
                )}
                {cat.unit && <div className={s.catUnit}>/{cat.unit}</div>}
              </div>
            ))}
          </div>
        ) : categorySummary.length > 0 ? (
          <SectionEmpty
            title="모든 카테고리의 가격이 아직 적재되지 않았어요"
            hint="크롤링 → AI 매칭 파이프가 첫 가격 데이터를 수집 중입니다. 잠시 후 새로고침해 주세요."
            actionLabel="전체 물가 페이지로 이동"
            onAction={() => navigate('/price')}
          />
        ) : (
          <div className={s.priceGrid}>
            {products.filter(p => {
              const price = p.cur ?? p.price ?? p.sale_price ?? p.current_price ?? 0;
              return price > 0;
            }).slice(0, 8).map(p => {
              const price = p.cur ?? p.price ?? p.sale_price ?? p.current_price ?? 0;
              const avg = p.avg ?? price;
              const diff = price - avg;
              const pct = avg > 0 ? ((diff / avg) * 100).toFixed(1) : '0.0';
              let trend = 'same', icon = <Minus size={12} />;
              if (avg > 0 && diff < -avg * 0.03) { trend = 'down'; icon = <TrendingDown size={12} />; }
              else if (avg > 0 && diff > avg * 0.03) { trend = 'up'; icon = <TrendingUp size={12} />; }
              const fav = isFavorite(p.id);
              return (
                <div key={p.id} className={s.priceCard} onClick={() => selectProduct(p)}>
                  <div className={s.priceCardTop}>
                    <span className={s.priceCardIcon}>{p.icon || '📦'}</span>
                    <div className={s.priceCardBtns}>
                      <button
                        className={s.cartSmall}
                        onClick={(e) => {
                          e.stopPropagation();
                          addToShoppingList({ ...p, productId: p.id, price, unit: p.unit, icon: p.icon });
                          addToast(`${p.name}을(를) 장보기 리스트에 추가했어요`, 'success');
                        }}
                        title="장보기에 추가"
                      >
                        🛒
                      </button>
                      <button
                        className={`${s.favBtn} ${fav ? s.favActive : ''}`}
                        onClick={(e) => { e.stopPropagation(); fav ? removeFavorite(p.id) : addFavorite(p.id); }}
                        title={fav ? '관심 해제' : '관심 등록'}
                      >
                        <Heart size={14} fill={fav ? 'currentColor' : 'none'} />
                      </button>
                    </div>
                  </div>
                  <div className={s.priceCardName}>{p.name} ({p.unit})</div>
                  <div className={s.priceCardPrice}>
                    {price > 0 ? `${fmt(price)}원` : '가격 미정'}
                  </div>
                  {price > 0 && avg > 0 && (
                    <span className={`${s.change} ${s[trend]}`}>{icon} {trend !== 'same' ? `${Math.abs(pct)}%` : '→'}</span>
                  )}
                </div>
              );
            })}
            {products.filter(p => (p.cur ?? p.price ?? p.sale_price ?? p.current_price ?? 0) > 0).length === 0 && (
              <SectionEmpty
                title="물가 데이터가 아직 없어요"
                hint="크롤러/매칭 파이프가 첫 적재 중일 수 있어요."
                actionLabel="전체 물가 페이지로 이동"
                onAction={() => navigate('/price')}
              />
            )}
          </div>
        )}
      </section>

      {/* 🛍️ 패션 할인 */}
      {(sectionLoading.fashion || fashionDeals.length > 0) && (
        <section className={s.sec}>
          <div className={s.secHead}>
            <div>
              <h2 className={s.secTitle}>🛍️ 패션 할인</h2>
              <p className={s.secDesc}>무신사 · 지오다노 등 인기 패션 할인</p>
            </div>
            <button className={s.secMore} onClick={() => navigate('/hotdeal', { state: { category: 'fashion' } })}>전체보기 <ArrowRight size={14} /></button>
          </div>
          {sectionLoading.fashion ? (
            <div className={s.fashionGrid}>
              {[...Array(4)].map((_, i) => <SkeletonCard key={i} className={s.skeletonMart} />)}
            </div>
          ) : (
            <div className={s.fashionGrid}>
              {fashionDeals.slice(0, 6).map((d, i) => {
                const salePrice = d.price ?? d.sale_price ?? 0;
                const origPrice = d.origPrice ?? d.original_price ?? 0;
                const discRate = d.discountRate ?? d.discount_rate ?? d.discount_percent
                  ?? (origPrice > 0 && salePrice > 0 ? Math.round((1 - salePrice / origPrice) * 100) : 0);
                const source = d.source || d.store || d.platform || '';
                return (
                  <div key={d.id || i} className={s.fashionCard} onClick={() => {
                    if (d.detail_url || d.url) {
                      window.open(d.detail_url || d.url, '_blank', 'noopener');
                    } else {
                      navigate('/hotdeal', { state: { openDealId: d.id } });
                    }
                  }}>
                    {(d.image_url || d.thumb) && (
                      <div className={s.fashionImgWrap}>
                        <img src={d.image_url || d.thumb} alt={d.title || d.name} className={s.fashionImg} loading="lazy" onError={(e) => { e.target.style.display = 'none'; }} />
                      </div>
                    )}
                    <div className={s.fashionInfo}>
                      {source && <span className={s.fashionSource}>{source}</span>}
                      <div className={s.fashionName}>{d.title || d.name}</div>
                      <div className={s.fashionPrices}>
                        <span className={s.fashionSalePrice}>
                          {salePrice > 0 ? `${fmt(salePrice)}원` : '가격 미정'}
                        </span>
                        {origPrice > 0 && origPrice !== salePrice && (
                          <span className={s.fashionOrigPrice}>{fmt(origPrice)}원</span>
                        )}
                      </div>
                      {discRate > 0 && (
                        <span className={s.fashionDiscount}>-{discRate}%</span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      )}

      {/* 마트 세일 미리보기 */}
      <section className={s.sec}>
        <div className={s.secHead}>
          <div>
            <h2 className={s.secTitle}>🏪 이번 주 마트 세일</h2>
            <p className={s.secDesc}>이마트 · 홈플러스 · 롯데마트 · 코스트코</p>
          </div>
          <button className={s.secMore} onClick={() => navigate('/mart')}>전체보기 <ArrowRight size={14} /></button>
        </div>
        <div className={s.martTabs}>
          {MARTS.map(m => (
            <button
              key={m.key}
              className={`${s.martTab} ${martTab === m.key ? s.martTabActive : ''}`}
              onClick={() => setMartTab(m.key)}
            >
              <span className={s.martDot} style={{ background: m.color }} />
              {m.name}
            </button>
          ))}
        </div>
        {martLoading ? (
          <div className={s.martSaleGrid}>
            {[...Array(4)].map((_, i) => <SkeletonCard key={i} className={s.skeletonMart} />)}
          </div>
        ) : martError ? (
          <SectionError onRetry={() => fetchMart(martTab)} />
        ) : (
          <div className={s.martSaleGrid}>
            {activeMartItems.slice(0, 4).map((item, i) => (
              <div key={item.id || item.name || `mart-${i}`} className={s.martSaleCard} onClick={() => {
                const productData = { ...item, martKey: martTab, martName: activeMartInfo?.name };
                navigate(`/mart?mart=${encodeURIComponent(martTab)}&product=${encodeURIComponent(item.id || item.name)}`);
                openMartModal(productData);
              }}>
                <div className={s.martSaleName}>{item.name}</div>
                <div className={s.martSalePrices}>
                  <span className={s.martSalePrice}>{item.sale ? `${fmt(item.sale)}원` : '가격 미정'}</span>
                  {item.orig > 0 && <span className={s.martSaleOrig}>{fmt(item.orig)}원</span>}
                  {item.disc > 0 && <span className={s.martSaleDisc}>-{item.disc}%</span>}
                </div>
                <div className={s.martSaleBottom}>
                  <span className={s.martSaleEvent}>{activeMartInfo?.name} · {item.event}</span>
                  <button
                    className={s.cartSmall}
                    onClick={(e) => {
                      e.stopPropagation();
                      addToShoppingList({ ...item, icon: '🏪', martKey: martTab, martName: activeMartInfo?.name });
                      addToast(`${item.name}을(를) 장보기 리스트에 추가했어요`, 'success');
                    }}
                    title="장보기에 추가"
                  >
                    🛒
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* 주변 최저가 주유소 */}
      <section className={s.sec}>
        <div className={s.secHead}>
          <div>
            <h2 className={s.secTitle}>⛽ 주변 최저가 주유소</h2>
            <p className={s.secDesc}>현재 위치 기준 가까운 주유소</p>
          </div>
          <button className={s.secMore} onClick={() => navigate('/local')}>전체보기 <ArrowRight size={14} /></button>
        </div>
        {sectionLoading.gas ? (
          <div className={s.gasGrid}>
            {[...Array(4)].map((_, i) => <SkeletonRow key={i} />)}
          </div>
        ) : sectionError.gas ? (
          <SectionError onRetry={() => fetchAllData(coords)} />
        ) : topGas.length === 0 ? (
          <EmptyState
            title="주변 주유소 정보가 없습니다"
            description="위치 권한을 허용하면 주변 주유소를 찾을 수 있습니다."
          />
        ) : (
          <div className={s.gasGrid}>
            {topGas.map((g, i) => (
              <div key={g.id || g.name || `gas-${i}`} className={s.gasCard} onClick={() => openGasStationModal(g)} style={{ cursor: 'pointer' }}>
                <span className={s.gasRank}>{i + 1}</span>
                <div className={s.gasInfo}>
                  <div className={s.gasName}>{g.brand ? `${g.brand} ` : ''}{g.name}</div>
                  <div className={s.gasAddr}>{g.addr}</div>
                </div>
                <div className={s.gasPrices}>
                  {g.gasoline != null && <span className={s.gasPrice}>휘발유 {fmt(g.gasoline)}원</span>}
                  {g.diesel != null && <span className={s.gasPriceDiesel}>경유 {fmt(g.diesel)}원</span>}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* 커뮤니티 인기글 */}
      <section className={s.sec}>
        <div className={s.secHead}>
          <div>
            <h2 className={s.secTitle}>💬 커뮤니티 인기 게시글</h2>
            <p className={s.secDesc}>직접 발견한 할인을 공유하세요</p>
          </div>
          <button className={s.secMore} onClick={() => navigate('/community')}>전체보기 <ArrowRight size={14} /></button>
        </div>
        {sectionLoading.community ? (
          <div className={s.communityList}>
            {[...Array(5)].map((_, i) => <SkeletonRow key={i} />)}
          </div>
        ) : sectionError.community ? (
          <SectionError onRetry={() => fetchAllData(coords)} />
        ) : (
          <div className={s.communityList}>
            {communityPosts.slice(0, 5).map(p => (
              <div key={p.id} className={s.communityItem} onClick={() => navigate('/community', { state: { openPostId: p.id } })}>
                <span className={s.comCat}>{p.cat}</span>
                <div className={s.comBody}>
                  <div className={s.comTitle}>{p.title}</div>
                  <div className={s.comMeta}>
                    <span>{p.author}</span>
                    <span>{p.time}</span>
                    <span>👁️ {p.views}</span>
                    <span>💬 {p.commentData?.length || p.comments}</span>
                  </div>
                </div>
                {p.priceVsAvg !== null && (
                  <span className={`${s.comBadge} ${p.priceVsAvg < -20 ? s.cheap : ''}`}>
                    평균 대비 {p.priceVsAvg}%
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      {/* 판매자 신뢰 등급 — TrustBadge 3종 (공식/검증/주의) */}
      <section className={s.sec}>
      <div className={s.secHead}>
        <div>
          <h2 className={s.secTitle}>🛡️ 판매자 신뢰 등급</h2>
          <p className={s.secDesc}>공식·검증·주의 판매처를 한눈에 확인하세요</p>
        </div>
      </div>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', padding: '4px 0' }}>
        <TrustBadge kind="official" variant="detail" />
        <TrustBadge kind="verified" variant="detail" />
        <TrustBadge kind="caution" variant="detail" />
      </div>
      <div style={{ marginTop: 10, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <TrustBadge kind="official" variant="card" />
        <TrustBadge kind="verified" variant="card" />
        <TrustBadge kind="caution" variant="card" />
      </div>
      </section>

      {/* 핫딜러 모드 — ON 시 추가 가격 분석 레이어 노출 */}
      {hotdealerMode && (
      <section className={s.sec}>
        <div className={s.secHead}>
          <div>
            <h2 className={s.secTitle}>🔥 핫딜러 모드: 상세 가격 분석</h2>
            <p className={s.secDesc}>전문 핫딜러를 위한 심층 가격 정보</p>
          </div>
        </div>
        <PriceGauge product={{ current_low: 1290, p10: 1200, p50: 1600, p90: 2100 }} />
        <div style={{ marginTop: 8, fontSize: 13, color: '#888' }}>
          ※ 핫딜러 모드: 상세 가격 분위수, 최저가 트래킹, 알림 설정이 활성화됩니다.
        </div>
      </section>
      )}
    </div>
  );
}
