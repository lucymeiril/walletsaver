import { useParams, useNavigate } from 'react-router-dom';
import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { fmt } from '../../utils/helpers';
import { searchService } from '../../services/searchService';
import Spinner from '../../components/common/Spinner';
import s from './CategoryComparePage.module.css';

const RANK_CONFIG = {
  ultra:     { label: '초특가', color: '#3B82F6', icon: '🔥🔥' },
  hotdeal:   { label: '핫딜',   color: '#10B981', icon: '🔥' },
  fair:      { label: '적정가', color: '#F59E0B', icon: '👍' },
  expensive: { label: '비쌈',   color: '#EF4444', icon: '💸' },
};

const SORT_OPTIONS = [
  { value: 'price_asc',  label: '가격↑' },
  { value: 'price_desc', label: '가격↓' },
  { value: 'discount',   label: '할인율' },
  { value: 'recent',     label: '최신' },
];

const STORAGE_OPTIONS = [
  { value: null, label: '전체' },
  { value: '냉장', label: '냉장' },
  { value: '냉동', label: '냉동' },
];

const ORIGIN_OPTIONS = [
  { value: null, label: '전체' },
  { value: '국산', label: '국산' },
  { value: '수입', label: '수입' },
];

function getRank(product, summary) {
  if (product.price_rank) return product.price_rank;
  const price = product.normalized?.per_100g ?? product.price?.current;
  if (!price || !summary) return 'fair';
  if (summary.ultra_threshold && price <= summary.ultra_threshold) return 'ultra';
  if (summary.hotdeal_threshold && price <= summary.hotdeal_threshold) return 'hotdeal';
  if (summary.avg_price_per_100g && price <= summary.avg_price_per_100g) return 'fair';
  return 'expensive';
}

function getPercentile(product, summary) {
  if (product.percentile != null) return product.percentile;
  const price = product.normalized?.per_100g ?? product.price?.current;
  if (!price || !summary?.min_price_per_100g || !summary?.max_price_per_100g) return 50;
  const range = summary.max_price_per_100g - summary.min_price_per_100g;
  if (range <= 0) return 50;
  return Math.round(((price - summary.min_price_per_100g) / range) * 100);
}

/* ── Sub-components ── */

const PricePositionBar = React.memo(function PricePositionBar({ percentile, rank }) {
  const cfg = RANK_CONFIG[rank] || RANK_CONFIG.fair;
  return (
    <div className={s.priceBar}>
      <div
        className={s.priceBarFill}
        style={{ width: `${Math.max(percentile, 4)}%`, background: cfg.color }}
      />
      {percentile <= 50 && (
        <span className={s.priceBarRankLabel}>
          {cfg.icon} {cfg.label}
        </span>
      )}
      <span className={s.priceBarLabel}>하위 {percentile}%</span>
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
  return (
    <div className={s.summaryCards}>
      <div className={`${s.summaryCard} ${s.summaryAvg}`}>
        <span className={s.summaryLabel}>평균가</span>
        <span className={s.summaryValue}>₩{fmt(summary.avg_price_per_100g)}/100g</span>
      </div>
      <div className={`${s.summaryCard} ${s.summaryMin}`}>
        <span className={s.summaryLabel}>최저가</span>
        <span className={s.summaryValue}>₩{fmt(summary.min_price_per_100g)}</span>
      </div>
      <div className={`${s.summaryCard} ${s.summaryHotdeal}`}>
        <span className={s.summaryLabel}>핫딜기준</span>
        <span className={s.summaryValue}>₩{fmt(summary.hotdeal_threshold)}</span>
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
  const isBest = percentile <= 10 || rank === 'ultra';
  const price100g = product.normalized?.per_100g ?? product.price?.current;
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
            {cfg.icon} {cfg.label}
          </span>
          {isBest && <span className={s.cardBadge} style={{ background: '#10B981' }}>🏆 Best</span>}
          {product.name}
        </div>
        <span className={s.cardSource}>{product.source || product.brand || ''}</span>
      </div>

      <div className={s.cardPriceRow}>
        <span className={s.cardPrice}>₩{fmt(price100g)}/100g</span>
        {original && <span className={s.cardOriginal}>원가 ₩{fmt(original)}</span>}
        {discountPct != null && discountPct > 0 && (
          <span className={s.cardDiscount}>-{discountPct}%</span>
        )}
      </div>

      {tags.length > 0 && (
        <div className={s.cardTags}>
          {tags.map((t, i) => (
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
          <th>100g당</th>
          <th>원가</th>
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
          const price100g = p.normalized?.per_100g ?? p.price?.current;
          return (
            <tr key={p.id} onClick={() => onRowClick(p)} style={{ cursor: 'pointer' }}>
              <td>
                <span style={{ color: cfg.color, fontWeight: 600 }}>
                  {cfg.icon} {cfg.label}
                </span>
              </td>
              <td>{p.name}</td>
              <td className={s.tablePrice}>₩{fmt(price100g)}</td>
              <td>{p.price?.original ? `₩${fmt(p.price.original)}` : '-'}</td>
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

const AlternativesSection = React.memo(function AlternativesSection({ alternatives, navigate, currentAvg }) {
  if (!alternatives || alternatives.length === 0) return null;

  return (
    <div className={s.alternatives}>
      <div className={s.alternativesTitle}>💡 대안 카테고리</div>
      {alternatives.map((alt, i) => {
        const diff = currentAvg && alt.avg_per_100g
          ? Math.round(((alt.avg_per_100g - currentAvg) / currentAvg) * 100)
          : alt.saving_pct != null ? -alt.saving_pct : null;
        const cheaper = diff != null && diff < 0;

        return (
          <div
            key={alt.category_id || alt.name || `alt-${i}`}
            className={s.altItem}
            onClick={() => alt.category_id && navigate(`/price/category/${alt.category_id}`)}
          >
            <span className={s.altIcon}>💡</span>
            <span>
              {alt.name || alt.category_id}은(는) 평균 ₩{fmt(alt.avg_per_100g || alt.avg_100g)}/100g
            </span>
            {diff != null && (
              <span className={cheaper ? s.altSaving : s.altExpensive}>
                ({Math.abs(diff)}% {cheaper ? '저렴' : '비쌈'})
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
  // ALL hooks at the top, unconditionally
  const { categoryId } = useParams();
  const navigate = useNavigate();

  const [products, setProducts] = useState([]);
  const [summary, setSummary] = useState(null);
  const [subcategories, setSubcategories] = useState([]);
  const [alternatives, setAlternatives] = useState([]);
  const [pagination, setPagination] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [filters, setFilters] = useState({
    storage: null,
    origin: null,
    usage: null,
    source: null,
  });
  const [sort, setSort] = useState('price_asc');
  const [viewMode, setViewMode] = useState('card');
  const [page, setPage] = useState(1);

  const fetchData = useCallback(async (signal) => {
    if (!categoryId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await searchService.categoryCompare(categoryId, {
        sort,
        storage: filters.storage,
        origin: filters.origin,
        usage: filters.usage,
        source: filters.source,
        page,
        perPage: 20,
      });
      if (signal?.aborted) return;
      setSummary(data.summary || null);
      setSubcategories(data.subcategories || []);
      setProducts(data.products || []);
      setAlternatives(data.alternatives || []);
      setPagination(data.pagination || null);
    } catch (err) {
      if (err.name === 'AbortError') return;
      console.error('CategoryCompare fetch error:', err);
      setError(err.message || '카테고리 비교 데이터를 불러오는 중 오류가 발생했습니다');
      setSummary(null);
      setSubcategories([]);
      setProducts([]);
      setAlternatives([]);
    } finally {
      setLoading(false);
    }
  }, [categoryId, sort, filters, page]);

  useEffect(() => {
    const controller = new AbortController();
    fetchData(controller.signal);
    return () => controller.abort();
  }, [fetchData]);

  // Reset page when filters or sort change
  useEffect(() => {
    setPage(1);
  }, [sort, filters]);

  const enrichedProducts = useMemo(() => {
    return products.map((p) => ({
      ...p,
      _rank: getRank(p, summary),
      _percentile: getPercentile(p, summary),
    }));
  }, [products, summary]);

  const handleFilterChange = useCallback((key, value) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
  }, []);

  const handleProductClick = useCallback(
    (product) => {
      if (product.id) navigate(`/price/${product.id}`);
    },
    [navigate],
  );

  // ── Render ──

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
      {/* Breadcrumb */}
      <CategoryBreadcrumb
        categoryPath={summary?.category_path}
        categoryId={categoryId}
        navigate={navigate}
      />

      {/* Loading */}
      {loading && (
        <div className={s.loadingWrap}>
          <Spinner />
          <span>카테고리 비교 데이터를 불러오는 중입니다</span>
        </div>
      )}

      {/* Error (graceful degradation) */}
      {!loading && error && (
        <div className={s.errorState}>
          <div className={s.errorIcon}>⚠️</div>
          <div className={s.errorText}>데이터를 불러오는 데 실패했습니다</div>
          <button className={s.retryBtn} onClick={fetchData}>
            다시 시도
          </button>
        </div>
      )}

      {/* Data loaded */}
      {!loading && !error && (
        <>
          {/* Summary */}
          <SummaryCards summary={summary} />

          {/* Filters */}
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

          {/* Filters */}
          {products.length > 0 && (
          <div className={s.filters}>
            <div className={s.filterGroup}>
              <span className={s.filterLabel}>보관:</span>
              {STORAGE_OPTIONS.map((opt) => (
                <button
                  key={opt.label}
                  className={`${s.filterBtn} ${filters.storage === opt.value ? s.filterBtnActive : ''}`}
                  onClick={() => handleFilterChange('storage', opt.value)}
                >
                  {opt.label}
                </button>
              ))}
            </div>
            <div className={s.filterGroup}>
              <span className={s.filterLabel}>원산지:</span>
              {ORIGIN_OPTIONS.map((opt) => (
                <button
                  key={opt.label}
                  className={`${s.filterBtn} ${filters.origin === opt.value ? s.filterBtnActive : ''}`}
                  onClick={() => handleFilterChange('origin', opt.value)}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
          )}

          {/* Sort & View toggle */}
          {products.length > 0 && (
          <div className={s.sortBar}>
            <div className={s.sortGroup}>
              <span className={s.filterLabel}>정렬:</span>
              {SORT_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  className={`${s.sortBtn} ${sort === opt.value ? s.sortBtnActive : ''}`}
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

          {/* Empty */}
          {products.length === 0 && subcategories.length === 0 && (
            <div className={s.emptyState}>
              <div className={s.emptyIcon}>📦</div>
              <div className={s.emptyText}>이 카테고리에 등록된 상품이 없습니다</div>
              <div className={s.emptySub}>곧 데이터가 추가될 예정입니다.</div>
            </div>
          )}

          {/* Product List — Card View */}
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

          {/* Product List — Table View */}
          {products.length > 0 && viewMode === 'table' && (
            <ProductTable
              products={enrichedProducts}
              summary={summary}
              onRowClick={handleProductClick}
            />
          )}

          {/* Pagination */}
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

          {/* Alternatives */}
          <AlternativesSection
            alternatives={alternatives}
            navigate={navigate}
            currentAvg={summary?.avg_price_per_100g}
          />
        </>
      )}
    </div>
  );
}
