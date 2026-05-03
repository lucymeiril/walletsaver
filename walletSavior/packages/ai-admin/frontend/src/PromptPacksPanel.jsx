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

function PromptDraftForm({ onSubmitted, onError }) {
  const [form, setForm] = useState({
    pack_id: '', role: 'normalizer', version: '', content: '', changelog: '', created_by: '',
  });
  const update = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    try {
      await postJson('/api/prompts', form);
      setForm({ pack_id: '', role: 'normalizer', version: '', content: '', changelog: '', created_by: '' });
      onSubmitted();
    } catch (err) {
      onError(err.message);
    }
  };

  return (
    <form onSubmit={submit} className="row" style={{ flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
      <input placeholder="pack_id" value={form.pack_id} onChange={update('pack_id')} required />
      <input placeholder="version" value={form.version} onChange={update('version')} required />
      <input placeholder="role" value={form.role} onChange={update('role')} required />
      <input placeholder="created_by" value={form.created_by} onChange={update('created_by')} required />
      <input placeholder="changelog" value={form.changelog} onChange={update('changelog')} />
      <textarea
        placeholder="content"
        value={form.content}
        onChange={update('content')}
        required
        rows={2}
        style={{ flexBasis: '100%' }}
      />
      <button type="submit">초안 제출</button>
    </form>
  );
}

export default function PromptPacksPanel() {
  const [items, setItems] = useState([]);
  const [error, setError] = useState(null);
  const [tick, setTick] = useState(0);
  const refresh = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let cancelled = false;
    fetch('/api/prompts')
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
      <h2>프롬프트 팩 <span className="muted">({items.length})</span></h2>
      {error && <div className="muted" style={{ color: '#a00' }}>오류: {error}</div>}
      <details className="inline-details" style={{ marginBottom: 10 }}>
        <summary>고급: 프롬프트 초안 작성 열기</summary>
        <div style={{ marginTop: 10 }}>
          <PromptDraftForm onSubmitted={refresh} onError={(m) => setError(m)} />
        </div>
      </details>
      <ul className="items">
        {items.map((p) => (
          <li key={`${p.pack_id}@${p.version}`}>
            <span>
              <code>{p.pack_id}@{p.version}</code> <span className="muted">{p.role}</span>
            </span>
            <span className="badge">{p.status}</span>
            <span className="row" style={{ gap: 6 }}>
              {p.status === 'draft' && (
                <button onClick={() => act(`/api/prompts/${p.pack_id}/${p.version}/request-review`)}>
                  검수 요청
                </button>
              )}
              {p.status === 'in_review' && (
                <button onClick={() => {
                  const approver = window.prompt('승인자 ID');
                  if (approver) {
                    act(`/api/prompts/${p.pack_id}/${p.version}/activate`, { approved_by: approver });
                  }
                }}>활성화</button>
              )}
              {(p.status === 'deprecated' || p.status === 'rolled_back') && (
                <button onClick={() => {
                  const requester = window.prompt('요청자 ID');
                  if (requester) {
                    act(`/api/prompts/${p.pack_id}/${p.version}/rollback`, { requested_by: requester });
                  }
                }}>롤백</button>
              )}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
