import { useCallback, useEffect, useMemo, useState } from 'react';

const STATUS_OPTIONS = [
  'ai_proposed',
  'human_reviewing',
  'approved',
  'published',
  'needs_rework',
  'rejected',
  'superseded',
  'dead_letter',
];

async function requestJson(url, { method = 'GET', body } = {}) {
  const res = await fetch(url, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
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

function parseJsonOrString(value) {
  try { return JSON.parse(value); } catch { return value; }
}

function pretty(value) {
  if (value == null || value === '') return '-';
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  return JSON.stringify(value);
}

function statusBadgeClass(status) {
  if (status === 'approved' || status === 'published') return 'ok';
  if (status === 'ai_proposed' || status === 'human_reviewing') return 'warn';
  if (status === 'rejected' || status === 'dead_letter' || status === 'needs_rework') return 'err';
  return '';
}

function groupByRecord(proposals) {
  return proposals.reduce((acc, proposal) => {
    const rawId = proposal.provenance?.raw_record_id || '(unlinked)';
    acc[rawId] = acc[rawId] || [];
    acc[rawId].push(proposal);
    return acc;
  }, {});
}

function WorkflowGuide({ audit, rawCount, proposalCount }) {
  return (
    <div className="card workflow-card">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <strong>크롤러 → AI → 검수 운영 흐름</strong>
        <span className={`badge ${audit?.status === 'ok' ? 'ok' : 'warn'}`}>{audit?.status || 'unknown'}</span>
      </div>
      <ol className="workflow-steps">
        <li><b>Raw 확인</b> — crawler-admin에서 넘어온 원본 레코드와 payload를 먼저 확인합니다.</li>
        <li><b>AI 제안 검토</b> — 연결된 proposal, provenance, audit issue를 한 화면에서 비교합니다.</li>
        <li><b>오프라인 검수 액션</b> — 시작/승인/보정/반려/수정/삭제는 로컬 review API만 호출하고 모델을 호출하지 않습니다.</li>
      </ol>
      <div className="muted">
        원본 {audit?.raw_record_count ?? rawCount}개 · 커버 {audit?.covered_record_count ?? 0}개 ·
        누락 {audit?.missing_record_count ?? 0}개 · 제안 {audit?.proposal_count ?? proposalCount}개 · 이슈 {audit?.issue_count ?? 0}개
      </div>
      <div className="muted" style={{ marginTop: 6 }}>
        라이브 모델 호출은 <code>/api/ingest/raw-records/label</code> 같은 ingest/provider 액션에서만 발생합니다. 이 검수 화면은 재라벨링을 실행하지 않습니다.
      </div>
    </div>
  );
}

function ProposalActions({ proposal, reviewerId, setReviewerId, onRefresh, onError }) {
  const [editOpen, setEditOpen] = useState(false);
  const [targetField, setTargetField] = useState(proposal.target_field);
  const [valueText, setValueText] = useState(JSON.stringify(proposal.proposed_value));
  const [alternativesText, setAlternativesText] = useState(JSON.stringify(proposal.alternatives || []));
  const [reason, setReason] = useState('');
  const [correctedText, setCorrectedText] = useState(JSON.stringify(proposal.proposed_value));
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setTargetField(proposal.target_field);
    setValueText(JSON.stringify(proposal.proposed_value));
    setAlternativesText(JSON.stringify(proposal.alternatives || []));
    setCorrectedText(JSON.stringify(proposal.proposed_value));
    setReason('');
    setEditOpen(false);
  }, [proposal.proposal_id, proposal.target_field, proposal.proposed_value, proposal.alternatives]);

  async function run(label, callback) {
    setBusy(true);
    try {
      await callback();
      onError(null);
      await onRefresh();
    } catch (err) {
      onError(`${label}: ${err.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function saveEdit() {
    let alternatives;
    try {
      alternatives = JSON.parse(alternativesText || '[]');
      if (!Array.isArray(alternatives)) throw new Error('alternatives must be an array');
    } catch (err) {
      onError(`수정: alternatives JSON 오류 (${err.message})`);
      return;
    }
    await run('수정', () => requestJson(`/api/review/proposals/${encodeURIComponent(proposal.proposal_id)}`, {
      method: 'PUT',
      body: {
        target_field: targetField,
        proposed_value: parseJsonOrString(valueText),
        alternatives,
      },
    }));
  }

  async function approve() {
    if (!reviewerId.trim()) return onError('승인: 검수자 ID를 입력하세요.');
    await run('승인', () => requestJson(`/api/review/proposals/${encodeURIComponent(proposal.proposal_id)}/approve`, {
      method: 'POST',
      body: { reviewer_id: reviewerId.trim() },
    }));
  }

  async function correct() {
    if (!reviewerId.trim()) return onError('보정: 검수자 ID를 입력하세요.');
    if (!reason.trim()) return onError('보정: 사유를 입력하세요.');
    await run('보정', () => requestJson(`/api/review/proposals/${encodeURIComponent(proposal.proposal_id)}/correct`, {
      method: 'POST',
      body: {
        reviewer_id: reviewerId.trim(),
        corrected_value: parseJsonOrString(correctedText),
        reason: reason.trim(),
      },
    }));
  }

  async function reject() {
    if (!reviewerId.trim()) return onError('반려: 검수자 ID를 입력하세요.');
    if (!reason.trim()) return onError('반려: 사유를 입력하세요.');
    await run('반려', () => requestJson(`/api/review/proposals/${encodeURIComponent(proposal.proposal_id)}/reject`, {
      method: 'POST',
      body: { reviewer_id: reviewerId.trim(), reason: reason.trim() },
    }));
  }

  async function remove() {
    if (!window.confirm(`${proposal.proposal_id} 제안을 삭제할까요?`)) return;
    await run('삭제', () => requestJson(`/api/review/proposals/${encodeURIComponent(proposal.proposal_id)}`, { method: 'DELETE' }));
  }

  const reviewable = proposal.status === 'ai_proposed' || proposal.status === 'human_reviewing';
  const deletable = ['ai_proposed', 'human_reviewing', 'rejected'].includes(proposal.status);

  return (
    <div className="proposal-actions">
      <div className="row" style={{ gap: 6 }}>
        {proposal.status === 'ai_proposed' && (
          <button disabled={busy} onClick={() => run('검수 시작', () => requestJson(`/api/review/proposals/${encodeURIComponent(proposal.proposal_id)}/start`, { method: 'POST' }))}>
            검수 시작
          </button>
        )}
        {reviewable && <button disabled={busy} onClick={approve}>승인</button>}
        {reviewable && <button disabled={busy} onClick={correct}>보정 승인</button>}
        {reviewable && <button disabled={busy} onClick={reject}>반려</button>}
        {reviewable && <button disabled={busy} onClick={() => setEditOpen((open) => !open)}>값 수정</button>}
        {deletable && <button disabled={busy} onClick={remove}>삭제</button>}
      </div>
      {reviewable && (
        <div className="form-grid compact-grid" style={{ marginTop: 8 }}>
          <label>
            검수자 ID
            <input value={reviewerId} onChange={(e) => setReviewerId(e.target.value)} placeholder="admin" />
          </label>
          <label>
            보정 값(JSON 또는 문자열)
            <input value={correctedText} onChange={(e) => setCorrectedText(e.target.value)} />
          </label>
          <label>
            반려/보정 사유
            <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="왜 결정했는지" />
          </label>
        </div>
      )}
      {editOpen && (
        <div className="card nested-card">
          <strong>제안 값 직접 수정</strong>
          <div className="form-grid compact-grid" style={{ marginTop: 8 }}>
            <label>
              target_field
              <input value={targetField} onChange={(e) => setTargetField(e.target.value)} />
            </label>
            <label>
              proposed_value(JSON 또는 문자열)
              <input value={valueText} onChange={(e) => setValueText(e.target.value)} />
            </label>
            <label>
              alternatives(JSON 배열)
              <input value={alternativesText} onChange={(e) => setAlternativesText(e.target.value)} />
            </label>
          </div>
          <button style={{ marginTop: 8 }} disabled={busy || !targetField.trim()} onClick={saveEdit}>수정 저장</button>
        </div>
      )}
    </div>
  );
}

function ProposalCard({ proposal, reviewerId, setReviewerId, onRefresh, onError }) {
  return (
    <li className="proposal-card">
      <div className="proposal-main">
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <span>
            <code>{proposal.proposal_id}</code>{' '}
            <span className={`badge ${statusBadgeClass(proposal.status)}`}>{proposal.status}</span>{' '}
            <span className="badge">{proposal.proposal_type}</span>
          </span>
          <span className="muted">raw: {proposal.provenance?.raw_record_id || '-'}</span>
        </div>
        <div style={{ marginTop: 6 }}>
          <b>{proposal.target_field}</b> = <code>{pretty(proposal.proposed_value)}</code>
        </div>
        <div className="muted" style={{ marginTop: 4 }}>
          role {proposal.provenance?.worker_role || '-'} · confidence {proposal.provenance?.confidence ?? '-'} · model {proposal.provenance?.provider?.model_name || '-'}
        </div>
        {proposal.provenance?.evidence_text && (
          <div className="muted" style={{ marginTop: 4 }}>근거: {proposal.provenance.evidence_text}</div>
        )}
        {!!proposal.alternatives?.length && (
          <div className="muted" style={{ marginTop: 4 }}>대안: {proposal.alternatives.map(pretty).join(', ')}</div>
        )}
        <ProposalActions
          proposal={proposal}
          reviewerId={reviewerId}
          setReviewerId={setReviewerId}
          onRefresh={onRefresh}
          onError={onError}
        />
      </div>
    </li>
  );
}

export default function ReviewQueuePanel() {
  const [items, setItems] = useState([]);
  const [rawRecords, setRawRecords] = useState([]);
  const [audit, setAudit] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState('');
  const [search, setSearch] = useState('');
  const [selectedRawId, setSelectedRawId] = useState(null);
  const [reviewerId, setReviewerIdState] = useState(() => (
    typeof window === 'undefined' ? '' : window.localStorage.getItem('ai-admin-reviewer-id') || ''
  ));

  const setReviewerId = useCallback((value) => {
    setReviewerIdState(value);
    if (typeof window !== 'undefined') window.localStorage.setItem('ai-admin-reviewer-id', value);
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [proposals, records, auditReport] = await Promise.all([
        requestJson('/api/review/proposals'),
        requestJson('/api/review/raw-records?include_proposals=true'),
        requestJson('/api/review/audit'),
      ]);
      const nextItems = proposals.items || [];
      const nextRecords = records.items || [];
      setItems(nextItems);
      setRawRecords(nextRecords);
      setAudit(auditReport);
      setSelectedRawId((current) => current || nextRecords[0]?.raw_record_id || null);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const proposalsByRecord = useMemo(() => groupByRecord(items), [items]);
  const issuesByRecord = useMemo(() => {
    const grouped = {};
    for (const issue of audit?.issues || []) {
      grouped[issue.raw_record_id] = grouped[issue.raw_record_id] || [];
      grouped[issue.raw_record_id].push(issue);
    }
    return grouped;
  }, [audit]);

  const filteredRecords = useMemo(() => {
    const term = search.trim().toLowerCase();
    return rawRecords.filter((record) => {
      const proposals = proposalsByRecord[record.raw_record_id] || [];
      const statusOk = !statusFilter || proposals.some((p) => p.status === statusFilter);
      const text = `${record.raw_record_id} ${record.source_name} ${record.raw_title} ${record.source_record_key || ''}`.toLowerCase();
      return statusOk && (!term || text.includes(term));
    });
  }, [rawRecords, proposalsByRecord, statusFilter, search]);

  const selectedRecord = rawRecords.find((record) => record.raw_record_id === selectedRawId) || filteredRecords[0] || null;
  const selectedProposals = selectedRecord ? (proposalsByRecord[selectedRecord.raw_record_id] || []) : [];
  const selectedIssues = selectedRecord ? (issuesByRecord[selectedRecord.raw_record_id] || []) : [];
  const statusCounts = useMemo(() => items.reduce((acc, proposal) => {
    acc[proposal.status] = (acc[proposal.status] || 0) + 1;
    return acc;
  }, {}), [items]);

  return (
    <section className="panel review-panel">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <h2>검수 큐 <span className="muted">({items.length} proposals / {rawRecords.length} raw)</span></h2>
        <button className="secondary-button" onClick={refresh} disabled={loading}>{loading ? '불러오는 중...' : '새로고침'}</button>
      </div>
      {error && <div className="badge err" style={{ marginBottom: 10 }}>오류: {error}</div>}

      <WorkflowGuide audit={audit} rawCount={rawRecords.length} proposalCount={items.length} />

      <div className="row" style={{ margin: '12px 0' }}>
        <label className="muted">
          상태 필터&nbsp;
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">전체</option>
            {STATUS_OPTIONS.map((status) => (
              <option key={status} value={status}>{status} ({statusCounts[status] || 0})</option>
            ))}
          </select>
        </label>
        <label className="muted">
          검색&nbsp;
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="raw id/source/title" />
        </label>
      </div>

      <div className="split-view">
        <div className="card list-card">
          <div className="row" style={{ justifyContent: 'space-between', marginBottom: 8 }}>
            <strong>Raw records</strong>
            <span className="muted">{filteredRecords.length}개 표시</span>
          </div>
          {filteredRecords.length === 0 && <div className="muted">조건에 맞는 원본이 없습니다.</div>}
          <ul className="items compact-list">
            {filteredRecords.map((record) => {
              const linked = proposalsByRecord[record.raw_record_id] || [];
              const issues = issuesByRecord[record.raw_record_id] || [];
              const active = selectedRecord?.raw_record_id === record.raw_record_id;
              return (
                <li key={record.raw_record_id} className={active ? 'selected-list-item' : ''} onClick={() => setSelectedRawId(record.raw_record_id)}>
                  <span>
                    <code>{record.raw_record_id}</code> {record.raw_title}
                    <div className="muted">{record.source_name} · price {record.raw_price ?? '-'} · proposal {linked.length}</div>
                  </span>
                  <span className={`badge ${issues.length ? 'warn' : 'ok'}`}>{issues.length ? `이슈 ${issues.length}` : '감사 OK'}</span>
                </li>
              );
            })}
          </ul>
        </div>

        <div className="card detail-card">
          {!selectedRecord && <div className="muted">원본 레코드를 선택하세요.</div>}
          {selectedRecord && (
            <>
              <div className="row" style={{ justifyContent: 'space-between' }}>
                <strong>{selectedRecord.raw_title}</strong>
                <code>{selectedRecord.raw_record_id}</code>
              </div>
              <div className="muted" style={{ marginTop: 6 }}>
                source {selectedRecord.source_name} · key {selectedRecord.source_record_key || '-'} · price {selectedRecord.raw_price ?? '-'}
                {selectedRecord.source_url ? <> · <a href={selectedRecord.source_url} target="_blank" rel="noreferrer">source URL</a></> : null}
              </div>

              {!!selectedIssues.length && (
                <div className="card nested-card issue-card">
                  <strong>Audit issues</strong>
                  {selectedIssues.map((issue, index) => (
                    <div key={`${issue.code}-${index}`} className="muted" style={{ marginTop: 6 }}>
                      <span className="badge warn">{issue.code}</span> {issue.message}
                      {issue.expected !== undefined && <div>expected: <code>{pretty(issue.expected)}</code></div>}
                      {issue.actual !== undefined && <div>actual: <code>{pretty(issue.actual)}</code></div>}
                    </div>
                  ))}
                </div>
              )}

              <details style={{ marginTop: 10 }}>
                <summary>raw_payload 보기</summary>
                <pre className="json-block">{JSON.stringify(selectedRecord.raw_payload || {}, null, 2)}</pre>
              </details>

              <div style={{ marginTop: 14 }}>
                <div className="row" style={{ justifyContent: 'space-between', marginBottom: 8 }}>
                  <strong>Linked proposals</strong>
                  <span className="muted">{selectedProposals.length}개</span>
                </div>
                {selectedProposals.length === 0 && <div className="muted">이 원본에 연결된 AI 제안이 없습니다. audit의 missing_* 이슈를 확인하세요.</div>}
                <ul className="items proposal-list">
                  {selectedProposals.map((proposal) => (
                    <ProposalCard
                      key={proposal.proposal_id}
                      proposal={proposal}
                      reviewerId={reviewerId}
                      setReviewerId={setReviewerId}
                      onRefresh={refresh}
                      onError={setError}
                    />
                  ))}
                </ul>
              </div>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
