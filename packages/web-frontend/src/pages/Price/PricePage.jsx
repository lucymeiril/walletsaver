import { useParams, useNavigate, useLocation } from 'react-router-dom';
import { useMemo, useState, useEffect, useCallback } from 'react';
import { AreaChart, Area, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts';
import { Heart, Search, ChevronDown, ChevronUp } from 'lucide-react';
import { MARTS } from '../../utils/constants';
import { fmt } from '../../utils/helpers';
import { OfferFacts } from '../../components/ProductDetailModal';
import { searchService } from '../../services/searchService';
import { getVariantBestOffer, getPriceHistorySummary, getOfferConditionText, getOfferReceiptText, getQuantityComponentTexts, getConditionalOfferConditionText, getObservedOfferPriceText, isObservationReceiptEligible, getOfferAmountLabel } from '../../utils/productDecision';
import useStore from '../../stores/appStore';
import useCartStore from '../../stores/cartStore';
import { buildCartPayload, buildWishlistPayload, normalizeProduct, selectProductOffer, getProductSelection } from '../../utils/productActions';
import { api } from '../../services/api';
import useModalStore from '../../stores/modalStore';
import useDebounce from '../../hooks/useDebounce';
import useAbortController from '../../hooks/useAbortController';
import Spinner from '../../components/common/Spinner';
import EmptyState from '../../components/common/EmptyState';
import s from './PricePage.module.css';

function highlightMatch(text, query) {
  if (!query || !text) return text;
  const idx = text.toLowerCase().indexOf(query.toLowerCase());
  if (idx === -1) return text;
  return <>{text.slice(0, idx)}<strong>{text.slice(idx, idx + query.length)}</strong>{text.slice(idx + query.length)}</>;
}

function positivePrice(...values) {
  return values.find(v => typeof v === 'number' && v > 0) ?? 0;
}

export function LegacyObservationFacts({ unit, observedAt }) {
  return <div>
    <div>저장 규격 · {unit || '미확인'}</div>
    <small>관측 시각 · {observedAt || '미확인'}</small>
    <div><small>수령량·묶음 수량·구매 조건 검증 미확인 · 동일 수량 가격 비교 미확인</small></div>
  </div>;
}

export function RelatedHotdealFacts({ deal }) {
  return <>
    <div className={s.rdMeta}><span>{deal.source_label || deal.source}</span></div>
    <div><small>{deal.posted_at ? `출처 게시 시각 · ${deal.posted_at}` : '출처 게시 시각 · 미확인'}</small></div>
    {deal.fetched_at && <div><small>수집 시각 · {deal.fetched_at}</small></div>}
    {deal.time && <div><small>{deal.posted_at ? '출처 게시 후 경과' : deal.fetched_at ? '수집 후 경과' : '표시 상대 시각'} · {deal.time}{!deal.posted_at && !deal.fetched_at && ' · 기준 시각 미확인'}</small></div>}
    <div><small>{deal.expired === true ? '판매 기간 종료 · 과거 출처 관측' : '현재 판매 가능 여부 미확인'}</small></div>
    {deal.source_period && <div><small>출처 기간 · {deal.source_period}</small></div>}
    {(deal.source_conditions || []).map((condition, index) => <div key={index}><small>출처 조건 · {condition}</small></div>)}
  </>;
}

export function ObservedExpertStats({ stats = {} }) {
  const entries = [
    ['평균 할인율', stats.avgDiscount != null ? `${stats.avgDiscount}%` : null],
    ['할인 빈도', stats.discFreq != null ? `월 ${stats.discFreq}회` : null],
    ['데이터 기간', stats.dataDays != null ? `${stats.dataDays}일` : null],
    ['수집 레코드', stats.records != null ? `${fmt(stats.records)}건` : null],
    ['이상치 제거', stats.outliers != null ? `${stats.outliers}건` : null],
    ['신뢰 구간', stats.confidence?.length === 2 ? `${fmt(stats.confidence[0])}~${fmt(stats.confidence[1])}원` : null],
  ].filter(([, value]) => value != null);
  if (!entries.length) return null;
  return <div className={s.expertPanel}>
    <h5>📊 상세 통계</h5>
    <div className={s.statsGrid}>{entries.map(([label, value]) => <div key={label} className={s.stat}>
      <span className={s.statLabel}>{label}</span><span className={s.statVal}>{value}</span>
    </div>)}</div>
  </div>;
}

export default function PricePage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const { openMartModal, openHotdealModal, openProductModal, openProductDetailModal } = useModalStore();
  const { selectedProduct, setSelectedProduct, isLoggedIn, favoriteItems, addFavorite, removeFavorite, setFavoriteRemoteId, isFavorite, addRecentSearch, addToast } = useStore();
  const [wishlistSaving, setWishlistSaving] = useState(false);

  const [products, setProducts] = useState([]);
  const [categories, setCategories] = useState([]);
  const [productData, setProductData] = useState(null);
  const [detailError, setDetailError] = useState(null);
  const sharedSelection = useMemo(() => {
    const params = new URLSearchParams(location.search);
    const keys = ['variant', 'listing', 'offer'];
    const present = keys.some(key => params.has(key));
    const valid = keys.every(key => params.getAll(key).length === 1
      && params.get(key)?.trim() && params.get(key).length <= 200);
    return { present, valid, selection: { variantId: params.get('variant'),
      listingId: params.get('listing'), offerId: params.get('offer') } };
  }, [location.search]);
  const [allChartData, setChartData] = useState([]);
  const [selectedListingId, setSelectedListingId] = useState(null);
  const addCartItem = useCartStore(st => st.addItem);
  const [priceHistory, setPriceHistory] = useState(null);
  const [chartError, setChartError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [chartLoading, setChartLoading] = useState(false);
  const [acKeywords, setAcKeywords] = useState([]);
  const [acProducts, setAcProducts] = useState([]);
  const [totalKeywords, setTotalKeywords] = useState(0);
  const [totalProducts, setTotalProducts] = useState(0);
  const [trendingKeywords, setTrendingKeywords] = useState([]);
  const [detailOpen, setDetailOpen] = useState(false);
  const getSignal = useAbortController();

  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState(null);

  // Fetch all products for search
  useEffect(() => {
    const signal = getSignal();
    setListLoading(true);
    setListError(null);
    Promise.all([
      fetch('/api/products/search?per_page=50', { signal }).then(r => r.json()),
      fetch('/api/products/categories', { signal }).then(r => r.json()),
    ])
      .then(([productsRes, categoriesRes]) => {
        setProducts(productsRes.data || []);
        setCategories(categoriesRes.data || []);
      })
      .catch(err => {
        if (err.name !== 'AbortError') {
          console.error(err);
          setListError(err);
        }
      })
      .finally(() => setListLoading(false));
  }, [getSignal]);

  // Fetch product detail by ID
  useEffect(() => {
    if (!id) {
      setProductData(null);
      setSelectedProduct(null);
      return;
    }
    const controller = new AbortController();
    setProductData(null);
    setDetailError(null);
    setLoading(true);
    fetch(`/api/products/${encodeURIComponent(id)}`, { signal: controller.signal }).then(async r => {
      const response = await r.json();
      if (!r.ok) throw new Error(response.detail || '상품 정보를 불러오지 못했습니다');
      return response;
    })
      .then(res => setProductData(res.data))
      .catch(err => {
        if (err.name === 'AbortError') return;
        console.error(err);
        setDetailError(err.message);
        addToast('상품 정보를 불러오는데 실패했습니다', 'error');
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [id, addToast, setSelectedProduct]);

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
  }, [location.state, products, navigate, setSelectedProduct, addRecentSearch]);

  const [searchQuery, setSearchQuery] = useState('');
  const [range, setRange] = useState(365);
  const [variantIdx, setVariantIdx] = useState(0);
  useEffect(() => { setVariantIdx(0); setSelectedListingId(null); setChartData([]); setPriceHistory(null); }, [id]);

  const debouncedQuery = useDebounce(searchQuery, 200);

  // 인기 검색어 로드
  useEffect(() => {
    searchService.trending(8)
      .then(res => setTrendingKeywords(res.data || []))
      .catch(() => {});
  }, []);

  // 검색 자동완성 — 키워드+상품 2섹션
  useEffect(() => {
    const controller = new AbortController();
    setAcKeywords([]);
    setAcProducts([]);
    setTotalKeywords(0);
    setTotalProducts(0);
    if (debouncedQuery.length < 1 || searchQuery !== debouncedQuery) return () => controller.abort();
    searchService.autocomplete(debouncedQuery, 10, { signal: controller.signal })
      .then(res => {
        if (controller.signal.aborted) return;
        const d = res.data || {};
        setAcKeywords(d.keywords || []);
        setAcProducts(d.products || []);
        setTotalKeywords(d.total_keyword_count || 0);
        setTotalProducts(d.total_product_count || 0);
      })
      .catch(err => {
        if (controller.signal.aborted || err.name === 'AbortError') return;
        setAcKeywords([]);
        setAcProducts([]);
        setTotalKeywords(0);
        setTotalProducts(0);
      });
    return () => controller.abort();
  }, [debouncedQuery, searchQuery]);

  const hasAcResults = acKeywords.length > 0 || acProducts.length > 0;

  // 기존 product 검색 결과 (products 목록 기반 — fallback)
  const searchResults = useMemo(() =>
    debouncedQuery.length > 0 && !hasAcResults
      ? products.filter(p => p.name?.includes(debouncedQuery) || p.cat?.includes(debouncedQuery))
      : [],
    [debouncedQuery, hasAcResults, products]
  );

  const product = productData || (id ? products.find(p => String(p.id) === id) : null)
    || (selectedProduct && (!id || String(selectedProduct.id) === id) ? selectedProduct : null);

  // Fetch price history from API
  useEffect(() => {
    if (!product) return;
    const controller = new AbortController();
    setChartLoading(true);
    setChartError(null);
    fetch(`/api/products/${product.id}/price-history?days=${range}`, { signal: controller.signal })
      .then(async r => {
        const res = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(res.detail || '가격 이력을 불러오지 못했습니다');
        return res;
      })
      .then(res => {
        const payload = res.data || {};
        const points = Array.isArray(payload) ? payload : (payload.history || payload.points || []);
        setPriceHistory(Array.isArray(payload) ? { history: points, points, point_count: points.length } : payload);
        setChartData([...points].sort((a, b) =>
          Date.parse(a.date || a.observed_at || a.crawled_at || '') - Date.parse(b.date || b.observed_at || b.crawled_at || '')));
      })
      .catch(err => {
        if (err.name === 'AbortError') return;
        setPriceHistory({ history: [], points: [], point_count: 0, is_sparse: true, message: err.message });
        setChartData([]);
        setChartError(err.message);
      })
      .finally(() => setChartLoading(false));
    return () => controller.abort();
  }, [product?.id, range]);

  const handleSelectProduct = useCallback((p) => {
    setSelectedProduct(p);
    addRecentSearch(p.name);
    setSearchQuery('');
    navigate(`/price/${p.id}`);
  }, [setSelectedProduct, addRecentSearch, navigate]);

  const handleKeywordClick = useCallback((kw) => {
    addRecentSearch(kw.word);
    searchService.trackKeyword(kw.id);
    setSearchQuery('');

    // Prioritize product name match: if products exist in autocomplete, go to search
    if (acProducts.length > 0) {
      navigate(`/search?q=${encodeURIComponent(kw.word)}`);
    } else if (kw.suggested_action === 'category_page' && kw.category_id && kw.category_path?.toLowerCase().includes(kw.word?.toLowerCase?.().slice(0, 2))) {
      navigate(`/price/category/${kw.category_id}`);
    } else {
      navigate(`/search?q=${encodeURIComponent(kw.word)}`);
    }
  }, [addRecentSearch, navigate, acProducts]);

  const handleAcProductClick = useCallback((p) => {
    if (p.id) searchService.trackKeyword(p.id);
    setSearchQuery('');

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

  // 엔터 누르면 검색 결과 페이지로 이동 (자동완성에서 선택 안 했을 때)
  const handleSearchKeyDown = useCallback((e) => {
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
  }, [searchQuery, searchResults, handleSelectProduct, navigate]);

  // 상품 상세 — 속성 변형은 DB에서 조회
  const variants = productData?.variants || [];
  const sharedChoice = sharedSelection.present && sharedSelection.valid && productData && String(productData.id) === id
    ? getProductSelection(productData, sharedSelection.selection) : null;
  useEffect(() => {
    if (!sharedChoice || String(productData.id) !== id) return;
    setVariantIdx(productData.variants.findIndex(variant => variant.id === sharedChoice.variant.id));
    setSelectedListingId(sharedChoice.listing.id);
    openProductDetailModal(selectProductOffer(productData, sharedSelection.selection));
  }, [productData, id, sharedSelection, openProductDetailModal]);
  const activeVariant = variants[variantIdx] || null;
  const normalizedCatalog = Boolean(product?.public_product_id);
  const variantBest = normalizedCatalog ? getVariantBestOffer(activeVariant) : null;
  const activeListing = activeVariant?.listings?.find(listing => listing.id === selectedListingId)
    || activeVariant?.listings?.find(listing => listing.id === variantBest?.listingId) || activeVariant?.listings?.[0];
  const selectedProductQuote = normalizedCatalog ? selectProductOffer(product, { variantId: activeVariant?.id, listingId: activeListing?.id, offerId: activeListing?.offers?.[0]?.id }) : product;
  const favoriteId = normalizeProduct(selectedProductQuote || {}).favoriteId;
  const selectedIsFavorite = isFavorite(favoriteId);
  const handleToggleWishlist = async () => {
    if (!isLoggedIn) {
      addToast('로그인이 필요합니다', 'warning');
      return;
    }
    if (wishlistSaving) return;
    setWishlistSaving(true);
    try {
      if (selectedIsFavorite) {
        let remoteId = favoriteItems?.[favoriteId]?.remote_id;
        if (!remoteId) {
          const result = await api.getJson('/api/wishlist');
          const items = result?.data || result?.items || result || [];
          remoteId = Array.isArray(items)
            ? items.find(item => normalizeProduct(item).favoriteId === favoriteId)?.id
            : null;
        }
        if (!remoteId) throw new Error('wishlist item is not synchronized');
        await api.delete(`/api/wishlist/${remoteId}`);
        removeFavorite(favoriteId);
        addToast('찜 목록에서 제거했어요', 'info');
      } else {
        const payload = buildWishlistPayload(selectedProductQuote);
        const response = await api.post('/api/wishlist', payload);
        const json = await response.json();
        const remoteId = json?.data?.id || json?.id;
        if (!remoteId) throw new Error('wishlist id missing from server response');
        addFavorite(favoriteId, payload);
        setFavoriteRemoteId(favoriteId, remoteId);
        addToast(`${product.name} 찜했어요 ❤️`, 'success');
      }
    } catch {
      addToast(selectedIsFavorite ? '찜 삭제에 실패했어요. 목록을 다시 불러온 뒤 시도해주세요.' : '찜 추가에 실패했어요. 잠시 후 다시 시도해주세요.', 'error');
    } finally {
      setWishlistSaving(false);
    }
  };
  const activeOffer = normalizedCatalog ? selectedProductQuote?.selected_offer || selectedProductQuote?.best_offer : null;
  const currentOffer = priceHistory?.current_offer || priceHistory?.latest_offer || null;
  const currentOfferPrice = positivePrice(currentOffer?.price, product?.current_price, product?.price, product?.sale_price);
  const displayCur = normalizedCatalog ? (isObservationReceiptEligible(activeOffer) ? selectedProductQuote?.best_offer?.comparable_price ?? null : null)
    : product ? positivePrice(activeVariant?.cur, product.cur, currentOfferPrice) : 0;
  // Product-wide history can combine different package variants. Keep it in
  // the history chart rather than label it as this variant's price range.
  const selectedHistory = getPriceHistorySummary(selectedProductQuote || {}, allChartData, {variantId:activeVariant?.id});
  const chartData = normalizedCatalog ? selectedHistory.history : allChartData;
  const displayAvg = normalizedCatalog ? selectedHistory.avg : product ? positivePrice(activeVariant?.avg, product.avg, priceHistory?.average_price, displayCur) : 0;
  const displayLow = normalizedCatalog ? selectedHistory.min : product ? positivePrice(activeVariant?.low, product.low, priceHistory?.min_price, displayCur) : 0;
  const displayHigh = normalizedCatalog ? selectedHistory.max : product ? positivePrice(activeVariant?.high, product.high, priceHistory?.max_price, displayCur) : 0;
  const displayUnit = normalizedCatalog ? activeVariant?.display_unit || '' : product?.unit;

  const timing = useMemo(() => normalizedCatalog
    ? { cls:'good', icon:'📊', title:'동일 조건 관측 비교', desc:`선택 규격의 같은 수령·행사 조건 관측 평균 ${fmt(displayAvg)}원과 비교합니다. 표시된 회원·쿠폰 조건을 확인하세요.` }
    : { cls:'good', icon:'📊', title:'저장 가격 이력', desc:'저장된 가격 관측입니다. 수량·구매 조건과 현재 판매 가능 여부가 확인된 비교는 아닙니다.' },
  [displayAvg, normalizedCatalog]);

  const hasData = displayCur != null && displayCur > 0 && displayAvg != null && displayAvg > 0;
  const activeStats = normalizedCatalog ? activeVariant?.stats || {} : product?.stats || {};
  const historyPointCount = normalizedCatalog ? chartData.length : priceHistory?.point_count ?? chartData.length;
  const historyMessage = chartError || priceHistory?.message;

  const martBarData = useMemo(() => {
    if (!product?.stores) return [];
    return MARTS.map(m => ({
      name: m.name,
      price: product.stores?.[m.key],
      color: m.color,
    }));
  }, [product]);

  const handleBackToList = useCallback(() => {
    setSelectedProduct(null);
    navigate('/price');
  }, [setSelectedProduct, navigate]);

  const categoryGroups = useMemo(() => {
    const productGroups = new Map();
    products.forEach((p) => {
      const path = String(p.cat || p.category_path || '기타').split('>').map(v => v.trim()).filter(Boolean);
      const top = path[0] || '기타';
      const leaf = path[path.length - 1] || top;
      if (!productGroups.has(top)) {
        productGroups.set(top, {
          id: top,
          name: top,
          icon: p.icon || '🧺',
          count: 0,
          children: new Map(),
          examples: [],
        });
      }
      const group = productGroups.get(top);
      group.count += 1;
      if (!group.children.has(leaf)) group.children.set(leaf, 0);
      group.children.set(leaf, group.children.get(leaf) + 1);
      if (group.examples.length < 3) group.examples.push(p.name);
    });
    const productCategoryGroups = Array.from(productGroups.values()).map((group) => ({
      ...group,
      children: Array.from(group.children.entries())
        .map(([name, count]) => ({ name, count }))
        .sort((a, b) => b.count - a.count),
    }));

    if (categories.length > 0) {
      return categories.map((cat) => ({
        id: cat.id || cat.name,
        name: cat.name || cat.id,
        icon: cat.icon || '🧺',
        count: cat.count || productGroups.get(cat.name)?.count || 0,
        children: (Array.isArray(cat.children) && cat.children.length > 0)
          ? cat.children
          : (productCategoryGroups.find(group => group.name === cat.name)?.children || []),
        examples: (Array.isArray(cat.examples) && cat.examples.length > 0)
          ? cat.examples
          : (productGroups.get(cat.name)?.examples || []),
      }));
    }
    return productCategoryGroups;
  }, [categories, products]);

  // --- Early returns (after all hooks) ---
  if (sharedSelection.present) {
    const error = !sharedSelection.valid ? '공유 링크의 규격·판매처·관측 정보가 불완전합니다'
      : detailError || (productData && !sharedChoice
        ? '공유된 규격·판매처·관측을 확인할 수 없습니다. 다른 거래로 자동 변경하지 않았습니다' : null);
    if (error) return <div role="alert"><p>{error}</p>
      <button onClick={() => navigate(`/price/${encodeURIComponent(id)}`, { replace: true })}>상품 다시 선택</button></div>;
    if (!productData) return <div style={{ padding: '4rem 0' }}><Spinner size="lg" /></div>;
  }
  if (loading) {
    return <div style={{ display: 'flex', justifyContent: 'center', padding: '4rem 0' }}><Spinner size="lg" /></div>;
  }

  if (!product) {
    return (
      <div>
        <div className={s.hdr}>
          <h2>물가 비교</h2>
          <p>판매처 원문과 저장 관측을 비교하세요 — 규격·구매 조건·관측일을 함께 확인합니다</p>
        </div>
        {listLoading && (
          <div style={{ display: 'flex', justifyContent: 'center', padding: '2rem 0' }}><Spinner /></div>
        )}
        {listError && !listLoading && (
          <EmptyState
            icon={Search}
            title="상품 목록을 불러오지 못했습니다"
            description="잠시 후 다시 시도해주세요."
          />
        )}
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
              aria-label="물가 검색"
            />
            {(hasAcResults || searchResults.length > 0) && (
              <div className={s.acList}>
                {acKeywords.length > 0 && (
                  <>
                    <div className={s.acSectionLabel}>키워드</div>
                    {acKeywords.map(kw => (
                      <div key={`kw-${kw.id}`} className={s.acItem} onClick={() => handleKeywordClick(kw)}>
                        <span className={s.acIcon}>🔍</span>
                        <div className={s.acContent}>
                          <span className={s.acName}>{highlightMatch(kw.word, searchQuery)}</span>
                          {kw.matched_synonym && <span className={s.acHint}>← &ldquo;{kw.matched_synonym}&rdquo; 포함</span>}
                          <span className={s.acPath}>{kw.category_path}</span>
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
                      <div key={`p-${p.id}`} className={s.acItem} onClick={() => handleAcProductClick(p)}>
                        <span className={s.acIcon}>{p.icon || '📦'}</span>
                        <div className={s.acContent}>
                          <span className={s.acName}>{highlightMatch(p.name, searchQuery)}</span>
                          <span className={s.acMeta}>{p.unit} {p.current_price ? `· ${fmt(p.current_price)}원` : ''}</span>
                        </div>
                      </div>
                    ))}
                  </>
                )}
                {!hasAcResults && searchResults.map(p => (
                  <div key={p.id} className={s.acItem} onClick={() => handleSelectProduct(p)}>
                    <span className={s.acIcon}>{p.icon}</span>
                    <span className={s.acName}>{p.name}</span>
                    <span className={s.acCat}>{p.cat}</span>
                    <span className={s.acPrice}>{fmt(p.cur)}원</span>
                  </div>
                ))}
                {(totalKeywords > 3 || totalProducts > 5) && (
                  <div className={s.acFooter} onClick={() => navigate(`/search?q=${encodeURIComponent(searchQuery)}`)}>
                    🔍 &ldquo;{searchQuery}&rdquo; 전체 검색 결과 보기 ({totalKeywords + totalProducts}건)
                  </div>
                )}
              </div>
            )}
            {debouncedQuery.length > 0 && !hasAcResults && searchResults.length === 0 && (
              <div className={s.acList}>
                <div className={s.acEmpty}>
                  😅 &ldquo;{searchQuery}&rdquo;에 대한 결과가 없습니다.
                  {trendingKeywords.length > 0 && (
                    <div className={s.acTrending}>
                      {trendingKeywords.map(t => (
                        <button key={t.word} className={s.acTrendBtn} onClick={() => setSearchQuery(t.word)}>🔥 {t.word}</button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
        <section className={s.categoryIntro}>
          <h3>카테고리로 물가 비교하기</h3>
          <p>먼저 큰 상품군을 고르고, 다음 화면에서 사과·우유·두부처럼 세부 상품군으로 좁혀 비교하세요.</p>
        </section>
        <div className={s.categoryGrid}>
          {categoryGroups.map((cat) => (
            <button
              key={cat.id}
              type="button"
              className={s.categoryCard}
              onClick={() => navigate(`/price/category/${encodeURIComponent(cat.id)}`)}
            >
              <span className={s.categoryIcon}>{cat.icon}</span>
              <span className={s.categoryName}>{cat.name}</span>
              <span className={s.categoryCount}>{cat.count}개 상품군·품목</span>
              <span className={s.categoryExamples}>{cat.examples?.join?.(' · ') || ''}</span>
              <span className={s.categoryChildren}>
                {cat.children.slice(0, 4).map(child => child.name).join(' / ')}
              </span>
            </button>
          ))}
        </div>
        {categoryGroups.length === 0 && !listLoading && !listError && (
          <EmptyState
            icon={Search}
            title="승인된 물가 데이터가 아직 없습니다"
            description="수집·분류·관리자 승인 후 카테고리와 상품 가격이 표시됩니다."
          />
        )}
      </div>
    );
  }

  return (
    <div>
      <div className={s.hdr}>
        {id && (
          <button className={s.backToList} onClick={handleBackToList}>
            ← 목록으로
          </button>
        )}
        <h2>물가 비교</h2>
        <p>판매처 원문과 저장 관측을 비교하세요 — 규격·구매 조건·관측일을 함께 확인합니다</p>
      </div>
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
            aria-label="물가 검색"
          />
          {(hasAcResults || searchResults.length > 0) && (
            <div className={s.acList}>
              {acKeywords.length > 0 && (
                <>
                  <div className={s.acSectionLabel}>키워드</div>
                  {acKeywords.map(kw => (
                    <div key={`kw-${kw.id}`} className={s.acItem} onClick={() => handleKeywordClick(kw)}>
                      <span className={s.acIcon}>🔍</span>
                      <div className={s.acContent}>
                        <span className={s.acName}>{highlightMatch(kw.word, searchQuery)}</span>
                        {kw.matched_synonym && <span className={s.acHint}>← &ldquo;{kw.matched_synonym}&rdquo; 포함</span>}
                        <span className={s.acPath}>{kw.category_path}</span>
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
                    <div key={`p-${p.id}`} className={s.acItem} onClick={() => handleAcProductClick(p)}>
                      <span className={s.acIcon}>{p.icon || '📦'}</span>
                      <div className={s.acContent}>
                        <span className={s.acName}>{highlightMatch(p.name, searchQuery)}</span>
                        <span className={s.acMeta}>{p.unit} {p.current_price ? `· ${fmt(p.current_price)}원` : ''}</span>
                      </div>
                    </div>
                  ))}
                </>
              )}
              {!hasAcResults && searchResults.map(p => (
                <div key={p.id} className={s.acItem} onClick={() => handleSelectProduct(p)}>
                  <span className={s.acIcon}>{p.icon}</span>
                  <span className={s.acName}>{p.name}</span>
                  <span className={s.acCat}>{p.cat}</span>
                  <span className={s.acPrice}>{fmt(p.cur)}원</span>
                </div>
              ))}
              {(totalKeywords > 3 || totalProducts > 5) && (
                <div className={s.acFooter} onClick={() => navigate(`/search?q=${encodeURIComponent(searchQuery)}`)}>
                  🔍 &ldquo;{searchQuery}&rdquo; 전체 검색 결과 보기 ({totalKeywords + totalProducts}건)
                </div>
              )}
            </div>
          )}
          {debouncedQuery.length > 0 && !hasAcResults && searchResults.length === 0 && (
            <div className={s.acList}>
              <div className={s.acEmpty}>
                😅 &ldquo;{searchQuery}&rdquo;에 대한 결과가 없습니다.
                {trendingKeywords.length > 0 && (
                  <div className={s.acTrending}>
                    {trendingKeywords.map(t => (
                      <button key={t.word} className={s.acTrendBtn} onClick={() => setSearchQuery(t.word)}>🔥 {t.word}</button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      <div className={s.layout}>
        <div className={s.left}>
          {/* 상품 정보 */}
          <div className={s.itemInfo}>
            <span className={s.icon}>{product.icon}</span>
            <div>
              <h3>{product.name} {normalizedCatalog ? displayUnit : ''}</h3>
              <span className={s.cat}>{product.cat}</span>
              {!normalizedCatalog && <LegacyObservationFacts unit={displayUnit} observedAt={currentOffer?.observed_at || currentOffer?.crawled_at || currentOffer?.date} />}
              {normalizedCatalog && <>
                <div>출처 표시 가격 {getObservedOfferPriceText(activeOffer)}</div>
                <div><small>{displayCur > 0 ? `${getOfferAmountLabel(activeOffer)} ${fmt(displayCur)}원` : '행사 적용 금액·수령량 비교 미확인'}</small></div>
                <small>관측 시각 · {activeOffer?.crawled_at || activeOffer?.observed_at || '미확인'}</small>
                <div><small>{activeOffer?.current_eligible === false ? '현 판매 여부 미확인 · ' : ''}관측 가격 · 추가 혜택은 원문 조건 확인</small></div>
              </>}
            </div>
            <button
              className={`${s.favBtn} ${selectedIsFavorite ? s.favActive : ''}`}
              onClick={handleToggleWishlist}
              disabled={wishlistSaving}
              title={selectedIsFavorite ? '관심 해제' : '관심 등록'}
            >
              <Heart size={20} fill={selectedIsFavorite ? 'currentColor' : 'none'} />
            </button>
            <button
              className={s.cartBtn}
              onClick={() => {
                Promise.resolve().then(() => addCartItem(buildCartPayload(selectedProductQuote)))
                  .then(() => addToast(`${product.name}을(를) 장보기 리스트에 추가했어요`, 'success'))
                  .catch(error => addToast(error.message || '장바구니 저장에 실패했습니다', 'error'));
              }}
              title="장보기에 추가"
            >
              🛒 장보기에 추가
            </button>
          </div>

          {/* 속성 변형 */}
          {variants.length > 0 && (
            <div className={s.variantSec}>
              <span className={s.variantLabel}>판매 규격·출처 선택</span>
              <small>같은 내용량도 출처별 원문 규격을 따로 보존합니다.</small>
              <div className={s.variantChips}>
                {variants.map((v, i) => (
                  <button key={v.id || v.label || v.name || `var-${i}`} className={`${s.variantChip} ${variantIdx === i ? s.variantActive : ''}`} onClick={() => { setVariantIdx(i); setSelectedListingId(null); }}>
                    {v.label || v.name || v.display_unit}
                    {v.storage && v.storage !== '-' && <span className={s.variantTag}>{v.storage}</span>}
                    {v.grade && v.grade !== '-' && v.grade !== '1등급' && <span className={s.variantTag}>{v.grade}</span>}
                  </button>
                ))}
              </div>
            </div>
          )}

          {normalizedCatalog && activeVariant?.quantity_components?.length > 0 && <div aria-label="선택 규격 구성">
            <strong>선택 규격 구성 · 구성별 수량</strong>
            {getQuantityComponentTexts(activeVariant.quantity_components).map((text, index) => <div key={index}>{text}</div>)}
            <small>구성품의 내용량·수량을 개별 표시합니다. 전체 구성의 정확한 단위가는 표시하지 않습니다.</small>
          </div>}
          {hasData ? (
            <>
              {/* 타이밍 뱃지 */}
              <div className={`${s.timing} ${s[timing.cls]}`}>
                <span className={s.timingIcon}>{timing.icon}</span>
                <div><strong>{timing.title}</strong><p>{timing.desc}</p></div>
              </div>

              {!normalizedCatalog && <>
              {/* 점진적 공개 — 상세 분석 접기/펼치기 */}
              <div className={s.detailToggle} onClick={() => setDetailOpen(!detailOpen)}>
                <span>📊 상세 가격 분석</span>
                {detailOpen ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
              </div>

              {detailOpen && (
                <div className={s.detailPanel}>
                  {/* 가격 박스 4칸 */}
                  <div className={s.prices}>
                    <div className={`${s.priceBox} ${s.current}`}><span className={s.label}>저장 관측 가격</span><span className={s.val}>{fmt(displayCur)}원</span></div>
                    <div className={s.priceBox}><span className={s.label}>저장 평균</span><span className={s.val}>{fmt(displayAvg)}원</span></div>
                    <div className={`${s.priceBox} ${s.low}`}><span className={s.label}>최근 최저</span><span className={s.val}>{fmt(displayLow)}원</span></div>
                    <div className={`${s.priceBox} ${s.high}`}><span className={s.label}>최근 최고</span><span className={s.val}>{fmt(displayHigh)}원</span></div>
                  </div>

                </div>
              )}
              </>}
            </>
          ) : normalizedCatalog && activeOffer?.listed_price != null ? null : (
            <div className={s.noData}>
              <div className={s.noDataIcon}>📊</div>
              <p className={s.noDataText}>아직 가격 데이터가 충분하지 않습니다</p>
              <p className={s.noDataSub}>{historyMessage || '데이터가 수집되면 가격 추이, 적정가, 마트별 비교를 확인할 수 있어요'}</p>
              {currentOffer && (!normalizedCatalog || isObservationReceiptEligible(currentOffer)) && (
                <div className={s.currentOfferCard}>
                  <span>{normalizedCatalog ? '관측 가격' : '저장 관측 가격'}</span>
                  <strong>{fmt(currentOffer.price)}원</strong>
                  {currentOffer.source && <em>{currentOffer.source}</em>}
                </div>
              )}
              <p>수집 요청 기능은 제공되지 않습니다.</p>
            </div>
          )}
          {normalizedCatalog && activeVariant && (
            <div className={s.variantSec}>
              <span className={s.variantLabel}>판매처와 구매 조건</span>
              {(activeVariant.listings || []).map(listing => {
                const offer = listing.offers?.[0];
                return <div key={listing.id}>
                  <button type="button" aria-pressed={listing.id === activeListing?.id} onClick={() => setSelectedListingId(listing.id)}>{listing.source} · {listing.title}</button>
                  {offer?.listed_price != null && <span> · 표시 가격 {getObservedOfferPriceText(offer)}</span>}
                  <small> · 관측일 {(offer?.crawled_at || offer?.observed_at || '').slice(0,10) || '미확인'}</small>
                  <OfferFacts offer={offer} variant={activeVariant} components={activeVariant.quantity_components || []} />
                </div>;
              })}
            </div>
          )}
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
                    {normalizedCatalog && selectedHistory.comparableCount > 0 && <p>선택 규격·같은 수령 및 행사 조건의 관측 통계: 최저 {displayLow > 0 ? `${fmt(displayLow)}원` : '미확인'} · 평균 {displayAvg > 0 ? `${fmt(displayAvg)}원` : '미확인'} · 최고 {displayHigh > 0 ? `${fmt(displayHigh)}원` : '미확인'} ({selectedHistory.comparableCount}건)</p>}
                    {chartLoading ? (
                      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: 220 }}>
                        <Spinner />
                        <p style={{ marginTop: 8, color: 'var(--text3)', fontSize: '.85rem' }}>차트 데이터 로딩 중...</p>
                      </div>
                    ) : chartData.length === 0 ? normalizedCatalog && activeOffer?.listed_price != null ? (
                      <p role="status">선택 기간에 관측 이력이 없습니다. 90일 또는 1년을 선택해 이전 관측을 확인하세요.</p>
                    ) : (
                      <div className={s.historyEmpty}>
                        <EmptyState
                          title="가격 이력이 없습니다"
                          description={historyMessage || '아직 기간별 가격 데이터가 충분하지 않습니다.'}
                        />
                        {currentOffer && (!normalizedCatalog || isObservationReceiptEligible(currentOffer)) && (
                          <div className={s.currentOfferCard}>
                            <span>{normalizedCatalog ? '관측 가격' : '저장 관측 가격'}</span>
                            <strong>{fmt(currentOffer.price)}원</strong>
                            {currentOffer.source && <em>{currentOffer.source}</em>}
                          </div>
                        )}
                      </div>
                    ) : (
                      <>
                        {historyPointCount < 2 && (
                          <div className={s.sparseNotice}>{historyMessage || '가격 이력이 적어 추세 판단은 제한적입니다.'}</div>
                        )}
                        {normalizedCatalog && selectedHistory.corrections.length > 0 && <p>보존 원문 해석 교정 {selectedHistory.corrections.length}건 · 새 수집 관측이 아닙니다. 원가격·관측 시각은 원문 이력에 보존합니다.</p>}
                        {normalizedCatalog && <p>표시 가격 이력 {chartData.length}건 · 점은 저장된 관측 기록입니다. 선은 관측점 연결이며, 사이 날짜의 가격 확인을 뜻하지 않습니다.</p>}
                        {normalizedCatalog && chartData.some(point => !isObservationReceiptEligible(point) || !(point.comparable_price > 0) || (point.offer_state && point.offer_state !== 'active')) && <p>표시 가격 이력에는 비교 조건이 미확인인 관측도 포함됩니다.</p>}
                        <ResponsiveContainer width="100%" height={220}>
                          <AreaChart data={chartData}>
                            <defs>
                              <linearGradient id="colorPrice" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="5%" stopColor="#38bdf8" stopOpacity={0.2} />
                                <stop offset="95%" stopColor="#38bdf8" stopOpacity={0} />
                              </linearGradient>
                            </defs>
                            <XAxis dataKey="date" tickFormatter={value => String(value).slice(0,10)} interval="preserveStartEnd" tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} />
                            <YAxis tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} width={50} tickFormatter={v => fmt(v)} />
                            <Tooltip
                              content={normalizedCatalog ? ({active,payload}) => active && payload?.[0]?.payload ? <div style={{background:'var(--surface)',padding:12}}><strong>{payload[0].payload.date} · 관측 표시 가격 {getObservedOfferPriceText(payload[0].payload, payload[0].payload.price)}</strong><p>{getOfferConditionText(payload[0].payload)}</p>{isObservationReceiptEligible(payload[0].payload) && payload[0].payload.total_price > 0 && <p>{getOfferAmountLabel(payload[0].payload)} {fmt(payload[0].payload.total_price)}원</p>}{(!isObservationReceiptEligible(payload[0].payload) || payload[0].payload.comparable_price == null) && <p>비교 조건 미확인</p>}</div> : null : undefined}
                              contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, fontSize: '.85rem' }}
                              formatter={v => [`${fmt(v)}원`, '가격']}
                            />
                            <Area type="linear" dataKey="price" dot={{r:3}} stroke="#38bdf8" strokeWidth={2} fill="url(#colorPrice)" />
                          </AreaChart>
                        </ResponsiveContainer>
                        {normalizedCatalog && <details><summary>관측별 구매 조건</summary>{chartData.map((point,index) => <p key={point.id || `${point.date}-${index}`}>{point.date} · 관측 표시 가격 {getObservedOfferPriceText(point, point.price)} · {getOfferConditionText(point)}{isObservationReceiptEligible(point) && point.total_price > 0 ? ` · ${getOfferAmountLabel(point)} ${fmt(point.total_price)}원` : ''}{!isObservationReceiptEligible(point) || point.comparable_price == null ? ' · 비교 조건 미확인' : ''}</p>)}</details>}
                      </>
                    )}
                  </div>

          <ObservedExpertStats stats={activeStats} />
        </div>

        {/* 우측 사이드바 */}
        {!normalizedCatalog && <aside className={s.right}>
          <>
          {/* 마트별 바 차트 */}
          <div className={s.barChartBox}>
            <h4>마트별 저장 관측 가격</h4>
            <small>규격·수령량·구매 조건의 호환 여부 미확인</small>
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={martBarData} layout="vertical" margin={{ left: 10, right: 10 }}>
                <XAxis type="number" tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={v => fmt(v)} />
                <YAxis type="category" dataKey="name" tick={{ fill: '#94a3b8', fontSize: 12 }} axisLine={false} tickLine={false} width={60} />
                <Tooltip
                  contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, fontSize: '.85rem' }}
                  formatter={v => [`${fmt(v)}원`, '가격']}
                />
                <Bar dataKey="price" radius={[0, 6, 6, 0]} barSize={20}>
                  {martBarData.map((entry, index) => (
                    <Cell key={entry.name || entry.mart || `cell-${index}`} fill={entry.color} fillOpacity={0.7} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          <h4>마트별 저장 가격</h4>
          <div className={s.martList}>
            {MARTS.map(m => {
              const price = product.stores?.[m.key];
              if (price == null) return null;
              return (
                <div key={m.key} className={s.mlItem}>
                  <div className={s.mlLeft}>
                    <span className={s.mlDot} style={{ background: m.color }} />
                    <span className={s.mlName}>{m.name}</span>
                  </div>
                  <div>
                    <span className={s.mlPrice}>{fmt(price)}원</span>

                  </div>
                </div>
              );
            })}
          </div>

          </>
        </aside>}
      </div>
    </div>
  );
}
