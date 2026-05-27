import { useState, useCallback } from 'react';
import {
  Activity, AlertTriangle, CheckCircle2, RefreshCw, Search,
} from 'lucide-react';
import { api } from '../../api/client';
import s from './HealthCheckPage.module.css';

const SEV_LABEL = { ok: '정상', warning: '경고', critical: '심각' };

export default function HealthCheckPage() {
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);
  const [openCheck, setOpenCheck] = useState(null);
  const [sample, setSample] = useState(null);

  const run = useCallback(async () => {
    setLoading(true); setErr(null);
    try { setReport(await api.getHealthIntegrity()); }
    catch (e) { if (e?.name !== 'AbortError') setErr(e?.message || '정합성 점검 실패'); }
    finally { setLoading(false); }
  }, []);

  const showProducts = async (check) => {
    setOpenCheck(check.key);
    setSample(null);
    if (!check.sample_product_ids?.length) return;
    try {
      const ids = check.sample_product_ids.slice(0, 20);
      const results = await Promise.all(ids.map(id => api.getProduct(id).catch(() => null)));
      setSample(results.filter(Boolean));
    } catch { /* ignore */ }
  };

  return (
    <div className={s.page}>
      <div className={s.titleRow}>
        <h2 className={s.title}><Activity size={22} /> 데이터 정합성 점검</h2>
        <button className={s.runBtn} onClick={run} disabled={loading}>
          <RefreshCw size={14} className={loading ? s.spin : ''} />
          {report ? '재실행' : '점검 시작'}
        </button>
      </div>

      <p className={s.intro}>
        RD8 결함 카탈로그 기반: 마트 미상 / 단일 마트 baseline / unit_kind 미지정 / 카테고리 미할당 / 중복 의심.
        버튼 클릭 시 전체 DB를 스캔합니다 (수 초 ~ 수십 초 소요).
      </p>

      {err && <div className={s.err}><AlertTriangle size={14} /> {err}</div>}

      {!report && !loading && (
        <div className={s.placeholder}>
          <Search size={36} />
          <p>아직 점검을 실행하지 않았습니다. 위의 <strong>점검 시작</strong> 버튼을 눌러 주세요.</p>
        </div>
      )}

      {report && (
        <>
          <div className={s.meta}>
            총 상품 <strong>{report.totalProducts?.toLocaleString()}</strong>건 · 점검 시각 {new Date(report.generatedAt).toLocaleString('ko-KR')}
          </div>

          <div className={s.grid}>
            {report.checks.map(c => (
              <div
                key={c.key}
                className={`${s.card} ${s[c.severity]} ${openCheck === c.key ? s.cardOpen : ''}`}
                onClick={() => showProducts(c)}
              >
                <div className={s.cardHead}>
                  {c.severity === 'ok'
                    ? <CheckCircle2 size={16} />
                    : <AlertTriangle size={16} />}
                  <span className={s.sev}>{SEV_LABEL[c.severity] || c.severity}</span>
                </div>
                <div className={s.cardCount}>{(c.count ?? 0).toLocaleString()}</div>
                <div className={s.cardLabel}>{c.label}</div>
                {c.ratio != null && (
                  <div className={s.cardRatio}>비율: {c.ratio}%</div>
                )}
                <div className={s.cardHint}>클릭 → 해당 상품 샘플 표시</div>
              </div>
            ))}
          </div>

          {openCheck && (
            <div className={s.detail}>
              <div className={s.detailHead}>
                <strong>상세: {report.checks.find(c => c.key === openCheck)?.label}</strong>
                <button onClick={() => { setOpenCheck(null); setSample(null); }}>닫기</button>
              </div>

              {openCheck === 'duplicate_suspects'
                ? (
                  <DupTable samples={report.checks.find(c => c.key === openCheck)?.samples || []} />
                )
                : (
                  sample == null
                    ? <p className={s.muted}>샘플 로드 중...</p>
                    : sample.length === 0
                      ? <p className={s.muted}>샘플 상품 없음</p>
                      : <ProductSample items={sample} />
                )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function ProductSample({ items }) {
  return (
    <table className={s.sampleTable}>
      <thead><tr><th>ID</th><th>name</th><th>category_id</th><th>source_type</th></tr></thead>
      <tbody>
        {items.map(p => (
          <tr key={p.id}>
            <td>{p.id}</td>
            <td>{p.name}</td>
            <td>{p.category_id || <em>미할당</em>}</td>
            <td>{p.source_type || '-'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function DupTable({ samples }) {
  return (
    <table className={s.sampleTable}>
      <thead><tr><th>brand</th><th>name_core</th><th>중복 수</th></tr></thead>
      <tbody>
        {samples.map((d, i) => (
          <tr key={i}><td>{d.brand}</td><td>{d.name_core}</td><td>{d.count}</td></tr>
        ))}
        {samples.length === 0 && (
          <tr><td colSpan={3} className={s.muted}>중복 의심 없음</td></tr>
        )}
      </tbody>
    </table>
  );
}
