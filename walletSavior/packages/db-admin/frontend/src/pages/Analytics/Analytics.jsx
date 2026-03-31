import { useState, useMemo } from 'react';
import { Download, AlertTriangle, Database, TrendingUp } from 'lucide-react';
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid, Legend,
} from 'recharts';
import useDbAdminStore from '../../stores/dbAdminStore';
import s from './Analytics.module.css';

export default function Analytics() {
  const { products, priceHistories, categoryAvgPrices, qualityReport, sourceStats } = useDbAdminStore();
  const [selectedProduct, setSelectedProduct] = useState(products[0]?.id || '');
  const [period, setPeriod] = useState(30);

  const trendData = useMemo(() => {
    const history = priceHistories[selectedProduct] || [];
    return history.slice(-period);
  }, [priceHistories, selectedProduct, period]);

  /* CSV export */
  const exportCSV = (data, filename) => {
    if (!data.length) return;
    const headers = Object.keys(data[0]).join(',');
    const rows = data.map(d => Object.values(d).join(',')).join('\n');
    download(`${headers}\n${rows}`, `${filename}.csv`, 'text/csv');
  };

  const exportJSON = (data, filename) => {
    download(JSON.stringify(data, null, 2), `${filename}.json`, 'application/json');
  };

  return (
    <div className={s.page}>
      <h2 className={s.title}>분석</h2>

      {/* 가격 추이 차트 */}
      <div className={s.card}>
        <div className={s.cardHeader}>
          <h3 className={s.cardTitle}><TrendingUp size={16} /> 가격 추이</h3>
          <div className={s.controls}>
            <select value={selectedProduct} onChange={e => setSelectedProduct(e.target.value)} className={s.select}>
              {products.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
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
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={trendData} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis dataKey="date" tick={{ fill: 'var(--text3)', fontSize: 11 }} tickFormatter={v => v.slice(5)} />
            <YAxis tick={{ fill: 'var(--text3)', fontSize: 11 }} />
            <Tooltip contentStyle={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, color: 'var(--text)' }} />
            <Line type="monotone" dataKey="price" stroke="var(--accent)" strokeWidth={2} dot={false} name="가격" />
          </LineChart>
        </ResponsiveContainer>
        <div className={s.exportBtns}>
          <button onClick={() => exportCSV(trendData, '가격추이')}><Download size={14} /> CSV</button>
          <button onClick={() => exportJSON(trendData, '가격추이')}><Download size={14} /> JSON</button>
        </div>
      </div>

      <div className={s.grid}>
        {/* 카테고리별 평균 가격 */}
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

        {/* 데이터 품질 리포트 */}
        <div className={s.card}>
          <h3 className={s.cardTitle}><AlertTriangle size={16} /> 데이터 품질 리포트</h3>
          <div className={s.qualityGrid}>
            <QualityStat label="이상치 수" value={qualityReport.outliers} color="var(--red)" />
            <QualityStat label="중복 수" value={qualityReport.duplicates} color="var(--yellow)" />
            <QualityStat label="누락 필드" value={qualityReport.missingFields} color="var(--orange)" />
            <QualityStat label="총 레코드" value={qualityReport.totalRecords.toLocaleString()} color="var(--accent)" />
            <QualityStat label="완전성" value={`${qualityReport.completeness}%`} color="var(--green)" />
            <QualityStat label="정확도" value={`${qualityReport.accuracy}%`} color="var(--accent2)" />
          </div>
        </div>
      </div>

      {/* 크롤 데이터 출처별 통계 */}
      <div className={s.card}>
        <div className={s.cardHeader}>
          <h3 className={s.cardTitle}><Database size={16} /> 크롤 데이터 출처별 통계</h3>
          <div className={s.exportBtns}>
            <button onClick={() => exportCSV(sourceStats, '출처통계')}><Download size={14} /> CSV</button>
            <button onClick={() => exportJSON(sourceStats, '출처통계')}><Download size={14} /> JSON</button>
          </div>
        </div>
        <div className={s.tableWrap}>
          <table className={s.table}>
            <thead>
              <tr>
                <th>출처</th>
                <th>레코드 수</th>
                <th>마지막 크롤</th>
                <th>상태</th>
              </tr>
            </thead>
            <tbody>
              {sourceStats.map(src => (
                <tr key={src.source}>
                  <td className={s.bold}>{src.source}</td>
                  <td>{src.records.toLocaleString()}</td>
                  <td>{new Date(src.lastCrawl).toLocaleString('ko-KR')}</td>
                  <td>
                    <span className={`${s.status} ${s[src.status]}`}>
                      {src.status === 'active' ? '활성' : src.status === 'warning' ? '경고' : '오류'}
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

function download(content, filename, type) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
