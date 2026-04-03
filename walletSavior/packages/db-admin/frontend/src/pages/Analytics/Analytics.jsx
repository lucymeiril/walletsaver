import { useState, useMemo, useEffect, useCallback, useRef } from 'react';
import { Download, AlertTriangle, Database, TrendingUp, Search, X } from 'lucide-react';
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid, Legend, ReferenceLine,
} from 'recharts';
import useDbAdminStore from '../../stores/dbAdminStore';
import { api } from '../../api/client';
import s from './Analytics.module.css';

const CHART_COLORS = ['#38bdf8', '#f472b6', '#a3e635', '#fb923c', '#c084fc'];
const MAX_PRODUCTS = 5;

export default function Analytics() {
  const {
    products, qualityReport, categoryAvgPrices, sourceStats,
    fetchAnalytics, fetchProducts,
  } = useDbAdminStore();
  const [selectedProducts, setSelectedProducts] = useState([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [showDropdown, setShowDropdown] = useState(false);
  const [period, setPeriod] = useState(30);
  const [priceTrends, setPriceTrends] = useState({});
  const [sourceStatsDetail, setSourceStatsDetail] = useState([]);
  const searchRef = useRef(null);

  useEffect(() => {
    fetchAnalytics();
    fetchProducts();
    api.getSourceStatsDetail()
      .then(data => { if (Array.isArray(data)) setSourceStatsDetail(data); })
      .catch(() => {});
  }, [fetchAnalytics, fetchProducts]);

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

  // 상품 검색 (클라이언트사이드 필터)
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

  // 기준가/핫딜가 수평선 (단일 상품 선택 시)
  const refLines = useMemo(() => {
    if (selectedProducts.length !== 1) return {};
    const pid = selectedProducts[0].id;
    return {
      baseline: priceTrends[pid]?.baselinePrice,
      hotdeal: priceTrends[pid]?.hotdealPrice,
    };
  }, [priceTrends, selectedProducts]);

  // Export 데이터
  const exportTrendData = useMemo(() => {
    return chartData.map(row => {
      const out = { 날짜: row.date };
      selectedProducts.forEach(p => { out[p.name] = row[`price_${p.id}`] ?? ''; });
      return out;
    });
  }, [chartData, selectedProducts]);

  const effectiveSourceStats = sourceStatsDetail.length > 0 ? sourceStatsDetail : sourceStats;

  return (
    <div className={s.page}>
      <h2 className={s.title}>분석</h2>

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

        {/* ── 데이터 품질 리포트 (실데이터) ── */}
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
