/**
 * ExternalExportPanel.jsx
 * 외부 분류 내보내기 — raw batch를 JSONL/CSV zip으로 내보냅니다.
 *
 * API:
 *   POST /api/export/raw-batch  { raw_batch_ids, include_matched, format }
 *   GET  /api/export/raw-batch/recent?limit=20
 *   GET  /api/export/raw-batch/{export_id}/download  (zip)
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { Upload, RefreshCw, Download, BookOpen, CheckCircle2, AlertTriangle } from 'lucide-react';
import { api } from '../../api/client';
import styles from './ExternalExportPanel.module.css';

// ── 포맷 유틸 ────────────────────────────────────────────────────────────────

function formatDate(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z');
    return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, '0')}.${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  } catch { return iso; }
}

// ── 3단계 인디케이터 ─────────────────────────────────────────────────────────

const STEPS = ['raw batch 선택', '옵션 설정', '내보내기'];

function StepIndicator({ current }) {
  return (
    <ol className={styles.steps} aria-label="진행 단계">
      {STEPS.map((label, i) => {
        const stepNum = i + 1;
        const isDone = current > stepNum;
        const isActive = current === stepNum;
        return (
          <li
            key={label}
            className={`${styles.step} ${isDone ? styles.stepDone : ''} ${isActive ? styles.stepActive : ''}`}
          >
            <span className={styles.stepNum}>{isDone ? '✓' : stepNum}</span>
            <span className={styles.stepLabel}>{label}</span>
            {i < STEPS.length - 1 && <span className={styles.stepSep} aria-hidden="true" />}
          </li>
        );
      })}
    </ol>
  );
}

// ── 이력 테이블 ───────────────────────────────────────────────────────────────

function HistoryTable({ items, loading, error, onDownload }) {
  if (loading) {
    return <p className={styles.muted}>이력 불러오는 중…</p>;
  }
  if (error) {
    return (
      <div className={styles.errorBox}>
        <AlertTriangle size={14} /> {error}
      </div>
    );
  }
  if (!items || items.length === 0) {
    return (
      <div className={styles.empty}>
        <CheckCircle2 size={24} />
        <p>내보내기 이력이 없습니다.</p>
      </div>
    );
  }
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Export ID</th>
            <th>생성일시</th>
            <th>미스 행수</th>
            <th>다운로드</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.export_id || item.batch_id || item.id}>
              <td className={styles.codeCell}>
                <code>{item.export_id || item.batch_id || item.id || '—'}</code>
              </td>
              <td className={styles.dateCell}>{formatDate(item.created_at)}</td>
              <td>
                <span className={styles.badgeMiss}>
                  {item.miss_rows ?? item.miss_count ?? '—'}
                </span>
              </td>
              <td>
                <a
                  href={api.getRawBatchExportDownloadUrl(item.export_id || item.batch_id || item.id)}
                  className={styles.dlBtn}
                  download
                  data-testid={`history-dl-${item.export_id || item.id}`}
                >
                  <Download size={13} /> ZIP
                </a>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── 메인 컴포넌트 ────────────────────────────────────────────────────────────

export default function ExternalExportPanel() {
  // 단계: 1=batch 선택, 2=옵션, 3=내보내기(결과)
  const [step, setStep] = useState(1);

  // Step 1: batch 선택
  const [recentRuns, setRecentRuns] = useState([]);
  const [runsLoading, setRunsLoading] = useState(true);
  const [runsError, setRunsError] = useState(null);
  const [checkedIds, setCheckedIds] = useState(new Set());
  const [manualIds, setManualIds] = useState('');

  // Step 2: 옵션
  const [includeMatched, setIncludeMatched] = useState(false);
  const [formats, setFormats] = useState(['jsonl', 'csv']);

  // Step 3: 내보내기
  const [exporting, setExporting] = useState(false);
  const [exportResult, setExportResult] = useState(null);
  const [exportError, setExportError] = useState(null);

  // 이력
  const [history, setHistory] = useState({ items: [], loading: true, error: null });

  const toastRef = useRef(null);
  const [toast, setToast] = useState(null);

  const showToast = useCallback((msg, isError = false) => {
    setToast({ msg, isError });
    clearTimeout(toastRef.current);
    toastRef.current = setTimeout(() => setToast(null), 4000);
  }, []);

  // ── 최근 runs 로드 (batch 선택 목록용) ──
  const loadRuns = useCallback(async () => {
    setRunsLoading(true);
    setRunsError(null);
    try {
      const data = await api.getRuns({ limit: 20 });
      const items = Array.isArray(data) ? data : (data.items || data.runs || []);
      setRecentRuns(items);
    } catch (e) {
      setRunsError(e.message || String(e));
    } finally {
      setRunsLoading(false);
    }
  }, []);

  // ── 이력 로드 ──
  const loadHistory = useCallback(async () => {
    setHistory((p) => ({ ...p, loading: true, error: null }));
    try {
      const data = await api.getRecentExports(20);
      const items = Array.isArray(data) ? data : (data.exports || data.items || []);
      setHistory({ items, loading: false, error: null });
    } catch (e) {
      setHistory({ items: [], loading: false, error: e.message || String(e) });
    }
  }, []);

  useEffect(() => {
    loadRuns();
    loadHistory();
    return () => clearTimeout(toastRef.current);
  }, [loadRuns, loadHistory]);

  // ── batch id 수집 ──
  const collectBatchIds = useCallback(() => {
    const fromCheck = [...checkedIds];
    const fromManual = manualIds
      .split(/[\n,]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    const all = [...new Set([...fromCheck, ...fromManual])];
    return all;
  }, [checkedIds, manualIds]);

  // ── 토글 체크박스 ──
  const toggleId = useCallback((id) => {
    setCheckedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  // ── Step 전환 ──
  const goStep2 = useCallback(() => {
    const ids = collectBatchIds();
    if (ids.length === 0) {
      showToast('raw batch를 하나 이상 선택하거나 ID를 입력하세요.', true);
      return;
    }
    setStep(2);
  }, [collectBatchIds, showToast]);

  const goStep1 = useCallback(() => setStep(1), []);

  // ── 포맷 토글 ──
  const toggleFormat = useCallback((fmt) => {
    setFormats((prev) =>
      prev.includes(fmt) ? prev.filter((f) => f !== fmt) : [...prev, fmt]
    );
  }, []);

  // ── Export 실행 ──
  const handleExport = useCallback(async () => {
    if (exporting) return;
    if (formats.length === 0) {
      showToast('출력 형식을 하나 이상 선택하세요.', true);
      return;
    }
    const raw_batch_ids = collectBatchIds();
    if (raw_batch_ids.length === 0) {
      showToast('raw batch ID가 없습니다.', true);
      return;
    }
    setExporting(true);
    setExportError(null);
    setExportResult(null);
    setStep(3);
    try {
      const result = await api.triggerRawBatchExport({
        raw_batch_ids,
        include_matched: includeMatched,
        format: formats,
      });
      setExportResult(result);
      showToast(`내보내기 완료 — 미스 ${result.miss_rows ?? result.miss_count ?? 0}행`);
      loadHistory();
    } catch (e) {
      const msg = e.message || String(e);
      setExportError(msg);
      showToast(`내보내기 실패: ${msg}`, true);
    } finally {
      setExporting(false);
    }
  }, [exporting, formats, collectBatchIds, includeMatched, showToast, loadHistory]);

  // ── 렌더 ──────────────────────────────────────────────────────────────────

  const batchIds = collectBatchIds();

  return (
    <div className={styles.page} data-testid="external-export-panel">
      {/* 헤더 */}
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>
            <Upload size={20} className={styles.titleIcon} />
            외부 분류 내보내기
          </h1>
          <p className={styles.desc}>
            매칭 테이블에 없는 raw 상품만 LLM 분류용으로 내보냅니다. 매주 1회 권장.
          </p>
        </div>
        <a
          href="https://github.com/lucymeiril/walletSavior/blob/main/docs/EXTERNAL_CLASSIFICATION_GUIDE.md"
          target="_blank"
          rel="noopener noreferrer"
          className={styles.manualLink}
        >
          <BookOpen size={14} /> 📘 외부 분류 운영 매뉴얼
        </a>
      </div>

      {/* 단계 인디케이터 */}
      <StepIndicator current={step} />

      {/* ── Step 1: raw batch 선택 ── */}
      {step === 1 && (
        <section className={styles.card} aria-label="Step 1: raw batch 선택">
          <h2 className={styles.cardTitle}>① raw batch 선택</h2>

          {runsLoading && <p className={styles.muted}>최근 실행 목록 불러오는 중…</p>}
          {runsError && (
            <div className={styles.warnBox}>
              <AlertTriangle size={14} /> 실행 목록 로드 실패: {runsError}
            </div>
          )}

          {!runsLoading && recentRuns.length > 0 && (
            <fieldset className={styles.checkGroup}>
              <legend className={styles.checkLegend}>최근 실행 (run_id = raw_batch_id)</legend>
              {recentRuns.map((run) => {
                const id = run.run_id || run.id || run.batch_id;
                const label = run.plugin_name || run.crawler_name || id;
                const ts = formatDate(run.started_at || run.created_at);
                return (
                  <label key={id} className={styles.checkLabel}>
                    <input
                      type="checkbox"
                      checked={checkedIds.has(id)}
                      onChange={() => toggleId(id)}
                      data-testid={`raw-batch-checkbox-${id}`}
                    />
                    <span className={styles.checkText}>
                      <code className={styles.runId}>{id}</code>
                      <span className={styles.runMeta}>{label} · {ts}</span>
                    </span>
                  </label>
                );
              })}
            </fieldset>
          )}

          <label className={styles.manualLabel}>
            <span className={styles.fieldName}>또는 batch ID 직접 입력</span>
            <textarea
              className={styles.textarea}
              value={manualIds}
              onChange={(e) => setManualIds(e.target.value)}
              placeholder="한 줄에 하나씩 또는 쉼표로 구분"
              rows={3}
              data-testid="manual-batch-ids"
            />
          </label>

          {batchIds.length > 0 && (
            <p className={styles.selectedCount}>
              선택된 batch: <strong>{batchIds.length}개</strong>
            </p>
          )}

          <div className={styles.btnRow}>
            <button
              className={styles.btnPrimary}
              onClick={goStep2}
            >
              다음: 옵션 설정 →
            </button>
          </div>
        </section>
      )}

      {/* ── Step 2: 옵션 ── */}
      {step === 2 && (
        <section className={styles.card} aria-label="Step 2: 옵션 설정">
          <h2 className={styles.cardTitle}>② 옵션 설정</h2>

          <div className={styles.optionGroup}>
            <label className={styles.optionLabel}>
              <input
                type="checkbox"
                checked={includeMatched}
                onChange={(e) => setIncludeMatched(e.target.checked)}
                data-testid="include-matched"
              />
              <span>
                <strong>이미 매칭된 항목 포함</strong>
                <span className={styles.optionHint}> (기본 off — 미스 항목만 내보냄)</span>
              </span>
            </label>
          </div>

          <fieldset className={styles.fmtGroup}>
            <legend className={styles.checkLegend}>출력 형식</legend>
            {['jsonl', 'csv'].map((fmt) => (
              <label key={fmt} className={styles.checkLabel}>
                <input
                  type="checkbox"
                  checked={formats.includes(fmt)}
                  onChange={() => toggleFormat(fmt)}
                  data-testid={`format-${fmt}`}
                />
                {fmt.toUpperCase()}
              </label>
            ))}
          </fieldset>

          <p className={styles.selectedCount}>
            선택된 batch <strong>{batchIds.length}개</strong> ·
            형식 <strong>{formats.join(' + ') || '—'}</strong>
          </p>

          <div className={styles.btnRow}>
            <button className={styles.btnSecondary} onClick={goStep1}>
              ← 이전
            </button>
            <button
              className={styles.btnPrimary}
              onClick={handleExport}
              disabled={exporting || formats.length === 0}
              data-testid="export-trigger-btn"
            >
              {exporting ? (
                <>
                  <RefreshCw size={14} className={styles.spinning} /> 내보내는 중…
                </>
              ) : (
                '내보내기 실행'
              )}
            </button>
          </div>
        </section>
      )}

      {/* ── Step 3: 결과 ── */}
      {step === 3 && (
        <section className={styles.card} aria-label="Step 3: 결과">
          <h2 className={styles.cardTitle}>③ 내보내기 결과</h2>

          {exporting && (
            <div className={styles.loadingRow}>
              <RefreshCw size={16} className={styles.spinning} />
              <span>백엔드 처리 중입니다. 잠시 기다려 주세요…</span>
            </div>
          )}

          {exportError && (
            <div className={styles.errorBox}>
              <AlertTriangle size={14} /> {exportError}
            </div>
          )}

          {exportResult && (
            <div data-testid="export-result-panel">
              <div className={styles.resultMeta}>
                <div className={styles.resultRow}>
                  <span className={styles.resultKey}>Export ID</span>
                  <code>{exportResult.export_id || exportResult.batch_id || '—'}</code>
                </div>
                <div className={styles.resultRow}>
                  <span className={styles.resultKey}>미스 행수</span>
                  <span className={styles.badgeMiss}>
                    {exportResult.miss_rows ?? exportResult.miss_count ?? '—'}
                  </span>
                </div>
                {exportResult.file_sha256s && (
                  <div className={styles.resultRow}>
                    <span className={styles.resultKey}>파일 SHA256</span>
                    <code className={styles.sha}>{JSON.stringify(exportResult.file_sha256s)}</code>
                  </div>
                )}
              </div>

              <div className={styles.guideBanner}>
                💡 이 파일을 외부 LLM(Haiku/GPT-4.1)에 매뉴얼대로 넘기세요.
                분류 결과를 받으면 db-admin &apos;분류 Import&apos;로 업로드합니다.
              </div>

              <div className={styles.dlRow}>
                <a
                  href={api.getRawBatchExportDownloadUrl(
                    exportResult.export_id || exportResult.batch_id
                  )}
                  className={styles.btnPrimary}
                  download
                  data-testid="download-zip-btn"
                >
                  <Download size={14} /> ZIP 다운로드
                </a>
              </div>
            </div>
          )}

          <div className={styles.btnRow} style={{ marginTop: 16 }}>
            <button className={styles.btnSecondary} onClick={goStep1}>
              ← 처음으로
            </button>
          </div>
        </section>
      )}

      {/* ── 이력 테이블 ── */}
      <section className={styles.historySection} data-testid="export-history-section">
        <div className={styles.historyHeader}>
          <h2 className={styles.cardTitle} style={{ margin: 0 }}>최근 내보내기 이력</h2>
          <button
            className={styles.btnSecondary}
            onClick={loadHistory}
            disabled={history.loading}
            title="새로고침"
          >
            <RefreshCw size={14} className={history.loading ? styles.spinning : ''} />
            새로고침
          </button>
        </div>
        <HistoryTable
          items={history.items}
          loading={history.loading}
          error={history.error}
          onDownload={api.getRawBatchExportDownloadUrl}
        />
      </section>

      {/* 토스트 */}
      {toast && (
        <div
          className={`${styles.toast} ${toast.isError ? styles.toastErr : ''}`}
          role="alert"
          data-testid="export-toast"
        >
          {toast.msg}
        </div>
      )}
    </div>
  );
}
