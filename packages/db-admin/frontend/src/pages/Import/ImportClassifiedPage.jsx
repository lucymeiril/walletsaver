import { useState, useRef, useCallback } from 'react';
import {
  Upload, Eye, CheckCircle2, AlertTriangle, Download, FileText,
  ChevronDown, ChevronRight, RotateCcw,
} from 'lucide-react';
import { api } from '../../api/client';
import ImportDiffTable from '../../components/ImportDiffTable';
import ImportConflictList from '../../components/ImportConflictList';
import s from './ImportClassifiedPage.module.css';

/* ── 진행 단계 표시 ── */
function StepBar({ current }) {
  const steps = ['① 파일 선택', '② 미리보기', '③ 적용 결과'];
  return (
    <div className={s.stepBar}>
      {steps.map((label, i) => (
        <div
          key={i}
          className={`${s.step} ${i === current ? s.stepActive : i < current ? s.stepDone : ''}`}
        >
          {label}
        </div>
      ))}
    </div>
  );
}

/* ── 카운트 카드 ── */
function CountCard({ label, value, tone = 'neutral' }) {
  const cls = { add: s.cardAdd, update: s.cardUpdate, conflict: s.cardConflict, neutral: s.cardNeutral };
  return (
    <div className={`${s.countCard} ${cls[tone] ?? s.cardNeutral}`}>
      <span className={s.countVal}>{value ?? 0}</span>
      <span className={s.countLabel}>{label}</span>
    </div>
  );
}

/* ── 접기/펴기 섹션 ── */
function Collapsible({ title, defaultOpen = true, children }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className={s.collapsible}>
      <button className={s.collapseHeader} onClick={() => setOpen(v => !v)}>
        {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        <span>{title}</span>
      </button>
      {open && <div className={s.collapseBody}>{children}</div>}
    </div>
  );
}

/* ── 오류/경고 목록 ── */
function ErrorList({ errors = [], warnings = [] }) {
  if (!errors.length && !warnings.length) return null;
  return (
    <div className={s.errorList}>
      {errors.map((e, i) => (
        <div key={i} className={s.errorRow}>
          <AlertTriangle size={13} /> <span>행 {e.row}: {e.message}</span>
        </div>
      ))}
      {warnings.map((w, i) => (
        <div key={i} className={s.warnRow}>
          <AlertTriangle size={13} /> <span>{w}</span>
        </div>
      ))}
    </div>
  );
}

/* ── 메인 페이지 ── */
export default function ImportClassifiedPage() {
  const [step, setStep] = useState(0);
  const [file, setFile] = useState(null);
  const [mode, setMode] = useState('strict');
  const [preview, setPreview] = useState(null);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [dragOver, setDragOver] = useState(false);
  const [toast, setToast] = useState(null);

  const fileInputRef = useRef(null);

  const showToast = useCallback((msg, type = 'info') => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 4500);
  }, []);

  const applyFile = useCallback((f) => {
    if (!f) return;
    const name = f.name.toLowerCase();
    if (!name.endsWith('.jsonl') && !name.endsWith('.csv')) {
      showToast('.jsonl 또는 .csv 파일만 업로드 가능합니다.', 'error');
      return;
    }
    setFile(f);
    setPreview(null);
    setResult(null);
    setStep(0);
    setProgress(0);
  }, [showToast]);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files?.[0];
    if (f) applyFile(f);
  }, [applyFile]);

  const handleDragOver = useCallback((e) => { e.preventDefault(); setDragOver(true); }, []);
  const handleDragLeave = useCallback(() => setDragOver(false), []);

  const handleFileInput = (e) => {
    const f = e.target.files?.[0];
    if (f) applyFile(f);
    e.target.value = '';
  };

  const handlePreview = async () => {
    if (!file || loading) return;
    setLoading(true);
    setProgress(0);
    try {
      const data = await api.previewImport(file, mode, { onProgress: setProgress });
      setPreview(data);
      setStep(1);
      if (!data.ok) showToast(`검증 오류 ${data.errors?.length ?? 0}건`, 'error');
    } catch (e) {
      showToast(e.message || '미리보기 요청 실패', 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleConfirm = async () => {
    if (!file || loading) return;
    setLoading(true);
    setProgress(0);
    try {
      const data = await api.confirmImport(file, mode, preview?.trace_id, { onProgress: setProgress });
      setResult(data);
      setStep(2);
      if (data.ok) showToast('적용 완료!', 'success');
    } catch (e) {
      showToast(e.message || '적용 요청 실패', 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleReset = () => {
    setFile(null);
    setPreview(null);
    setResult(null);
    setStep(0);
    setProgress(0);
  };

  /* ── 파일 포맷 자동 감지 ── */
  const detectedFormat = file
    ? file.name.toLowerCase().endsWith('.jsonl') ? 'JSONL'
      : file.name.toLowerCase().endsWith('.csv') ? 'CSV'
      : '알 수 없음'
    : null;

  return (
    <div className={s.page}>
      {/* 토스트 */}
      {toast && (
        <div className={`${s.toast} ${s[toast.type]}`} role="alert">
          {toast.msg}
        </div>
      )}

      <div className={s.header}>
        <div>
          <div className={s.title}>
            <FileText size={22} />
            <span>외부 분류 결과 Import</span>
          </div>
          <p style={{ margin: '4px 0 0', fontSize: 'var(--fs-sm)', color: 'var(--text3)' }}>
            ai-admin에서 Export한 JSONL/CSV를 업로드해 분류 결과를 DB에 반영합니다. 3단계: 파일 선택 → 미리보기 → 적용.
          </p>
        </div>
        {step > 0 && (
          <button className={s.resetBtn} onClick={handleReset} title="처음부터 다시">
            <RotateCcw size={15} /> 초기화
          </button>
        )}
      </div>

      <StepBar current={step} />

      {/* ── STEP 0: 파일 선택 ── */}
      {step === 0 && (
        <div className={s.card}>
          {/* 드래그드롭 영역 */}
          <div
            className={`${s.dropzone} ${dragOver ? s.dropzoneActive : ''} ${file ? s.dropzoneHasFile : ''}`}
            onDrop={handleDrop}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onClick={() => fileInputRef.current?.click()}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => e.key === 'Enter' && fileInputRef.current?.click()}
            aria-label="파일 업로드 영역"
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".jsonl,.csv"
              className={s.fileInput}
              onChange={handleFileInput}
              aria-label="파일 선택"
            />
            <Upload size={32} className={s.uploadIcon} />
            {file ? (
              <div className={s.fileInfo}>
                <span className={s.fileName}>{file.name}</span>
                <span className={s.fileMeta}>
                  {detectedFormat} · {(file.size / 1024).toFixed(1)} KB
                </span>
              </div>
            ) : (
              <div className={s.dropHint}>
                <span>파일을 여기에 드래그하거나 클릭하여 선택</span>
                <span className={s.dropSub}>.jsonl 또는 .csv · 최대 50 MB</span>
              </div>
            )}
          </div>

          {/* 모드 선택 */}
          <div className={s.modeRow}>
            <span className={s.modeLabel}>검증 모드</span>
            <label className={s.radio}>
              <input type="radio" name="mode" value="strict" checked={mode === 'strict'} onChange={() => setMode('strict')} />
              <span>strict</span>
              <span className={s.radioDesc}>— 오류 1건이라도 있으면 전체 거부</span>
            </label>
            <label className={s.radio}>
              <input type="radio" name="mode" value="lenient" checked={mode === 'lenient'} onChange={() => setMode('lenient')} />
              <span>lenient</span>
              <span className={s.radioDesc}>— 유효한 행만 적용, 오류 행 스킵</span>
            </label>
          </div>

          {/* 진행률 */}
          {loading && (
            <div className={s.progressWrap}>
              <div className={s.progressBar} style={{ width: `${progress}%` }} />
              <span className={s.progressText}>{progress}%</span>
            </div>
          )}

          <button
            className={s.primaryBtn}
            onClick={handlePreview}
            disabled={!file || loading}
            data-testid="preview-btn"
          >
            {loading ? '처리 중…' : <><Eye size={16} /> 미리보기</>}
          </button>
        </div>
      )}

      {/* ── STEP 1: ImportDiff 미리보기 ── */}
      {step === 1 && preview && (
        <div className={s.card}>
          {/* 카운트 카드 */}
          <div className={s.countRow} data-testid="diff-counts">
            <CountCard label="추가" value={preview.diff?.added} tone="add" />
            <CountCard label="수정" value={preview.diff?.updated} tone="update" />
            <CountCard label="충돌" value={preview.diff?.conflicts} tone="conflict" />
            <CountCard label="변동없음" value={preview.diff?.unchanged} tone="neutral" />
            <CountCard label="전체 입력" value={preview.diff?.total_incoming} tone="neutral" />
          </div>

          {/* 오류/경고 */}
          {(!!preview.errors?.length || !!preview.warnings?.length) && (
            <Collapsible title={`오류·경고 (${preview.errors?.length ?? 0}건)`} defaultOpen={true}>
              <ErrorList errors={preview.errors} warnings={preview.warnings} />
            </Collapsible>
          )}

          {/* 충돌 */}
          <ImportConflictList count={preview.diff?.conflicts ?? 0} mode={mode} />

          {/* 미리보기 테이블 */}
          <Collapsible title={`행 미리보기 (상위 20행)`} defaultOpen={true}>
            <ImportDiffTable rows={preview.diff?.preview_rows ?? []} maxRows={20} />
          </Collapsible>

          {/* 파일 정보 */}
          <p className={s.fileSummary}>
            파일: <strong>{file?.name}</strong> · 모드: <strong>{mode}</strong> ·
            총 {preview.total_rows}행 중 유효 {preview.valid_rows}행
          </p>

          {/* 진행률 */}
          {loading && (
            <div className={s.progressWrap}>
              <div className={s.progressBar} style={{ width: `${progress}%` }} />
              <span className={s.progressText}>{progress}%</span>
            </div>
          )}

          <div className={s.btnRow}>
            <button className={s.secondaryBtn} onClick={handleReset} disabled={loading}>
              취소
            </button>
            <button
              className={s.primaryBtn}
              onClick={handleConfirm}
              disabled={loading || !preview.ok}
              data-testid="confirm-btn"
            >
              {loading ? '처리 중…' : <><CheckCircle2 size={16} /> 적용 확인</>}
            </button>
          </div>
        </div>
      )}

      {/* ── STEP 2: 적용 결과 ── */}
      {step === 2 && result && (
        <div className={s.card}>
          <div className={`${s.resultBanner} ${result.ok ? s.resultSuccess : s.resultError}`}>
            {result.ok
              ? <><CheckCircle2 size={20} /> 적용 완료{result.idempotent ? ' (멱등 — 이미 적용됨)' : ''}</>
              : <><AlertTriangle size={20} /> 적용 실패</>
            }
          </div>

          <div className={s.countRow} data-testid="result-counts">
            <CountCard label="삽입" value={result.inserted} tone="add" />
            <CountCard label="수정" value={result.updated} tone="update" />
            <CountCard label="충돌 스킵" value={result.conflicts} tone="conflict" />
            <CountCard label="변동없음" value={result.skipped} tone="neutral" />
          </div>

          {(!!result.errors?.length || !!result.warnings?.length) && (
            <Collapsible title={`오류·경고 (${result.errors?.length ?? 0}건)`} defaultOpen={false}>
              <ErrorList errors={result.errors} warnings={result.warnings} />
            </Collapsible>
          )}

          {result.failure_csv_url && (
            <a
              href={result.failure_csv_url}
              className={s.csvLink}
              download
              data-testid="csv-download"
            >
              <Download size={15} /> 실패 행 CSV 다운로드
            </a>
          )}

          <button className={s.primaryBtn} onClick={handleReset} style={{ marginTop: 16 }}>
            <RotateCcw size={15} /> 새 파일 Import
          </button>
        </div>
      )}
    </div>
  );
}
