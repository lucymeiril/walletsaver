import { useCallback, useEffect, useState } from 'react';

const ROLES = [
  'normalizer',
  'unit_converter',
  'classifier',
  'canonical_matcher',
  'keyword_generator',
  'prompt_curator',
  'data_auditor',
];

const STATUSES = [
  'queued',
  'running',
  'paused',
  'completed',
  'partial',
  'failed',
  'dead_letter',
  'cancelled',
];

function statusBadgeClass(status) {
  if (status === 'completed' || status === 'partial') return 'ok';
  if (status === 'queued' || status === 'running') return 'warn';
  if (status === 'failed' || status === 'dead_letter' || status === 'cancelled') return 'err';
  return '';
}

function EnqueueForm({ onEnqueued }) {
  const [jobId, setJobId] = useState('');
  const [batchId, setBatchId] = useState('');
  const [role, setRole] = useState(ROLES[0]);
  const [priority, setPriority] = useState(100);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await fetch('/api/jobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          job_id: jobId,
          batch_id: batchId,
          role,
          priority: Number(priority),
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      setJobId('');
      setBatchId('');
      onEnqueued?.();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="provider-form" onSubmit={submit}>
      <div className="form-grid">
        <label>
          job_id
          <input value={jobId} onChange={(e) => setJobId(e.target.value)} required />
        </label>
        <label>
          batch_id
          <input value={batchId} onChange={(e) => setBatchId(e.target.value)} required />
        </label>
        <label>
          role
          <select value={role} onChange={(e) => setRole(e.target.value)}>
            {ROLES.map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
        </label>
        <label>
          priority
          <input
            type="number"
            min={0}
            max={1000}
            value={priority}
            onChange={(e) => setPriority(e.target.value)}
          />
        </label>
      </div>
      <div className="row" style={{ marginTop: 10 }}>
        <button type="submit" disabled={busy || !jobId || !batchId}>
          {busy ? '등록 중...' : '큐에 등록'}
        </button>
        {error && <span className="badge err">{error}</span>}
      </div>
    </form>
  );
}

export default function JobsPanel() {
  const [jobs, setJobs] = useState([]);
  const [filter, setFilter] = useState('');
  const [roleFilter, setRoleFilter] = useState('');
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filter) params.set('status', filter);
      if (roleFilter) params.set('role', roleFilter);
      const url = params.toString() ? `/api/jobs?${params.toString()}` : '/api/jobs';
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const body = await res.json();
      setJobs(body.jobs ?? []);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [filter, roleFilter]);

  useEffect(() => { refresh(); }, [refresh]);

  async function action(jobId, suffix) {
    try {
      const res = await fetch(`/api/jobs/${encodeURIComponent(jobId)}/${suffix}`, {
        method: 'POST',
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      await refresh();
    } catch (err) {
      setError(err.message);
    }
  }

  const counts = jobs.reduce((acc, job) => {
    acc[job.status] = (acc[job.status] || 0) + 1;
    return acc;
  }, {});

  return (
    <section className="panel">
      <h2>AI Job 큐 <span className="muted">({jobs.length})</span></h2>
      <div className="card workflow-card">
        <strong>Job 운영 가이드</strong>
        <div className="muted" style={{ marginTop: 6 }}>
          이 화면의 등록/일시정지/재개는 로컬 큐 상태만 변경합니다. 실제 워커가 job을 acquire해 실행할 때 provider 설정에 따라 LIVE 모델 호출이 발생할 수 있습니다.
        </div>
        <div className="row" style={{ marginTop: 8 }}>
          {STATUSES.filter((status) => counts[status]).map((status) => (
            <span key={status} className={`badge ${statusBadgeClass(status)}`}>{status} {counts[status]}</span>
          ))}
        </div>
      </div>

      <EnqueueForm onEnqueued={refresh} />

      <div className="row" style={{ marginTop: 14, marginBottom: 10 }}>
        <label className="muted">
          상태 필터:&nbsp;
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="">(전체)</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </label>
        <label className="muted">
          role 필터:&nbsp;
          <select value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)}>
            <option value="">(전체)</option>
            {ROLES.map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
        </label>
        <button className="provider-form" onClick={refresh} disabled={loading}>
          {loading ? '불러오는 중...' : '새로고침'}
        </button>
        {error && <span className="badge err">{error}</span>}
      </div>

      {jobs.length === 0 && !loading && (
        <div className="muted">표시할 job이 없습니다.</div>
      )}

      <ul className="items">
        {jobs.map((j) => (
          <li key={j.job_id}>
            <span style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <span>
                <code>{j.job_id}</code> · {j.role} · 우선순위 {j.priority} · 시도 {j.attempts}
              </span>
              <span className="muted">batch: {j.batch_id}{j.lease_owner ? ` · 워커 ${j.lease_owner}` : ''}</span>
              {j.error_summary && <span className="muted">err: {j.error_summary}</span>}
            </span>
            <span className="row" style={{ gap: 6 }}>
              <span className={`badge ${statusBadgeClass(j.status)}`}>{j.status}</span>
              {j.status === 'queued' && (
                <button onClick={() => action(j.job_id, 'pause')}>일시정지</button>
              )}
              {j.status === 'paused' && (
                <button onClick={() => action(j.job_id, 'resume')}>재개</button>
              )}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
