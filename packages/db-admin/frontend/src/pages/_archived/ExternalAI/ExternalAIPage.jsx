import { useState } from 'react';
import { Download, Upload, Bot, CheckCircle2, AlertTriangle } from 'lucide-react';
import { api } from '../../api/client';
import s from './ExternalAIPage.module.css';

function JsonBlock({ data }) {
  if (!data) return null;
  return <pre className={s.json}>{JSON.stringify(data, null, 2)}</pre>;
}

export default function ExternalAIPage() {
  const [matchingFile, setMatchingFile] = useState(null);
  const [categoryFile, setCategoryFile] = useState(null);
  const [productFile, setProductFile] = useState(null);
  const [dryRun, setDryRun] = useState(true);
  const [loading, setLoading] = useState(false);
  const [exportResult, setExportResult] = useState(null);
  const [importResult, setImportResult] = useState(null);
  const [error, setError] = useState('');

  const runExport = async () => {
    setLoading(true);
    setError('');
    try {
      setExportResult(await api.exportExternalAI());
    } catch (e) {
      setError(e.message || 'Export 실패');
    } finally {
      setLoading(false);
    }
  };

  const runImport = async () => {
    setLoading(true);
    setError('');
    try {
      setImportResult(await api.importExternalAI(matchingFile, categoryFile, productFile, { dryRun }));
    } catch (e) {
      setError(e.message || 'Import 실패');
      setImportResult(e.data || null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={s.page}>
      <div className={s.header}>
        <div>
          <h1><Bot size={24} /> 외부 AI 분류 사이클</h1>
          <p>미분류 상품 번들을 내보내고 외부 AI 산출물 3종을 검증/적용합니다.</p>
        </div>
      </div>

      {error && <div className={s.alert}><AlertTriangle size={16} /> {error}</div>}

      <section className={s.card}>
        <h2><Download size={20} /> Export</h2>
        <p>unclassified.jsonl, category_list.yaml, keyword_list.yaml, instructions.md 번들을 생성합니다.</p>
        <button className={s.primary} disabled={loading} onClick={runExport}>Export 번들 생성</button>
        {exportResult && (
          <div className={s.result}>
            <CheckCircle2 size={16} /> 생성 경로: <code>{exportResult.download_path}</code>
            <JsonBlock data={exportResult.manifest?.counts} />
          </div>
        )}
      </section>

      <section className={s.card}>
        <h2><Upload size={20} /> Import</h2>
        <div className={s.grid}>
          <label>matching_updates.jsonl<input type="file" accept=".jsonl" onChange={(e) => setMatchingFile(e.target.files?.[0] || null)} /></label>
          <label>category_keyword_updates.yaml<input type="file" accept=".yaml,.yml" onChange={(e) => setCategoryFile(e.target.files?.[0] || null)} /></label>
          <label>product_updates.jsonl<input type="file" accept=".jsonl" onChange={(e) => setProductFile(e.target.files?.[0] || null)} /></label>
        </div>
        <label className={s.check}><input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} /> dry-run (DB 미반영)</label>
        <button className={s.primary} disabled={loading || !matchingFile || !categoryFile || !productFile} onClick={runImport}>Import 실행</button>
        <JsonBlock data={importResult} />
      </section>
    </div>
  );
}
