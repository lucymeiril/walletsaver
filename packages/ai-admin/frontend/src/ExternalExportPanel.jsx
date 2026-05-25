/**
 * ExternalExportPanel.jsx
 *
 * ⚠️ 이 기능은 crawler-admin으로 이전되었습니다.
 *
 * 기존 구현은 ExternalExportPanel.legacy.jsx 에 보존되어 있습니다.
 * 이 파일은 안내 페이지만 표시합니다.
 */

export default function ExternalExportPanel() {
  return (
    <section
      className="panel"
      data-testid="external-export-panel"
      style={{ maxWidth: 600 }}
    >
      {/* 이전 안내 배너 */}
      <div
        style={{
          padding: '16px 20px',
          background: 'rgba(248, 113, 113, 0.08)',
          border: '1px solid rgba(248, 113, 113, 0.3)',
          borderRadius: 8,
          marginBottom: 20,
          display: 'flex',
          alignItems: 'flex-start',
          gap: 12,
        }}
        data-testid="moved-notice"
      >
        <span style={{ fontSize: 20, lineHeight: 1 }}>🚨</span>
        <div>
          <p style={{ margin: '0 0 4px', fontWeight: 600, color: '#f87171' }}>
            외부 분류 export는 crawler-admin으로 이전되었습니다
          </p>
          <p style={{ margin: 0, fontSize: '0.85rem', color: 'var(--text3, #64748b)' }}>
            이 페이지에서는 더 이상 export를 실행할 수 없습니다.
          </p>
        </div>
      </div>

      {/* 이동 링크 */}
      <p style={{ margin: '0 0 12px', fontSize: '0.9rem' }}>
        👉{' '}
        <a
          href="http://localhost:5174/external-export"
          target="_blank"
          rel="noopener noreferrer"
          className="btn btn-primary"
          style={{ display: 'inline-flex', alignItems: 'center', gap: 6, textDecoration: 'none' }}
          data-testid="crawler-admin-link"
        >
          crawler-admin /external-export 열기
        </a>
      </p>

      {/* 이전 이유 */}
      <details style={{ marginTop: 16 }}>
        <summary
          style={{ cursor: 'pointer', fontSize: '0.85rem', color: 'var(--text3, #64748b)' }}
          data-testid="why-moved-summary"
        >
          왜 옮겼나요?
        </summary>
        <p
          style={{
            marginTop: 10,
            fontSize: '0.85rem',
            color: 'var(--text3, #64748b)',
            lineHeight: 1.6,
          }}
          data-testid="why-moved-body"
        >
          Export는 크롤링 직후 raw_batch 데이터를 다루는 작업입니다.
          크롤러 운영자가 크롤링 완료 후 즉시 export → 외부 LLM 분류 → db-admin import 흐름을
          한 곳(crawler-admin)에서 처리할 수 있도록 이전되었습니다.
          ai-admin은 분류 결과를 검수하고 AI 파이프라인을 관리하는 용도로 분리됩니다.
        </p>
      </details>
    </section>
  );
}
