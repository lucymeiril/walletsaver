import { useEffect, useState } from 'react';
import { Activity, TrendingUp, Brain, Users, Zap, RefreshCw } from 'lucide-react';
import { api } from '../../api/client';
import s from './MatchingMonitor.module.css';

export default function MatchingMonitor() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);

  const load = async () => {
    setLoading(true); setErr(null);
    try { setData(await api.getMatchingMonitor()); }
    catch (e) { if (e?.name !== 'AbortError') setErr(e?.message); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  return (
    <div className={s.page}>
      <div className={s.titleRow}>
        <h2 className={s.title}><Activity size={22} /> 매칭 누적 모니터</h2>
        <button className={s.btn} onClick={load} disabled={loading}>
          <RefreshCw size={14} className={loading ? s.spin : ''} /> 새로고침
        </button>
      </div>

      {err && <div className={s.err}>{err}</div>}

      {data && (
        <>
          <div className={s.row}>
            <Card icon={Zap} label="매칭 테이블 총량" value={data.totalEntries?.toLocaleString()} />
            <Card icon={Brain} label="외부 LLM 누적 비율" value={`${data.externalLlmRatio}%`}
                  tone={data.externalLlmRatio > 50 ? 'warn' : 'ok'} />
            <Card icon={TrendingUp} label="최근 7일 신규" value={data.recent7d?.added?.toLocaleString()} />
            <Card icon={Users} label="최근 7일 hit 수" value={data.recent7d?.hitCount?.toLocaleString()} />
          </div>

          <div className={s.section}>
            <h3>source 분포 (누적)</h3>
            <SourceTable data={data.bySource} />
          </div>

          <div className={s.section}>
            <h3>source 분포 (최근 7일)</h3>
            <SourceTable data={data.recent7d?.bySource} />
            <p className={s.note}>
              외부 LLM 의존 {data.recent7d?.externalLlmRatio}% · 자동 분류 {data.recent7d?.crawlerAutoRatio}% · 사람 검수 {data.recent7d?.humanRatio}%
            </p>
          </div>
        </>
      )}
    </div>
  );
}

function Card({ icon: Icon, label, value, tone = 'ok' }) {
  return (
    <div className={`${s.card} ${s[tone]}`}>
      <Icon size={18} />
      <div>
        <div className={s.cardLabel}>{label}</div>
        <div className={s.cardVal}>{value ?? '–'}</div>
      </div>
    </div>
  );
}

function SourceTable({ data }) {
  const entries = Object.entries(data || {});
  if (entries.length === 0) return <p className={s.muted}>데이터 없음</p>;
  const total = entries.reduce((a, [, v]) => a + v, 0) || 1;
  return (
    <table className={s.tbl}>
      <thead><tr><th>source</th><th>count</th><th>비율</th></tr></thead>
      <tbody>
        {entries.map(([k, v]) => (
          <tr key={k}>
            <td>{k}</td>
            <td>{v.toLocaleString()}</td>
            <td>{((v / total) * 100).toFixed(1)}%</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
