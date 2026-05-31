import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Download, Upload, Eye, RefreshCw, CheckCircle2, AlertTriangle,
  FileArchive, Layers, ArrowRight, ListChecks, History, X, RotateCcw,
} from 'lucide-react';
import { api } from '../../api/client';
import s from './CatalogSyncPage.module.css';

/* ── 엔티티 메타 ── */
const ENTITY_LABELS = {
  categories: '통합 카테고리',
  match_rules: '매칭 규칙(정본)',
  products: '상품',
  mappings: '마트 매핑(보조)',
};
const ALL_ENTITIES = ['categories', 'match_rules', 'products', 'mappings'];

const SCOPE_OPTIONS = {
  categories: [['all', '전체'], ['subtree', '특정 트리(root_id)']],
  match_rules: [['all', '전체'], ['by_category', '카테고리별(category_id)'], ['unmatched', '미연결 규칙']],
  products: [['all', '전체'], ['unclassified', '미분류만'], ['by_category', '카테고리별(category_id)'], ['by_mart', '마트별(mart)']],
  mappings: [['all', '전체'], ['by_mart', '마트별(mart)'], ['needs_review', '검토 필요']],
};
const SCOPE_ARG = { subtree: 'root_id', by_category: 'category_id', by_mart: 'mart' };

const RECAT_SCOPES = [
  ['all', '전체 상품'],
  ['unclassified', '미분류 상품만'],
  ['by_category', '특정 카테고리(category_id)'],
  ['by_mart', '특정 마트(mart)'],
];

function CountCard({ label, value, tone = '' }) {
  return (
    <div className={`${s.countCard} ${tone}`}>
      <span className={s.countVal}>{Number(value ?? 0).toLocaleString()}</span>
      <span className={s.countLabel}>{label}</span>
    </div>
  );
}

function Alert({ kind = 'err', children }) {
  const cls = { err: s.alertErr, ok: s.alertOk, warn: s.alertWarn }[kind];
  const Icon = kind === 'ok' ? CheckCircle2 : AlertTriangle;
  return <div className={`${s.alert} ${cls}`}><Icon size={15} /><span>{children}</span></div>;
}

/* ───────────────────────── Export ───────────────────────── */
function ExportTab() {
  const [selected, setSelected] = useState({ categories: true, match_rules: true, products: true, mappings: false });
  const [scopeMode, setScopeMode] = useState({});
  const [scopeArg, setScopeArg] = useState({});
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const toggle = (e) => setSelected((p) => ({ ...p, [e]: !p[e] }));

  const run = async () => {
    setBusy(true); setError(null); setResult(null);
    try {
      const entities = ALL_ENTITIES.filter((e) => selected[e]);
      if (!entities.length) { setError('엔티티를 1개 이상 선택하세요.'); setBusy(false); return; }
      const scopes = {};
      for (const e of entities) {
        const m = scopeMode[e] || 'all';
        if (m === 'all') continue;
        const sc = { mode: m };
        const argKey = SCOPE_ARG[m];
        if (argKey) {
          const v = (scopeArg[e] || '').trim();
          if (!v) { setError(`${ENTITY_LABELS[e]}의 ${argKey} 값을 입력하세요.`); setBusy(false); return; }
          sc[argKey] = v;
        }
        scopes[e] = sc;
      }
      const res = await api.catalogSyncExport(entities, Object.keys(scopes).length ? scopes : null);
      setResult(res);
    } catch (err) {
      setError(err.message || '내보내기 실패');
    } finally {
      setBusy(false);
    }
  };

  const download = async () => {
    if (!result?.name) return;
    try {
      await api.downloadAuthed(api.catalogSyncDownloadUrl(result.name), `${result.name}.zip`);
    } catch (err) {
      setError(err.message || '다운로드 실패');
    }
  };

  return (
    <div className={s.card}>
      <h3 className={s.cardTitle}><Download size={16} /> 내보내기 (외부 AI 전달용 번들 생성)</h3>
      <div className={s.checks}>
        {ALL_ENTITIES.map((e) => (
          <label key={e} className={s.check}>
            <input type="checkbox" checked={!!selected[e]} onChange={() => toggle(e)} />
            {ENTITY_LABELS[e]}
          </label>
        ))}
      </div>

      {ALL_ENTITIES.filter((e) => selected[e]).map((e) => {
        const mode = scopeMode[e] || 'all';
        const argKey = SCOPE_ARG[mode];
        return (
          <div key={e} className={s.row} style={{ marginBottom: 8 }}>
            <span className={s.label} style={{ minWidth: 130 }}>{ENTITY_LABELS[e]} 범위</span>
            <select
              className={s.select}
              value={mode}
              onChange={(ev) => setScopeMode((p) => ({ ...p, [e]: ev.target.value }))}
            >
              {SCOPE_OPTIONS[e].map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
            {argKey && (
              <input
                className={s.input}
                placeholder={argKey}
                value={scopeArg[e] || ''}
                onChange={(ev) => setScopeArg((p) => ({ ...p, [e]: ev.target.value }))}
              />
            )}
          </div>
        );
      })}

      <div className={s.row} style={{ marginTop: 12 }}>
        <button className={s.btn} onClick={run} disabled={busy}>
          <FileArchive size={15} /> {busy ? '생성 중…' : '내보내기 실행'}
        </button>
        {result && (
          <button className={`${s.btn} ${s.btnGhost}`} onClick={download}>
            <Download size={15} /> zip 다운로드
          </button>
        )}
      </div>

      {error && <Alert kind="err">{error}</Alert>}
      {result && (
        <>
          <div className={s.cards}>
            {Object.entries(result.manifest?.counts || {}).map(([k, v]) => (
              <CountCard key={k} label={ENTITY_LABELS[k] || k} value={v} tone={s.toneGood} />
            ))}
          </div>
          <p className={s.muted}>서버 저장 위치: <span className={s.snapPath}>{result.out_dir}</span></p>
        </>
      )}
    </div>
  );
}

/* ───────────────────────── Import ───────────────────────── */
const WRITE_MODES = [
  ['upsert', 'upsert — 추가 + 갱신(기본)'],
  ['append_only', 'append_only — 신규만 추가'],
  ['patch', 'patch — 기존만 갱신'],
  ['replace_all', 'replace_all — 파일을 정본 전체로(없는 행 삭제, 상품 제외)'],
];

function ImportTab() {
  const [files, setFiles] = useState([]);
  const [report, setReport] = useState(null);
  const [applyResult, setApplyResult] = useState(null);
  const [force, setForce] = useState(false);
  const [writeMode, setWriteMode] = useState('upsert');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [confirmDestructive, setConfirmDestructive] = useState(false);
  const inputRef = useRef(null);

  const pickFiles = (list) => {
    setFiles(Array.from(list || []));
    setReport(null); setApplyResult(null); setError(null);
  };

  const validate = async () => {
    setBusy(true); setError(null); setReport(null); setApplyResult(null);
    try {
      const res = await api.catalogSyncValidate(files, { mode: writeMode, force });
      setReport(res);
    } catch (err) {
      setError(err.message || '검증 실패');
    } finally { setBusy(false); }
  };

  const doApply = async () => {
    setBusy(true); setError(null); setConfirmDestructive(false);
    try {
      const res = await api.catalogSyncApply(files, { mode: writeMode, force });
      setApplyResult(res);
      if (!res.ok) setError(res.error_message || '적용 실패');
    } catch (err) {
      setError(err.message || '적용 실패');
    } finally { setBusy(false); }
  };

  const totalDeletes = Object.values(report?.diff || {}).reduce((n, d) => n + (d.delete || 0), 0);

  const apply = () => {
    if (writeMode === 'replace_all' && totalDeletes > 0) {
      setConfirmDestructive(true);
      return;
    }
    doApply();
  };

  return (
    <div className={s.card}>
      <h3 className={s.cardTitle}><Upload size={16} /> 가져오기 (manifest.json + *.jsonl 번들)</h3>

      <div
        className={s.dropzone}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => { e.preventDefault(); pickFiles(e.dataTransfer.files); }}
      >
        <Upload size={26} />
        <div className={s.dropHint}>클릭하거나 파일을 끌어다 놓으세요 (manifest.json 필수 + 엔티티 .jsonl)</div>
        <input
          ref={inputRef}
          type="file"
          multiple
          style={{ display: 'none' }}
          onChange={(e) => pickFiles(e.target.files)}
        />
      </div>

      {files.length > 0 && (
        <div className={s.fileList}>
          {files.map((f) => <span key={f.name} className={s.fileChip}>{f.name}</span>)}
        </div>
      )}

      <div className={s.row} style={{ marginTop: 12 }}>
        <label className={s.check} style={{ gap: 6 }}>
          반영 방식
          <select
            className={s.select}
            value={writeMode}
            onChange={(e) => { setWriteMode(e.target.value); setReport(null); setApplyResult(null); }}
          >
            {WRITE_MODES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
          </select>
        </label>
      </div>
      {writeMode === 'replace_all' && (
        <Alert kind="warn">
          replace_all은 파일에 없는 카테고리·규칙을 <b>삭제</b>합니다. 참조 중인 카테고리는 검증에서 차단됩니다. 상품은 포함할 수 없습니다.
        </Alert>
      )}

      <div className={s.row} style={{ marginTop: 12 }}>
        <button className={s.btn} onClick={validate} disabled={busy || !files.length}>
          <Eye size={15} /> {busy ? '검증 중…' : '검증(미리보기)'}
        </button>
        <label className={s.check}>
          <input type="checkbox" checked={force} onChange={() => setForce((v) => !v)} />
          사람이 지정한 분류도 덮어쓰기(force)
        </label>
        <button
          className={s.btn}
          onClick={apply}
          disabled={busy || !files.length || !report || !report.ok}
          title={!report ? '먼저 검증하세요' : (!report.ok ? '검증 오류를 해결하세요' : '')}
        >
          <CheckCircle2 size={15} /> 적용({writeMode})
        </button>
      </div>

      {error && <Alert kind="err">{error}</Alert>}

      {report && (
        <>
          {report.same_database
            ? <Alert kind="ok">동일 DB 번들입니다 — 상품 id 기반 적용이 허용됩니다.</Alert>
            : <Alert kind="warn">다른 DB의 번들입니다 — 상품은 id 불일치 시 건너뜁니다(카테고리·규칙은 자연키로 적용).</Alert>}
          {report.errors?.length > 0 && report.errors.map((e, i) => <Alert key={i} kind="err">{e}</Alert>)}
          {report.warnings?.length > 0 && report.warnings.map((w, i) => <Alert key={i} kind="warn">{w}</Alert>)}

          <table className={s.table}>
            <thead>
              <tr><th>엔티티</th><th>생성</th><th>수정</th><th>삭제</th><th>변화없음</th><th>건너뜀</th><th>모드제외</th><th>보호</th><th>오류</th></tr>
            </thead>
            <tbody>
              {Object.entries(report.diff || {}).map(([k, d]) => (
                <tr key={k}>
                  <td>{ENTITY_LABELS[k] || k}</td>
                  <td>{d.create ?? 0}</td>
                  <td>{d.update ?? 0}</td>
                  <td className={(d.delete ?? 0) > 0 ? s.danger : ''}>{d.delete ?? 0}</td>
                  <td>{d.unchanged ?? 0}</td>
                  <td>{d.skipped ?? 0}</td>
                  <td>{d.skipped_mode ?? 0}</td>
                  <td>{d.protected ?? 0}</td>
                  <td>{d.invalid ?? 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {applyResult?.ok && (
        <>
          <Alert kind="ok">적용 완료. 스냅샷이 저장되었습니다.</Alert>
          <table className={s.table}>
            <thead><tr><th>엔티티</th><th>결과</th></tr></thead>
            <tbody>
              {Object.entries(applyResult.counts || {}).map(([k, c]) => (
                <tr key={k}>
                  <td>{ENTITY_LABELS[k] || k}</td>
                  <td className={s.mono}>{Object.entries(c).map(([ck, cv]) => `${ck}:${cv}`).join('  ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className={s.muted}>스냅샷: <span className={s.snapPath}>{applyResult.snapshot_path}</span></p>
        </>
      )}

      {confirmDestructive && (
        <div className={s.modalBackdrop} onClick={() => setConfirmDestructive(false)}>
          <div className={s.modal} onClick={(e) => e.stopPropagation()}>
            <div className={s.modalHead}>
              <AlertTriangle size={18} /> <b>삭제를 포함한 적용(replace_all)</b>
              <button className={s.iconBtn} onClick={() => setConfirmDestructive(false)}><X size={16} /></button>
            </div>
            <p>이 작업은 파일에 없는 행 <b className={s.danger}>{totalDeletes.toLocaleString()}건</b>을 삭제합니다. 적용 직전 자동 스냅샷이 생성되며, 롤백 탭에서 복원할 수 있습니다.</p>
            <div className={s.row} style={{ justifyContent: 'flex-end' }}>
              <button className={s.btnGhost} onClick={() => setConfirmDestructive(false)}>취소</button>
              <button className={s.btnDanger} onClick={doApply} disabled={busy}>
                {busy ? '적용 중…' : `삭제 포함 적용`}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ───────────────────── Recategorize (영향 미리보기 모달) ───────────────────── */
function RecategorizeTab() {
  const [mode, setMode] = useState('all');
  const [arg, setArg] = useState('');
  const [force, setForce] = useState(false);
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState(null);
  const [applyResult, setApplyResult] = useState(null);
  const [error, setError] = useState(null);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const buildScope = () => {
    const scope = { mode };
    const argKey = SCOPE_ARG[mode];
    if (argKey) scope[argKey] = arg.trim();
    return scope;
  };

  const argKey = SCOPE_ARG[mode];

  const runPreview = async () => {
    if (argKey && !arg.trim()) { setError(`${argKey} 값을 입력하세요.`); return; }
    setBusy(true); setError(null); setPreview(null); setApplyResult(null);
    try {
      const res = await api.catalogSyncRecategorizePreview(buildScope(), force);
      setPreview(res);
    } catch (err) {
      setError(err.message || '미리보기 실패');
    } finally { setBusy(false); }
  };

  const runApply = async () => {
    setBusy(true); setError(null);
    try {
      const res = await api.catalogSyncRecategorizeApply(buildScope(), force);
      setApplyResult(res);
      setConfirmOpen(false);
      if (!res.ok) setError(res.error_message || '적용 실패');
      else setPreview(null);
    } catch (err) {
      setError(err.message || '적용 실패');
      setConfirmOpen(false);
    } finally { setBusy(false); }
  };

  return (
    <div className={s.card}>
      <h3 className={s.cardTitle}><RefreshCw size={16} /> 상품 일괄 재분류 (매칭 규칙 → 상품 카테고리)</h3>
      <p className={s.muted} style={{ marginTop: -4, marginBottom: 12 }}>
        매칭 규칙(정본)으로 상품 이름을 대조해 카테고리를 다시 매깁니다. 규칙이 없는 상품은 그대로 둡니다.
      </p>

      <div className={s.row}>
        <span className={s.label}>범위</span>
        <select className={s.select} value={mode} onChange={(e) => setMode(e.target.value)}>
          {RECAT_SCOPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        {argKey && (
          <input className={s.input} placeholder={argKey} value={arg} onChange={(e) => setArg(e.target.value)} />
        )}
        <label className={s.check}>
          <input type="checkbox" checked={force} onChange={() => setForce((v) => !v)} />
          사람이 지정한 분류도 덮어쓰기(force)
        </label>
        <button className={s.btn} onClick={runPreview} disabled={busy}>
          <Eye size={15} /> {busy ? '계산 중…' : '영향 미리보기'}
        </button>
      </div>

      {error && <Alert kind="err">{error}</Alert>}

      {preview && (
        <>
          <div className={s.cards}>
            <CountCard label="대상 상품" value={preview.total_considered} />
            <CountCard label="규칙 매칭" value={preview.matched_rule} />
            <CountCard label="변경 예정" value={preview.will_change} tone={s.toneChange} />
            <CountCard label="새로 분류" value={preview.newly_classified} tone={s.toneGood} />
            <CountCard label="재분류" value={preview.reclassified} tone={s.toneChange} />
            <CountCard label="변화 없음" value={preview.unchanged} />
            <CountCard label="규칙 없음(유지)" value={preview.no_rule_match} tone={s.toneWarn} />
            <CountCard label="보호 스킵" value={preview.protected_skipped} tone={s.toneDanger} />
          </div>

          <div className={s.row}>
            <button
              className={s.btn}
              onClick={() => setConfirmOpen(true)}
              disabled={busy || preview.will_change === 0}
            >
              <CheckCircle2 size={15} /> {preview.will_change}건 적용하기
            </button>
          </div>

          <h4 className={s.cardTitle} style={{ marginTop: 16 }}><Layers size={15} /> 카테고리 전이 (상위 {preview.transitions?.length || 0}그룹)</h4>
          <table className={s.table}>
            <thead><tr><th>변경 전</th><th></th><th>변경 후</th><th>건수</th><th>예시 상품</th></tr></thead>
            <tbody>
              {(preview.transitions || []).map((t, i) => (
                <tr key={i}>
                  <td className={s.mono}>{t.from || '(미분류)'}</td>
                  <td><ArrowRight size={13} className={s.arrow} /></td>
                  <td className={s.mono}>{t.to}</td>
                  <td><strong>{t.count}</strong></td>
                  <td>
                    {(t.samples || []).slice(0, 3).map((sp) => sp.name).join(', ')}
                    {t.count > 3 ? ' …' : ''}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {applyResult?.ok && (
        <>
          <Alert kind="ok">재분류 완료 — {applyResult.changed}건 변경. 스냅샷이 저장되었습니다.</Alert>
          <p className={s.muted}>스냅샷: <span className={s.snapPath}>{applyResult.snapshot_path}</span></p>
        </>
      )}

      {confirmOpen && preview && (
        <div className={s.overlay} onClick={() => !busy && setConfirmOpen(false)}>
          <div className={s.modal} onClick={(e) => e.stopPropagation()}>
            <div className={s.row} style={{ justifyContent: 'space-between' }}>
              <h3 className={s.modalTitle}>재분류 적용 확인</h3>
              <button className={`${s.btn} ${s.btnGhost}`} onClick={() => !busy && setConfirmOpen(false)} style={{ padding: 6 }}>
                <X size={16} />
              </button>
            </div>
            <p className={s.modalSub}>
              아래 변경이 즉시 DB에 반영됩니다. 적용 직전 자동 스냅샷이 저장되어 되돌릴 수 있습니다.
              {force && ' (force: 사람이 지정한 분류도 덮어씁니다)'}
            </p>
            <div className={s.cards}>
              <CountCard label="변경 예정" value={preview.will_change} tone={s.toneChange} />
              <CountCard label="새로 분류" value={preview.newly_classified} tone={s.toneGood} />
              <CountCard label="재분류" value={preview.reclassified} tone={s.toneChange} />
              <CountCard label="보호 스킵" value={preview.protected_skipped} tone={s.toneDanger} />
            </div>
            <div className={s.modalActions}>
              <button className={`${s.btn} ${s.btnGhost}`} onClick={() => setConfirmOpen(false)} disabled={busy}>취소</button>
              <button className={s.btn} onClick={runApply} disabled={busy}>
                {busy ? '적용 중…' : '확인하고 적용'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ───────────────────────── Rollback (스냅샷 복원) ───────────────────────── */
function fmtSize(b) {
  const n = Number(b || 0);
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function RollbackTab({ onChanged }) {
  const [snaps, setSnaps] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const [confirm, setConfirm] = useState(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const res = await api.catalogSyncSnapshots();
      setSnaps(res.snapshots || []);
    } catch (err) {
      setError(err.message || '스냅샷 조회 실패');
    }
  }, []);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await api.catalogSyncSnapshots();
        if (alive) setSnaps(res.snapshots || []);
      } catch (err) {
        if (alive) setError(err.message || '스냅샷 조회 실패');
      }
    })();
    return () => { alive = false; };
  }, []);

  const doRestore = async (filename) => {
    setBusy(true); setError(null); setResult(null); setConfirm(null);
    try {
      const res = await api.catalogSyncRestore(filename);
      setResult(res);
      onChanged?.();
      await load();
    } catch (err) {
      setError(err.message || '복원 실패');
    } finally { setBusy(false); }
  };

  return (
    <div className={s.card}>
      <h3 className={s.cardTitle}><RotateCcw size={16} /> 롤백 (스냅샷 복원)
        <button className={`${s.btn} ${s.btnGhost}`} onClick={load} style={{ marginLeft: 'auto', padding: '4px 10px' }}>
          <RefreshCw size={13} /> 새로고침
        </button>
      </h3>
      <Alert kind="warn">
        복원은 현재 DB 전체를 선택한 시점으로 되돌립니다. 복원 직전 현재 상태가 자동으로 새 스냅샷에 백업됩니다.
      </Alert>

      {error && <Alert kind="err">{error}</Alert>}
      {result?.ok && (
        <Alert kind="ok">
          복원 완료 — {result.restored_from} 로 되돌렸습니다. (직전 상태 백업: {result.pre_restore_backup})
        </Alert>
      )}

      <table className={s.table}>
        <thead><tr><th>스냅샷 파일</th><th>크기</th><th>생성 시각</th><th></th></tr></thead>
        <tbody>
          {snaps.map((sn) => (
            <tr key={sn.filename}>
              <td className={s.mono}>{sn.filename}</td>
              <td>{fmtSize(sn.size_bytes)}</td>
              <td className={s.mono}>{sn.created_at ? new Date(sn.created_at).toLocaleString() : '-'}</td>
              <td>
                <button className={s.btnDanger} disabled={busy} onClick={() => setConfirm(sn)}>
                  <RotateCcw size={13} /> 이 시점으로 복원
                </button>
              </td>
            </tr>
          ))}
          {snaps.length === 0 && <tr><td colSpan={4} className={s.muted}>스냅샷 없음</td></tr>}
        </tbody>
      </table>

      {confirm && (
        <div className={s.modalBackdrop} onClick={() => !busy && setConfirm(null)}>
          <div className={s.modal} onClick={(e) => e.stopPropagation()}>
            <div className={s.modalHead}>
              <AlertTriangle size={18} /> <b>DB 복원 확인</b>
              <button className={s.iconBtn} onClick={() => !busy && setConfirm(null)}><X size={16} /></button>
            </div>
            <p>
              현재 데이터베이스를 <b className={s.mono}>{confirm.filename}</b> 시점으로 되돌립니다.
              이후의 모든 변경이 사라집니다. (직전 상태는 자동 백업)
            </p>
            <div className={s.row} style={{ justifyContent: 'flex-end' }}>
              <button className={s.btnGhost} onClick={() => setConfirm(null)} disabled={busy}>취소</button>
              <button className={s.btnDanger} onClick={() => doRestore(confirm.filename)} disabled={busy}>
                {busy ? '복원 중…' : '복원 실행'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ───────────────────────── Logs ───────────────────────── */
function LogsPanel({ refreshKey }) {
  const [logs, setLogs] = useState([]);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    try {
      const res = await api.catalogSyncLogs(30);
      setLogs(res.logs || []);
    } catch (err) {
      setError(err.message || '로그 조회 실패');
    }
  }, []);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await api.catalogSyncLogs(30);
        if (alive) setLogs(res.logs || []);
      } catch (err) {
        if (alive) setError(err.message || '로그 조회 실패');
      }
    })();
    return () => { alive = false; };
  }, [refreshKey]);

  return (
    <div className={s.card}>
      <h3 className={s.cardTitle}><History size={16} /> 작업 로그
        <button className={`${s.btn} ${s.btnGhost}`} onClick={load} style={{ marginLeft: 'auto', padding: '4px 10px' }}>
          <RefreshCw size={13} /> 새로고침
        </button>
      </h3>
      {error && <Alert kind="err">{error}</Alert>}
      <table className={s.table}>
        <thead><tr><th>시각</th><th>작업</th><th>모드</th><th>건수</th><th>결과</th></tr></thead>
        <tbody>
          {logs.map((l) => (
            <tr key={l.id}>
              <td className={s.mono}>{l.timestamp ? new Date(l.timestamp).toLocaleString() : '-'}</td>
              <td>{l.operation}{l.dry_run ? ' (dry-run)' : ''}</td>
              <td>{l.mode || '-'}</td>
              <td className={s.mono}>{l.counts ? JSON.stringify(l.counts) : '-'}</td>
              <td>{l.ok ? '✅' : `❌ ${l.error_message || ''}`}</td>
            </tr>
          ))}
          {logs.length === 0 && <tr><td colSpan={5} className={s.muted}>로그 없음</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

/* ───────────────────────── Page ───────────────────────── */
const TABS = [
  ['export', '내보내기', Download],
  ['import', '가져오기', Upload],
  ['recategorize', '재분류', RefreshCw],
  ['rollback', '롤백', RotateCcw],
];

export default function CatalogSyncPage() {
  const [tab, setTab] = useState('export');
  const [logKey, setLogKey] = useState(0);

  return (
    <div className={s.page}>
      <h1 className={s.title}><ListChecks size={22} style={{ verticalAlign: '-4px', marginRight: 8 }} />카탈로그 동기화</h1>
      <p className={s.subtitle}>통합 카테고리 · 매칭 규칙 · 상품을 외부 AI와 주고받고(export/import), 매칭 규칙으로 상품을 일괄 재분류하고, 문제가 생기면 스냅샷으로 롤백합니다.</p>

      <div className={s.tabs}>
        {TABS.map(([id, label, Icon]) => (
          <button key={id} className={`${s.tab} ${tab === id ? s.tabActive : ''}`} onClick={() => setTab(id)}>
            <Icon size={15} /> {label}
          </button>
        ))}
      </div>

      {tab === 'export' && <ExportTab />}
      {tab === 'import' && <ImportTab />}
      {tab === 'recategorize' && <RecategorizeTab />}
      {tab === 'rollback' && <RollbackTab onChanged={() => setLogKey((k) => k + 1)} />}

      <LogsPanel refreshKey={`${tab}-${logKey}`} />
    </div>
  );
}
