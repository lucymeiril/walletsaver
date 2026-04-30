import { useCallback, useEffect, useState } from 'react';

const PROVIDER_KINDS = [
  { value: 'gemini', label: 'Google Gemini' },
  { value: 'openai_compatible', label: 'OpenAI 호환' },
  { value: 'ollama', label: 'Ollama (로컬)' },
  { value: 'custom', label: '사용자 정의' },
];

const EMPTY_FORM = {
  provider_id: '',
  provider_kind: 'gemini',
  display_name: '',
  base_url: '',
  default_model: '',
  secret_alias: '',
  is_enabled: true,
  max_concurrent_jobs: 1,
  min_request_interval_seconds: 1.0,
  daily_budget_limit: '',
};

function toPayload(form) {
  return {
    provider_id: form.provider_id.trim(),
    provider_kind: form.provider_kind,
    display_name: form.display_name.trim(),
    base_url: form.base_url.trim() ? form.base_url.trim() : null,
    default_model: form.default_model.trim(),
    secret_alias: form.secret_alias.trim() ? form.secret_alias.trim() : null,
    is_enabled: !!form.is_enabled,
    max_concurrent_jobs: Number(form.max_concurrent_jobs) || 1,
    min_request_interval_seconds: Number(form.min_request_interval_seconds) || 1.0,
    daily_budget_limit:
      form.daily_budget_limit === '' || form.daily_budget_limit == null
        ? null
        : Number(form.daily_budget_limit),
  };
}

function fromConfig(cfg) {
  return {
    provider_id: cfg.provider_id ?? '',
    provider_kind: cfg.provider_kind ?? 'gemini',
    display_name: cfg.display_name ?? '',
    base_url: cfg.base_url ?? '',
    default_model: cfg.default_model ?? '',
    secret_alias: cfg.secret_alias ?? '',
    is_enabled: !!cfg.is_enabled,
    max_concurrent_jobs: cfg.max_concurrent_jobs ?? 1,
    min_request_interval_seconds: cfg.min_request_interval_seconds ?? 1.0,
    daily_budget_limit:
      cfg.daily_budget_limit == null ? '' : String(cfg.daily_budget_limit),
  };
}

export default function ProvidersPanel() {
  const [providers, setProviders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(null);
  const [editingId, setEditingId] = useState(null);
  const [modelResults, setModelResults] = useState({});

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch('/api/providers');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const body = await res.json();
      setProviders(body.providers ?? []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  function update(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  function startEdit(cfg) {
    setForm(fromConfig(cfg));
    setEditingId(cfg.provider_id);
    setSaveError(null);
  }

  function resetForm() {
    setForm(EMPTY_FORM);
    setEditingId(null);
    setSaveError(null);
  }

  async function submit(event) {
    event.preventDefault();
    setSaving(true);
    setSaveError(null);
    try {
      const res = await fetch('/api/providers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(toPayload(form)),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(`HTTP ${res.status}: ${text}`);
      }
      await refresh();
      resetForm();
    } catch (err) {
      setSaveError(err.message);
    } finally {
      setSaving(false);
    }
  }

  async function toggle(cfg) {
    try {
      const res = await fetch(`/api/providers/${encodeURIComponent(cfg.provider_id)}/enabled`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_enabled: !cfg.is_enabled }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await refresh();
    } catch (err) {
      setError(err.message);
    }
  }

  async function loadModels(cfg) {
    setModelResults((prev) => ({
      ...prev,
      [cfg.provider_id]: { status: 'loading', data: null, error: null },
    }));
    try {
      const res = await fetch(`/api/providers/${encodeURIComponent(cfg.provider_id)}/models`);
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
      setModelResults((prev) => ({
        ...prev,
        [cfg.provider_id]: { status: 'ok', data: body, error: null },
      }));
    } catch (err) {
      setModelResults((prev) => ({
        ...prev,
        [cfg.provider_id]: { status: 'error', data: null, error: err.message },
      }));
    }
  }

  return (
    <section className="panel">
      <h2>Provider 설정 <span className="muted">({providers.length})</span></h2>
      {loading && <div className="muted">로딩 중...</div>}
      {error && <div className="muted">불러올 수 없습니다 — {error}</div>}

      {!loading && !error && providers.length === 0 && (
        <div className="muted">등록된 provider가 없습니다. 아래에서 추가하세요.</div>
      )}

      {providers.length > 0 && (
        <ul className="items">
          {providers.map((p) => {
            const models = modelResults[p.provider_id];
            return (
            <li key={p.provider_id}>
              <div>
                <div>
                  <strong>{p.display_name}</strong>{' '}
                  <code>{p.provider_id}</code>{' '}
                  <span className="badge">{p.provider_kind}</span>
                </div>
                <div className="muted" style={{ marginTop: 4 }}>
                  model: <code>{p.default_model}</code>
                  {p.base_url ? <> · base_url: <code>{p.base_url}</code></> : null}
                  {p.secret_alias ? <> · alias: <code>{p.secret_alias}</code></> : <> · alias 없음</>}
                  {' '}· 동시 {p.max_concurrent_jobs} · 간격 {p.min_request_interval_seconds}s
                </div>
                {models?.status === 'loading' && (
                  <div className="muted" style={{ marginTop: 6 }}>모델 목록 확인 중...</div>
                )}
                {models?.status === 'error' && (
                  <div className="muted" style={{ marginTop: 6, color: '#ff8a8a' }}>
                    모델 조회 실패: {models.error}
                  </div>
                )}
                {models?.status === 'ok' && (
                  <div className="muted" style={{ marginTop: 6 }}>
                    모델 {models.data.models?.length ?? 0}개 · 남은 할당량 제공:{' '}
                    {models.data.quota_remaining_available ? '예' : '아니오'}
                    <div style={{ marginTop: 4 }}>
                      {(models.data.models ?? []).slice(0, 8).map((m) => (
                        <code key={m.name} style={{ marginRight: 6 }}>{m.name}</code>
                      ))}
                    </div>
                  </div>
                )}
              </div>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <span className={`badge ${p.is_enabled ? 'ok' : ''}`}>
                  {p.is_enabled ? '활성' : '비활성'}
                </span>
                <button type="button" onClick={() => toggle(p)}>
                  {p.is_enabled ? '비활성화' : '활성화'}
                </button>
                <button type="button" onClick={() => loadModels(p)}>모델 조회</button>
                <button type="button" onClick={() => startEdit(p)}>편집</button>
              </div>
            </li>
          );})}
        </ul>
      )}

      <form className="provider-form" onSubmit={submit}>
        <h3 style={{ margin: '16px 0 8px', fontSize: '0.95rem' }}>
          {editingId ? `편집: ${editingId}` : '새 provider 추가'}
        </h3>
        <div className="form-grid">
          <label>
            <span>provider_id</span>
            <input
              required
              value={form.provider_id}
              disabled={!!editingId}
              onChange={(e) => update('provider_id', e.target.value)}
              placeholder="gemini-prod"
            />
          </label>
          <label>
            <span>provider 종류</span>
            <select
              value={form.provider_kind}
              onChange={(e) => update('provider_kind', e.target.value)}
            >
              {PROVIDER_KINDS.map((k) => (
                <option key={k.value} value={k.value}>{k.label}</option>
              ))}
            </select>
          </label>
          <label>
            <span>표시 이름</span>
            <input
              required
              value={form.display_name}
              onChange={(e) => update('display_name', e.target.value)}
              placeholder="Gemini Prod"
            />
          </label>
          <label>
            <span>기본 모델</span>
            <input
              required
              value={form.default_model}
              onChange={(e) => update('default_model', e.target.value)}
              placeholder="gemma-3-27b-it"
            />
          </label>
          <label>
            <span>base_url (선택)</span>
            <input
              value={form.base_url}
              onChange={(e) => update('base_url', e.target.value)}
              placeholder="https://api.example.com/v1"
            />
          </label>
          <label>
            <span>secret alias</span>
            <input
              value={form.secret_alias}
              onChange={(e) => update('secret_alias', e.target.value)}
              placeholder="GEMINI_API_KEY"
            />
          </label>
          <label>
            <span>최대 동시 요청</span>
            <input
              type="number"
              min={1}
              max={20}
              value={form.max_concurrent_jobs}
              onChange={(e) => update('max_concurrent_jobs', e.target.value)}
            />
          </label>
          <label>
            <span>최소 요청 간격(초)</span>
            <input
              type="number"
              step="0.1"
              min={1.0}
              value={form.min_request_interval_seconds}
              onChange={(e) => update('min_request_interval_seconds', e.target.value)}
            />
          </label>
          <label>
            <span>일일 예산 한도 (선택)</span>
            <input
              type="number"
              step="0.01"
              min={0}
              value={form.daily_budget_limit}
              onChange={(e) => update('daily_budget_limit', e.target.value)}
            />
          </label>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={!!form.is_enabled}
              onChange={(e) => update('is_enabled', e.target.checked)}
            />
            <span>활성화</span>
          </label>
        </div>
        <div className="muted" style={{ marginTop: 6 }}>
          비밀값(API 키 등)은 절대 입력하지 마세요. alias 이름만 등록합니다.
        </div>
        {saveError && (
          <div className="muted" style={{ marginTop: 8, color: '#ff8a8a' }}>
            저장 실패: {saveError}
          </div>
        )}
        <div style={{ marginTop: 10, display: 'flex', gap: 8 }}>
          <button type="submit" disabled={saving}>
            {saving ? '저장 중...' : editingId ? '업데이트' : '추가'}
          </button>
          {editingId && (
            <button type="button" onClick={resetForm} disabled={saving}>
              취소
            </button>
          )}
        </div>
      </form>
    </section>
  );
}
