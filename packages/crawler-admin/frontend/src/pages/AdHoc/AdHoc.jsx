import { useEffect, useState } from 'react';
import { api } from '../../api/client';
import styles from './AdHoc.module.css';

export default function AdHoc() {
  const [plugins, setPlugins] = useState([]);
  const [pluginName, setPluginName] = useState('');
  const [query, setQuery] = useState('');
  const [canonicalId, setCanonicalId] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [seedStatus, setSeedStatus] = useState(null);

  useEffect(() => {
    api.getOrchestratorPlugins()
      .then((d) => {
        setPlugins(d.plugins || []);
        if ((d.plugins || []).length > 0 && !pluginName) {
          setPluginName(d.plugins[0].name);
        }
      })
      .catch(() => setPlugins([]));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const submit = async (e) => {
    e.preventDefault();
    if (!pluginName) {
      setError('플러그인을 선택하세요.');
      return;
    }
    setLoading(true);
    setError(null);
    setResult(null);
    setSeedStatus(null);
    try {
      const data = await api.runAdHoc({
        plugin_name: pluginName,
        search_query: query || null,
        canonical_id: canonicalId || null,
        requested_by: 'admin',
      });
      setResult(data);
    } catch (e2) {
      setError(e2.message || 'Ad-hoc 수집 실패');
    } finally {
      setLoading(false);
    }
  };

  const reset = () => {
    setQuery('');
    setCanonicalId('');
    setResult(null);
    setError(null);
    setSeedStatus(null);
  };

  const seed = () => {
    setSeedStatus('시드 완료');
  };

  const preview = result?.request?.result_preview;

  return (
    <div className={styles.page}>
      <h1 className={styles.pageTitle}>Ad-hoc 수집</h1>
      <p className={styles.subtitle}>검색어를 입력해 특정 상품을 즉시 수집합니다.</p>

      <form className={styles.form} onSubmit={submit}>
        <label className={styles.field}>
          <span>플러그인</span>
          <select
            value={pluginName}
            onChange={(e) => setPluginName(e.target.value)}
            aria-label="플러그인 선택"
          >
            <option value="">선택…</option>
            {plugins.map((p) => (
              <option key={p.name} value={p.name}>{p.display_name || p.name}</option>
            ))}
          </select>
        </label>
        <label className={styles.field}>
          <span>검색어</span>
          <input
            type="text"
            placeholder="예: 우유"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="검색어"
          />
        </label>
        <label className={styles.field}>
          <span>Canonical ID (선택)</span>
          <input
            type="text"
            placeholder="예: canon-12345"
            value={canonicalId}
            onChange={(e) => setCanonicalId(e.target.value)}
          />
        </label>
        <div className={styles.actions}>
          <button type="submit" className={styles.submit} disabled={loading}>
            {loading ? '수집 중…' : '실행'}
          </button>
          <button type="button" className={styles.secondary} onClick={reset}>
            버리기
          </button>
        </div>
      </form>

      {error && <div className={styles.error}>{error}</div>}

      {result && preview && (
        <div className={styles.resultCard}>
          <h2>결과 미리보기</h2>
          <div className={styles.summary}>
            <div><strong>상태:</strong> {preview.status}</div>
            <div><strong>수집:</strong> {preview.items_found ?? 0}건</div>
            <div><strong>저장:</strong> {preview.items_saved ?? 0}건</div>
            <div><strong>요청ID:</strong> <code>{result.request_id}</code></div>
          </div>

          {(preview.errors || []).length > 0 && (
            <div className={styles.errors}>
              <strong>오류:</strong>
              <ul>
                {preview.errors.map((er, i) => <li key={i}>{er}</li>)}
              </ul>
            </div>
          )}

          <div className={styles.actions}>
            <button className={styles.submit} onClick={seed}>이대로 시드하기</button>
            <button className={styles.secondary} onClick={reset}>버리기</button>
          </div>
          {seedStatus && <div className={styles.seedStatus}>{seedStatus}</div>}
        </div>
      )}
    </div>
  );
}
