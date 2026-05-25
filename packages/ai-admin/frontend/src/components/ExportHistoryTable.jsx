/**
 * ExportHistoryTable.jsx
 *
 * 최근 export 이력 테이블 컴포넌트.
 * GET /api/export/unmatched/recent 응답을 받아 표 형식으로 표시.
 *
 * ⚠️ 이 컴포넌트는 "외부 분류 워크플로우" export 이력 전용.
 *     LivePipelinePanel(라이브 AI 처리, 보류 중)과는 무관.
 */

import { buildDownloadUrl, formatMartFilter } from '../externalExportHelpers.js';

/**
 * @param {{
 *   items: Array<{batch_id, generated_at, mart, row_count, files}>,
 *   loading: boolean,
 *   error: string|null,
 * }} props
 */
export default function ExportHistoryTable({ items, loading, error }) {
  if (loading) {
    return (
      <div className="export-history-loading muted small" data-testid="history-loading">
        이력 불러오는 중…
      </div>
    );
  }

  if (error) {
    return (
      <div className="alert alert-err" data-testid="history-error">
        이력 조회 실패: {error}
      </div>
    );
  }

  if (!items || items.length === 0) {
    return (
      // empty 상태: "아직 export 기록이 없습니다" 플레이스홀더
      <div className="empty export-history-empty" data-testid="history-empty">
        아직 export 기록이 없습니다. 위에서 Export를 실행하면 여기에 표시됩니다.
      </div>
    );
  }

  return (
    <div className="export-history-table-wrap" data-testid="history-table">
      <table className="export-history-table">
        <thead>
          <tr>
            <th>Batch ID</th>
            <th>생성 시각</th>
            <th>마트 필터</th>
            <th>행 수</th>
            <th>다운로드</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const jsonlUrl = buildDownloadUrl(item.batch_id, 'jsonl');
            const csvUrl = buildDownloadUrl(item.batch_id, 'csv');
            const zipUrl = buildDownloadUrl(item.batch_id, 'zip');
            const hasJsonl = item.files && 'jsonl' in item.files;
            const hasCsv = item.files && 'csv' in item.files;

            return (
              <tr key={item.batch_id} data-testid={`history-row-${item.batch_id}`}>
                {/* batch_id 앞 8자리만 표시, 전체는 title로 */}
                <td
                  className="export-batch-id muted small"
                  title={item.batch_id}
                >
                  {String(item.batch_id).slice(0, 8)}…
                </td>
                <td className="muted small">
                  {item.generated_at
                    ? new Date(item.generated_at).toLocaleString('ko-KR')
                    : '—'}
                </td>
                <td className="muted small">{formatMartFilter(item.mart)}</td>
                <td className="muted small">
                  {item.row_count != null
                    ? item.row_count.toLocaleString()
                    : '—'}
                </td>
                <td className="export-dl-buttons">
                  {hasJsonl && (
                    <a
                      href={jsonlUrl}
                      className="btn btn-secondary export-dl-btn"
                      download
                      data-testid={`dl-jsonl-${item.batch_id}`}
                    >
                      JSONL
                    </a>
                  )}
                  {hasCsv && (
                    <a
                      href={csvUrl}
                      className="btn btn-secondary export-dl-btn"
                      download
                      data-testid={`dl-csv-${item.batch_id}`}
                    >
                      CSV
                    </a>
                  )}
                  {hasJsonl && hasCsv && (
                    <a
                      href={zipUrl}
                      className="btn btn-secondary export-dl-btn"
                      download
                      data-testid={`dl-zip-${item.batch_id}`}
                    >
                      ZIP
                    </a>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
