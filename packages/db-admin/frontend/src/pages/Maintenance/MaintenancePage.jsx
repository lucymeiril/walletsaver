import { useEffect, useState, useCallback } from 'react';
import { Wrench, Trash2, Play, AlertTriangle, RefreshCw, CheckCircle2 } from 'lucide-react';
import { api } from '../../api/client';

const SCOPE_OPTIONS = [
  { value: 'raw',      label: 'raw (수집 원본 · PendingIngestion / CrawlLog)' },
  { value: 'mappings', label: 'mappings (카테고리/키워드 매핑 · Keyword / ProductKeyword 등)' },
  { value: 'all',      label: 'all (현재 working DB 도메인 · 카테고리 마스터는 보존)' },
];

const SCOPE_CONFIRM = {
  raw: 'PURGE RAW',
  mappings: 'PURGE MAPPINGS',
  all: 'PURGE ALL',
};

function Badge({ tone = 'neutral', children }) {
  const color = { ok: '#16a34a', warn: '#f59e0b', danger: '#dc2626', neutral: '#64748b' }[tone] || '#64748b';
  return (
    <span style={{
      background: color, color: '#fff', borderRadius: 6, padding: '2px 8px',
      fontSize: 12, fontWeight: 600,
    }}>{children}</span>
  );
}

function PurgeCard() {
  const [scope, setScope] = useState('raw');
  const [confirming, setConfirming] = useState(false);
  const [confirmText, setConfirmText] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const expected = SCOPE_CONFIRM[scope];
  const canRun = confirming && confirmText === expected;

  const onPurge = async () => {
    setBusy(true); setError(null); setResult(null);
    try {
      const data = await api.maintenancePurge(scope, note);
      setResult(data);
      setConfirming(false); setConfirmText('');
    } catch (e) {
      setError(e?.message || '비우기 실패');
    } finally {
      setBusy(false);
    }
  };

  return (
    <section style={{ border: '1px solid #e2e8f0', borderRadius: 8, padding: 16, marginBottom: 16 }}>
      <h3 style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '0 0 12px' }}>
        <Trash2 size={18} /> DB 비우기
      </h3>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <label>
          삭제 범위
          <select
            aria-label="삭제 범위"
            value={scope}
            onChange={(e) => { setScope(e.target.value); setConfirming(false); setConfirmText(''); setResult(null); }}
            style={{ width: '100%', padding: 8, marginTop: 4 }}
            disabled={busy}
          >
            {SCOPE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </label>
        <label>
          메모 (감사 로그에 기록됨)
          <input
            aria-label="메모"
            type="text"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="예: 테스트 데이터 정리"
            maxLength={500}
            style={{ width: '100%', padding: 8, marginTop: 4 }}
            disabled={busy}
          />
        </label>

        {!confirming ? (
          <button
            type="button"
            onClick={() => setConfirming(true)}
            disabled={busy}
            style={{
              background: '#dc2626', color: '#fff', border: 'none', borderRadius: 6,
              padding: '10px 16px', cursor: 'pointer', fontWeight: 600,
            }}
          >
            <AlertTriangle size={14} style={{ verticalAlign: 'middle' }} /> 비우기 시작…
          </button>
        ) : (
          <div role="dialog" aria-label="DB 비우기 확인" style={{
            background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 6, padding: 12,
          }}>
            <p style={{ margin: '0 0 8px' }}>
              이 작업은 즉시 실행되며 되돌릴 수 없습니다.
              계속하려면 <code>{expected}</code> 를 그대로 입력하세요.
            </p>
            <input
              type="text"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              placeholder={expected}
              aria-label="확인 문자열"
              style={{ width: '100%', padding: 8, marginBottom: 8 }}
              disabled={busy}
            />
            <div style={{ display: 'flex', gap: 8 }}>
              <button
                type="button"
                onClick={onPurge}
                disabled={!canRun || busy}
                style={{
                  background: canRun ? '#dc2626' : '#cbd5e1', color: '#fff',
                  border: 'none', borderRadius: 6, padding: '8px 14px',
                  cursor: canRun ? 'pointer' : 'not-allowed', fontWeight: 600,
                }}
              >
                {busy ? '실행 중…' : `즉시 비우기 (${scope})`}
              </button>
              <button
                type="button"
                onClick={() => { setConfirming(false); setConfirmText(''); }}
                disabled={busy}
                style={{ padding: '8px 14px' }}
              >
                취소
              </button>
            </div>
          </div>
        )}

        {error && (
          <div role="alert" style={{ color: '#dc2626' }}>오류: {error}</div>
        )}
        {result && (
          <div role="status" style={{ background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 6, padding: 10 }}>
            <CheckCircle2 size={14} style={{ verticalAlign: 'middle', color: '#16a34a' }} />{' '}
            <strong>{result.scope}</strong> 비우기 완료 — 총 <strong>{result.total}</strong> 행 삭제
            <pre style={{ marginTop: 8, whiteSpace: 'pre-wrap', fontSize: 12 }}>
              {JSON.stringify(result.deleted, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </section>
  );
}

function MigrateCard() {
  const [revision, setRevision] = useState('head');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const onMigrate = async () => {
    setBusy(true); setError(null); setResult(null);
    try {
      const data = await api.maintenanceMigrate(revision);
      setResult(data);
    } catch (e) {
      setError(e?.message || '마이그레이션 실패');
    } finally {
      setBusy(false);
    }
  };

  return (
    <section style={{ border: '1px solid #e2e8f0', borderRadius: 8, padding: 16, marginBottom: 16 }}>
      <h3 style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '0 0 12px' }}>
        <Play size={18} /> 스키마 마이그레이션 (Alembic)
      </h3>
      <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
        <label style={{ flex: 1 }}>
          revision
          <input
            aria-label="revision"
            type="text"
            value={revision}
            onChange={(e) => setRevision(e.target.value)}
            style={{ width: '100%', padding: 8, marginTop: 4 }}
            disabled={busy}
          />
        </label>
        <button
          type="button"
          onClick={onMigrate}
          disabled={busy || !revision}
          style={{
            background: '#2563eb', color: '#fff', border: 'none', borderRadius: 6,
            padding: '10px 16px', cursor: 'pointer', fontWeight: 600,
          }}
        >
          {busy ? '실행 중…' : 'alembic upgrade'}
        </button>
      </div>
      {error && <div role="alert" style={{ color: '#dc2626', marginTop: 10 }}>오류: {error}</div>}
      {result && (
        <pre style={{ background: '#f8fafc', padding: 10, marginTop: 10, fontSize: 12, whiteSpace: 'pre-wrap' }}>
          {result.stdout || '(no stdout)'}
        </pre>
      )}
    </section>
  );
}

function IntegrityCard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const d = await api.maintenanceIntegrity();
      setData(d);
    } catch (e) {
      setError(e?.message || '검토 실패');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <section style={{ border: '1px solid #e2e8f0', borderRadius: 8, padding: 16 }}>
      <h3 style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '0 0 12px', justifyContent: 'space-between' }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <AlertTriangle size={18} /> 이상 데이터 검토 (null · duplicate · orphan)
        </span>
        <button type="button" onClick={load} disabled={loading} title="재검사" style={{ padding: '6px 10px' }}>
          <RefreshCw size={14} /> {loading ? '검사 중…' : '재검사'}
        </button>
      </h3>
      {error && <div role="alert" style={{ color: '#dc2626' }}>{error}</div>}
      {data && (
        <div>
          <div style={{ marginBottom: 8 }}>
            총 이슈:{' '}
            <Badge tone={data.issue_total > 0 ? 'warn' : 'ok'}>{data.issue_total}</Badge>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}>
            <div>
              <strong>NULL</strong>
              <ul style={{ paddingLeft: 18, margin: '4px 0' }}>
                <li>카테고리 없음: {data.null.products_without_category}</li>
                <li>이름 없음: {data.null.products_without_name}</li>
              </ul>
            </div>
            <div>
              <strong>중복 상품</strong>
              <div>총 {data.duplicates.products} 건</div>
              <ul style={{ paddingLeft: 18, margin: '4px 0', fontSize: 12 }}>
                {(data.duplicates.samples || []).slice(0, 5).map((s, i) => (
                  <li key={i}>{s.name} ({s.source_type}) × {s.count}</li>
                ))}
              </ul>
            </div>
            <div>
              <strong>고아 FK</strong>
              <ul style={{ paddingLeft: 18, margin: '4px 0' }}>
                {Object.entries(data.orphan_fk).map(([k, v]) => (
                  <li key={k}>{k}: {v}</li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

export default function MaintenancePage() {
  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: 16 }}>
      <h2 style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <Wrench size={22} /> DB 유지보수
      </h2>
      <p style={{ color: '#64748b' }}>
        현재 working DB를 관리합니다. 모든 변경은 AuditLog 에 자동 기록됩니다.
      </p>
      <PurgeCard />
      <MigrateCard />
      <IntegrityCard />
    </div>
  );
}
