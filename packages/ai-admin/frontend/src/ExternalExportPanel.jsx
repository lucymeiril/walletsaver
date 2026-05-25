/**
 * ExternalExportPanel.jsx
 *
 * 외부 분류 워크플로우 — export 패널.
 *
 * 역할:
 *   - 매칭 미히트 raw 데이터를 JSONL/CSV로 내보내 외부에서 분류.
 *   - 분류 후 db-admin '분류 Import'로 업로드.
 *
 * ⚠️ 이 패널은 "정상 운영" 경로임 (보류 없음).
 *     LivePipelinePanel(라이브 AI 처리)은 현재 🚧 보류 상태이며 별도 카드로 관리.
 *     이 파일은 LivePipelinePanel을 대체하거나 복구하는 것이 아님.
 *
 * 라우팅 위치:
 *   App.jsx 탭 "외부 분류" → 이 패널 단독 표시.
 *   ExternalExportPanel (정상, 권장)이 LivePipelinePanel (보류) 위에 위치.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import ExportHistoryTable from './components/ExportHistoryTable.jsx';
import {
  MART_OPTIONS,
  FORMAT_OPTIONS,
  buildExportPayload,
  buildDownloadButtons,
  validateExportForm,
} from './externalExportHelpers.js';

/** 폼 초기값: 전체 마트, 전 기간, 양식 둘 다 */
const INITIAL_FORM = {
  marts: MART_OPTIONS.map((m) => m.id), // 전체 마트 기본 선택
  capturedSince: '',
  limit: '',
  formats: FORMAT_OPTIONS.map((f) => f.id), // JSONL + CSV 기본 선택
};

export default function ExternalExportPanel() {
  // 필터 폼 상태
  const [form, setForm] = useState(INITIAL_FORM);
  // 필터 패널 펼침/접힘 (기본: 펼침)
  const [filterOpen, setFilterOpen] = useState(true);

  // export 실행 상태
  const [exportState, setExportState] = useState({
    loading: false,
    result: null, // { batch_id, hit_count, miss_count, files, generated_at }
    error: null,
  });

  // 최근 이력 상태
  const [historyState, setHistoryState] = useState({
    loading: true,
    items: [],
    error: null,
  });

  // toast 상태 (에러/성공 메시지)
  const [toast, setToast] = useState(null);
  const toastTimer = useRef(null);

  /** toast 표시 헬퍼 */
  const showToast = useCallback((msg, isError = false) => {
    setToast({ msg, isError });
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 4000);
  }, []);

  /** 최근 export 이력 조회 */
  const fetchHistory = useCallback(async () => {
    setHistoryState((p) => ({ ...p, loading: true, error: null }));
    try {
      const res = await fetch('/api/export/unmatched/recent?limit=20', {
        cache: 'no-store',
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        const detail = body?.detail;
        throw new Error(
          typeof detail === 'string'
            ? detail
            : detail?.message || `HTTP ${res.status}`,
        );
      }
      const body = await res.json();
      setHistoryState({ loading: false, items: body.exports || body.items || (Array.isArray(body) ? body : []), error: null });
    } catch (err) {
      setHistoryState({ loading: false, items: [], error: err.message || String(err) });
    }
  }, []);

  // 마운트 시 이력 로드
  useEffect(() => {
    fetchHistory();
    return () => clearTimeout(toastTimer.current);
  }, [fetchHistory]);

  /** 마트 체크박스 토글 */
  const toggleMart = useCallback((martId) => {
    setForm((prev) => {
      const has = prev.marts.includes(martId);
      return {
        ...prev,
        marts: has
          ? prev.marts.filter((m) => m !== martId)
          : [...prev.marts, martId],
      };
    });
  }, []);

  /** 전체 마트 선택/해제 토글 */
  const toggleAllMarts = useCallback(() => {
    setForm((prev) => ({
      ...prev,
      marts:
        prev.marts.length === MART_OPTIONS.length
          ? []
          : MART_OPTIONS.map((m) => m.id),
    }));
  }, []);

  /** 출력 형식 체크박스 토글 */
  const toggleFormat = useCallback((fmtId) => {
    setForm((prev) => {
      const has = prev.formats.includes(fmtId);
      return {
        ...prev,
        formats: has
          ? prev.formats.filter((f) => f !== fmtId)
          : [...prev.formats, fmtId],
      };
    });
  }, []);

  /** Export 실행 */
  const handleExport = useCallback(async () => {
    if (exportState.loading) return; // 더블 클릭 방지

    const validationError = validateExportForm(form);
    if (validationError) {
      showToast(validationError, true);
      return;
    }

    setExportState({ loading: true, result: null, error: null });

    try {
      const payload = buildExportPayload(form);
      const res = await fetch('/api/export/unmatched', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        cache: 'no-store',
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        const detail = body?.detail;
        throw new Error(
          typeof detail === 'string'
            ? detail
            : detail?.message || `HTTP ${res.status}`,
        );
      }
      const result = await res.json();
      setExportState({ loading: false, result, error: null });
      showToast(`Export 완료: ${result.miss_count ?? 0}행 생성됨`);
      // 이력 목록 갱신
      fetchHistory();
    } catch (err) {
      const msg = err.message || String(err);
      setExportState({ loading: false, result: null, error: msg });
      showToast(`Export 실패: ${msg}`, true);
    }
  }, [exportState.loading, form, showToast, fetchHistory]);

  // export 결과에서 다운로드 버튼 목록 계산
  const downloadButtons =
    exportState.result
      ? buildDownloadButtons(exportState.result.batch_id, exportState.result.files)
      : [];

  return (
    <section
      className="panel export-panel"
      data-testid="external-export-panel"
    >
      {/* ── 페이지 설명 ── */}
      <p className="page-desc muted small" style={{ marginBottom: 14 }}>
        매칭 미히트(캡처됐으나 상품 DB에 연결 안 된) 데이터를 JSONL/CSV로 추출합니다.
        추출 후 외부에서 분류하고 db-admin 「분류 Import」로 업로드하면 DB에 반영됩니다.
      </p>
      {/* ── 헤더 ── */}
      <div className="row export-panel-header">
        <div>
          <h2>외부 분류 워크플로우</h2>
          {/* 2026-05-25: 라이브 AI 처리(LivePipelinePanel)는 보류 중.
              이 패널이 현재 권장 경로임. */}
          <div className="muted export-panel-desc">
            라이브 AI 처리는 보류 중입니다. 매칭 미히트 raw 데이터를 JSONL/CSV로 내보내
            외부에서 분류 후 db-admin &apos;분류 Import&apos;로 업로드하세요.
          </div>
        </div>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={fetchHistory}
          disabled={historyState.loading}
          data-testid="export-refresh-history"
        >
          이력 새로고침
        </button>
      </div>

      {/* ── 필터 폼 (펼침/접힘) ── */}
      <details
        className="inline-details export-filter-details"
        open={filterOpen}
        onToggle={(e) => setFilterOpen(e.currentTarget.open)}
        data-testid="export-filter-details"
      >
        <summary>필터 설정</summary>

        <div className="export-filter-body">
          {/* 마트 다중선택 */}
          <fieldset className="export-fieldset">
            <legend className="muted small">마트</legend>
            <div className="export-checkbox-row">
              <label className="export-checkbox-label">
                <input
                  type="checkbox"
                  checked={form.marts.length === MART_OPTIONS.length}
                  onChange={toggleAllMarts}
                  data-testid="mart-all"
                />
                전체
              </label>
              {MART_OPTIONS.map((m) => (
                <label key={m.id} className="export-checkbox-label">
                  <input
                    type="checkbox"
                    checked={form.marts.includes(m.id)}
                    onChange={() => toggleMart(m.id)}
                    data-testid={`mart-${m.id}`}
                  />
                  {m.label}
                </label>
              ))}
            </div>
          </fieldset>

          <div className="export-filter-grid">
            {/* 캡처 일자 이후 */}
            <label className="export-field-label">
              <span className="muted small">캡처 일자 이후</span>
              <input
                type="datetime-local"
                className="export-input"
                value={form.capturedSince}
                onChange={(e) =>
                  setForm((p) => ({ ...p, capturedSince: e.target.value }))
                }
                data-testid="captured-since"
              />
            </label>

            {/* 최대 행수 */}
            <label className="export-field-label">
              <span className="muted small">최대 행수 (빈 값 = 무제한)</span>
              <input
                type="number"
                className="export-input"
                value={form.limit}
                min="1"
                placeholder="무제한"
                onChange={(e) =>
                  setForm((p) => ({ ...p, limit: e.target.value }))
                }
                data-testid="limit-input"
              />
            </label>

            {/* 출력 형식 */}
            <fieldset className="export-fieldset">
              <legend className="muted small">출력 형식</legend>
              <div className="export-checkbox-row">
                {FORMAT_OPTIONS.map((f) => (
                  <label key={f.id} className="export-checkbox-label">
                    <input
                      type="checkbox"
                      checked={form.formats.includes(f.id)}
                      onChange={() => toggleFormat(f.id)}
                      data-testid={`format-${f.id}`}
                    />
                    {f.label}
                  </label>
                ))}
              </div>
            </fieldset>
          </div>
        </div>
      </details>

      {/* ── Export 실행 버튼 ── */}
      <div className="export-run-row">
        <button
          type="button"
          className="btn btn-primary export-run-btn"
          onClick={handleExport}
          disabled={exportState.loading}
          data-testid="export-run-btn"
        >
          {exportState.loading ? (
            <>
              <span className="export-spinner" aria-hidden="true" /> Export 실행 중…
            </>
          ) : (
            'Export 실행'
          )}
        </button>
        <span className="muted small">
          {form.marts.length < MART_OPTIONS.length
            ? `마트: ${form.marts.join(', ')}`
            : '마트: 전체'}{' '}
          · 형식: {form.formats.join('+') || '—'}
        </span>
      </div>

      {/* ── Export 결과 카드 ── */}
      {exportState.result && (
        <div
          className="panel export-result-card"
          data-testid="export-result-card"
        >
          <div className="row export-result-header">
            <h3>Export 결과</h3>
            <span className="badge badge-safe">완료</span>
          </div>

          <ul className="items export-result-meta">
            <li>
              <span className="muted small">Batch ID</span>
              <code data-testid="result-batch-id">{exportState.result.batch_id}</code>
            </li>
            <li>
              <span className="muted small">생성 시각</span>
              <span className="muted small">
                {exportState.result.generated_at
                  ? new Date(exportState.result.generated_at).toLocaleString('ko-KR')
                  : '—'}
              </span>
            </li>
            <li>
              <span className="muted small">히트 수 (이미 매칭됨)</span>
              <span
                className="badge badge-safe"
                data-testid="result-hit-count"
              >
                {exportState.result.hit_count ?? '—'}
              </span>
            </li>
            <li>
              <span className="muted small">미스 수 (외부 분류 대상)</span>
              <span
                className="badge badge-warn"
                data-testid="result-miss-count"
              >
                {exportState.result.miss_count ?? '—'}
              </span>
            </li>
          </ul>

          {/* 다운로드 버튼 */}
          <div className="export-dl-row" data-testid="export-dl-row">
            {downloadButtons.map((btn) => (
              <a
                key={btn.format}
                href={btn.url}
                className="btn btn-secondary export-dl-btn"
                download
                data-testid={`dl-${btn.format}`}
              >
                {btn.label}
              </a>
            ))}
          </div>
        </div>
      )}

      {/* export 진행 중 로딩 인디케이터 */}
      {exportState.loading && (
        <div className="export-loading-bar muted small" data-testid="export-loading">
          <span className="export-spinner" aria-hidden="true" />
          백엔드 처리 중입니다. 잠시 기다려 주세요…
        </div>
      )}

      {/* ── 최근 export 이력 ── */}
      <div className="export-history-section" data-testid="export-history-section">
        <h3 className="export-history-title">최근 export 이력</h3>
        <ExportHistoryTable
          items={historyState.items}
          loading={historyState.loading}
          error={historyState.error}
        />
      </div>

      {/* ── Toast 알림 ── */}
      {toast && (
        <div
          className={`toast${toast.isError ? ' toast-err' : ''}`}
          role="alert"
          data-testid="export-toast"
        >
          {toast.msg}
        </div>
      )}
    </section>
  );
}
