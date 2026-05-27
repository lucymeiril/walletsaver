import { useState, useRef } from 'react';
import {
  Upload, FileText, CheckCircle2, AlertTriangle, RefreshCw, X,
} from 'lucide-react';
import { api } from '../../api/client';
import s from './TripleImportPage.module.css';

/* ────────────────────────────────────────────
   외부 LLM 분류 결과 업로드 (3-zone DnD)
   - 매칭 업데이트
   - 카테고리·키워드 업데이트 (taxonomy)
   - 상품 데이터
   기존 /api/import/bundle/preview + /confirm 사용
   ──────────────────────────────────────────── */

const ZONES = [
  { key: 'matching', title: '매칭 테이블 업데이트', hint: 'matching_entries.* json/xlsx — brand|name_core|pack_qty|pack_unit 매칭' },
  { key: 'taxonomy', title: '카테고리 · 키워드 업데이트', hint: 'categories + keywords 분류 트리' },
  { key: 'products', title: '상품 데이터', hint: 'products + baseline_prices 본문' },
];

function DropZone({ zone, file, onFile, onClear, disabled }) {
  const inputRef = useRef(null);
  const [hover, setHover] = useState(false);

  const handleDrop = (e) => {
    e.preventDefault(); setHover(false);
    if (disabled) return;
    const f = e.dataTransfer.files?.[0];
    if (f) onFile(f);
  };

  return (
    <div
      className={`${s.zone} ${hover ? s.zoneHover : ''} ${file ? s.zoneFilled : ''} ${disabled ? s.zoneDisabled : ''}`}
      onDragOver={(e) => { e.preventDefault(); if (!disabled) setHover(true); }}
      onDragLeave={() => setHover(false)}
      onDrop={handleDrop}
      onClick={() => !disabled && inputRef.current?.click()}
    >
      <input
        ref={inputRef} type="file" hidden
        accept=".json,.xlsx,.csv"
        onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])}
      />
      <div className={s.zoneIcon}>
        {file ? <FileText size={28} /> : <Upload size={28} />}
      </div>
      <div className={s.zoneTitle}>{zone.title}</div>
      <div className={s.zoneHint}>{zone.hint}</div>
      {file
        ? (
          <div className={s.zoneFile}>
            <span>{file.name}</span>
            <button onClick={(e) => { e.stopPropagation(); onClear(); }} aria-label="제거"><X size={14} /></button>
          </div>
        )
        : (
          <div className={s.zoneEmpty}>드래그&드롭 또는 클릭</div>
        )}
    </div>
  );
}

export default function TripleImportPage() {
  const [files, setFiles] = useState({ matching: null, taxonomy: null, products: null });
  const [preview, setPreview] = useState(null);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [mode, setMode] = useState('lenient');

  const update = (k, v) => setFiles(f => ({ ...f, [k]: v }));
  const hasAny = !!(files.matching || files.taxonomy || files.products);

  const doPreview = async () => {
    setBusy(true); setErr(null); setResult(null);
    try {
      const r = await api.previewBundleImport(files.matching, files.taxonomy, files.products, { mode });
      setPreview(r);
    } catch (e) { setErr(e?.message || '미리보기 실패'); }
    finally { setBusy(false); }
  };

  const doConfirm = async () => {
    if (!preview) return;
    if (!confirm('미리보기 결과를 DB에 적용하시겠습니까?')) return;
    setBusy(true); setErr(null);
    try {
      const r = await api.confirmBundleImport(
        files.matching, files.taxonomy, files.products,
        { mode, batchId: preview.batch_id || preview.batchId },
      );
      setResult(r);
      setPreview(null);
    } catch (e) { setErr(e?.message || '적용 실패'); }
    finally { setBusy(false); }
  };

  const reset = () => {
    setFiles({ matching: null, taxonomy: null, products: null });
    setPreview(null); setResult(null); setErr(null);
  };

  return (
    <div className={s.page}>
      <h2 className={s.title}>외부 LLM 분류 결과 업로드</h2>
      <p className={s.intro}>
        외부 LLM에서 산출한 분류 결과(json / xlsx / csv)를 드래그&드롭하거나 클릭해서 업로드하세요.
        세 가지 모두 또는 일부만 업로드 가능합니다. 업로드 즉시 dry-run 미리보기가 표시됩니다.
      </p>

      <div className={s.zones}>
        {ZONES.map(z => (
          <DropZone key={z.key} zone={z} file={files[z.key]}
                    onFile={(f) => update(z.key, f)} onClear={() => update(z.key, null)}
                    disabled={busy} />
        ))}
      </div>

      <div className={s.controls}>
        <label>
          모드:
          <select value={mode} onChange={(e) => setMode(e.target.value)} disabled={busy}>
            <option value="lenient">lenient (오류 행 skip)</option>
            <option value="strict">strict (전체 실패 시 롤백)</option>
          </select>
        </label>
        <button className={s.btnSecondary} onClick={reset} disabled={busy}>초기화</button>
        <button className={s.btnPrimary} onClick={doPreview} disabled={busy || !hasAny}>
          <RefreshCw size={14} className={busy ? s.spin : ''} /> 미리보기
        </button>
      </div>

      {err && <div className={s.err}><AlertTriangle size={14} /> {err}</div>}

      {/* ── 미리보기 모달/패널 ── */}
      {preview && (
        <div className={s.preview}>
          <h3>미리보기 결과 (dry-run)</h3>
          <div className={s.previewGrid}>
            <Stat label="신규 product" value={preview.products_added ?? preview.summary?.products_added} />
            <Stat label="alias 추가" value={preview.matching_added ?? preview.summary?.matching_added} />
            <Stat label="카테고리 신설" value={preview.categories_added ?? preview.summary?.categories_added} />
            <Stat label="baseline 추가" value={preview.baselines_added ?? preview.summary?.baselines_added} />
            <Stat label="오류 행" value={preview.errors ?? preview.summary?.errors} tone="warn" />
          </div>
          <pre className={s.json}>{JSON.stringify(preview, null, 2).slice(0, 3000)}</pre>
          <div className={s.previewActions}>
            <button className={s.btnSecondary} onClick={() => setPreview(null)}>취소</button>
            <button className={s.btnPrimary} onClick={doConfirm} disabled={busy}>
              <CheckCircle2 size={14} /> 적용
            </button>
          </div>
        </div>
      )}

      {/* ── 적용 결과 ── */}
      {result && (
        <div className={s.result}>
          <h3><CheckCircle2 size={16} /> 적용 완료</h3>
          <pre className={s.json}>{JSON.stringify(result, null, 2).slice(0, 3000)}</pre>
          <p className={s.rollback}>
            ⚠ 롤백 안내: 적용 후 자동 롤백은 지원하지 않습니다.
            잘못 적용된 경우 <code>/maintenance</code>에서 백업으로부터 복구하거나,
            <code>matching_entries</code>의 source='external-ai' 항목만 선별 삭제하세요.
          </p>
          <button className={s.btnSecondary} onClick={reset}>새 업로드</button>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, tone = 'neutral' }) {
  return (
    <div className={`${s.stat} ${s[tone]}`}>
      <div className={s.statVal}>{value ?? 0}</div>
      <div className={s.statLabel}>{label}</div>
    </div>
  );
}
