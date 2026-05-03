import { useCallback, useEffect, useState } from 'react';

async function postJson(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body == null ? null : JSON.stringify(body),
  });
  const text = await res.text();
  let parsed = null;
  try { parsed = text ? JSON.parse(text) : null; } catch { parsed = text; }
  if (!res.ok) {
    const detail = parsed && parsed.detail ? parsed.detail : `HTTP ${res.status}`;
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return parsed;
}

async function putJson(url, body) {
  const res = await fetch(url, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

async function deleteJson(url) {
  const res = await fetch(url, { method: 'DELETE' });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

export default function ReviewQueuePanel() {
  const [items, setItems] = useState([]);
  const [rawRecords, setRawRecords] = useState([]);
  const [audit, setAudit] = useState(null);
  const [error, setError] = useState(null);
  const [tick, setTick] = useState(0);
  const refresh = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetch('/api/review/proposals').then((r) => r.json()),
      fetch('/api/review/raw-records?include_proposals=false').then((r) => r.json()),
      fetch('/api/review/audit').then((r) => r.json()),
    ])
      .then(([proposals, records, auditReport]) => {
        if (!cancelled) {
          setItems(proposals.items || []);
          setRawRecords(records.items || []);
          setAudit(auditReport);
          setError(null);
        }
      })
      .catch((err) => { if (!cancelled) setError(err.message); });
    return () => { cancelled = true; };
  }, [tick]);

  const act = async (url, body) => {
    try {
      await postJson(url, body);
      refresh();
    } catch (err) {
      setError(err.message);
    }
  };

  const editProposal = async (proposal) => {
    const field = window.prompt('필드명', proposal.target_field);
    if (!field) return;
    const value = window.prompt('제안 값 (JSON 또는 문자열)', JSON.stringify(proposal.proposed_value));
    if (value == null) return;
    let parsed = value;
    try { parsed = JSON.parse(value); } catch { /* keep as string */ }
    try {
      await putJson(`/api/review/proposals/${proposal.proposal_id}`, {
        target_field: field,
        proposed_value: parsed,
      });
      refresh();
    } catch (err) {
      setError(err.message);
    }
  };

  const deleteProposal = async (proposal) => {
    if (!window.confirm(`${proposal.proposal_id} 제안을 삭제할까요?`)) return;
    try {
      await deleteJson(`/api/review/proposals/${proposal.proposal_id}`);
      refresh();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <section className="panel">
      <h2>검수 큐 <span className="muted">({items.length})</span></h2>
      {error && <div className="muted" style={{ color: '#a00' }}>오류: {error}</div>}
      <div className="card" style={{ marginBottom: 12 }}>
        <strong>Raw vs AI 감사</strong>{' '}
        <span className="badge">{audit?.status || 'unknown'}</span>
        <div className="muted">
          원본 {audit?.raw_record_count ?? rawRecords.length}개 · 커버 {audit?.covered_record_count ?? 0}개 ·
          이슈 {audit?.issue_count ?? 0}개
        </div>
        {!!audit?.issues?.length && (
          <pre style={{ whiteSpace: 'pre-wrap', maxHeight: 220, overflow: 'auto' }}>
            {JSON.stringify(audit.issues.slice(0, 20), null, 2)}
          </pre>
        )}
      </div>
      <ul className="items">
        {items.map((p) => (
          <li key={p.proposal_id} style={{ flexWrap: 'wrap' }}>
            <span>
              <code>{p.proposal_id}</code> {p.target_field} ={' '}
              <code>{JSON.stringify(p.proposed_value)}</code>
            </span>
            <span className="muted">raw: {p.provenance?.raw_record_id || '-'}</span>
            <span className="badge">{p.status}</span>
            <span className="row" style={{ gap: 6 }}>
              {p.status === 'ai_proposed' && (
                <button onClick={() => act(`/api/review/proposals/${p.proposal_id}/start`)}>
                  검수 시작
                </button>
              )}
              {(p.status === 'ai_proposed' || p.status === 'human_reviewing') && (
                <>
                  <button onClick={() => {
                    const reviewer = window.prompt('검수자 ID');
                    if (reviewer) {
                      act(`/api/review/proposals/${p.proposal_id}/approve`, { reviewer_id: reviewer });
                    }
                  }}>승인</button>
                  <button onClick={() => {
                    const reviewer = window.prompt('검수자 ID');
                    if (!reviewer) return;
                    const value = window.prompt('보정 값 (JSON 또는 문자열)');
                    if (value == null) return;
                    const reason = window.prompt('보정 사유');
                    if (!reason) return;
                    let parsed = value;
                    try { parsed = JSON.parse(value); } catch { /* keep as string */ }
                    act(`/api/review/proposals/${p.proposal_id}/correct`, {
                      reviewer_id: reviewer,
                      corrected_value: parsed,
                      reason,
                    });
                  }}>보정</button>
                  <button onClick={() => {
                    const reviewer = window.prompt('검수자 ID');
                    if (!reviewer) return;
                    const reason = window.prompt('반려 사유');
                    if (!reason) return;
                    act(`/api/review/proposals/${p.proposal_id}/reject`, {
                      reviewer_id: reviewer,
                      reason,
                    });
                  }}>반려</button>
                  <button onClick={() => editProposal(p)}>수정</button>
                </>
              )}
              {['ai_proposed', 'human_reviewing', 'rejected'].includes(p.status) && (
                <button onClick={() => deleteProposal(p)}>삭제</button>
              )}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
