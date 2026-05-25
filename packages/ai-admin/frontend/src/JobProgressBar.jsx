import { useEffect, useState } from 'react';
import { computeJobProgress, fmtEta } from './pipelineErrors.js';

/**
 * /api/jobs/{job_id} 를 1.5s 주기로 폴링해 진행률/ETA 를 표시.
 *
 * 사용자 비판: "잡 등록됨" 한 줄 뒤에 아무 정보가 없다 → 진행 중인지, 끝났는지,
 * 얼마나 남았는지 알 수 없다. 진행 막대 + 평균 시간 + ETA 명시.
 *
 * props.jobId 가 null/undefined 면 폴링하지 않음.
 */
export default function JobProgressBar({ jobId, intervalMs = 1500, onDone }) {
  const [job, setJob] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    if (!jobId) return undefined;
    let cancelled = false;
    let timer = null;

    async function tick() {
      try {
        const res = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, { cache: 'no-store' });
        const body = await res.json().catch(() => ({}));
        if (cancelled) return;
        if (!res.ok) {
          setErr(body?.detail || `HTTP ${res.status}`);
        } else {
          setErr(null);
          setJob(body.job || body);
          const prog = computeJobProgress(body.job || body);
          if (prog.done || prog.failed) {
            onDone?.(body.job || body, prog);
            return; // stop polling
          }
        }
      } catch (e) {
        if (!cancelled) setErr(e.message || String(e));
      }
      if (!cancelled) timer = setTimeout(tick, intervalMs);
    }
    tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [jobId, intervalMs, onDone]);

  if (!jobId) return null;
  const p = computeJobProgress(job);
  const stateLabel = p.failed
    ? '실패'
    : p.done
      ? '완료'
      : job?.status || '대기 중';

  return (
    <div className="job-progress" data-testid="job-progress" data-status={job?.status || 'pending'}>
      <div className="job-progress-head">
        <code>{jobId}</code>
        <span className={`badge ${p.failed ? 'err' : p.done ? 'ok' : 'warn'}`}>{stateLabel}</span>
      </div>
      <div
        className="job-progress-bar"
        role="progressbar"
        aria-valuenow={p.percent}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div className="job-progress-fill" style={{ width: `${p.percent}%` }} />
      </div>
      <div className="job-progress-meta muted">
        {p.total > 0 ? (
          <>
            {p.processed.toLocaleString()} / {p.total.toLocaleString()} ({p.percent}%)
            {p.avgSecPerItem != null && (
              <>
                {' · '}평균 {p.avgSecPerItem.toFixed(1)}s/item
              </>
            )}
            {p.etaSec != null && (
              <>
                {' · '}ETA {fmtEta(p.etaSec)}
              </>
            )}
          </>
        ) : (
          <>진행 정보 대기 중…</>
        )}
        {err && <span className="text-err"> · {String(err)}</span>}
      </div>
    </div>
  );
}
