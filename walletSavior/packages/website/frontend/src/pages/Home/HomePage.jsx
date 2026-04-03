import { useState, useRef, useCallback, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, X, TrendingUp, TrendingDown, Minus, ArrowRight, Heart, Clock, MapPin, RefreshCw } from 'lucide-react';
import { MARTS } from '../../utils/constants';
import { fmt } from '../../utils/helpers';
import { searchService } from '../../services/searchService';
import useStore from '../../stores/appStore';
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

function SectionError({ onRetry }) {
  return (
    <div className={s.sectionError}>
      <p>데이터를 불러오지 못했습니다.</p>
      {onRetry && (
        <button className={s.retryBtn} onClick={onRetry}>
          <RefreshCw size={14} /> 다시 시도
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
  const {
    setSelectedProduct,
    favorites, addFavorite, removeFavorite, isFavorite,
    recentSearches, addRecentSearch, clearRecentSearches,
    addToShoppingList, addToast, setLocation,
  } = useStore();

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
  const [hotdeals, setHotdeals] = useState([]);
  const [martDeals, setMartDeals] = useState({});
  const [communityPosts, setCommunityPosts] = useState([]);
  const [gasStations, setGasStations] = useState([]);
  const [trending, setTrending] = useState([]);
  const [trendingKeywords, setTrendingKeywords] = useState([]);

  // 섹션별 로딩/에러 상태
  const [sectionLoading, setSectionLoading] = useState({
    products: true, hotdeals: true, community: true, gas: true, trending: true,
  });
  const [sectionError, setSectionError] = useState({
    products: false, hotdeals: false, community: false, gas: false, trending: false,
  });

  const [coords, setCoords] = useState(null);
  const [martLoading, setMartLoading] = useState(false);
  const [martError, setMartError] = useState(false);

  // 1) GPS 위치 연동
  useEffect(() => {
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
  }, [setLocation]);

  // 2) API 병렬 최적화 — Promise.allSettled, 위치 확정 후 실행
  const fetchAllData = useCallback((loc) => {
    const gasQuery = loc ? `lat=${loc.lat}&lng=${loc.lng}&sort=price_asc` : 'sort=price_asc';

    setSectionLoading({ products: true, hotdeals: true, community: true, gas: true, trending: true });
    setSectionError({ products: false, hotdeals: false, community: false, gas: false, trending: false });

    Promise.allSettled([
      fetch('/api/hotdeals?per_page=10').then(r => r.json()),
      fetch('/api/products/search?per_page=50').then(r => r.json()),
      fetch('/api/posts?board=hotdeal&per_page=5').then(r => r.json()),
      fetch(`/api/gas/nearby?${gasQuery}`).then(r => r.json()),
      fetch('/api/products/trending').then(r => r.json()),
      searchService.trending(8),
    ]).then(([dealRes, prodRes, postRes, gasRes, trendRes, trendApiRes]) => {
      // 핫딜 (우선 표시)
      if (dealRes.status === 'fulfilled') {
        setHotdeals(dealRes.value.data || []);
      } else {
        setSectionError(prev => ({ ...prev, hotdeals: true }));
      }
      setSectionLoading(prev => ({ ...prev, hotdeals: false }));

      // 물가 (우선 표시)
      if (prodRes.status === 'fulfilled') {
        setProducts(prodRes.value.data || []);
      } else {
        setSectionError(prev => ({ ...prev, products: true }));
      }
      setSectionLoading(prev => ({ ...prev, products: false }));

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
        setSectionError(prev => ({ ...prev, gas: true }));
      }
      setSectionLoading(prev => ({ ...prev, gas: false }));

      // 인기 검색어 (기존 /api/products/trending)
      if (trendRes.status === 'fulfilled') {
        setTrending(trendRes.value.data || []);
      } else {
        setSectionError(prev => ({ ...prev, trending: true }));
      }
      setSectionLoading(prev => ({ ...prev, trending: false }));

      // 인기 키워드 (새 API — 자동완성용)
      if (trendApiRes.status === 'fulfilled') {
        setTrendingKeywords(trendApiRes.value.data || []);
      }
    });
  }, []);

  useEffect(() => {
    if (coords) fetchAllData(coords);
  }, [coords, fetchAllData]);

  // 5) 마트 데이터 정규화
  const fetchMart = useCallback((tab) => {
    setMartLoading(true);
    setMartError(false);
    fetch(`/api/marts/${tab}/promotions`).then(r => r.json())
      .then(res => {
        const items = normalizeMartItems(res.data ?? res);
        setMartDeals(prev => ({ ...prev, [tab]: items }));
      })
      .catch(() => setMartError(true))
      .finally(() => setMartLoading(false));
  }, []);

  useEffect(() => { fetchMart(martTab); }, [martTab, fetchMart]);

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
    navigate(`/search?q=${encodeURIComponent(kw.word)}`);
  }, [navigate, addRecentSearch]);

  const handleProductClick = useCallback((p) => {
    setQuery('');
    setAcOpen(false);
    setAcKeywords([]);
    setAcProducts([]);
    navigate(`/price/${p.id}`);
  }, [navigate]);

  const selectProduct = useCallback((p) => {
    setSelectedProduct(p);
    addRecentSearch(p.name);
    setQuery('');
    setAcOpen(false);
    navigate(`/price/${p.id}`);
  }, [navigate, setSelectedProduct, addRecentSearch]);

  const quickTags = ['양파', '삼겹살', '계란', '휘발유', '사과', '우유'];

  const activeMartInfo = MARTS.find(m => m.key === martTab);
  const activeMartItems = martDeals[martTab] || [];
  const topGas = [...gasStations].sort((a, b) => (a.gasoline || Infinity) - (b.gasoline || Infinity)).slice(0, 4);

  // 3) 오늘의 핫딜 TOP 3 — 할인율 기준
  const topHotdeals = [...hotdeals]
    .map(d => {
      const discountRate = d.price && d.origPrice && d.origPrice > 0
        ? Math.round((1 - d.price / d.origPrice) * 100) : 0;
      return { ...d, discountRate };
    })
    .sort((a, b) => b.discountRate - a.discountRate)
    .slice(0, 3);

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
                placeholder="무엇을 찾으시나요?"
                autoComplete="off"
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
          <SectionError onRetry={() => fetchAllData(coords)} />
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
                <div key={d.id} className={s.topDealCard} onClick={() => navigate('/hotdeal', { state: { openDealId: d.id } })}>
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

      {/* 오늘의 물가 */}
      <section className={s.sec}>
        <h2 className={s.secTitle}>오늘의 물가</h2>
        <p className={s.secDesc}>정부 공시 + 마트 평균 기준</p>
        {sectionLoading.products ? (
          <div className={s.priceGrid}>
            {[...Array(8)].map((_, i) => <SkeletonCard key={i} className={s.skeletonPrice} />)}
          </div>
        ) : sectionError.products ? (
          <SectionError onRetry={() => fetchAllData(coords)} />
        ) : (
          <div className={s.priceGrid}>
            {products.slice(0, 8).map(p => {
              const diff = p.cur - p.avg;
              const pct = ((diff / p.avg) * 100).toFixed(1);
              let trend = 'same', icon = <Minus size={12} />;
              if (diff < -p.avg * 0.03) { trend = 'down'; icon = <TrendingDown size={12} />; }
              else if (diff > p.avg * 0.03) { trend = 'up'; icon = <TrendingUp size={12} />; }
              const fav = isFavorite(p.id);
              return (
                <div key={p.id} className={s.priceCard} onClick={() => selectProduct(p)}>
                  <div className={s.priceCardTop}>
                    <span className={s.priceCardIcon}>{p.icon}</span>
                    <div className={s.priceCardBtns}>
                      <button
                        className={s.cartSmall}
                        onClick={(e) => {
                          e.stopPropagation();
                          addToShoppingList({ productId: p.id, name: p.name, price: p.cur, unit: p.unit, icon: p.icon });
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
                  <div className={s.priceCardPrice}>{fmt(p.cur)}원</div>
                  <span className={`${s.change} ${s[trend]}`}>{icon} {trend !== 'same' ? `${Math.abs(pct)}%` : '→'}</span>
                </div>
              );
            })}
          </div>
        )}
      </section>

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
              <div key={i} className={s.martSaleCard} onClick={() => navigate('/mart')}>
                <div className={s.martSaleName}>{item.name}</div>
                <div className={s.martSalePrices}>
                  <span className={s.martSalePrice}>{fmt(item.sale)}원</span>
                  <span className={s.martSaleOrig}>{fmt(item.orig)}원</span>
                  <span className={s.martSaleDisc}>-{item.disc}%</span>
                </div>
                <div className={s.martSaleBottom}>
                  <span className={s.martSaleEvent}>{activeMartInfo?.name} · {item.event}</span>
                  <button
                    className={s.cartSmall}
                    onClick={(e) => {
                      e.stopPropagation();
                      addToShoppingList({ name: item.name, price: item.sale, icon: '🏪' });
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
        ) : (
          <div className={s.gasGrid}>
            {topGas.map((g, i) => (
              <div key={i} className={s.gasCard}>
                <span className={s.gasRank}>{i + 1}</span>
                <div className={s.gasInfo}>
                  <div className={s.gasName}>{g.name}</div>
                  <div className={s.gasAddr}>{g.addr}</div>
                </div>
                <span className={s.gasPrice}>{fmt(g.gasoline)}원</span>
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
    </div>
  );
}
