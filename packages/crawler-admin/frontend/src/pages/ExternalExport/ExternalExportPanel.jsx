/**
 * 외부 분류 내보내기.
 *
 * 폐기된 내부 분류 batch ID나 orchestrator run_id를 사용하지 않는다.
 * db-admin PendingIngestion ID를 선택해 현재 저장된 원본 items를 내보낸다.
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { Upload, RefreshCw, Download, CheckCircle2, AlertTriangle } from 'lucide-react';
import { api } from '../../api/client';
import styles from './ExternalExportPanel.module.css';

function formatDate(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`);
    return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, '0')}.${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  } catch {
    return iso;
  }
}

const STEPS = ['대기열 선택', '옵션 설정', '내보내기'];

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

function HistoryTable({ items }) {
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
            <th>원본 대기열</th>
            <th>미스 행수</th>
            <th>다운로드</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.export_id}>
              <td className={styles.codeCell}><code>{item.export_id}</code></td>
              <td className={styles.dateCell}>{formatDate(item.created_at)}</td>
              <td>{(item.source_ingestions || []).join(', ') || '—'}</td>
              <td><span className={styles.badgeMiss}>{item.miss_rows ?? '—'}</span></td>
              <td>
                <a
                  href={api.getRawBatchExportDownloadUrl(item.export_id)}
                  className={styles.dlBtn}
                  download
                  data-testid={`history-dl-${item.export_id}`}
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

export default function ExternalExportPanel() {
  const [step, setStep] = useState(1);
  const [recentIngestions, setRecentIngestions] = useState([]);
  const [ingestionsLoading, setIngestionsLoading] = useState(true);
  const [ingestionsError, setIngestionsError] = useState(null);
  const [checkedIds, setCheckedIds] = useState(new Set());
  const [manualIds, setManualIds] = useState('');
  const [includeMatched, setIncludeMatched] = useState(false);
  const [formats, setFormats] = useState(['jsonl', 'csv']);
  const [exporting, setExporting] = useState(false);
  const [exportResult, setExportResult] = useState(null);
  const [exportError, setExportError] = useState(null);
  const [history, setHistory] = useState({ items: [], loading: true, error: null });
  const toastRef = useRef(null);
  const [toast, setToast] = useState(null);

  const showToast = useCallback((msg, isError = false) => {
    setToast({ msg, isError });
    clearTimeout(toastRef.current);
    toastRef.current = setTimeout(() => setToast(null), 4000);
  }, []);

  const loadIngestions = useCallback(async () => {
    setIngestionsLoading(true);
    setIngestionsError(null);
    try {
      const data = await api.getIngestions({ limit: 50, offset: 0 });
      const items = Array.isArray(data) ? data : (data.items || []);
      setRecentIngestions(items);
    } catch (error) {
      setIngestionsError(error.message || String(error));
    } finally {
      setIngestionsLoading(false);
    }
  }, []);

  const loadHistory = useCallback(async () => {
    setHistory((prev) => ({ ...prev, loading: true, error: null }));
    try {
      const data = await api.getRecentExports(20);
      setHistory({ items: data.exports || data.items || [], loading: false, error: null });
    } catch (error) {
      setHistory({ items: [], loading: false, error: error.message || String(error) });
    }
  }, []);

  useEffect(() => {
    loadIngestions();
    loadHistory();
    return () => clearTimeout(toastRef.current);
  }, [loadIngestions, loadHistory]);

  const collectIngestionIds = useCallback(() => {
    const manual = manualIds
      .split(/[\n,]+/)
      .map((value) => value.trim())
      .filter(Boolean)
      .map(Number)
      .filter((value) => Number.isInteger(value) && value > 0);
    return [...new Set([...checkedIds, ...manual])];
  }, [checkedIds, manualIds]);

  const toggleId = useCallback((id) => {
    setCheckedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const goStep2 = useCallback(() => {
    const ids = collectIngestionIds();
    if (ids.length === 0) {
      showToast('대기열 ID를 하나 이상 선택하세요.', true);
      return;
    }
    setStep(2);
  }, [collectIngestionIds, showToast]);

  const toggleFormat = useCallback((fmt) => {
    setFormats((prev) => prev.includes(fmt) ? prev.filter((value) => value !== fmt) : [...prev, fmt]);
  }, []);

  const handleExport = useCallback(async () => {
    if (exporting) return;
    const ingestion_ids = collectIngestionIds();
    if (ingestion_ids.length === 0) {
      showToast('대기열 ID가 없습니다.', true);
      return;
    }
    if (formats.length === 0) {
      showToast('출력 형식을 하나 이상 선택하세요.', true);
      return;
    }

    setExporting(true);
    setExportError(null);
    setExportResult(null);
    setStep(3);
    try {
      const result = await api.triggerRawBatchExport({
        ingestion_ids,
        include_matched: includeMatched,
        format: formats,
      });
      setExportResult(result);
      showToast(`내보내기 완료 — 미스 ${result.miss_rows ?? 0}행`);
      loadHistory();
    } catch (error) {
      const message = error.message || String(error);
      setExportError(message);
      showToast(`내보내기 실패: ${message}`, true);
    } finally {
      setExporting(false);
    }
  }, [exporting, collectIngestionIds, formats, includeMatched, showToast, loadHistory]);

  const ingestionIds = collectIngestionIds();

  return (
    <div className={styles.page} data-testid="external-export-panel">
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>
            <Upload size={20} className={styles.titleIcon} /> 외부 분류 내보내기
          </h1>
          <p className={styles.desc}>
            현재 db-admin 대기열의 원본 상품을 외부 LLM 분류용 JSONL/CSV로 내보냅니다.
          </p>
        </div>
      </div>

      <StepIndicator current={step} />

      {step === 1 && (
        <section className={styles.card} aria-label="Step 1: 대기열 선택">
          <h2 className={styles.cardTitle}>① 대기열 선택</h2>
          <p className={styles.optionHint}>
            orchestrator run ID가 아니라 데이터 검토 화면과 같은 PendingIngestion ID를 사용합니다.
          </p>

          {ingestionsLoading && <p className={styles.muted}>최근 대기열 불러오는 중…</p>}
          {ingestionsError && (
            <div className={styles.warnBox}><AlertTriangle size={14} /> {ingestionsError}</div>
          )}

          {!ingestionsLoading && recentIngestions.length > 0 && (
            <fieldset className={styles.checkGroup}>
              <legend className={styles.checkLegend}>최근 대기열</legend>
              {recentIngestions.map((ingestion) => {
                const id = Number(ingestion.id);
                if (!Number.isInteger(id)) return null;
                const label = ingestion.crawler_name || ingestion.crawlerName || 'crawler';
                const count = ingestion.items_count ?? ingestion.itemCount ?? 0;
                const status = ingestion.status || 'unknown';
                return (
                  <label key={id} className={styles.checkLabel}>
                    <input
                      type="checkbox"
                      checked={checkedIds.has(id)}
                      onChange={() => toggleId(id)}
                      data-testid={`ingestion-checkbox-${id}`}
                    />
                    <span className={styles.checkText}>
                      <code className={styles.runId}>#{id}</code>
                      <span className={styles.runMeta}>
                        {label} · {count}건 · {status} · {formatDate(ingestion.crawled_at)}
                      </span>
                    </span>
                  </label>
                );
              })}
            </fieldset>
          )}

          <label className={styles.manualLabel}>
            <span className={styles.fieldName}>또는 대기열 ID 직접 입력</span>
            <textarea
              className={styles.textarea}
              value={manualIds}
              onChange={(e) => setManualIds(e.target.value)}
              placeholder="예: 12, 13, 21"
              rows={3}
              data-testid="manual-ingestion-ids"
            />
          </label>

          {ingestionIds.length > 0 && (
            <p className={styles.selectedCount}>선택된 대기열: <strong>{ingestionIds.length}개</strong></p>
          )}

          <div className={styles.btnRow}>
            <button className={styles.btnPrimary} onClick={goStep2}>다음: 옵션 설정 →</button>
          </div>
        </section>
      )}

      {step === 2 && (
        <section className={styles.card} aria-label="Step 2: 옵션 설정">
          <h2 className={styles.cardTitle}>② 옵션 설정</h2>
          <div className={styles.optionGroup}>
            <label className={styles.optionLabel}>
              <input
                type="checkbox"
                checked={includeMatched}
                onChange={(e) => setIncludeMatched(e.target.checked)}
              />
              <span><strong>이미 매칭된 항목 포함</strong><span className={styles.optionHint}> (기본 off)</span></span>
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
                />
                {fmt.toUpperCase()}
              </label>
            ))}
          </fieldset>

          <p className={styles.selectedCount}>
            대기열 <strong>{ingestionIds.length}개</strong> · 형식 <strong>{formats.join(' + ') || '—'}</strong>
          </p>

          <div className={styles.btnRow}>
            <button className={styles.btnSecondary} onClick={() => setStep(1)}>← 이전</button>
            <button
              className={styles.btnPrimary}
              onClick={handleExport}
              disabled={exporting || formats.length === 0}
              data-testid="export-trigger-btn"
            >
              {exporting ? '내보내는 중…' : '내보내기 실행'}
            </button>
          </div>
        </section>
      )}

      {step === 3 && (
        <section className={styles.card} aria-label="Step 3: 결과">
          <h2 className={styles.cardTitle}>③ 내보내기 결과</h2>
          {exporting && (
            <div className={styles.loadingRow}>
              <RefreshCw size={16} className={styles.spinning} /> 처리 중…
            </div>
          )}
          {exportError && <div className={styles.errorBox}><AlertTriangle size={14} /> {exportError}</div>}
          {exportResult && (
            <div data-testid="export-result-panel">
              <div className={styles.resultMeta}>
                <div className={styles.resultRow}><span className={styles.resultKey}>Export ID</span><code>{exportResult.export_id}</code></div>
                <div className={styles.resultRow}><span className={styles.resultKey}>원본 대기열</span><span>{(exportResult.source_ingestions || []).join(', ')}</span></div>
                <div className={styles.resultRow}><span className={styles.resultKey}>미스 행수</span><span className={styles.badgeMiss}>{exportResult.miss_rows ?? 0}</span></div>
                <div className={styles.resultRow}><span className={styles.resultKey}>내보낸 행수</span><span>{exportResult.exported_rows ?? 0}</span></div>
              </div>
              <a
                className={styles.dlBtnPrimary}
                href={api.getRawBatchExportDownloadUrl(exportResult.export_id)}
                download
              >
                <Download size={15} /> ZIP 다운로드
              </a>
              <div className={styles.btnRow}>
                <button className={styles.btnSecondary} onClick={() => setStep(1)}>다른 대기열 선택</button>
              </div>
            </div>
          )}
        </section>
      )}

      <section className={styles.card} aria-label="내보내기 이력">
        <div className={styles.tableHeaderRow}>
          <h2 className={styles.cardTitle}>최근 내보내기</h2>
          <button className={styles.btnSecondary} onClick={loadHistory} disabled={history.loading}>
            <RefreshCw size={13} className={history.loading ? styles.spinning : ''} /> 새로고침
          </button>
        </div>
        {history.error ? (
          <div className={styles.errorBox}><AlertTriangle size={14} /> {history.error}</div>
        ) : history.loading ? (
          <p className={styles.muted}>이력 불러오는 중…</p>
        ) : (
          <HistoryTable items={history.items} />
        )}
      </section>

      {toast && (
        <div className={toast.isError ? styles.toastError : styles.toast} role="status">
          {toast.msg}
        </div>
      )}
    </div>
  );
}
