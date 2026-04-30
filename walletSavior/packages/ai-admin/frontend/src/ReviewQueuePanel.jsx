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

export default function ReviewQueuePanel() {
  const [items, setItems] = useState([]);
  const [error, setError] = useState(null);
  const [tick, setTick] = useState(0);
  const refresh = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let cancelled = false;
    fetch('/api/review/proposals')
      .then((r) => r.json())
      .then((data) => { if (!cancelled) { setItems(data.items || []); setError(null); } })
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

  return (
    <section className="panel">
      <h2>검수 큐 <span className="muted">({items.length})</span></h2>
      {error && <div className="muted" style={{ color: '#a00' }}>오류: {error}</div>}
      <ul className="items">
        {items.map((p) => (
          <li key={p.proposal_id} style={{ flexWrap: 'wrap' }}>
            <span>
              <code>{p.proposal_id}</code> {p.target_field} ={' '}
              <code>{JSON.stringify(p.proposed_value)}</code>
            </span>
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
                </>
              )}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
