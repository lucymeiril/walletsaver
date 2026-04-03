import { useParams, useNavigate, useLocation } from 'react-router-dom';
import { useMemo, useState, useEffect } from 'react';
import { AreaChart, Area, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts';
import { Heart, Search, TrendingUp, TrendingDown, Minus, ChevronDown, ChevronUp } from 'lucide-react';
import { MARTS } from '../../utils/constants';
import { fmt } from '../../utils/helpers';
import useStore from '../../stores/appStore';
import useDebounce from '../../hooks/useDebounce';
import Spinner from '../../components/common/Spinner';
import s from './PricePage.module.css';

export default function PricePage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const { selectedProduct, setSelectedProduct, addFavorite, removeFavorite, isFavorite, addRecentSearch, addToShoppingList, addToast } = useStore();

  const [products, setProducts] = useState([]);
  const [productData, setProductData] = useState(null);
  const [chartData, setChartData] = useState([]);
  const [relatedHotdeals, setRelatedHotdeals] = useState([]);
  const [loading, setLoading] = useState(false);
  const [suggestions, setSuggestions] = useState([]);
  const [detailOpen, setDetailOpen] = useState(false);

  // Fetch all products for search
  useEffect(() => {
    fetch('/api/products/search?per_page=50').then(r => r.json())
      .then(res => setProducts(res.data || []))
      .catch(console.error);
  }, []);

  // Fetch product detail by ID
  useEffect(() => {
    if (!id) { setProductData(null); return; }
    setLoading(true);
    fetch(`/api/products/${id}`).then(r => r.json())
      .then(res => setProductData(res.data))
      .catch(err => {
        console.error(err);
        addToast('상품 정보를 불러오는데 실패했습니다', 'error');
      })
      .finally(() => setLoading(false));
  }, [id]);

  // Navigate from search query in location state
  useEffect(() => {
    const sq = location.state?.searchQuery;
    if (sq && products.length > 0) {
      const match = products.find(p => p.name?.includes(sq) || sq.includes(p.name));
      if (match) {
        setSelectedProduct(match);
        addRecentSearch(match.name);
        navigate(`/price/${match.id}`, { replace: true });
      }
    }
  }, [location.state, products]);

  const [searchQuery, setSearchQuery] = useState('');
  const [range, setRange] = useState(30);
  const [variantIdx, setVariantIdx] = useState(0);

  const debouncedQuery = useDebounce(searchQuery, 300);

  // 검색 자동완성 — DB 키워드 연동
  useEffect(() => {
    if (debouncedQuery.length < 2) { setSuggestions([]); return; }
    fetch(`/api/search/autocomplete?q=${encodeURIComponent(debouncedQuery)}&limit=10`)
      .then(r => r.json())
      .then(res => setSuggestions(res.data || []))
      .catch(() => setSuggestions([]));
  }, [debouncedQuery]);

  const searchResults = debouncedQuery.length > 0
    ? (suggestions.length > 0
      ? suggestions.map(sg => {
          const found = products.find(p => p.id === sg.id);
          return found || { id: sg.id, name: sg.text, cat: '', cur: null, icon: '🔍' };
        })
      : products.filter(p => p.name?.includes(debouncedQuery) || p.cat?.includes(debouncedQuery)))
    : [];

  const product = productData || (id ? products.find(p => p.id === Number(id)) : null) || selectedProduct;

  // Fetch price history from API
  useEffect(() => {
    if (!product) return;
    fetch(`/api/products/${product.id}/price-history?days=${range}`)
      .then(r => r.json())
      .then(res => setChartData(res.data || []))
      .catch(console.error);
  }, [product?.id, range]);

  // Fetch related hotdeals — 상품 카테고리에 맞는 핫딜 동적 연결
  useEffect(() => {
    if (!product) return;
    const CAT_MAP = { '농산물': 'food', '축산물': 'food', '수산물': 'food', '가공식품': 'food', '생활용품': 'living', '전자제품': 'electronics', '패션': 'fashion' };
    const hotdealCat = CAT_MAP[product.cat] || '';
    const catParam = hotdealCat ? `category=${hotdealCat}&` : '';
    fetch(`/api/hotdeals?${catParam}per_page=3`).then(r => r.json())
      .then(res => setRelatedHotdeals(res.data || []))
      .catch(console.error);
  }, [product?.id, product?.cat]);

  const handleSelectProduct = (p) => {
    setSelectedProduct(p);
    addRecentSearch(p.name);
    setSearchQuery('');
    navigate(`/price/${p.id}`);
  };

  // 엔터 누르면 검색 결과 페이지로 이동 (자동완성에서 선택 안 했을 때)
  const handleSearchKeyDown = (e) => {
    if (e.key === 'Enter' && searchQuery.trim()) {
      // 자동완성 결과 중 정확히 매칭되는 게 있으면 바로 이동
      const exact = searchResults.find(p => p.name === searchQuery.trim());
      if (exact) {
        handleSelectProduct(exact);
      } else {
        // 유사 매칭 목록을 보여주기 위해 검색 페이지로 이동
        navigate(`/search?q=${encodeURIComponent(searchQuery.trim())}`);
      }
    }
  };

  // 상품 상세 — 속성 변형은 DB에서 조회
  const variants = productData?.variants || [];
  const activeVariant = variants[variantIdx] || null;
  const displayAvg = product ? (activeVariant?.avg ?? product.avg) : 0;
  const displayCur = product ? (activeVariant?.cur ?? product.cur) : 0;
  const displayLow = product ? (activeVariant?.low ?? product.low) : 0;
  const displayHigh = product ? (activeVariant?.high ?? product.high) : 0;

  const ratio = displayAvg > 0 ? displayCur / displayAvg : 1;
  const diff = displayCur - displayAvg;

  const timing = useMemo(() => {
    if (ratio <= 0.7) return { cls: 'ultra', icon: '🔥', title: '역대급 기회!', desc: `현재 ${fmt(displayCur)}원은 평균보다 ${Math.round((1 - ratio) * 100)}% 저렴합니다.` };
    if (ratio <= 0.85) return { cls: 'great', icon: '💙', title: '좋은 가격이에요!', desc: `현재 ${fmt(displayCur)}원은 평균(${fmt(displayAvg)}원)보다 ${Math.round((1 - ratio) * 100)}% 저렴합니다.` };
    if (ratio <= 1.05) return { cls: 'good', icon: '✅', title: '지금 사도 괜찮아요!', desc: `현재 ${fmt(displayCur)}원은 평균(${fmt(displayAvg)}원) 수준입니다. (${diff >= 0 ? '+' : ''}${fmt(diff)}원)` };
    return { cls: 'wait', icon: '⏳', title: '조금 기다려보세요', desc: `현재 ${fmt(displayCur)}원은 평균보다 ${Math.round((ratio - 1) * 100)}% 비쌉니다.` };
  }, [ratio, displayCur, displayAvg, diff]);

  const tierPos = (displayHigh - displayLow) > 0
    ? Math.max(3, Math.min(97, ((displayCur - displayLow) / (displayHigh - displayLow)) * 100))
    : 50;

  const fairPrice = Math.round(displayAvg * 0.8);

  const hasData = displayCur != null && displayAvg != null && displayAvg > 0;

  // 마트별 최저가 계산 — 모든 훅은 early return 전에 호출해야 함
  const cheapestMart = useMemo(() => {
    if (!product?.stores) return null;
    let min = Infinity, name = '', key = '';
    MARTS.forEach(m => {
      const p = product.stores[m.key];
      if (p != null && p < min) { min = p; name = m.name; key = m.key; }
    });
    return min < Infinity ? { name, price: min, key } : null;
  }, [product]);

  const minMartPrice = useMemo(() => {
    if (!product?.stores) return 0;
    const prices = MARTS.map(m => product.stores[m.key]).filter(p => p != null);
    return prices.length > 0 ? Math.min(...prices) : 0;
  }, [product]);

  const martBarData = useMemo(() => {
    if (!product?.stores) return [];
    return MARTS.map(m => ({
      name: m.name,
      price: product.stores?.[m.key],
      color: m.color,
      isCheapest: product.stores?.[m.key] === minMartPrice,
    }));
  }, [product, minMartPrice]);

  // --- Early returns (after all hooks) ---
  if (loading) {
    return <div style={{ display: 'flex', justifyContent: 'center', padding: '4rem 0' }}><Spinner size="lg" /></div>;
  }

  if (!product) {
    return (
      <div>
        <div className={s.hdr}>
          <h2>물가 비교</h2>
          <p>정부 공식 + 마트 전단 기반 — 진짜 적정 가격을 확인하세요</p>
        </div>
        <div className={s.searchSection}>
          <div className={s.searchWrap}>
            <Search size={18} className={s.searchIcon} />
            <input
              className={s.searchInput}
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              onKeyDown={handleSearchKeyDown}
              placeholder="상품명을 검색하세요 (양파, 삼겹살, 계란...)"
              autoComplete="off"
            />
            {searchResults.length > 0 && (
              <div className={s.acList}>
                {searchResults.map(p => (
                  <div key={p.id} className={s.acItem} onClick={() => handleSelectProduct(p)}>
                    <span className={s.acIcon}>{p.icon}</span>
                    <span className={s.acName}>{p.name}</span>
                    <span className={s.acCat}>{p.cat}</span>
                    <span className={s.acPrice}>{fmt(p.cur)}원</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
        <div className={s.resultGrid}>
          {products.map(p => {
            const d = (p.cur || 0) - (p.avg || 1);
            const pct = p.avg ? ((d / p.avg) * 100).toFixed(1) : '0.0';
            let changeClass = s.changeSame;
            let icon = <Minus size={12} />;
            if (d < -(p.avg || 1) * 0.03) { changeClass = s.changeDown; icon = <TrendingDown size={12} />; }
            else if (d > (p.avg || 1) * 0.03) { changeClass = s.changeUp; icon = <TrendingUp size={12} />; }
            return (
              <div key={p.id} className={s.resultCard} onClick={() => handleSelectProduct(p)}>
                <div className={s.resultIcon}>{p.icon}</div>
                <div className={s.resultName}>{p.name}</div>
                <div className={s.resultUnit}>{p.unit}</div>
                <div className={s.resultPrice}>{fmt(p.cur)}원</div>
                <span className={`${s.resultChange} ${changeClass}`}>
                  {icon} {Math.abs(pct)}%
                </span>
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className={s.hdr}>
        <h2>물가 비교</h2>
        <p>정부 공식 + 마트 전단 기반 — 진짜 적정 가격을 확인하세요</p>
      </div>

      {/* Search bar at top */}
      <div className={s.searchSection}>
        <div className={s.searchWrap}>
          <Search size={18} className={s.searchIcon} />
          <input
            className={s.searchInput}
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            onKeyDown={handleSearchKeyDown}
            placeholder="다른 상품 검색..."
            autoComplete="off"
          />
          {searchResults.length > 0 && (
            <div className={s.acList}>
              {searchResults.map(p => (
                <div key={p.id} className={s.acItem} onClick={() => handleSelectProduct(p)}>
                  <span className={s.acIcon}>{p.icon}</span>
                  <span className={s.acName}>{p.name}</span>
                  <span className={s.acCat}>{p.cat}</span>
                  <span className={s.acPrice}>{fmt(p.cur)}원</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* 결론형 요약 */}
      {hasData && cheapestMart && (
        <div className={s.summaryBar}>
          <span className={s.summaryIcon}>{product.icon}</span>
          <span className={s.summaryText}>
            {product.name} {product.unit}: <strong>{cheapestMart.name}</strong>가 가장 싸요 (<strong>{fmt(cheapestMart.price)}원</strong>) — {timing.title}
          </span>
        </div>
      )}

      <div className={s.layout}>
        <div className={s.left}>
          {/* 상품 정보 */}
          <div className={s.itemInfo}>
            <span className={s.icon}>{product.icon}</span>
            <div>
              <h3>{product.name} {product.unit}</h3>
              <span className={s.cat}>{product.cat}</span>
            </div>
            <button
              className={`${s.favBtn} ${isFavorite(product.id) ? s.favActive : ''}`}
              onClick={() => isFavorite(product.id) ? removeFavorite(product.id) : addFavorite(product.id)}
              title={isFavorite(product.id) ? '관심 해제' : '관심 등록'}
            >
              <Heart size={20} fill={isFavorite(product.id) ? 'currentColor' : 'none'} />
            </button>
            <button
              className={s.cartBtn}
              onClick={() => {
                addToShoppingList({ productId: product.id, name: product.name, price: displayCur, unit: product.unit, icon: product.icon });
                addToast(`${product.name}을(를) 장보기 리스트에 추가했어요`, 'success');
              }}
              title="장보기에 추가"
            >
              🛒 장보기에 추가
            </button>
          </div>

          {/* 속성 변형 */}
          {variants.length > 0 && (
            <div className={s.variantSec}>
              <span className={s.variantLabel}>속성 분류</span>
              <div className={s.variantChips}>
                {variants.map((v, i) => (
                  <button key={i} className={`${s.variantChip} ${variantIdx === i ? s.variantActive : ''}`} onClick={() => setVariantIdx(i)}>
                    {v.label}
                    {v.storage !== '-' && <span className={s.variantTag}>{v.storage}</span>}
                    {v.grade !== '-' && v.grade !== '1등급' && <span className={s.variantTag}>{v.grade}</span>}
                  </button>
                ))}
              </div>
            </div>
          )}

          {hasData ? (
            <>
              {/* 타이밍 뱃지 */}
              <div className={`${s.timing} ${s[timing.cls]}`}>
                <span className={s.timingIcon}>{timing.icon}</span>
                <div><strong>{timing.title}</strong><p>{timing.desc}</p></div>
              </div>

              {/* 점진적 공개 — 상세 분석 접기/펼치기 */}
              <div className={s.detailToggle} onClick={() => setDetailOpen(!detailOpen)}>
                <span>📊 상세 가격 분석</span>
                {detailOpen ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
              </div>

              {detailOpen && (
                <div className={s.detailPanel}>
                  {/* 적정 핫딜가 안내 */}
                  <div className={s.fairPrice}>
                    <span className={s.fairIcon}>🎯</span>
                    <div>
                      <div className={s.fairLabel}>적정 핫딜가 (평균의 80%)</div>
                      <div className={s.fairVal}>{fmt(fairPrice)}원 이하면 구매 추천!</div>
                    </div>
                  </div>

                  {/* 가격 박스 4칸 */}
                  <div className={s.prices}>
                    <div className={`${s.priceBox} ${s.current}`}><span className={s.label}>현재 평균</span><span className={s.val}>{fmt(displayCur)}원</span></div>
                    <div className={s.priceBox}><span className={s.label}>30일 평균</span><span className={s.val}>{fmt(displayAvg)}원</span></div>
                    <div className={`${s.priceBox} ${s.low}`}><span className={s.label}>최근 최저</span><span className={s.val}>{fmt(displayLow)}원</span></div>
                    <div className={`${s.priceBox} ${s.high}`}><span className={s.label}>최근 최고</span><span className={s.val}>{fmt(displayHigh)}원</span></div>
                  </div>

                  {/* 가격 등급 바 */}
                  <div className={s.tierBar}>
                    <div className={s.tierLabel}>가격 등급</div>
                    <div className={s.tierTrack}>
                      <div className={`${s.zone} ${s.zoneUltra}`} style={{ width: '15%' }}>역대급</div>
                      <div className={`${s.zone} ${s.zoneGreat}`} style={{ width: '20%' }}>좋은 가격</div>
                      <div className={`${s.zone} ${s.zoneOk}`} style={{ width: '30%' }}>평균 수준</div>
                      <div className={`${s.zone} ${s.zoneWait}`} style={{ width: '20%' }}>조금 비쌈</div>
                      <div className={`${s.zone} ${s.zoneBad}`} style={{ width: '15%' }}>비쌈</div>
                      <div className={s.marker} style={{ left: `${tierPos}%` }} />
                    </div>
                  </div>

                  {/* 차트 */}
                  <div className={s.chartBox}>
                    <div className={s.chartHead}>
                      <h4>{range}일 가격 추이</h4>
                      <div className={s.chartBtns}>
                        {[30, 90, 365].map(r => (
                          <button key={r} className={`${s.chartBtn} ${range === r ? s.chartBtnActive : ''}`} onClick={() => setRange(r)}>
                            {r === 365 ? '1년' : `${r}일`}
                          </button>
                        ))}
                      </div>
                    </div>
                    <ResponsiveContainer width="100%" height={220}>
                      <AreaChart data={chartData}>
                        <defs>
                          <linearGradient id="colorPrice" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#38bdf8" stopOpacity={0.2} />
                            <stop offset="95%" stopColor="#38bdf8" stopOpacity={0} />
                          </linearGradient>
                        </defs>
                        <XAxis dataKey="date" tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} />
                        <YAxis tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} width={50} tickFormatter={v => fmt(v)} />
                        <Tooltip
                          contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, fontSize: '.85rem' }}
                          formatter={v => [`${fmt(v)}원`, '가격']}
                        />
                        <Area type="monotone" dataKey="price" stroke="#38bdf8" strokeWidth={2} fill="url(#colorPrice)" />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>

                  {/* 상세 통계 */}
                  <div className={s.expertPanel}>
                    <h5>📊 상세 통계</h5>
                    <div className={s.statsGrid}>
                      <div className={s.stat}><span className={s.statLabel}>평균 할인율</span><span className={s.statVal}>{product.stats?.avgDiscount ?? Math.round((1 - displayCur / displayHigh) * 100)}%</span></div>
                      <div className={s.stat}><span className={s.statLabel}>할인 빈도</span><span className={s.statVal}>월 {product.stats?.discFreq?.toFixed?.(1) ?? (product.stats?.discFreq || ((displayAvg - displayLow) / displayAvg * 5).toFixed(1))}회</span></div>
                      <div className={s.stat}><span className={s.statLabel}>데이터 기간</span><span className={s.statVal}>{product.stats?.dataDays ?? 180}일</span></div>
                      <div className={s.stat}><span className={s.statLabel}>수집 레코드</span><span className={s.statVal}>{fmt(product.stats?.records ?? Math.round(displayAvg / 2))}건</span></div>
                      <div className={s.stat}><span className={s.statLabel}>이상치 제거</span><span className={s.statVal}>{product.stats?.outliers ?? Math.round((displayHigh - displayLow) / displayAvg * 10)}건</span></div>
                      <div className={s.stat}><span className={s.statLabel}>신뢰 구간</span><span className={s.statVal}>{fmt(product.stats?.confidence?.[0] ?? displayLow)}~{fmt(product.stats?.confidence?.[1] ?? displayHigh)}원</span></div>
                    </div>
                  </div>
                </div>
              )}
            </>
          ) : (
            <div className={s.noData}>
              <div className={s.noDataIcon}>📊</div>
              <p className={s.noDataText}>아직 가격 데이터가 충분하지 않습니다</p>
              <p className={s.noDataSub}>데이터가 수집되면 가격 추이, 적정가, 마트별 비교를 확인할 수 있어요</p>
              <button className={s.requestBtn} onClick={() => addToast('데이터 수집 요청이 접수되었습니다', 'success')}>
                📥 데이터 수집 요청
              </button>
            </div>
          )}
        </div>

        {/* 우측 사이드바 */}
        <aside className={s.right}>
          {/* 마트별 바 차트 */}
          <div className={s.barChartBox}>
            <h4>마트별 현재 가격 비교</h4>
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={martBarData} layout="vertical" margin={{ left: 10, right: 10 }}>
                <XAxis type="number" tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={v => fmt(v)} />
                <YAxis type="category" dataKey="name" tick={{ fill: '#94a3b8', fontSize: 12 }} axisLine={false} tickLine={false} width={60} />
                <Tooltip
                  contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, fontSize: '.85rem' }}
                  formatter={v => [`${fmt(v)}원`, '가격']}
                />
                <Bar dataKey="price" radius={[0, 6, 6, 0]} barSize={20} label={({ x, y, width, height, index }) => {
                    const entry = martBarData[index];
                    return entry?.isCheapest ? (
                      <text x={x + width + 4} y={y + height / 2 + 4} fill="#22c55e" fontSize={11} fontWeight="bold">최저</text>
                    ) : null;
                  }}>
                  {martBarData.map((entry, index) => (
                    <Cell key={index} fill={entry.isCheapest ? '#22c55e' : entry.color} fillOpacity={entry.isCheapest ? 1 : 0.7} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          <h4>마트별 현재 가격</h4>
          <div className={s.martList}>
            {MARTS.map(m => {
              const price = product.stores[m.key];
              const d = price - product.avg;
              const isCheapest = price === minMartPrice;
              return (
                <div key={m.key} className={`${s.mlItem} ${isCheapest ? s.mlCheapest : ''}`}>
                  <div className={s.mlLeft}>
                    <span className={s.mlDot} style={{ background: isCheapest ? '#22c55e' : m.color }} />
                    <span className={s.mlName}>{m.name}</span>
                    {isCheapest && <span className={s.mlBadge}>최저</span>}
                  </div>
                  <div>
                    <span className={s.mlPrice}>{fmt(price)}원</span>
                    <span className={`${s.mlVs} ${d <= 0 ? s.cheap : s.expensive}`}>
                      {d <= 0 ? fmt(d) : `+${fmt(d)}`}원
                    </span>
                  </div>
                </div>
              );
            })}
          </div>

          <h4>관련 핫딜</h4>
          <div className={s.relatedDeals}>
            {relatedHotdeals.slice(0, 3).map(d => (
              <div key={d.id} className={s.rdItem}>
                <div className={s.rdTitle}>{d.title}</div>
                <div className={s.rdMeta}><span>{d.source}</span><span>{d.time}</span></div>
              </div>
            ))}
          </div>
        </aside>
      </div>
    </div>
  );
}
