/* RD8-F7 Workbench — 4사 마트 운영자 매주 관찰용 한 화면.
 *
 * 디자인 의도:
 *  - 카드 4장이 한 줄 → "한 화면" 보장 (1280px+)
 *  - 큰 숫자 = 캡처 row 수: 매주 관찰 시 즉시 비정상 감지
 *  - 마트별 brand 컬러는 상단 4px 띠로만 hint → 회색 베이스 + 액센트
 *  - 차단/실패는 하단 적색 띠 + status badge로 이중 알림
 *  - 클릭 → drilldown(같은 페이지 하단에 펼침) — 컨텍스트 보존
 *  - 액션 바: 전수 크롤 / unmatched export — 운영자 1주 1회 루틴 2개
 */

import { useEffect, useState, useCallback, useMemo } from 'react';
import {
  Play,
  PackageOpen,
  RefreshCw,
  AlertTriangle,
  Clock,
  Database,
  Activity,
  Layers,
  Hash,
  ChevronRight,
  Download,
  Server,
} from 'lucide-react';
import styles from './Workbench.module.css';
import { api } from '../../api/client';

const MART_ORDER = ['emart', 'homeplus', 'lottemart', 'costco'];

function fmtTime(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z');
    if (Number.isNaN(d.getTime())) return iso;
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    const hh = String(d.getHours()).padStart(2, '0');
    const mi = String(d.getMinutes()).padStart(2, '0');
    return `${mm}.${dd} ${hh}:${mi}`;
  } catch {
    return iso;
  }
}

function fmtDuration(ms) {
  if (ms == null) return '—';
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const m = Math.floor(ms / 60000);
  const s = Math.floor((ms % 60000) / 1000);
  return `${m}m ${s}s`;
}

function fmtNumber(n) {
  if (n == null) return '—';
  return n.toLocaleString();
}

function statusBadge(status) {
  switch (status) {
    case 'success':  return { cls: styles.statusSuccess, text: '성공' };
    case 'failed':   return { cls: styles.statusFailed,  text: '실패' };
    case 'running':  return { cls: styles.statusRunning, text: '실행중' };
    case 'partial':  return { cls: styles.statusPartial, text: '부분' };
    default:         return { cls: styles.statusNone,    text: '미실행' };
  }
}

function MartCard({ mart, active, onSelect }) {
  const status = statusBadge(mart.lastRunStatus);
  const blocked = mart.lastRunStatus === 'failed' || mart.recentFailed > 0;
  const dupPct = mart.dupRatio ? `${(mart.dupRatio * 100).toFixed(1)}%` : '0%';
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onSelect(mart.key)}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') onSelect(mart.key); }}
      className={`${styles.card} ${active ? styles.cardActive : ''} ${blocked ? styles.cardBlocked : ''}`}
      style={{ '--mart-color': mart.color }}
    >
      <div className={styles.cardHead}>
        <span className={styles.cardName}>
          <span className={styles.brandChip} />
          {mart.label}
        </span>
        <span className={`${styles.statusBadge} ${status.cls}`}>{status.text}</span>
      </div>

      <div className={styles.bigNumLabel}>최근 캡처 row</div>
      <div className={styles.bigNum}>
        {fmtNumber(mart.itemsFound)}
        {mart.capSuspect && (
          <span className={styles.capWarn} title="round number — 캡 의심">
            <AlertTriangle size={11} /> 캡?
          </span>
        )}
      </div>

      <div className={styles.metrics}>
        <div className={styles.metricRow}>
          <span className={styles.metricKey}><Clock size={11} /> 마지막</span>
          <span className={styles.metricVal}>{fmtTime(mart.lastRunAt)}</span>
        </div>
        <div className={styles.metricRow}>
          <span className={styles.metricKey}><Activity size={11} /> 소요</span>
          <span className={styles.metricVal}>{fmtDuration(mart.durationMs)}</span>
        </div>
        <div className={styles.metricRow}>
          <span className={styles.metricKey}><Database size={11} /> 총 raw</span>
          <span className={styles.metricVal}>{fmtNumber(mart.rawRecordCount)}</span>
        </div>
        <div className={styles.metricRow}>
          <span className={styles.metricKey}><Layers size={11} /> 중복률</span>
          <span className={mart.dupRatio > 0.2 ? styles.metricWarn : styles.metricVal}>{dupPct}</span>
        </div>
        <div className={styles.metricRow}>
          <span className={styles.metricKey}><AlertTriangle size={11} /> 최근실패</span>
          <span className={mart.recentFailed > 0 ? styles.metricBad : styles.metricVal}>
            {mart.recentFailed} / {mart.recentTotal}
          </span>
        </div>
        <div className={styles.metricRow}>
          <span className={styles.metricKey}><Hash size={11} /> 저장</span>
          <span className={styles.metricVal}>{fmtNumber(mart.itemsSaved)}</span>
        </div>
      </div>
    </div>
  );
}

function Drilldown({ martKey, color, runs, samples, loading, error, onRefresh }) {
  const [tab, setTab] = useState('runs');
  return (
    <div className={styles.drilldown} style={{ '--mart-color': color }}>
      <div className={styles.drillHead}>
        <div className={styles.drillTitle}>
          <ChevronRight size={16} /> {martKey} 상세
        </div>
        <div className={styles.drillTabs}>
          <button className={`${styles.tab} ${tab === 'runs' ? styles.tabActive : ''}`} onClick={() => setTab('runs')}>
            최근 run
          </button>
          <button className={`${styles.tab} ${tab === 'samples' ? styles.tabActive : ''}`} onClick={() => setTab('samples')}>
            raw_payload 샘플
          </button>
          <button className={styles.tab} onClick={onRefresh} title="새로고침">
            <RefreshCw size={12} />
          </button>
        </div>
      </div>

      {error && <div className={styles.errorBanner}>{error}</div>}
      {loading && <div className={styles.loadingBar} />}

      {tab === 'runs' && (
        runs.length === 0
          ? <div className={styles.empty}>아직 실행 이력이 없습니다.</div>
          : (
            <div>
              <div className={styles.runRow} style={{ color: 'var(--text3)', fontWeight: 600 }}>
                <span>시작 시각</span>
                <span>상태</span>
                <span>found</span>
                <span>소요</span>
                <span>차단/실패 사유</span>
              </div>
              {runs.map((r) => {
                const sb = statusBadge(r.status);
                return (
                  <div key={r.run_id || r.id} className={styles.runRow}>
                    <span>{fmtTime(r.started_at)}</span>
                    <span className={`${styles.statusBadge} ${sb.cls}`}>{sb.text}</span>
                    <strong>{fmtNumber(r.items_found)}</strong>
                    <span>{fmtDuration(r.durationMs)}</span>
                    <span className={styles.runReasons} title={(r.failure_reasons || []).join(' | ')}>
                      {(r.failure_reasons || []).join(' | ') || '—'}
                    </span>
                  </div>
                );
              })}
            </div>
          )
      )}

      {tab === 'samples' && (
        samples.length === 0
          ? <div className={styles.empty}>raw_crawl_records에서 샘플을 찾을 수 없습니다 (ai-admin DB 비어있거나 source_name 불일치).</div>
          : (
            <div className={styles.samples}>
              {samples.map((s) => (
                <div key={s.raw_record_id} className={styles.sampleCard}>
                  <div className={styles.sampleTitle}>
                    <span>{s.raw_title || '(제목 없음)'}</span>
                    <span className={styles.samplePrice}>
                      {s.raw_price != null ? `${Number(s.raw_price).toLocaleString()}원` : ''}
                    </span>
                  </div>
                  <div>batch={s.batch_id} · {fmtTime(s.crawled_at)}</div>
                  <pre className={styles.samplePayload}>
                    {JSON.stringify(s.raw_payload, null, 2)}
                  </pre>
                </div>
              ))}
            </div>
          )
      )}
    </div>
  );
}

export default function Workbench() {
  const [overview, setOverview] = useState(null);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState(null);
  const [selected, setSelected] = useState(null);

  const [runs, setRuns]         = useState([]);
  const [samples, setSamples]   = useState([]);
  const [drillLoading, setDrillLoading] = useState(false);
  const [drillError, setDrillError]     = useState(null);

  const [actionMsg, setActionMsg]   = useState(null);
  const [actionBusy, setActionBusy] = useState(false);
  const [exportMsg, setExportMsg]   = useState(null);
  const [exportBusy, setExportBusy] = useState(false);

  const loadOverview = useCallback(() => {
    setLoading(true);
    setError(null);
    return api.getWorkbenchOverview()
      .then((data) => {
        // 정렬 보장
        const order = (key) => MART_ORDER.indexOf(key);
        data.marts.sort((a, b) => order(a.key) - order(b.key));
        setOverview(data);
      })
      .catch((e) => setError(e.message || '워크밴치 데이터 로드 실패'))
      .finally(() => setLoading(false));
  }, []);

  const loadDrill = useCallback((key) => {
    if (!key) return;
    setDrillLoading(true);
    setDrillError(null);
    Promise.all([
      api.getWorkbenchMartRuns(key, 20),
      api.getWorkbenchMartSamples(key, 5),
    ])
      .then(([r, s]) => {
        setRuns(r.runs || []);
        setSamples(s.samples || []);
      })
      .catch((e) => setDrillError(e.message || '상세 데이터 로드 실패'))
      .finally(() => setDrillLoading(false));
  }, []);

  useEffect(() => { loadOverview(); }, [loadOverview]);
  useEffect(() => { if (selected) loadDrill(selected); }, [selected, loadDrill]);

  const handleRunAll = useCallback(async () => {
    setActionBusy(true);
    setActionMsg({ kind: 'info', text: '4사 전수 크롤 실행 중… (수 분 소요)' });
    try {
      const res = await api.workbenchRunAll();
      const ok = (res.results || []).filter((r) => r.status === 'started').length;
      const err = (res.results || []).filter((r) => r.status === 'error').length;
      setActionMsg({
        kind: err > 0 ? 'err' : 'ok',
        text: `완료 — 시작 ${ok}건, 오류 ${err}건`,
      });
      await loadOverview();
      if (selected) await loadDrill(selected);
    } catch (e) {
      setActionMsg({ kind: 'err', text: `실패: ${e.message}` });
    } finally {
      setActionBusy(false);
    }
  }, [loadOverview, loadDrill, selected]);

  const handleExport = useCallback(async () => {
    setExportBusy(true);
    setExportMsg(null);
    try {
      const res = await api.triggerRawBatchExport({
        raw_batch_ids: [],
        include_matched: false,
        format: ['jsonl', 'csv'],
      });
      const url = api.getRawBatchExportDownloadUrl(res.export_id);
      setExportMsg({
        kind: 'ok',
        text: `unmatched export 완료 — ${res.exported_rows}건 (miss ${res.miss_rows} / hit ${res.hit_rows})`,
        href: url,
        id: res.export_id,
      });
    } catch (e) {
      setExportMsg({ kind: 'err', text: `실패: ${e.message}` });
    } finally {
      setExportBusy(false);
    }
  }, []);

  const selectedMart = useMemo(() => {
    if (!overview || !selected) return null;
    return overview.marts.find((m) => m.key === selected) || null;
  }, [overview, selected]);

  const liveBadge = useMemo(() => {
    if (!overview) return null;
    if (overview.liveReady) {
      return { cls: 'ok',   dot: styles.dotOk,   text: `라이브 가용 (${overview.registeredCount}/4 마트 등록)` };
    }
    const cnt = overview.registeredCount || 0;
    return { cls: 'warn', dot: cnt > 0 ? styles.dotWarn : styles.dotDown,
             text: `라이브 부분 — ${cnt}/4 마트만 등록됨` };
  }, [overview]);

  return (
    <div className={styles.page}>
      {/* 헤더 */}
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>마트 4사 워크밴치</h1>
          <p className={styles.subtitle}>
            매주 들여다보는 단일 화면 — 각 카드의 큰 숫자가 캡처 row 수입니다. 클릭하면 상세가 펼쳐집니다.
          </p>
        </div>
        <div className={styles.meta}>
          {liveBadge && (
            <span>
              <span className={`${styles.metaDot} ${liveBadge.dot}`} /> {liveBadge.text}
            </span>
          )}
          {overview && (
            <span>총 raw <strong>{fmtNumber(overview.totalRawRecords)}</strong></span>
          )}
          <button className={styles.btnGhost} onClick={loadOverview} disabled={loading}>
            <RefreshCw size={14} className={loading ? styles.spinning : ''} /> 새로고침
          </button>
        </div>
      </div>

      {/* 액션 바 */}
      <div className={styles.actionBar}>
        <span className={styles.actionLabel}>액션</span>
        <button className={styles.btnPrimary} onClick={handleRunAll} disabled={actionBusy}>
          <Play size={14} /> 4사 전수 크롤 시작
        </button>
        <button className={styles.btnSecondary} onClick={handleExport} disabled={exportBusy}>
          <PackageOpen size={14} /> unmatched export
        </button>
        <span className={styles.btnGhost} style={{ cursor: 'default', pointerEvents: 'none' }} title="플러그인 yaml의 max_items가 캡으로 작동합니다. 'cap 없는 풀크롤'은 각 마트 plugin.yaml을 수정하세요.">
          <Server size={14} /> 캡 없는 풀크롤은 yaml 편집 필요
        </span>

        {(actionMsg || exportMsg) && (
          <span className={`${styles.actionStatus} ${(actionMsg?.kind === 'err' || exportMsg?.kind === 'err') ? styles.err : (actionMsg?.kind === 'ok' || exportMsg?.kind === 'ok') ? styles.ok : ''}`}>
            {actionMsg && <strong>{actionMsg.text}</strong>}
            {exportMsg && (
              <>
                <strong>{exportMsg.text}</strong>
                {exportMsg.href && (
                  <a className={styles.btnGhost} href={exportMsg.href} download>
                    <Download size={12} /> {exportMsg.id}
                  </a>
                )}
              </>
            )}
          </span>
        )}
      </div>

      {error && <div className={styles.errorBanner}>{error}</div>}
      {loading && !overview && <div className={styles.loadingBar} />}

      {/* 4사 카드 */}
      {overview && (
        <div className={styles.cards}>
          {overview.marts.map((m) => (
            <MartCard
              key={m.key}
              mart={m}
              active={selected === m.key}
              onSelect={(k) => setSelected(k === selected ? null : k)}
            />
          ))}
        </div>
      )}

      {/* Drilldown */}
      {selectedMart && (
        <Drilldown
          martKey={selectedMart.label}
          color={selectedMart.color}
          runs={runs}
          samples={samples}
          loading={drillLoading}
          error={drillError}
          onRefresh={() => loadDrill(selected)}
        />
      )}
    </div>
  );
}
