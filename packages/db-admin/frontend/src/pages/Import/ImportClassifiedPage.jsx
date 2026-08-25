import { useCallback, useRef, useState } from 'react';
import {
  Upload,
  Eye,
  CheckCircle2,
  AlertTriangle,
  Download,
  FileText,
  ChevronDown,
  ChevronRight,
  RotateCcw,
} from 'lucide-react';
import { api } from '../../api/client';
import ImportDiffTable from '../../components/ImportDiffTable';
import ImportConflictList from '../../components/ImportConflictList';
import s from './ImportClassifiedPage.module.css';

function StepBar({ current }) {
  const steps = ['① 파일 선택', '② 미리보기', '③ 적용 결과'];
  return (
    <div className={s.stepBar}>
      {steps.map((label, index) => (
        <div
          key={label}
          className={`${s.step} ${index === current ? s.stepActive : index < current ? s.stepDone : ''}`}
        >
          {label}
        </div>
      ))}
    </div>
  );
}

function CountCard({ label, value, tone = 'neutral' }) {
  const classes = {
    add: s.cardAdd,
    update: s.cardUpdate,
    conflict: s.cardConflict,
    neutral: s.cardNeutral,
  };
  return (
    <div className={`${s.countCard} ${classes[tone] ?? s.cardNeutral}`}>
      <span className={s.countVal}>{value ?? 0}</span>
      <span className={s.countLabel}>{label}</span>
    </div>
  );
}

function Collapsible({ title, defaultOpen = true, children }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className={s.collapsible}>
      <button className={s.collapseHeader} onClick={() => setOpen(value => !value)}>
        {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        <span>{title}</span>
      </button>
      {open && <div className={s.collapseBody}>{children}</div>}
    </div>
  );
}

function ErrorList({ errors = [], warnings = [] }) {
  if (!errors.length && !warnings.length) return null;
  return (
    <div className={s.errorList}>
      {errors.map((error, index) => (
        <div key={`error-${index}`} className={s.errorRow}>
          <AlertTriangle size={13} />
          <span>행 {error.row}: {error.message}</span>
        </div>
      ))}
      {warnings.map((warning, index) => (
        <div key={`warning-${index}`} className={s.warnRow}>
          <AlertTriangle size={13} />
          <span>{warning}</span>
        </div>
      ))}
    </div>
  );
}

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

  const showToast = useCallback((message, type = 'info') => {
    setToast({ message, type });
    window.setTimeout(() => setToast(null), 4500);
  }, []);

  const applyFile = useCallback((nextFile) => {
    if (!nextFile) return;
    const name = nextFile.name.toLowerCase();
    if (!name.endsWith('.jsonl') && !name.endsWith('.csv')) {
      showToast('.jsonl 또는 .csv 파일만 업로드 가능합니다.', 'error');
      return;
    }
    setFile(nextFile);
    setPreview(null);
    setResult(null);
    setStep(0);
    setProgress(0);
  }, [showToast]);

  const handleDrop = useCallback((event) => {
    event.preventDefault();
    setDragOver(false);
    applyFile(event.dataTransfer.files?.[0]);
  }, [applyFile]);

  const handlePreview = async () => {
    if (!file || loading) return;
    setLoading(true);
    setProgress(0);
    try {
      const data = await api.previewImport(file, mode, { onProgress: setProgress });
      setPreview(data);
      setStep(1);
      if (!data.ok) {
        showToast(`검증 오류 ${data.errors?.length ?? 0}건`, 'error');
      }
    } catch (error) {
      showToast(error.message || '미리보기 요청 실패', 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleConfirm = async () => {
    if (!file || !preview?.ok || loading) return;
    setLoading(true);
    setProgress(0);
    try {
      const data = await api.confirmImport(
        file,
        mode,
        preview.trace_id,
        { onProgress: setProgress },
      );
      setResult(data);
      setStep(2);
      if (data.ok) showToast('분류 결과 적용 완료', 'success');
    } catch (error) {
      showToast(error.message || '적용 요청 실패', 'error');
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

  const detectedFormat = file
    ? file.name.toLowerCase().endsWith('.jsonl') ? 'JSONL' : 'CSV'
    : null;

  return (
    <div className={s.page}>
      {toast && (
        <div className={`${s.toast} ${s[toast.type]}`} role="alert">
          {toast.message}
        </div>
      )}

      <div className={s.header}>
        <div>
          <div className={s.title}>
            <FileText size={22} />
            <span>외부 분류 결과 Import</span>
          </div>
          <p style={{ margin: '4px 0 0', fontSize: 'var(--fs-sm)', color: 'var(--text3)' }}>
            외부 분류 결과를 가져와 Matching Table을 갱신합니다. 상품·카테고리를 번들로 직접 생성하지 않습니다.
          </p>
        </div>
        {step > 0 && (
          <button className={s.resetBtn} onClick={handleReset} title="처음부터 다시">
            <RotateCcw size={15} /> 초기화
          </button>
        )}
      </div>

      <StepBar current={step} />

      {step === 0 && (
        <div className={s.card}>
          <div
            className={`${s.dropzone} ${dragOver ? s.dropzoneActive : ''} ${file ? s.dropzoneHasFile : ''}`}
            onDrop={handleDrop}
            onDragOver={(event) => { event.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onClick={() => fileInputRef.current?.click()}
            role="button"
            tabIndex={0}
            onKeyDown={(event) => event.key === 'Enter' && fileInputRef.current?.click()}
            aria-label="파일 업로드 영역"
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".jsonl,.csv"
              className={s.fileInput}
              onChange={(event) => {
                applyFile(event.target.files?.[0]);
                event.target.value = '';
              }}
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
                <span>분류 결과 파일을 드래그하거나 클릭하여 선택</span>
                <span className={s.dropSub}>.jsonl 또는 .csv · 최대 50 MB</span>
              </div>
            )}
          </div>

          <div className={s.modeRow}>
            <span className={s.modeLabel}>검증 모드</span>
            <label className={s.radio}>
              <input
                type="radio"
                name="mode"
                value="strict"
                checked={mode === 'strict'}
                onChange={() => setMode('strict')}
              />
              <span>strict</span>
              <span className={s.radioDesc}>— 오류가 있으면 적용하지 않음</span>
            </label>
            <label className={s.radio}>
              <input
                type="radio"
                name="mode"
                value="lenient"
                checked={mode === 'lenient'}
                onChange={() => setMode('lenient')}
              />
              <span>lenient</span>
              <span className={s.radioDesc}>— 유효한 행만 적용</span>
            </label>
          </div>

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

      {step === 1 && preview && (
        <div className={s.card}>
          <div className={s.countRow} data-testid="diff-counts">
            <CountCard label="추가" value={preview.diff?.added} tone="add" />
            <CountCard label="수정" value={preview.diff?.updated} tone="update" />
            <CountCard label="충돌" value={preview.diff?.conflicts} tone="conflict" />
            <CountCard label="변동없음" value={preview.diff?.unchanged} tone="neutral" />
            <CountCard label="전체 입력" value={preview.diff?.total_incoming} tone="neutral" />
          </div>

          {(!!preview.errors?.length || !!preview.warnings?.length) && (
            <Collapsible title={`오류·경고 (${preview.errors?.length ?? 0}건)`}>
              <ErrorList errors={preview.errors} warnings={preview.warnings} />
            </Collapsible>
          )}

          <div data-testid="conflict-box">
            <ImportConflictList count={preview.diff?.conflicts ?? 0} mode={mode} />
          </div>

          <Collapsible title="행 미리보기 (상위 20행)">
            <ImportDiffTable rows={preview.diff?.preview_rows ?? []} maxRows={20} />
          </Collapsible>

          <p className={s.fileSummary}>
            파일: <strong>{file?.name}</strong> · 모드: <strong>{mode}</strong> · 총 {preview.total_rows}행 중 유효 {preview.valid_rows}행
          </p>

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

      {step === 2 && result && (
        <div className={s.card}>
          <div className={`${s.resultBanner} ${result.ok ? s.resultSuccess : s.resultError}`}>
            {result.ok
              ? <><CheckCircle2 size={20} /> 적용 완료{result.idempotent ? ' (이미 적용됨)' : ''}</>
              : <><AlertTriangle size={20} /> 적용 실패</>}
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
