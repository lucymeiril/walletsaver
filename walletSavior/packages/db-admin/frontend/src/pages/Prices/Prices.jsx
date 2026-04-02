import { useState, useMemo, useEffect } from 'react';
import { AlertTriangle, Settings, Search, BarChart3 } from 'lucide-react';
import useDbAdminStore from '../../stores/dbAdminStore';
import s from './Prices.module.css';

export default function Prices() {
  const {
    products, priceOutliers, priceTiers, priceStats,
    priceHistoryPage, tierSaving,
    updatePriceTier, fetchTierConfig, saveTierConfig,
    fetchOutliers, fetchPriceHistory, fetchPriceStats, fetchProducts,
  } = useDbAdminStore();

  const [tab, setTab] = useState('tiers');
  const [priceSearch, setPriceSearch] = useState('');
  const [selectedProduct, setSelectedProduct] = useState('');
  const [historyPage, setHistoryPage] = useState(1);
  const [historySource, setHistorySource] = useState('');

  useEffect(() => {
    fetchProducts();
    fetchTierConfig();
  }, [fetchProducts, fetchTierConfig]);

  useEffect(() => {
    if (tab === 'outliers') fetchOutliers();
    if (tab === 'stats') fetchPriceStats();
  }, [tab, fetchOutliers, fetchPriceStats]);

  useEffect(() => {
    if (tab === 'data') {
      const params = { page: historyPage, per_page: 50 };
      if (selectedProduct) params.product_id = selectedProduct;
      if (historySource) params.source = historySource;
      if (priceSearch) params.source = priceSearch;
      fetchPriceHistory(params);
    }
  }, [tab, historyPage, selectedProduct, historySource, priceSearch, fetchPriceHistory]);

  /* 가격 통계 — API 데이터 우선, 없으면 products에서 계산 */
  const stats = useMemo(() => {
    if (priceStats) {
      return {
        avg: Math.round(priceStats.avg_baseline_price ?? 0),
        median: 0,
        stdDev: 0,
        min: 0,
        max: 0,
        count: priceStats.baseline_prices ?? priceStats.products ?? 0,
        productCount: priceStats.products ?? 0,
        discountCount: priceStats.discount_records ?? 0,
        hotdealCount: priceStats.hotdeal_records ?? 0,
      };
    }
    if (products.length === 0) return { avg: 0, median: 0, stdDev: 0, min: 0, max: 0, count: 0 };
    const allPrices = products.map(p => p.currentAvg ?? 0).filter(p => p > 0);
    if (allPrices.length === 0) return { avg: 0, median: 0, stdDev: 0, min: 0, max: 0, count: 0 };
    const sorted = [...allPrices].sort((a, b) => a - b);
    const avg = Math.round(allPrices.reduce((s, p) => s + p, 0) / allPrices.length);
    const median = sorted[Math.floor(sorted.length / 2)] ?? 0;
    const variance = allPrices.reduce((s, p) => s + (p - avg) ** 2, 0) / allPrices.length;
    const stdDev = Math.round(Math.sqrt(variance));
    return { avg, median, stdDev, min: sorted[0] ?? 0, max: sorted[sorted.length - 1] ?? 0, count: allPrices.length };
  }, [products, priceStats]);

  const [tierEdits, setTierEdits] = useState({});
  useEffect(() => {
    setTierEdits(
      Object.fromEntries(Object.entries(priceTiers).map(([k, v]) => [k, v.threshold === Infinity ? '' : v.threshold]))
    );
  }, [priceTiers]);

  const handleSaveTiers = async () => {
    Object.entries(tierEdits).forEach(([k, v]) => {
      const val = v === '' ? Infinity : Number(v);
      if (val !== priceTiers[k]?.threshold) updatePriceTier(k, val);
    });
    await saveTierConfig();
  };

  const historyItems = priceHistoryPage?.items || [];

  return (
    <div className={s.page}>
      <h2 className={s.title}>가격 관리</h2>

      {/* 탭 */}
      <div className={s.tabs}>
        {[
          { key: 'tiers', label: '티어 설정', icon: Settings },
          { key: 'outliers', label: '이상치', icon: AlertTriangle },
          { key: 'data', label: '가격 데이터', icon: Search },
          { key: 'stats', label: '통계 요약', icon: BarChart3 },
        ].map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            className={`${s.tab} ${tab === key ? s.tabActive : ''}`}
            onClick={() => setTab(key)}
          >
            <Icon size={15} /> {label}
          </button>
        ))}
      </div>

      {/* 티어 설정 */}
      {tab === 'tiers' && (
        <div className={s.section}>
          <h3 className={s.sectionTitle}>가격 티어 기준 설정</h3>
          <p className={s.desc}>기준가 대비 현재 평균가의 비율(%)로 가격 등급을 결정합니다.</p>
          <div className={s.tierGrid}>
            {Object.entries(priceTiers).filter(([k]) => k !== 'bad').map(([key, tier]) => (
              <div key={key} className={s.tierCard}>
                <span className={s.tierDot} style={{ background: tier.color }} />
                <span className={s.tierLabel}>{tier.label}</span>
                <div className={s.tierInput}>
                  <input
                    type="number"
                    value={tierEdits[key] ?? ''}
                    onChange={e => setTierEdits({ ...tierEdits, [key]: e.target.value })}
                    placeholder="∞"
                  />
                  <span>%</span>
                </div>
              </div>
            ))}
          </div>
          <button className={s.saveBtn} onClick={handleSaveTiers} disabled={tierSaving}>
            {tierSaving ? '저장 중...' : '저장'}
          </button>
        </div>
      )}

      {/* 이상치 */}
      {tab === 'outliers' && (
        <div className={s.section}>
          <h3 className={s.sectionTitle}>가격 이상치 목록 (IQR 탐지)</h3>
          {priceOutliers.length === 0 ? (
            <p className={s.desc}>이상치가 없습니다.</p>
          ) : (
            <div className={s.tableWrap}>
              <table className={s.table}>
                <thead>
                  <tr>
                    <th>상품명</th>
                    <th>날짜</th>
                    <th>감지 가격</th>
                    <th>평균 가격</th>
                    <th>편차(%)</th>
                    <th>출처</th>
                  </tr>
                </thead>
                <tbody>
                  {priceOutliers.map(o => (
                    <tr key={o.id}>
                      <td className={s.bold}>{o.productName}</td>
                      <td>{o.date}</td>
                      <td className={o.deviation > 0 ? s.red : s.green}>{(o.price ?? 0).toLocaleString()}원</td>
                      <td>{(o.avgPrice ?? 0).toLocaleString()}원</td>
                      <td className={o.deviation > 0 ? s.red : s.green}>{o.deviation > 0 ? '+' : ''}{o.deviation}%</td>
                      <td>{o.source}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* 가격 데이터 뷰어 */}
      {tab === 'data' && (
        <div className={s.section}>
          <h3 className={s.sectionTitle}>대량 가격 데이터 뷰어</h3>
          <div className={s.dataFilters}>
            <select
              className={s.select}
              value={selectedProduct}
              onChange={e => { setSelectedProduct(e.target.value); setHistoryPage(1); }}
            >
              <option value="">전체 상품</option>
              {products.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
            <input
              placeholder="출처로 검색..."
              value={priceSearch}
              onChange={e => { setPriceSearch(e.target.value); setHistoryPage(1); }}
            />
          </div>
          <div className={s.tableWrap}>
            <table className={s.table}>
              <thead>
                <tr><th>상품명</th><th>날짜</th><th>가격</th><th>출처</th></tr>
              </thead>
              <tbody>
                {historyItems.map((d, i) => (
                  <tr key={d.id || i}>
                    <td className={s.bold}>{d.productName || ''}</td>
                    <td>{d.date}</td>
                    <td>{(d.price ?? 0).toLocaleString()}원</td>
                    <td>{d.source}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className={s.count} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span>총 {priceHistoryPage?.total ?? 0}건</span>
            {(priceHistoryPage?.total_pages ?? 0) > 1 && (
              <div>
                <button disabled={historyPage <= 1} onClick={() => setHistoryPage(p => p - 1)} className={s.saveBtn} style={{ marginRight: 4, padding: '4px 10px' }}>이전</button>
                <span>{historyPage} / {priceHistoryPage.total_pages}</span>
                <button disabled={historyPage >= priceHistoryPage.total_pages} onClick={() => setHistoryPage(p => p + 1)} className={s.saveBtn} style={{ marginLeft: 4, padding: '4px 10px' }}>다음</button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* 통계 요약 */}
      {tab === 'stats' && (
        <div className={s.section}>
          <h3 className={s.sectionTitle}>가격 통계 요약</h3>
          <div className={s.statsGrid}>
            <div className={s.statCard}><span className={s.statLabel}>평균</span><span className={s.statValue}>{(stats.avg ?? 0).toLocaleString()}원</span></div>
            <div className={s.statCard}><span className={s.statLabel}>중앙값</span><span className={s.statValue}>{(stats.median ?? 0).toLocaleString()}원</span></div>
            <div className={s.statCard}><span className={s.statLabel}>표준편차</span><span className={s.statValue}>{(stats.stdDev ?? 0).toLocaleString()}원</span></div>
            <div className={s.statCard}><span className={s.statLabel}>최솟값</span><span className={s.statValue}>{(stats.min ?? 0).toLocaleString()}원</span></div>
            <div className={s.statCard}><span className={s.statLabel}>최댓값</span><span className={s.statValue}>{(stats.max ?? 0).toLocaleString()}원</span></div>
            <div className={s.statCard}><span className={s.statLabel}>상품 수</span><span className={s.statValue}>{stats.count ?? stats.productCount ?? 0}개</span></div>
          </div>
        </div>
      )}
    </div>
  );
}
