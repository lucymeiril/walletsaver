import { useState, useMemo, useEffect, useCallback, useRef } from 'react';
import { Download, AlertTriangle, Database, TrendingUp, Search, X, CheckCircle, Trash2, Pencil, Archive } from 'lucide-react';
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid, Legend, ReferenceLine,
  PieChart, Pie, Cell,
} from 'recharts';
import useDbAdminStore from '../../stores/dbAdminStore';
import { api } from '../../api/client';
import s from './Analytics.module.css';

const CHART_COLORS = ['#38bdf8', '#f472b6', '#a3e635', '#fb923c', '#c084fc'];
const DONUT_COLORS = ['#38bdf8', '#f472b6', '#a3e635', '#fb923c', '#c084fc', '#22d3ee', '#e879f9', '#facc15'];
const MAX_PRODUCTS = 5;

export default function Analytics() {
  const {
    products, qualityReport, categoryAvgPrices, sourceStats,
    fetchAnalytics, fetchProducts,
    priceOutliers, fetchOutliers,
  } = useDbAdminStore();
  const [selectedProducts, setSelectedProducts] = useState([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [showDropdown, setShowDropdown] = useState(false);
  const [period, setPeriod] = useState(30);
  const [priceTrends, setPriceTrends] = useState({});
  const [sourceStatsDetail, setSourceStatsDetail] = useState([]);
  const [sourceDistribution, setSourceDistribution] = useState([]);
  const [categoryDistribution, setCategoryDistribution] = useState([]);
  const [dailyTrend, setDailyTrend] = useState([]);
  const [qualitySummary, setQualitySummary] = useState(null);
  const [outlierSelected, setOutlierSelected] = useState(new Set());
  const [editingOutlier, setEditingOutlier] = useState(null);
  const [editPrice, setEditPrice] = useState('');
  const [outlierLoading, setOutlierLoading] = useState(false);
  const searchRef = useRef(null);

  useEffect(() => {
    fetchAnalytics();
    fetchProducts();
    fetchOutliers(50);
    api.getSourceStatsDetail()
      .then(data => { if (Array.isArray(data)) setSourceStatsDetail(data); })
      .catch(() => {});
    api.getSourceDistribution()
      .then(data => { if (Array.isArray(data)) setSourceDistribution(data); })
      .catch(() => {});
    api.getCategoryDistribution()
      .then(data => { if (Array.isArray(data)) setCategoryDistribution(data); })
      .catch(() => {});
    api.getDailyTrend(30)
      .then(data => { if (Array.isArray(data)) setDailyTrend(data); })
      .catch(() => {});
    api.getDataQualitySummary()
      .then(data => { if (data) setQualitySummary(data); })
      .catch(() => {});
  }, [fetchAnalytics, fetchProducts, fetchOutliers]);

  // 첫 상품 자동 선택
  useEffect(() => {
    if (products.length > 0 && selectedProducts.length === 0) {
      setSelectedProducts([{ id: products[0].id, name: products[0].name }]);
    }
  }, [products, selectedProducts.length]);

  // 선택 상품 변경 시 가격 추이 로드
  useEffect(() => {
    if (selectedProducts.length === 0) { setPriceTrends({}); return; }
    const ids = selectedProducts.map(p => p.id);
    api.getPriceTrends(ids, period)
      .then(data => setPriceTrends(data || {}))
      .catch(() => setPriceTrends({}));
  }, [selectedProducts, period]);

  // 검색 드롭다운 외부 클릭 닫기
  useEffect(() => {
    const handler = (e) => {
      if (searchRef.current && !searchRef.current.contains(e.target)) setShowDropdown(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  // 상품 검색
  const filteredProducts = useMemo(() => {
    if (!searchQuery.trim()) return [];
    const q = searchQuery.toLowerCase();
    return products
      .filter(p => p.name.toLowerCase().includes(q) && !selectedProducts.some(sp => sp.id === p.id))
      .slice(0, 10);
  }, [searchQuery, products, selectedProducts]);

  const addProduct = useCallback((p) => {
    if (selectedProducts.length >= MAX_PRODUCTS) return;
    setSelectedProducts(prev => [...prev, { id: p.id, name: p.name }]);
    setSearchQuery('');
    setShowDropdown(false);
  }, [selectedProducts.length]);

  const removeProduct = useCallback((id) => {
    setSelectedProducts(prev => prev.filter(p => p.id !== id));
  }, []);

  // 복수 상품 차트 데이터 변환
  const chartData = useMemo(() => {
    const allDates = new Set();
    selectedProducts.forEach(p => {
      (priceTrends[p.id]?.data || []).forEach(d => allDates.add(d.date));
    });
    return [...allDates].sort().map(date => {
      const point = { date };
      selectedProducts.forEach(p => {
        const found = (priceTrends[p.id]?.data || []).find(d => d.date === date);
        if (found) point[`price_${p.id}`] = found.price;
      });
      return point;
    });
  }, [priceTrends, selectedProducts]);

  const refLines = useMemo(() => {
    if (selectedProducts.length !== 1) return {};
    const pid = selectedProducts[0].id;
    return {
      baseline: priceTrends[pid]?.baselinePrice,
      hotdeal: priceTrends[pid]?.hotdealPrice,
    };
  }, [priceTrends, selectedProducts]);

  const exportTrendData = useMemo(() => {
    return chartData.map(row => {
      const out = { 날짜: row.date };
      selectedProducts.forEach(p => { out[p.name] = row[`price_${p.id}`] ?? ''; });
      return out;
    });
  }, [chartData, selectedProducts]);

  const effectiveSourceStats = sourceStatsDetail.length > 0 ? sourceStatsDetail : sourceStats;

  // 이상치 관리 함수
  const handleOutlierAction = async (id, action, newPrice) => {
    setOutlierLoading(true);
    try {
      await api.outlierAction(id, action, newPrice || undefined);
      await fetchOutliers(50);
      setOutlierSelected(prev => { const n = new Set(prev); n.delete(id); return n; });
      setEditingOutlier(null);
      setEditPrice('');
    } catch (e) {
      alert(`처리 실패: ${e.message}`);
    } finally {
      setOutlierLoading(false);
    }
  };

  const handleBulkOutlierAction = async (action) => {
    if (outlierSelected.size === 0) return;
    const msg = action === 'delete' ? `선택한 ${outlierSelected.size}개를 삭제하시겠습니까?` : `선택한 ${outlierSelected.size}개를 정상 처리하시겠습니까?`;
    if (!confirm(msg)) return;
    setOutlierLoading(true);
    try {
      for (const id of outlierSelected) {
        await api.outlierAction(id, action);
      }
      await fetchOutliers(50);
      setOutlierSelected(new Set());
    } catch (e) {
      alert(`처리 실패: ${e.message}`);
    } finally {
      setOutlierLoading(false);
    }
  };

  const toggleOutlierSelect = (id) => {
    setOutlierSelected(prev => {
      const n = new Set(prev);
      n.has(id) ? n.delete(id) : n.add(id);
      return n;
    });
  };

  const toggleOutlierSelectAll = () => {
    if (outlierSelected.size === priceOutliers.length) {
      setOutlierSelected(new Set());
    } else {
      setOutlierSelected(new Set(priceOutliers.map(o => o.id)));
    }
  };

  // 도넛 차트 커스텀 라벨
  const renderDonutLabel = ({ source, percentage, cx, cy, midAngle, innerRadius, outerRadius }) => {
    const RADIAN = Math.PI / 180;
    const radius = outerRadius + 24;
    const x = cx + radius * Math.cos(-midAngle * RADIAN);
    const y = cy + radius * Math.sin(-midAngle * RADIAN);
    return (
      <text x={x} y={y} fill="var(--text2)" textAnchor={x > cx ? 'start' : 'end'} dominantBaseline="central" fontSize={11}>
        {source} ({percentage}%)
      </text>
    );
  };

  return (
    <div className={s.page}>
      <h2 className={s.title}>분석</h2>

      {/* ── 데이터 품질 요약 ── */}
      {qualitySummary && (
        <div className={s.card}>
          <h3 className={s.cardTitle}><Database size={16} /> 데이터 품질 요약</h3>
          <div className={s.summaryGrid}>
            <div className={s.summaryItem}>
              <span className={s.summaryValue}>{qualitySummary.total?.toLocaleString()}개</span>
              <span className={s.summaryLabel}>총 상품</span>
            </div>
            <div className={s.summaryItem}>
              <span className={s.summaryValue} style={{ color: 'var(--green)' }}>
                {qualitySummary.withPrice?.toLocaleString()}개 ({qualitySummary.withPriceRate}%)
              </span>
              <span className={s.summaryLabel}>가격 정보 있음</span>
              <div className={s.progressBar}>
                <div className={s.progressFill} style={{ width: `${qualitySummary.withPriceRate}%`, background: 'var(--green)' }} />
              </div>
            </div>
            <div className={s.summaryItem}>
              <span className={s.summaryValue} style={{ color: 'var(--accent)' }}>
                {qualitySummary.withCategory?.toLocaleString()}개 ({qualitySummary.withCategoryRate}%)
              </span>
              <span className={s.summaryLabel}>카테고리 매핑됨</span>
              <div className={s.progressBar}>
                <div className={s.progressFill} style={{ width: `${qualitySummary.withCategoryRate}%`, background: 'var(--accent)' }} />
              </div>
            </div>
            <div className={s.summaryItem}>
              <span className={s.summaryValue} style={{ color: 'var(--accent2)' }}>
                {qualitySummary.withImage?.toLocaleString()}개 ({qualitySummary.withImageRate}%)
              </span>
              <span className={s.summaryLabel}>이미지 있음</span>
              <div className={s.progressBar}>
                <div className={s.progressFill} style={{ width: `${qualitySummary.withImageRate}%`, background: 'var(--accent2)' }} />
              </div>
            </div>
            {qualitySummary.expired > 0 && (
              <div className={s.summaryItem}>
                <span className={s.summaryValue} style={{ color: 'var(--red)' }}>
                  {qualitySummary.expired}개
                </span>
                <span className={s.summaryLabel}>
                  <Archive size={12} style={{ verticalAlign: 'middle', marginRight: 4 }} />
                  만료 상품
                </span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── 소스별 분포 + 카테고리별 상품 수 ── */}
      <div className={s.grid}>
        {sourceDistribution.length > 0 && (
          <div className={s.card}>
            <h3 className={s.cardTitle}>소스별 데이터 분포</h3>
            <ResponsiveContainer width="100%" height={280}>
              <PieChart>
                <Pie
                  data={sourceDistribution}
                  dataKey="count"
                  nameKey="source"
                  cx="50%"
                  cy="50%"
                  innerRadius={55}
                  outerRadius={90}
                  paddingAngle={2}
                  label={renderDonutLabel}
                >
                  {sourceDistribution.map((_, i) => (
                    <Cell key={i} fill={DONUT_COLORS[i % DONUT_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, color: 'var(--text)' }}
                  formatter={(val, name) => [`${val}개`, name]}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
        )}

        {categoryDistribution.length > 0 && (
          <div className={s.card}>
            <h3 className={s.cardTitle}>카테고리별 상품 수</h3>
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={categoryDistribution} layout="vertical" margin={{ top: 5, right: 20, bottom: 5, left: 60 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis type="number" tick={{ fill: 'var(--text3)', fontSize: 11 }} />
                <YAxis type="category" dataKey="category" tick={{ fill: 'var(--text3)', fontSize: 11 }} width={80} />
                <Tooltip contentStyle={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, color: 'var(--text)' }} />
                <Bar dataKey="count" fill="var(--accent2)" radius={[0, 4, 4, 0]} name="상품 수" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {/* ── 일별 크롤링 추이 ── */}
      {dailyTrend.length > 0 && (
        <div className={s.card}>
          <h3 className={s.cardTitle}><TrendingUp size={16} /> 일별 크롤링 추이 (최근 30일)</h3>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={dailyTrend} margin={{ top: 10, right: 20, bottom: 5, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="date" tick={{ fill: 'var(--text3)', fontSize: 11 }} tickFormatter={v => v.slice(5)} />
              <YAxis tick={{ fill: 'var(--text3)', fontSize: 11 }} />
              <Tooltip
                contentStyle={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, color: 'var(--text)' }}
                formatter={(val) => [`${val}개`, '추가 상품']}
                labelFormatter={l => l}
              />
              <Line type="monotone" dataKey="count" stroke="var(--accent)" strokeWidth={2} dot={false} name="일별 추가" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* ── 가격 추이 비교 차트 ── */}
      <div className={s.card}>
        <div className={s.cardHeader}>
          <h3 className={s.cardTitle}><TrendingUp size={16} /> 가격 추이 비교</h3>
          <div className={s.controls}>
            <div className={s.autocomplete} ref={searchRef}>
              <div className={s.searchInputWrap}>
                <Search size={14} className={s.searchIcon} />
                <input
                  type="text"
                  className={s.searchInput}
                  placeholder={selectedProducts.length >= MAX_PRODUCTS ? '최대 5개' : '상품 검색...'}
                  value={searchQuery}
                  onChange={e => { setSearchQuery(e.target.value); setShowDropdown(true); }}
                  onFocus={() => setShowDropdown(true)}
                  disabled={selectedProducts.length >= MAX_PRODUCTS}
                />
              </div>
              {showDropdown && filteredProducts.length > 0 && (
                <ul className={s.dropdown}>
                  {filteredProducts.map(p => (
                    <li key={p.id} className={s.dropdownItem} onClick={() => addProduct(p)}>
                      {p.name}
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className={s.periodBtns}>
              {[30, 60, 90].map(d => (
                <button
                  key={d}
                  className={`${s.periodBtn} ${period === d ? s.periodActive : ''}`}
                  onClick={() => setPeriod(d)}
                >
                  {d}일
                </button>
              ))}
            </div>
          </div>
        </div>

        {selectedProducts.length > 0 && (
          <div className={s.tags}>
            {selectedProducts.map((p, i) => (
              <span key={p.id} className={s.tag} style={{ borderColor: CHART_COLORS[i % CHART_COLORS.length] }}>
                <span className={s.tagDot} style={{ background: CHART_COLORS[i % CHART_COLORS.length] }} />
                {p.name}
                <button className={s.tagRemove} onClick={() => removeProduct(p.id)}><X size={12} /></button>
              </span>
            ))}
          </div>
        )}

        <ResponsiveContainer width="100%" height={320}>
          <LineChart data={chartData} margin={{ top: 10, right: 20, bottom: 5, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis dataKey="date" tick={{ fill: 'var(--text3)', fontSize: 11 }} tickFormatter={v => v.slice(5)} />
            <YAxis tick={{ fill: 'var(--text3)', fontSize: 11 }} tickFormatter={v => v.toLocaleString()} />
            <Tooltip
              contentStyle={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, color: 'var(--text)' }}
              formatter={(val) => val != null ? [`${val.toLocaleString()}원`] : ['-']}
              labelFormatter={l => l}
            />
            <Legend />
            {selectedProducts.map((p, i) => (
              <Line
                key={p.id}
                type="monotone"
                dataKey={`price_${p.id}`}
                stroke={CHART_COLORS[i % CHART_COLORS.length]}
                strokeWidth={2}
                dot={false}
                name={p.name}
                connectNulls
              />
            ))}
            {refLines.baseline != null && (
              <ReferenceLine
                y={refLines.baseline}
                stroke="#22d3ee"
                strokeDasharray="5 5"
                label={{ value: '기준가', fill: '#22d3ee', fontSize: 11, position: 'right' }}
              />
            )}
            {refLines.hotdeal != null && (
              <ReferenceLine
                y={refLines.hotdeal}
                stroke="#f472b6"
                strokeDasharray="5 5"
                label={{ value: '핫딜가', fill: '#f472b6', fontSize: 11, position: 'right' }}
              />
            )}
          </LineChart>
        </ResponsiveContainer>
        <div className={s.exportBtns}>
          <button onClick={() => exportCSV(exportTrendData, '가격추이')}><Download size={14} /> CSV</button>
          <button onClick={() => exportJSON(exportTrendData, '가격추이')}><Download size={14} /> JSON</button>
        </div>
      </div>

      <div className={s.grid}>
        {/* ── 카테고리별 평균 가격 ── */}
        <div className={s.card}>
          <h3 className={s.cardTitle}>카테고리별 평균 가격</h3>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={categoryAvgPrices} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="category" tick={{ fill: 'var(--text3)', fontSize: 11 }} />
              <YAxis tick={{ fill: 'var(--text3)', fontSize: 11 }} />
              <Tooltip contentStyle={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, color: 'var(--text)' }} />
              <Bar dataKey="avgPrice" fill="var(--accent2)" radius={[4, 4, 0, 0]} name="평균 가격" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* ── 데이터 품질 리포트 ── */}
        <div className={s.card}>
          <h3 className={s.cardTitle}><AlertTriangle size={16} /> 데이터 품질 리포트</h3>
          <div className={s.qualityGrid}>
            <QualityBar label="필드 완성도" value={qualityReport.fieldCompleteness} color="var(--green)" />
            <QualityBar label="가격 커버리지" value={qualityReport.priceCoverage} color="var(--accent)" />
            <QualityBar label="카테고리 분류율" value={qualityReport.categoryRate} color="var(--accent2)" />
            <QualityStat label="총 레코드" value={(qualityReport.totalRecords ?? 0).toLocaleString()} color="var(--accent)" />
            <QualityStat label="종합 완성도" value={`${qualityReport.completeness ?? 0}%`} color="var(--green)" />
            <QualityStat label="정확도" value={`${qualityReport.accuracy ?? 0}%`} color="var(--accent2)" />
          </div>
        </div>
      </div>

      {/* ── 이상치 관리 ── */}
      <div className={s.card}>
        <div className={s.cardHeader}>
          <h3 className={s.cardTitle}><AlertTriangle size={16} /> 이상치 관리</h3>
          {outlierSelected.size > 0 && (
            <div className={s.outlierBulkActions}>
              <span className={s.outlierBulkCount}>{outlierSelected.size}개 선택</span>
              <button className={s.outlierActionBtn} onClick={() => handleBulkOutlierAction('whitelist')} disabled={outlierLoading}>
                <CheckCircle size={13} /> 일괄 정상
              </button>
              <button className={`${s.outlierActionBtn} ${s.outlierDeleteBtn}`} onClick={() => handleBulkOutlierAction('delete')} disabled={outlierLoading}>
                <Trash2 size={13} /> 일괄 삭제
              </button>
            </div>
          )}
        </div>
        {priceOutliers.length > 0 ? (
          <div className={s.tableWrap}>
            <table className={s.table}>
              <thead>
                <tr>
                  <th style={{ width: 36, textAlign: 'center' }}>
                    <input type="checkbox" checked={outlierSelected.size === priceOutliers.length && priceOutliers.length > 0} onChange={toggleOutlierSelectAll} />
                  </th>
                  <th>상품</th>
                  <th>날짜</th>
                  <th>가격</th>
                  <th>평균가</th>
                  <th>편차</th>
                  <th>소스</th>
                  <th>관리</th>
                </tr>
              </thead>
              <tbody>
                {priceOutliers.map(o => (
                  <tr key={o.id}>
                    <td style={{ textAlign: 'center' }}>
                      <input type="checkbox" checked={outlierSelected.has(o.id)} onChange={() => toggleOutlierSelect(o.id)} />
                    </td>
                    <td className={s.bold}>{o.productName}</td>
                    <td>{o.date}</td>
                    <td>
                      {editingOutlier === o.id ? (
                        <input
                          type="number"
                          className={s.editPriceInput}
                          value={editPrice}
                          onChange={e => setEditPrice(e.target.value)}
                          autoFocus
                        />
                      ) : (
                        <span style={{ color: Math.abs(o.deviation) > 50 ? 'var(--red)' : 'var(--yellow)' }}>
                          {o.price?.toLocaleString()}원
                        </span>
                      )}
                    </td>
                    <td>{o.avgPrice?.toLocaleString()}원</td>
                    <td>
                      <span className={`${s.status} ${Math.abs(o.deviation) > 50 ? s.error : s.warning}`}>
                        {o.deviation > 0 ? '+' : ''}{o.deviation}%
                      </span>
                    </td>
                    <td>{o.source}</td>
                    <td>
                      <div className={s.outlierActions}>
                        {editingOutlier === o.id ? (
                          <>
                            <button className={s.outlierSmBtn} onClick={() => handleOutlierAction(o.id, 'edit', parseFloat(editPrice))} disabled={outlierLoading} title="저장">
                              <CheckCircle size={13} />
                            </button>
                            <button className={s.outlierSmBtn} onClick={() => { setEditingOutlier(null); setEditPrice(''); }} title="취소">
                              <X size={13} />
                            </button>
                          </>
                        ) : (
                          <>
                            <button className={s.outlierSmBtn} onClick={() => handleOutlierAction(o.id, 'whitelist')} disabled={outlierLoading} title="정상">
                              <CheckCircle size={13} />
                            </button>
                            <button className={s.outlierSmBtn} onClick={() => { setEditingOutlier(o.id); setEditPrice(String(o.avgPrice || o.price)); }} title="수정">
                              <Pencil size={13} />
                            </button>
                            <button className={`${s.outlierSmBtn} ${s.outlierDeleteBtn}`} onClick={() => handleOutlierAction(o.id, 'delete')} disabled={outlierLoading} title="삭제">
                              <Trash2 size={13} />
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className={s.noOutliers}>이상치가 없습니다.</p>
        )}
      </div>

      {/* ── 출처별 통계 ── */}
      <div className={s.card}>
        <div className={s.cardHeader}>
          <h3 className={s.cardTitle}><Database size={16} /> 크롤 데이터 출처별 통계</h3>
          <div className={s.exportBtns}>
            <button onClick={() => exportCSV(effectiveSourceStats, '출처통계')}><Download size={14} /> CSV</button>
            <button onClick={() => exportJSON(effectiveSourceStats, '출처통계')}><Download size={14} /> JSON</button>
          </div>
        </div>

        {effectiveSourceStats.length > 0 && (
          <div className={s.sourceChartWrap}>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={effectiveSourceStats} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="source" tick={{ fill: 'var(--text3)', fontSize: 11 }} />
                <YAxis tick={{ fill: 'var(--text3)', fontSize: 11 }} />
                <Tooltip contentStyle={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, color: 'var(--text)' }} />
                <Legend />
                <Bar dataKey="productCount" fill="var(--accent)" radius={[4, 4, 0, 0]} name="상품 수" />
                <Bar dataKey="totalRecords" fill="var(--accent2)" radius={[4, 4, 0, 0]} name="레코드 수" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}

        <div className={s.tableWrap}>
          <table className={s.table}>
            <thead>
              <tr>
                <th>출처</th>
                <th>상품 수</th>
                <th>평균 가격</th>
                <th>레코드 수</th>
                <th>최근 업데이트</th>
                <th>상태</th>
              </tr>
            </thead>
            <tbody>
              {effectiveSourceStats.map(src => (
                <tr key={src.source}>
                  <td className={s.bold}>{src.source}</td>
                  <td>{src.productCount ?? '-'}</td>
                  <td>{src.avgPrice ? `${Number(src.avgPrice).toLocaleString()}원` : '-'}</td>
                  <td>{(src.totalRecords ?? src.records ?? 0).toLocaleString()}</td>
                  <td>{(src.lastUpdate || src.lastCrawl) ? new Date(src.lastUpdate || src.lastCrawl).toLocaleString('ko-KR') : '-'}</td>
                  <td>
                    <span className={`${s.status} ${s[src.status || 'active']}`}>
                      {src.status === 'active' ? '활성' : src.status === 'warning' ? '경고' : src.status === 'error' ? '오류' : '활성'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function QualityStat({ label, value, color }) {
  return (
    <div className={s.qualityStat}>
      <span className={s.qualityValue} style={{ color }}>{value}</span>
      <span className={s.qualityLabel}>{label}</span>
    </div>
  );
}

function QualityBar({ label, value, color }) {
  return (
    <div className={s.qualityStat}>
      <span className={s.qualityValue} style={{ color }}>{value}%</span>
      <div className={s.progressBar}>
        <div className={s.progressFill} style={{ width: `${Math.min(value, 100)}%`, background: color }} />
      </div>
      <span className={s.qualityLabel}>{label}</span>
    </div>
  );
}

function exportCSV(data, filename) {
  if (!data || !data.length) return;
  const headers = Object.keys(data[0]).join(',');
  const rows = data.map(d =>
    Object.values(d).map(v => {
      const str = String(v ?? '');
      return str.includes(',') || str.includes('"') || str.includes('\n')
        ? `"${str.replace(/"/g, '""')}"` : str;
    }).join(',')
  ).join('\n');
  const bom = '\uFEFF';
  download(bom + headers + '\n' + rows, `${filename}.csv`, 'text/csv;charset=utf-8');
}

function exportJSON(data, filename) {
  if (!data || !data.length) return;
  download(JSON.stringify(data, null, 2), `${filename}.json`, 'application/json');
}

function download(content, filename, type) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
