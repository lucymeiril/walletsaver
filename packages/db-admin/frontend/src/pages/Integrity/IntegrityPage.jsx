import { useEffect, useState, useCallback } from 'react';
import {
  ShieldCheck, RefreshCw, AlertTriangle, CheckCircle2,
  HelpCircle, Wrench,
} from 'lucide-react';
import { api } from '../../api/client';
import { useAbortController } from '../../hooks/useAbortController';
import s from './IntegrityPage.module.css';

const SEVERITY_LABEL = {
  ok: '정상',
  warning: '경고',
  critical: '심각',
  not_configured: '미구성',
};

const CHECK_LABEL = {
  products_without_category: '카테고리 누락 상품',
  invalid_product_prices: '유효하지 않은 가격',
  orphan_product_keywords: '고아 상품-키워드',
  zombie_price_rows: '좀비 가격 레코드',
  expired_discounts: '만료된 할인',
  pending_ingestion_failures: '수집 실패 대기',
  crawl_log_failures: '크롤 실패 로그',
  backup_status: '백업 상태',
  projection_health: '프로젝션 상태',
  dlq_summary: 'DLQ 요약',
};

function severityIcon(sev) {
  if (sev === 'ok') return <CheckCircle2 size={16} />;
  if (sev === 'warning' || sev === 'critical') return <AlertTriangle size={16} />;
  return <HelpCircle size={16} />;
}

export default function IntegrityPage() {
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [recheckingName, setRecheckingName] = useState(null);
  const [error, setError] = useState(null);
  const [repairInputs, setRepairInputs] = useState({});
  const [repairResults, setRepairResults] = useState({});
  const [repairBusy, setRepairBusy] = useState({});

  const getSignal = useAbortController([]);

  const loadSummary = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getIntegritySummary({ signal: getSignal() });
      setReport(data);
    } catch (e) {
      if (e?.name !== 'AbortError') setError(e?.message || '무결성 조회에 실패했습니다.');
    } finally {
      setLoading(false);
    }
  }, [getSignal]);

  useEffect(() => { loadSummary(); }, [loadSummary]);

  const handleRecheckAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.recheckIntegrity(null, { signal: getSignal() });
      setReport(data);
    } catch (e) {
      if (e?.name !== 'AbortError') setError(e?.message || '재검사에 실패했습니다.');
    } finally {
      setLoading(false);
    }
  }, [getSignal]);

  const handleRecheckOne = useCallback(async (name) => {
    setRecheckingName(name);
    setError(null);
    try {
      const data = await api.recheckIntegrity(name, { signal: getSignal() });
      const updated = (data?.checks || []).find((c) => c.name === name);
      if (updated && report) {
        setReport({
          ...report,
          generated_at: data.generated_at || report.generated_at,
          overall_severity: data.overall_severity || report.overall_severity,
          checks: report.checks.map((c) => (c.name === name ? updated : c)),
        });
      } else if (data) {
        setReport(data);
      }
    } catch (e) {
      if (e?.name !== 'AbortError') setError(e?.message || `${name} 재검사에 실패했습니다.`);
    } finally {
      setRecheckingName(null);
    }
  }, [getSignal, report]);

  const handleRepair = useCallback(async (name) => {
    const confirm = (repairInputs[name] || '').trim();
    if (!confirm) return;
    setRepairBusy((b) => ({ ...b, [name]: true }));
    setRepairResults((r) => ({ ...r, [name]: null }));
    try {
      const resp = await api.repairIntegrity(name, confirm, { signal: getSignal() });
      setRepairResults((r) => ({ ...r, [name]: resp }));
    } catch (e) {
      if (e?.name !== 'AbortError') {
        setRepairResults((r) => ({ ...r, [name]: { status: 'error', message: e?.message || '복구 요청 실패' } }));
      }
    } finally {
      setRepairBusy((b) => ({ ...b, [name]: false }));
    }
  }, [getSignal, repairInputs]);

  const overall = report?.overall_severity || 'ok';
  const checks = report?.checks || [];

  return (
    <div className={s.page}>
      <div className={s.titleRow}>
        <h2 className={s.title}>
          <ShieldCheck size={24} /> DB 무결성
        </h2>
        <div className={s.actions}>
          <button className={s.btn} onClick={handleRecheckAll} disabled={loading} title="전체 재검사">
            <RefreshCw size={16} className={loading ? s.spin : ''} />
            전체 재검사
          </button>
        </div>
      </div>

      {error && <div className={s.errorBox}>{error}</div>}

      <div className={s.summary}>
        <div className={s.summaryCard}>
          <div className={s.summaryLabel}>전체 심각도</div>
          <div className={s.summaryValue}>
            <span className={`${s.badge} ${s[overall]}`}>{SEVERITY_LABEL[overall] || overall}</span>
          </div>
          <div className={s.summaryHint}>가장 높은 검사 심각도</div>
        </div>
        <div className={s.summaryCard}>
          <div className={s.summaryLabel}>이슈 합계</div>
          <div className={s.summaryValue}>
            {(report?.issue_total ?? 0).toLocaleString()}
          </div>
          <div className={s.summaryHint}>경고/심각 검사들의 count 합</div>
        </div>
        <div className={s.summaryCard}>
          <div className={s.summaryLabel}>검사 수</div>
          <div className={s.summaryValue}>{checks.length}</div>
          <div className={s.summaryHint}>마지막 스캔 기준</div>
        </div>
        <div className={s.summaryCard}>
          <div className={s.summaryLabel}>생성 시각</div>
          <div className={s.summaryValue} style={{ fontSize: 'var(--fs-md)' }}>
            {report?.generated_at
              ? new Date(report.generated_at).toLocaleString('ko-KR')
              : '-'}
          </div>
          <div className={s.summaryHint}>generated_at (UTC 원본)</div>
        </div>
      </div>

      {!loading && checks.length === 0 && (
        <div className={s.empty}>표시할 검사 결과가 없습니다.</div>
      )}

      <div className={s.checkList}>
        {checks.map((c) => (
          <CheckCard
            key={c.name}
            check={c}
            busy={recheckingName === c.name}
            repairBusy={!!repairBusy[c.name]}
            repairValue={repairInputs[c.name] || ''}
            repairResult={repairResults[c.name]}
            onRecheck={() => handleRecheckOne(c.name)}
            onRepairChange={(v) => setRepairInputs((r) => ({ ...r, [c.name]: v }))}
            onRepair={() => handleRepair(c.name)}
          />
        ))}
      </div>
    </div>
  );
}

function CheckCard({
  check, busy, repairBusy, repairValue, repairResult,
  onRecheck, onRepairChange, onRepair,
}) {
  const sev = check.severity || 'ok';
  const label = CHECK_LABEL[check.name] || check.name;
  const expectedConfirm = `REPAIR_${(check.name || '').toUpperCase()}`;
  const confirmMatches = repairValue.trim() === expectedConfirm;
  const isPlaceholder = sev === 'not_configured';

  const extraEntries = Object.entries(check)
    .filter(([k]) => !['name', 'severity', 'count', 'samples', 'by_table', 'by_status',
      'by_crawler', 'message', 'latest', 'buckets'].includes(k));

  return (
    <div className={`${s.checkCard} ${s[sev] || ''}`}>
      <div className={s.checkHead}>
        <div className={s.checkName}>
          {severityIcon(sev)} {label}
          <span className={`${s.badge} ${s[sev]}`}>{SEVERITY_LABEL[sev] || sev}</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span className={s.checkCount}>
            count <strong>{(check.count ?? 0).toLocaleString()}</strong>
          </span>
          <button
            className={s.btn}
            onClick={onRecheck}
            disabled={busy}
            title={`${label} 재검사`}
          >
            <RefreshCw size={14} className={busy ? s.spin : ''} />
            재검사
          </button>
        </div>
      </div>

      <div className={s.checkBody}>
        {check.message && (
          <div className={s.message}>{check.message}</div>
        )}

        {extraEntries.length > 0 && (
          <div className={s.kvGrid}>
            {extraEntries.map(([k, v]) => (
              <div key={k} className={s.kvItem}>
                <span>{k}</span>
                <strong>{formatScalar(v)}</strong>
              </div>
            ))}
          </div>
        )}

        {check.by_table && Object.keys(check.by_table).length > 0 && (
          <>
            <div className={s.samplesTitle}>by_table</div>
            <div className={s.kvGrid}>
              {Object.entries(check.by_table).map(([k, v]) => (
                <div key={k} className={s.kvItem}>
                  <span>{k}</span><strong>{Number(v).toLocaleString()}</strong>
                </div>
              ))}
            </div>
          </>
        )}

        {check.by_status && Object.keys(check.by_status).length > 0 && (
          <>
            <div className={s.samplesTitle}>by_status</div>
            <div className={s.kvGrid}>
              {Object.entries(check.by_status).map(([k, v]) => (
                <div key={k} className={s.kvItem}>
                  <span>{k}</span><strong>{Number(v).toLocaleString()}</strong>
                </div>
              ))}
            </div>
          </>
        )}

        {check.by_crawler && Object.keys(check.by_crawler).length > 0 && (
          <>
            <div className={s.samplesTitle}>by_crawler</div>
            <div className={s.kvGrid}>
              {Object.entries(check.by_crawler).map(([k, v]) => (
                <div key={k} className={s.kvItem}>
                  <span>{k}</span><strong>{Number(v).toLocaleString()}</strong>
                </div>
              ))}
            </div>
          </>
        )}

        {check.buckets && Object.keys(check.buckets).length > 0 && (
          <>
            <div className={s.samplesTitle}>buckets</div>
            <div className={s.kvGrid}>
              {Object.entries(check.buckets).map(([k, v]) => (
                <div key={k} className={s.kvItem}>
                  <span>{k}</span><strong>{formatScalar(v)}</strong>
                </div>
              ))}
            </div>
          </>
        )}

        {check.latest && (
          <>
            <div className={s.samplesTitle}>latest</div>
            <pre className={s.samples}>{JSON.stringify(check.latest, null, 2)}</pre>
          </>
        )}

        {Array.isArray(check.samples) && check.samples.length > 0 && (
          <>
            <div className={s.samplesTitle}>samples ({check.samples.length})</div>
            <pre className={s.samples}>{JSON.stringify(check.samples, null, 2)}</pre>
          </>
        )}

        <div className={s.repairRow}>
          <Wrench size={14} style={{ color: 'var(--text3)' }} />
          <input
            className={s.repairInput}
            type="text"
            placeholder={isPlaceholder ? '미구성 검사 — 복구 사용 불가' : expectedConfirm}
            value={repairValue}
            onChange={(e) => onRepairChange(e.target.value)}
            disabled={isPlaceholder || repairBusy}
            autoComplete="off"
          />
          <button
            className={`${s.btn} ${s.btnDanger}`}
            onClick={onRepair}
            disabled={isPlaceholder || repairBusy || !confirmMatches}
            title={isPlaceholder ? '미구성 검사' : `복구 실행 (${expectedConfirm} 입력 필요)`}
          >
            {repairBusy ? <RefreshCw size={14} className={s.spin} /> : <Wrench size={14} />}
            복구 실행
          </button>
          <div className={s.repairHint}>
            {isPlaceholder
              ? '이 검사는 아직 구성되지 않아 복구를 호출할 수 없습니다.'
              : <>안전을 위해 정확히 <code>{expectedConfirm}</code> 문자열을 입력해야 활성화됩니다. 현재 서버에 자동 복구 루틴이 구현되어 있지 않을 수 있습니다.</>}
          </div>
          {repairResult && (
            <div className={s.repairResult}>
              <strong>status:</strong> {repairResult.status || 'unknown'}
              {repairResult.message && <> — {repairResult.message}</>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function formatScalar(v) {
  if (v === null || v === undefined) return '-';
  if (typeof v === 'number') return v.toLocaleString();
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  if (typeof v === 'string') return v;
  try { return JSON.stringify(v); } catch { return String(v); }
}
