import { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Activity, AlertTriangle, RefreshCw, Package, FolderTree,
  Database, Clock, TrendingUp,
} from 'lucide-react';
import { api } from '../../api/client';
import { MART_CODES, martMeta } from '../../components/MartBadge';
import s from './OperatorDashboard.module.css';

const MART_LABEL = {
  emart: '이마트', homeplus: '홈플러스', lottemart: '롯데마트', costco: '코스트코',
};

export default function OperatorDashboard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);
  const navigate = useNavigate();

  const load = useCallback(async () => {
    setLoading(true); setErr(null);
    try { setData(await api.getHealthOverview()); }
    catch (e) { if (e?.name !== 'AbortError') setErr(e?.message || '조회 실패'); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); const t = setInterval(load, 60_000); return () => clearInterval(t); }, [load]);

  const dist = data?.martDistribution || {};
  const maxMart = Math.max(1, ...Object.values(dist));

  return (
    <div className={s.page}>
      <div className={s.titleRow}>
        <h2 className={s.title}>오늘의 DB 상태</h2>
        <button className={s.refresh} onClick={load} disabled={loading}>
          <RefreshCw size={14} className={loading ? s.spin : ''} /> 새로고침
        </button>
      </div>

      {err && <div className={s.err}>{err}</div>}

      {data?.warnings?.length > 0 && (
        <div className={s.warnBox}>
          <AlertTriangle size={18} />
          <div>
            <strong>⚠ DB 상태 경고 {data.warnings.length}건</strong>
            <ul>
              {data.warnings.map((w, i) => (
                <li key={i} className={s[`lvl_${w.level}`]}>{w.message}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      <div className={s.cards}>
        <Stat icon={Package}    label="총 상품 수"        value={data?.totalProducts} />
        <Stat icon={FolderTree} label="카테고리 / leaf"   value={`${data?.totalCategories ?? 0} / ${data?.leafCategories ?? 0}`} />
        <Stat icon={Database}   label="매칭테이블 항목"   value={data?.totalMatching} />
        <Stat icon={Clock}      label="최근 import"       value={fmtTime(data?.lastImport)} small />
      </div>

      <div className={s.section}>
        <h3 className={s.sectionTitle}><TrendingUp size={16} /> 마트별 상품 분포</h3>
        <div className={s.martGrid}>
          {MART_CODES.map((code) => {
            const v = dist[code] ?? 0;
            const meta = martMeta(code);
            const pct = Math.round((v / maxMart) * 100);
            const warn = v === 0 && maxMart >= 100;
            return (
              <div key={code} className={`${s.martCard} ${warn ? s.martWarn : ''}`}>
                <div className={s.martHead}>
                  <span className={meta.cls} style={{ fontSize: 11, fontWeight: 700, padding: '3px 8px', borderRadius: 999 }}>
                    {MART_LABEL[code]}
                  </span>
                  {warn && <AlertTriangle size={14} color="var(--red, #e74c3c)" />}
                </div>
                <div className={s.martVal}>{v.toLocaleString()}</div>
                <div className={s.martBar}>
                  <div className={`${s.martFill} ${meta.cls}`} style={{ width: `${pct}%` }} />
                </div>
                <div className={s.martSub}>전체 대비 {pct}%</div>
              </div>
            );
          })}
        </div>
        {data?.otherMarts > 0 && (
          <p className={s.otherNote}>그 외 비표준 출처: {data.otherMarts}건 — 정규화 검토 필요</p>
        )}
      </div>

      <div className={s.quickRow}>
        <QuickBtn icon={FolderTree} label="카테고리 드릴다운 탐색" onClick={() => navigate('/explorer')} />
        <QuickBtn icon={Activity}   label="정합성 점검 실행"      onClick={() => navigate('/health-check')} />
        <QuickBtn icon={Database}   label="외부 LLM 결과 업로드"  onClick={() => navigate('/triple-import')} />
      </div>
    </div>
  );
}

function Stat({ icon: Icon, label, value, small }) {
  return (
    <div className={s.statCard}>
      <Icon size={20} className={s.statIcon} />
      <div className={s.statBody}>
        <div className={s.statLabel}>{label}</div>
        <div className={`${s.statValue} ${small ? s.statSmall : ''}`}>
          {value ?? '–'}
        </div>
      </div>
    </div>
  );
}

function QuickBtn({ icon: Icon, label, onClick }) {
  return (
    <button className={s.quickBtn} onClick={onClick}>
      <Icon size={16} /> {label}
    </button>
  );
}

function fmtTime(iso) {
  if (!iso) return '없음';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return '방금 전';
  if (diff < 3600) return `${Math.floor(diff / 60)}분 전`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}시간 전`;
  return `${Math.floor(diff / 86400)}일 전`;
}
