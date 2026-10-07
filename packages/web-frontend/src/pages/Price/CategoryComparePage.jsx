import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { fmt, fmtUnitPrice } from '../../utils/helpers';
import { searchService } from '../../services/searchService';
import Spinner from '../../components/common/Spinner';
import { getOfferConditionText } from '../../utils/productDecision';
import s from './CategoryComparePage.module.css';

const RANK_CONFIG = {
  ultra:     { label: '초특가', color: '#3B82F6', icon: '🔥🔥' },
  hotdeal:   { label: '핫딜',   color: '#10B981', icon: '🔥' },
  fair:      { label: '적정가', color: '#F59E0B', icon: '👍' },
  expensive: { label: '비쌈',   color: '#EF4444', icon: '💸' },
  unknown:   { label: '비교 미확인', color: '#64748B', icon: '' },
};

const SORT_OPTIONS = [
  { value: 'price_asc',  label: '단위가↑' },
  { value: 'price_desc', label: '단위가↓' },
  { value: 'discount',   label: '할인율' },
  { value: 'recent',     label: '최신' },
];

function positive(value) {
  return value != null && value !== '' && Number.isFinite(Number(value)) && Number(value) > 0;
}

function money(value, suffix = '') {
  return positive(value) ? `${suffix ? fmtUnitPrice(value, '₩') : `₩${fmt(value)}`}${suffix}` : '미확인';
}

function basisLabel(basis) {
  return basis?.startsWith('variant:') ? '동일 규격의 판매 단위' : basis;
}

function comparisonValue(product, summary) {
  const basis = summary?.comparison_basis;
  if (
    basis
    && product.normalized?.basis === basis
    && positive(product.normalized?.unit_price)
    && product.best_offer?.current_eligible !== false
    && (!product.best_offer?.offer_state || product.best_offer.offer_state === 'active')
  ) {
    return product.normalized.unit_price;
  }
  return null;
}

function displayPrice(product) {
  const unitPrice = product.normalized?.unit_price;
  const basis = product.normalized?.basis;
  if (positive(unitPrice) && basis) {
    return { value: unitPrice, suffix: `/${basisLabel(basis)}`, normalized: true };
  }
  return { value: null, suffix: '', normalized: false };
}

function getRank(product, summary) {
  const price = comparisonValue(product, summary);
  if (price == null || !positive(summary?.avg_comparison_price)) return 'unknown';
  if (summary.ultra_threshold && price <= summary.ultra_threshold) return 'ultra';
  if (summary.hotdeal_threshold && price <= summary.hotdeal_threshold) return 'hotdeal';
  if (summary.avg_comparison_price && price <= summary.avg_comparison_price) return 'fair';
  return 'expensive';
}

function getPercentile(product, summary) {
  const price = comparisonValue(product, summary);
  const minimum = summary?.min_comparison_price;
  const maximum = summary?.max_comparison_price;
  if (price == null || !positive(minimum) || !positive(maximum)) return null;
  const range = maximum - minimum;
  if (range <= 0) return 50;
  return Math.max(0, Math.min(100, Math.round(((price - minimum) / range) * 100)));
}

function OfferFacts({ product }) {
  const offer = product.promotion || product.best_offer;
  if (!offer) return <p className={s.offerFacts}>거래 금액·판매 수량·구매 조건 미확인</p>;
  const conditions = { ...offer, promotion_condition: offer.promotion_condition ?? offer.condition };
  const spend = offer.total_price ?? offer.total_spend;
  const spec = offer.display_unit || product.normalized?.unit_price_display;
  return <div className={s.offerFacts}>
    {spec && <div>규격 {spec}</div>}
    <div>거래 금액 {money(spend)}</div>
    {positive(offer.listed_price) && <div>표시 가격 {money(offer.listed_price)}</div>}
    <div>{getOfferConditionText(conditions)}</div>
  </div>;
}

/* ── Sub-components ── */

const PricePositionBar = React.memo(function PricePositionBar({ percentile, rank }) {
  if (percentile == null || rank === 'unknown') return <div className={s.offerFacts}>단위 비교 미확인</div>;
  const cfg = RANK_CONFIG[rank] || RANK_CONFIG.fair;
  return (
    <div className={s.priceBar}>
      <div
        className={s.priceBarFill}
        style={{ width: `${Math.max(percentile, 4)}%`, background: cfg.color }}
      />
      {percentile <= 50 && (
        <span className={s.priceBarRankLabel}>
          {cfg.icon} {cfg.label} · 표시 조건 기준
        </span>
      )}
      <span className={s.priceBarLabel}>단위가 범위 위치 {percentile}%</span>
    </div>
  );
});

function CategoryBreadcrumb({ categoryPath, categoryId, navigate }) {
  if (!categoryPath && !categoryId) return null;

  const parts = categoryPath
    ? categoryPath.split(' > ')
    : categoryId.split('.').map((_, i, arr) => arr.slice(0, i + 1).join('.'));

  const idParts = categoryId ? categoryId.split('.') : [];

  return (
    <nav className={s.breadcrumb}>
      <span
        className={s.breadcrumbLink}
        onClick={() => navigate('/price')}
      >
        🏷️ 가격
      </span>
      <span className={s.breadcrumbSep}>›</span>
      {parts.map((part, i) => {
        const isLast = i === parts.length - 1;
        const linkId = idParts.slice(0, i + 1).join('.');
        return (
          <span key={linkId || `bc-${i}`}>
            {isLast ? (
              <span className={s.breadcrumbCurrent}>{part}</span>
            ) : (
              <>
                <span
                  className={s.breadcrumbLink}
                  onClick={() => navigate(`/price/category/${linkId}`)}
                >
                  {part}
                </span>
                <span className={s.breadcrumbSep}> › </span>
              </>
            )}
          </span>
        );
      })}
    </nav>
  );
}

const SummaryCards = React.memo(function SummaryCards({ summary }) {
  if (!summary) return null;
  if (summary.is_leaf === false) {
    return (
      <div className={s.summaryCards}>
        <div className={`${s.summaryCard} ${s.summaryCount}`}>
          <span className={s.summaryLabel}>하위 상품</span>
          <span className={s.summaryValue}>{fmt(summary.product_count)}개</span>
        </div>
        <div className={`${s.summaryCard} ${s.summaryAvg}`}>
          <span className={s.summaryLabel}>비교 기준</span>
          <span className={s.summaryValue}>세부 카테고리 선택</span>
        </div>
      </div>
    );
  }

  const basis = summary.comparison_basis;
  const suffix = basis ? `/${basisLabel(basis)}` : '';
  return (
    <div className={s.summaryCards}>
      <div className={`${s.summaryCard} ${s.summaryAvg}`}>
        <span className={s.summaryLabel}>평균 단위가 · 표시 조건 기준</span>
        <span className={s.summaryValue}>{money(basis ? summary.avg_comparison_price : null, suffix)}</span>
      </div>
      <div className={`${s.summaryCard} ${s.summaryMin}`}>
        <span className={s.summaryLabel}>최저 단위가 · 표시 조건 기준</span>
        <span className={s.summaryValue}>{money(basis ? summary.min_comparison_price : null, suffix)}</span>
      </div>
      <div className={`${s.summaryCard} ${s.summaryHotdeal}`}>
        <span className={s.summaryLabel}>핫딜기준</span>
        <span className={s.summaryValue}>{money(basis ? summary.hotdeal_threshold : null, suffix)}</span>
      </div>
      <div className={`${s.summaryCard} ${s.summaryCount}`}>
        <span className={s.summaryLabel}>상품수</span>
        <span className={s.summaryValue}>{fmt(summary.product_count)}개</span>
      </div>
    </div>
  );
});

const ProductCard = React.memo(function ProductCard({ product, summary, rank, percentile, onClick }) {
  const cfg = RANK_CONFIG[rank] || RANK_CONFIG.fair;
  const isBest = rank === 'ultra';
  const shown = displayPrice(product);
  const current = product.price?.current;
  const original = product.price?.original;
  const discountPct = product.price?.discount_pct;
  const tags = [
    product.attributes?.storage,
    product.attributes?.origin,
    product.attributes?.usage,
  ].filter(Boolean);

  return (
    <div
      className={`${s.productCard} ${isBest ? s.bestCard : ''}`}
      onClick={onClick}
    >
      <div className={s.cardHeader}>
        <div className={s.cardTitle}>
          <span className={s.cardBadge} style={{ background: cfg.color }}>
            {cfg.icon} {cfg.label}{rank !== 'unknown' ? ' · 표시 조건 기준' : ''}
          </span>
          {product.name}
        </div>
        <span className={s.cardSource}>{product.source || product.brand || ''}</span>
      </div>

      <div className={s.cardPriceRow}>
        <span className={s.cardPrice}>{money(shown.value, shown.suffix)}</span>
        {original && original !== current && (
          <span className={s.cardOriginal}>원가 ₩{fmt(original)}</span>
        )}
        {discountPct != null && discountPct > 0 && (
          <span className={s.cardDiscount}>-{discountPct}%</span>
        )}
      </div>

      <OfferFacts product={product} />

      {tags.length > 0 && (
        <div className={s.cardTags}>
          {tags.map((t) => (
            <span key={t} className={s.cardTag}>{t}</span>
          ))}
        </div>
      )}

      <PricePositionBar percentile={percentile} rank={rank} />
    </div>
  );
});

const ProductTable = React.memo(function ProductTable({ products, summary, onRowClick }) {
  return (
    <table className={s.table}>
      <thead>
        <tr>
          <th>등급</th>
          <th>상품명</th>
          <th>비교가</th>
          <th>거래 금액·구매 조건</th>
          <th>할인</th>
          <th>보관</th>
          <th>원산지</th>
          <th>출처</th>
        </tr>
      </thead>
      <tbody>
        {products.map((p) => {
          const rank = getRank(p, summary);
          const cfg = RANK_CONFIG[rank] || RANK_CONFIG.fair;
          const shown = displayPrice(p);
          return (
            <tr key={p.id} onClick={() => onRowClick(p)} style={{ cursor: 'pointer' }}>
              <td>
                <span style={{ color: cfg.color, fontWeight: 600 }}>
                  {cfg.icon} {cfg.label}{rank !== 'unknown' ? ' · 표시 조건 기준' : ''}
                </span>
              </td>
              <td>{p.name}</td>
              <td className={s.tablePrice}>{money(shown.value, shown.suffix)}</td>
              <td><OfferFacts product={p} /></td>
              <td className={s.tableDiscount}>
                {p.price?.discount_pct > 0 ? `-${p.price.discount_pct}%` : '-'}
              </td>
              <td>{p.attributes?.storage || '-'}</td>
              <td>{p.attributes?.origin || '-'}</td>
              <td>{p.source || p.brand || '-'}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
});

const AlternativesSection = React.memo(function AlternativesSection({ alternatives, navigate, currentAvg, currentBasis }) {
  if (!alternatives || alternatives.length === 0) return null;

  return (
    <div className={s.alternatives}>
      <div className={s.alternativesTitle}>💡 대안 카테고리</div>
      {alternatives.map((alt, i) => {
        const alternativeAvg = alt.avg_comparison_price ?? alt.avg_unit_price ?? alt.avg_per_100g;
        const diff = currentBasis && alt.comparison_basis === currentBasis && positive(currentAvg) && positive(alternativeAvg)
          ? Math.round(((alternativeAvg - currentAvg) / currentAvg) * 100)
          : null;
        const cheaper = diff != null && diff < 0;
        const basis = alt.comparison_basis || '';

        return (
          <div
            key={alt.category_id || alt.name || `alt-${i}`}
            className={s.altItem}
            onClick={() => alt.category_id && navigate(`/price/category/${alt.category_id}`)}
          >
            <span className={s.altIcon}>💡</span>
            <span>
              {alt.name || alt.category_id}은(는) 평균 {money(basis ? alternativeAvg : null, basis ? `/${basisLabel(basis)}` : '')}
            </span>
            {diff != null && (
              <span className={cheaper ? s.altSaving : s.altExpensive}>
                ({Math.abs(diff)}% {cheaper ? '저렴' : '비쌈'} · 표시 조건 기준)
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
});

/* ── Main Component ── */

export default function CategoryComparePage() {
  const { categoryId } = useParams();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const comparisonBasis = searchParams.get('comparison_basis') || null;

  const [products, setProducts] = useState([]);
  const [summary, setSummary] = useState(null);
  const [subcategories, setSubcategories] = useState([]);
  const [alternatives, setAlternatives] = useState([]);
  const [pagination, setPagination] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [sort, setSort] = useState('price_asc');
  const [viewMode, setViewMode] = useState('card');
  const [pageState, setPageState] = useState({ key: '', page: 1 });
  const queryKey = JSON.stringify([categoryId, comparisonBasis, sort]);
  const page = pageState.key === queryKey ? pageState.page : 1;
  const setPage = (value) => setPageState((previous) => ({
    key: queryKey,
    page: typeof value === 'function' ? value(previous.key === queryKey ? previous.page : 1) : value,
  }));
  const latestRequest = useRef(0);

  useEffect(() => {
    setPageState((previous) => previous.key === queryKey ? previous : { key: queryKey, page: 1 });
  }, [queryKey]);

  const fetchData = useCallback(async (signal) => {
    if (!categoryId) return;
    const requestId = ++latestRequest.current;
    setLoading(true);
    setError(null);
    try {
      const data = await searchService.categoryCompare(categoryId, {
        sort,
        page,
        perPage: 20,
        comparisonBasis,
        signal,
      });
      if (signal?.aborted || requestId !== latestRequest.current) return;
      setSummary(data.summary || null);
      setSubcategories(data.subcategories || []);
      setProducts(data.products || []);
      setAlternatives(data.alternatives || []);
      setPagination(data.pagination || null);
    } catch (err) {
      if (signal?.aborted || requestId !== latestRequest.current || err.name === 'AbortError') return;
      console.error('CategoryCompare fetch error:', err);
      setError(err.message || '카테고리 비교 데이터를 불러오는 중 오류가 발생했습니다');
      setSummary(null);
      setSubcategories([]);
      setProducts([]);
      setAlternatives([]);
      setPagination(null);
    } finally {
      if (!signal?.aborted && requestId === latestRequest.current) setLoading(false);
    }
  }, [categoryId, comparisonBasis, sort, page]);

  useEffect(() => {
    const controller = new AbortController();
    fetchData(controller.signal);
    return () => controller.abort();
  }, [fetchData]);

  const selectBasis = (basis) => setSearchParams((previous) => {
    const next = new URLSearchParams(previous);
    if (basis) next.set('comparison_basis', basis);
    else next.delete('comparison_basis');
    return next;
  });

  const enrichedProducts = useMemo(() => {
    return products.map((p) => ({
      ...p,
      _rank: getRank(p, summary),
      _percentile: getPercentile(p, summary),
    }));
  }, [products, summary]);

  const handleProductClick = useCallback(
    (product) => {
      if (product.id) navigate(`/price/${product.id}`);
    },
    [navigate],
  );

  if (!categoryId) {
    return (
      <div className={s.page}>
        <div className={s.emptyState}>
          <div className={s.emptyIcon}>📂</div>
          <div className={s.emptyText}>카테고리를 선택해주세요</div>
        </div>
      </div>
    );
  }

  return (
    <div className={s.page}>
      <CategoryBreadcrumb
        categoryPath={summary?.category_path}
        categoryId={categoryId}
        navigate={navigate}
      />

      {loading && (
        <div className={s.loadingWrap}>
          <Spinner />
          <span>카테고리 비교 데이터를 불러오는 중입니다</span>
        </div>
      )}

      {!loading && error && (
        <div className={s.errorState}>
          <div className={s.errorIcon}>⚠️</div>
          <div className={s.errorText}>데이터를 불러오는 데 실패했습니다</div>
          <p>{error}</p>
          <button className={s.retryBtn} onClick={() => fetchData()}>
            다시 시도
          </button>
        </div>
      )}

      {!loading && !error && (
        <>
          <SummaryCards summary={summary} />
          {summary?.comparison_groups?.length > 0 && (
            <div className={s.filters} role="group" aria-label="비교 단위 선택">
              <span className={s.filterLabel}>비교 단위:</span>
              <button
                type="button"
                className={`${s.filterBtn} ${!comparisonBasis ? s.filterBtnActive : ''}`}
                aria-pressed={!comparisonBasis}
                onClick={() => selectBasis(null)}
              >전체 상품</button>
              {summary.comparison_groups.map((group, index) => (
                <button
                  key={group.basis}
                  type="button"
                  className={`${s.filterBtn} ${comparisonBasis === group.basis ? s.filterBtnActive : ''}`}
                  aria-pressed={comparisonBasis === group.basis}
                  onClick={() => selectBasis(group.basis)}
                >
                  {group.basis.startsWith('variant:') ? `동일 규격 그룹 ${index + 1}` : group.basis}
                  {' · '}{fmt(group.product_count)}개 상품
                </button>
              ))}
            </div>
          )}
          {products.length > 0 && <p className={s.offerFacts}>{summary?.comparison_basis
            ? `${basisLabel(summary.comparison_basis)} 기준의 표시 가격을 비교합니다. 상품별 최소 구매·회원·쿠폰 조건을 확인하세요.`
            : '공통 비교 단위가 없어 가격 순위를 표시하지 않습니다.'}</p>}

          {subcategories.length > 0 && (
            <section className={s.subcategorySection}>
              <h3>세부 카테고리</h3>
              <div className={s.subcategoryGrid}>
                {subcategories.map((cat) => (
                  <button
                    key={cat.id}
                    type="button"
                    className={s.subcategoryCard}
                    onClick={() => navigate(`/price/category/${encodeURIComponent(cat.id)}`)}
                  >
                    <span>{cat.name}</span>
                    <small>{cat.count}개 상품</small>
                  </button>
                ))}
              </div>
            </section>
          )}

          {products.length > 0 && (
            <div className={s.sortBar}>
              <div className={s.sortGroup}>
                <span className={s.filterLabel}>정렬:</span>
                {SORT_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    className={`${s.sortBtn} ${sort === opt.value ? s.sortBtnActive : ''}`}
                    disabled={opt.value.startsWith('price_') && !summary?.comparison_basis}
                    onClick={() => setSort(opt.value)}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
              <div className={s.viewToggle}>
                <button
                  className={`${s.viewBtn} ${viewMode === 'card' ? s.viewBtnActive : ''}`}
                  onClick={() => setViewMode('card')}
                >
                  카드
                </button>
                <button
                  className={`${s.viewBtn} ${viewMode === 'table' ? s.viewBtnActive : ''}`}
                  onClick={() => setViewMode('table')}
                >
                  테이블
                </button>
              </div>
            </div>
          )}

          {products.length === 0 && subcategories.length === 0 && (
            <div className={s.emptyState}>
              <div className={s.emptyIcon}>📦</div>
              <div className={s.emptyText}>이 카테고리에 등록된 상품이 없습니다</div>
              <div className={s.emptySub}>곧 데이터가 추가될 예정입니다.</div>
            </div>
          )}

          {products.length > 0 && viewMode === 'card' && (
            <div className={s.productList}>
              {enrichedProducts.map((p) => (
                <ProductCard
                  key={p.id}
                  product={p}
                  summary={summary}
                  rank={p._rank}
                  percentile={p._percentile}
                  onClick={() => handleProductClick(p)}
                />
              ))}
            </div>
          )}

          {products.length > 0 && viewMode === 'table' && (
            <ProductTable
              products={enrichedProducts}
              summary={summary}
              onRowClick={handleProductClick}
            />
          )}

          {pagination && pagination.total_pages > 1 && (
            <div className={s.pagination}>
              <button
                className={s.pageBtn}
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                ← 이전
              </button>
              <span className={s.pageInfo}>
                {page} / {pagination.total_pages}
              </span>
              <button
                className={s.pageBtn}
                disabled={page >= pagination.total_pages}
                onClick={() => setPage((p) => p + 1)}
              >
                다음 →
              </button>
            </div>
          )}

          <AlternativesSection
            alternatives={alternatives}
            navigate={navigate}
            currentAvg={summary?.avg_comparison_price}
            currentBasis={summary?.comparison_basis}
          />
        </>
      )}
    </div>
  );
}
