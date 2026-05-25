import { useCallback, useEffect, useMemo, useState } from 'react';
import { serializeFilters, describeFilters, classifyImpact, confirmMessage, undoCountdown } from './bulkArchiveHelpers.js';

const STATUS_OPTIONS = [
  ['ai_proposed', '검수 대기'],
  ['human_reviewing', '사람 확인 중'],
  ['rejected', '반려'],
  ['held', '보류'],
  ['needs_rework', '재작업 필요'],
  ['superseded', '대체됨'],
  ['dead_letter', '실패 보관'],
];
const TYPE_OPTIONS = [
  ['normalized_field', '상품명/단위'],
  ['canonical_match', '기존 상품 연결'],
  ['category', '카테고리'],
  ['attribute_definition', '속성 정의'],
  ['attribute_value', '속성 값'],
  ['keyword', '검색 키워드'],
  ['alias', '별칭'],
];

function CheckGroup({ label, options, value, onChange }) {
  return (
    <div className="ba-group">
      <div className="ba-group-label">{label}</div>
      <div className="ba-chips">
        {options.map(([key, name]) => {
          const active = value.includes(key);
          return (
            <button
              key={key}
              type="button"
              className={`chip ${active ? 'chip-active' : ''}`}
              onClick={() => onChange(active ? value.filter((v) => v !== key) : [...value, key])}
            >
              {name}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export default function BulkArchiveDialog({ open, onClose, onArchived }) {
  const [statuses, setStatuses] = useState([]);
  const [proposalTypes, setProposalTypes] = useState([]);
  const [createdBefore, setCreatedBefore] = useState('');
  const [preview, setPreview] = useState(null);
  const [previewing, setPreviewing] = useState(false);
  const [archiving, setArchiving] = useState(false);
  const [error, setError] = useState(null);
  const [undoEntry, setUndoEntry] = useState(null);
  const [now, setNow] = useState(() => new Date());
  // rd4-bulk-archive-expand: 위험 상태(발행대기/승인/발행) 비우기 opt-in.
  const [includePublishing, setIncludePublishing] = useState(false);
  const [includeApproved, setIncludeApproved] = useState(false);
  const [includePublished, setIncludePublished] = useState(false);

  const filters = useMemo(
    () => ({ statuses, proposal_types: proposalTypes, created_before: createdBefore }),
    [statuses, proposalTypes, createdBefore],
  );

  const dangerFlags = useMemo(
    () => ({
      include_publishing: includePublishing,
      include_approved: includeApproved,
      include_published: includePublished,
    }),
    [includePublishing, includeApproved, includePublished],
  );

  const dangerOn = includePublishing || includeApproved || includePublished;

  useEffect(() => {
    if (!open) {
      setPreview(null);
      setUndoEntry(null);
      setError(null);
    }
  }, [open]);

  useEffect(() => {
    if (!undoEntry) return undefined;
    const id = setInterval(() => setNow(new Date()), 250);
    return () => clearInterval(id);
  }, [undoEntry]);

  const doPreview = useCallback(async () => {
    setPreviewing(true);
    setError(null);
    try {
      const res = await fetch('/api/review/proposals/bulk-archive/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reviewer_id: 'operator', filters: serializeFilters(filters), ...dangerFlags }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setPreview(await res.json());
    } catch (err) {
      setError(err.message || '미리보기 실패');
    } finally {
      setPreviewing(false);
    }
  }, [filters, dangerFlags]);

  const doArchive = useCallback(async () => {
    if (!preview || preview.matched === 0) return;
    if (!window.confirm(confirmMessage(preview.matched, filters))) return;
    if (dangerOn && !window.confirm('⚠️ 발행대기/승인/발행됨 상태도 함께 비웁니다. 정말 진행할까요?')) return;
    setArchiving(true);
    setError(null);
    try {
      const res = await fetch('/api/review/proposals/bulk-archive', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reviewer_id: 'operator', filters: serializeFilters(filters), ...dangerFlags }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const body = await res.json();
      setUndoEntry({ token: body.undo_token, expiresAt: body.expires_at, archived: body.archived });
      setPreview(null);
      onArchived?.(body.archived);
    } catch (err) {
      setError(err.message || '비우기 실패');
    } finally {
      setArchiving(false);
    }
  }, [preview, filters, onArchived, dangerFlags, dangerOn]);

  const doUndo = useCallback(async () => {
    if (!undoEntry?.token) return;
    try {
      const res = await fetch('/api/review/proposals/bulk-archive/undo', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ undo_token: undoEntry.token }),
      });
      if (!res.ok) throw new Error(res.status === 410 ? 'undo 30초 만료' : `HTTP ${res.status}`);
      setUndoEntry(null);
      onArchived?.(0);
    } catch (err) {
      setError(err.message || 'undo 실패');
    }
  }, [undoEntry, onArchived]);

  if (!open) return null;
  const impact = preview ? classifyImpact(preview.matched) : null;
  const countdown = undoEntry ? undoCountdown({ expiresAt: undoEntry.expiresAt, now }) : null;

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="AI 제안 비우기">
      <div className="modal">
        <div className="modal-head">
          <h2>AI 제안 비우기</h2>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="닫기">✕</button>
        </div>

        <p className="muted">
          누적 제안을 필터로 좁힌 뒤, 미리보기 → 확인 → 일괄 archive 합니다. 30초 안에 되돌릴 수 있습니다.
          <strong> 기본은 검수/반려/보류만 비웁니다.</strong>
        </p>

        <CheckGroup label="상태" options={STATUS_OPTIONS} value={statuses} onChange={setStatuses} />
        <CheckGroup label="제안 타입" options={TYPE_OPTIONS} value={proposalTypes} onChange={setProposalTypes} />
        <div className="ba-group">
          <label className="ba-group-label" htmlFor="ba-before">생성일 이전</label>
          <input
            id="ba-before"
            type="date"
            value={createdBefore}
            onChange={(e) => setCreatedBefore(e.target.value)}
            className="ba-date"
          />
        </div>

        <details className="ba-group" style={{ borderTop: '1px dashed #ccc', paddingTop: 8 }}>
          <summary style={{ cursor: 'pointer', fontWeight: 600, color: dangerOn ? '#b00' : 'inherit' }}>
            ⚠️ 위험 옵션: 발행 흐름 상태도 비우기 {dangerOn ? '(켜짐)' : ''}
          </summary>
          <div className="muted small" style={{ marginTop: 6 }}>
            DB 초기화 등 처음부터 다시 시작할 때만 사용하세요. catalog 행은 삭제되지 않고, 제안 audit 만 사라집니다.
          </div>
          <label style={{ display: 'block', marginTop: 6 }}>
            <input type="checkbox" checked={includePublishing} onChange={(e) => setIncludePublishing(e.target.checked)} />
            {' '}발행 대기(publishing) 포함
          </label>
          <label style={{ display: 'block' }}>
            <input type="checkbox" checked={includeApproved} onChange={(e) => setIncludeApproved(e.target.checked)} />
            {' '}승인됨(approved) 포함
          </label>
          <label style={{ display: 'block' }}>
            <input type="checkbox" checked={includePublished} onChange={(e) => setIncludePublished(e.target.checked)} />
            {' '}발행됨(published) 포함 — audit 만 삭제, catalog 유지
          </label>
        </details>

        <div className="ba-summary">조건: {describeFilters(filters)}</div>

        {error && <div className="alert alert-err">{error}</div>}

        {preview && (
          <div className={`ba-preview ba-impact-${impact.tone}`}>
            <div className="ba-preview-count">{preview.matched.toLocaleString()}건 영향</div>
            <div className="muted small">{impact.label}</div>
            {preview.sample?.length > 0 && (
              <details>
                <summary>샘플 {preview.sample.length}건 보기</summary>
                <ul className="ba-sample">
                  {preview.sample.map((s) => (
                    <li key={s.proposal_id}>
                      <code>{s.proposal_id}</code> · {s.proposal_type} · {s.target_field}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        )}

        {undoEntry && (
          <div className="ba-undo" role="status">
            <div>
              <strong>{undoEntry.archived.toLocaleString()}건 비움.</strong> {countdown.secondsLeft}초 안에 되돌릴 수 있습니다.
            </div>
            <button type="button" className="btn btn-warn" onClick={doUndo} disabled={countdown.expired}>
              되돌리기
            </button>
          </div>
        )}

        <div className="modal-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose}>닫기</button>
          <button type="button" className="btn" onClick={doPreview} disabled={previewing}>
            {previewing ? '계산 중…' : '미리보기'}
          </button>
          <button
            type="button"
            className="btn btn-danger"
            onClick={doArchive}
            disabled={!preview || preview.matched === 0 || archiving}
          >
            {archiving ? '비우는 중…' : `${preview ? preview.matched.toLocaleString() + '건 ' : ''}비우기`}
          </button>
        </div>
      </div>
    </div>
  );
}
