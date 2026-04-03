import { useState, useMemo, useEffect } from 'react';
import { AlertTriangle, Settings, Search, BarChart3, Download, CheckCircle } from 'lucide-react';
import {
  BarChart, Bar, LineChart, Line,
  XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts';
import useDbAdminStore from '../../stores/dbAdminStore';
import { api } from '../../api/client';
import s from './Prices.module.css';

const TOOLTIP_STYLE = {
  background: 'var(--surface)',
  border: '1px solid var(--border)',
  borderRadius: '8px',
  fontSize: '12px',
};

export default function Prices() {
  const {
    products, priceOutliers, priceTiers, priceStats,
    priceHistoryPage, tierSaving,
    updatePriceTier, fetchTierConfig, saveTierConfig,
    fetchOutliers, fetchPriceHistory, fetchPriceStats, fetchProducts,
    whitelistOutlier,
  } = useDbAdminStore();

  const [tab, setTab] = useState('tiers');
  const [priceSearch, setPriceSearch] = useState('');
  const [selectedProduct, setSelectedProduct] = useState('');
  const [historyPage, setHistoryPage] = useState(1);
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');

  // 토스트
  const [toast, setToast] = useState(null);
  useEffect(() => {
    if (toast) {
      const t = setTimeout(() => setToast(null), 3000);
      return () => clearTimeout(t);
    }
  }, [toast]);

  // 티어 미리보기
  const [tierPreview, setTierPreview] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  // 이상치 상세
  const [selectedOutlier, setSelectedOutlier] = useState(null);
  const [outlierDist, setOutlierDist] = useState([]);

  // 티어 편집
  const [tierEdits, setTierEdits] = useState({});
  useEffect(() => {
    setTierEdits(
      Object.fromEntries(Object.entries(priceTiers).map(([k, v]) => [k, v.threshold === Infinity ? '' : v.threshold]))
    );
  }, [priceTiers]);

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
      if (priceSearch) params.source = priceSearch;
      if (dateFrom) params.date_from = dateFrom;
      if (dateTo) params.date_to = dateTo;
      fetchPriceHistory(params);
    }
  }, [tab, historyPage, selectedProduct, priceSearch, dateFrom, dateTo, fetchPriceHistory]);

  /* 통계 — API 데이터 직접 사용 */
  const stats = useMemo(() => {
    if (priceStats) {
      return {
        avg: Math.round(priceStats.avg_baseline_price ?? 0),
        median: Math.round(priceStats.median ?? 0),
        stdDev: Math.round(priceStats.std_dev ?? 0),
        min: Math.round(priceStats.min_price ?? 0),
        max: Math.round(priceStats.max_price ?? 0),
        count: priceStats.baseline_prices ?? 0,
        productCount: priceStats.products ?? 0,
        sourceAverages: priceStats.source_averages ?? [],
        categoryPrices: priceStats.category_prices ?? [],
      };
    }
    return { avg: 0, median: 0, stdDev: 0, min: 0, max: 0, count: 0, productCount: 0, sourceAverages: [], categoryPrices: [] };
  }, [priceStats]);

  const handleSaveTiers = async () => {
    Object.entries(tierEdits).forEach(([k, v]) => {
      const val = v === '' ? Infinity : Number(v);
      if (val !== priceTiers[k]?.threshold) updatePriceTier(k, val);
    });
    const ok = await saveTierConfig();
    setToast(ok
      ? { type: 'success', msg: '티어 설정이 저장되었습니다' }
      : { type: 'error', msg: '티어 설정 저장에 실패했습니다' }
    );
  };

  const handleTierPreview = async () => {
    setPreviewLoading(true);
    try {
      const params = {};
      Object.entries(tierEdits).forEach(([k, v]) => {
        if (v !== '' && k !== 'bad') params[k] = Number(v);
      });
      const data = await api.getTierPreview(params);
      setTierPreview(data);
    } catch {
      setToast({ type: 'error', msg: '미리보기를 불러올 수 없습니다' });
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleWhitelist = async (id) => {
    try {
      await whitelistOutlier(id);
      setToast({ type: 'success', msg: '정상 가격으로 표시되었습니다' });
    } catch {
      setToast({ type: 'error', msg: '화이트리스트 추가 실패' });
    }
  };

  const handleOutlierClick = async (outlier) => {
    if (selectedOutlier?.id === outlier.id) {
      setSelectedOutlier(null);
      return;
    }
    setSelectedOutlier(outlier);
    try {
      const data = await api.getOutlierDistribution(outlier.productId);
      setOutlierDist(data);
    } catch {
      setOutlierDist([]);
    }
  };

  const handleExport = () => {
    const params = new URLSearchParams();
    if (selectedProduct) params.set('product_id', selectedProduct);
    if (priceSearch) params.set('source', priceSearch);
    if (dateFrom) params.set('date_from', dateFrom);
    if (dateTo) params.set('date_to', dateTo);
    window.open(`/api/prices/export?${params.toString()}`);
  };

  const historyItems = priceHistoryPage?.items || [];

  return (
    <div className={s.page}>
      <h2 className={s.title}>가격 관리</h2>

      {/* 토스트 */}
      {toast && (
        <div className={`${s.toast} ${toast.type === 'success' ? s.toastSuccess : s.toastError}`}>
          <CheckCircle size={16} />
          {toast.msg}
        </div>
      )}

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
          <div className={s.tierActions}>
            <button className={s.saveBtn} onClick={handleSaveTiers} disabled={tierSaving}>
              {tierSaving ? '저장 중...' : '저장'}
            </button>
            <button className={s.previewBtn} onClick={handleTierPreview} disabled={previewLoading}>
              {previewLoading ? '조회 중...' : '미리보기'}
            </button>
          </div>
          {tierPreview && (
            <div className={s.previewGrid}>
              {Object.entries(priceTiers).map(([key, tier]) => (
                <div key={key} className={s.previewItem}>
                  <span className={s.tierDot} style={{ background: tier.color }} />
                  <span className={s.previewCount}>{tierPreview[key] ?? 0}</span>
                  <span className={s.previewLabel}>{tier.label}</span>
                </div>
              ))}
              {tierPreview.no_data > 0 && (
                <div className={s.previewItem}>
                  <span className={s.previewCount} style={{ color: 'var(--text3)' }}>{tierPreview.no_data}</span>
                  <span className={s.previewLabel}>데이터 없음</span>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* 이상치 */}
      {tab === 'outliers' && (
        <div className={s.section}>
          <h3 className={s.sectionTitle}>가격 이상치 목록 (IQR 탐지)</h3>
          {priceOutliers.length === 0 ? (
            <p className={s.desc}>이상치가 없습니다.</p>
          ) : (
            <>
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
                      <th>관리</th>
                    </tr>
                  </thead>
                  <tbody>
                    {priceOutliers.map(o => (
                      <tr
                        key={o.id}
                        className={selectedOutlier?.id === o.id ? s.selectedRow : ''}
                        onClick={() => handleOutlierClick(o)}
                        style={{ cursor: 'pointer' }}
                      >
                        <td className={s.bold}>{o.productName}</td>
                        <td>{o.date}</td>
                        <td className={o.deviation > 0 ? s.red : s.green}>{(o.price ?? 0).toLocaleString()}원</td>
                        <td>{(o.avgPrice ?? 0).toLocaleString()}원</td>
                        <td className={o.deviation > 0 ? s.red : s.green}>{o.deviation > 0 ? '+' : ''}{o.deviation}%</td>
                        <td>{o.source}</td>
                        <td>
                          <button
                            className={s.whitelistBtn}
                            onClick={e => { e.stopPropagation(); handleWhitelist(o.id); }}
                          >
                            정상 처리
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {selectedOutlier && outlierDist.length > 0 && (
                <div className={s.miniChart}>
                  <h4 className={s.chartTitle}>
                    {selectedOutlier.productName} — 가격 분포
                  </h4>
                  <ResponsiveContainer width="100%" height={200}>
                    <LineChart data={outlierDist}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                      <XAxis dataKey="date" tick={{ fontSize: 11, fill: 'var(--text3)' }} />
                      <YAxis tick={{ fontSize: 11, fill: 'var(--text3)' }} />
                      <Tooltip contentStyle={TOOLTIP_STYLE} />
                      <Line
                        type="monotone"
                        dataKey="price"
                        stroke="var(--accent)"
                        strokeWidth={2}
                        dot={{ r: 3, fill: 'var(--accent)' }}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* 가격 데이터 뷰어 */}
      {tab === 'data' && (
        <div className={s.section}>
          <div className={s.dataHeader}>
            <h3 className={s.sectionTitle}>대량 가격 데이터 뷰어</h3>
            <button className={s.exportBtn} onClick={handleExport}>
              <Download size={14} /> CSV 내보내기
            </button>
          </div>
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
              placeholder="출처 필터..."
              value={priceSearch}
              onChange={e => { setPriceSearch(e.target.value); setHistoryPage(1); }}
            />
            <div className={s.dateRange}>
              <input
                type="date"
                value={dateFrom}
                onChange={e => { setDateFrom(e.target.value); setHistoryPage(1); }}
              />
              <span className={s.dateSep}>~</span>
              <input
                type="date"
                value={dateTo}
                onChange={e => { setDateTo(e.target.value); setHistoryPage(1); }}
              />
            </div>
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
            <div className={s.statCard}><span className={s.statLabel}>데이터 수</span><span className={s.statValue}>{(stats.count ?? 0).toLocaleString()}건</span></div>
          </div>

          {stats.sourceAverages.length > 0 && (
            <div className={s.chartWrap}>
              <h4 className={s.chartTitle}>소스별 평균가 비교</h4>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={stats.sourceAverages}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="source" tick={{ fontSize: 11, fill: 'var(--text3)' }} />
                  <YAxis tick={{ fontSize: 11, fill: 'var(--text3)' }} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} />
                  <Bar dataKey="avgPrice" name="평균가" fill="var(--accent)" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {stats.categoryPrices.length > 0 && (
            <div className={s.chartWrap}>
              <h4 className={s.chartTitle}>카테고리별 평균가</h4>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={stats.categoryPrices}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="category" tick={{ fontSize: 11, fill: 'var(--text3)' }} />
                  <YAxis tick={{ fontSize: 11, fill: 'var(--text3)' }} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} />
                  <Bar dataKey="avgPrice" name="평균가" fill="#a78bfa" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
