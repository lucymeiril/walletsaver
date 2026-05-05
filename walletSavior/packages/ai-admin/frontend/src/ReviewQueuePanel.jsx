import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  buildAutomationApplyMessage,
  buildBatchHealth,
  buildBulkPreview,
  buildPublishConfirmationMessage,
  buildRollbackConfirmationMessage,
  explainAutomationRow,
  nextOperatorAction,
  publishRowAction,
  summarizeAutomationPreview,
  summarizeProviderSetup,
} from './reviewQueueHelpers.js';

const STATUS_OPTIONS = [
  'ai_proposed',
  'human_reviewing',
  'pending_review',
  'approved',
  'publishing',
  'published',
  'publish_failed',
  'rolled_back',
  'held',
  'needs_rework',
  'rejected',
  'superseded',
  'dead_letter',
];

const STATUS_COPY = {
  raw_ingested: { label: '원본 수신', help: '크롤러에서 상품 원본이 들어왔습니다.' },
  ai_processing: { label: 'AI 처리 중', help: 'AI가 이름/카테고리/키워드 등을 붙이는 중입니다.' },
  ai_proposed: { label: '검수 대기', help: 'AI가 제안했지만 아직 사람이 확인하지 않았습니다.' },
  human_reviewing: { label: '사람 확인 중', help: '운영자가 보류/확인 대상으로 표시했습니다.' },
  pending_review: { label: '검수 대기', help: '승인/키워드/품질 조건이 아직 충족되지 않았습니다.' },
  approved: { label: '게시 준비', help: '검수 완료. 게시 단계로 넘길 수 있습니다.' },
  publishing: { label: '발행 중', help: 'DB-admin 큐로 전송 중입니다.' },
  published: { label: 'DB 큐 전송됨', help: 'DB-admin 검수 큐에 들어갔습니다. 최종 DB 반영은 DB-admin 승인이 필요합니다.' },
  publish_failed: { label: '발행 실패', help: 'DB-admin 전송에 실패했습니다. 오류를 확인하고 재시도하세요.' },
  rolled_back: { label: '롤백 요청됨', help: 'AI-admin 발행 기록을 되돌렸습니다. DB-admin ingestion 승인 금지/삭제를 별도로 확인하세요.' },
  held: { label: '보류', help: '반려 또는 차단 이슈가 있어 발행할 수 없습니다.' },
  needs_rework: { label: '재작업 필요', help: 'AI 또는 원본 재처리가 필요합니다.' },
  rejected: { label: '반려됨', help: '잘못된 제안으로 사용하지 않습니다.' },
  superseded: { label: '대체됨', help: '새 제안으로 대체되어 직접 처리하지 않습니다.' },
  dead_letter: { label: '실패 보관', help: '자동 복구가 어려워 원인 확인이 필요합니다.' },
};

const TYPE_COPY = {
  normalized_field: '상품명/단위 정리',
  canonical_match: '기존 상품 연결',
  category: '카테고리',
  attribute_definition: '속성 정의',
  attribute_value: '속성 값',
  keyword: '검색 키워드',
  alias: '별칭',
};

const FIELD_COPY = {
  canonical_name: '표준 상품명',
  category_id: '카테고리',
  keywords: '검색 키워드',
  price: '가격',
  sale_price: '판매가',
  raw_price: '원본 가격',
  package_unit: '포장 단위',
  standard_unit: '기준 단위',
  storage_type: '보관 방식',
  storage: '보관 방식',
  'attributes.storage_type': '보관 방식',
};

const ISSUE_COPY = {
  missing_all_proposals: 'AI 제안이 하나도 없음',
  missing_canonical_name_signal: '표준 상품명 누락',
  missing_category_id_signal: '카테고리 누락',
  missing_unit_signal: '단위 정보 누락',
  missing_keywords_signal: '검색 키워드 누락',
  mismatched_canonical_name: '예상 상품명과 다름',
  mismatched_category_id: '예상 카테고리와 다름',
  mismatched_package_unit: '예상 단위와 다름',
  mismatched_keywords: '예상 키워드와 다름',
  mismatched_raw_price: '원본 가격이 예상과 다름',
  mismatched_price: 'AI 가격이 예상과 다름',
  price_mismatch_raw: 'AI 가격이 원본 가격과 다름',
  missing_storage_attribute: '냉장/냉동/신선 보관 정보 누락',
  mismatched_storage_attribute: '보관 정보가 예상과 다름',
  name_signal_mismatch: '상품명이 원본과 어울리지 않음',
  keyword_signal_mismatch: '키워드가 원본과 어울리지 않음',
  snack_seafood_confusion: '과자를 수산물로 분류한 듯함',
  seafood_snack_confusion: '수산물을 과자로 분류한 듯함',
  orphan_ai_proposals: '없는 원본을 가리키는 AI 제안',
};

const BATCH_STATUS_COPY = {
  not_ready: { label: '발행 불가', help: '아직 검수/품질 조건이 부족합니다.' },
  partial_only: { label: '부분 발행만 가능', help: 'eligible 일부만 보낼 수 있고 남은 보류/미해결 항목은 배치 완료가 아닙니다.' },
  ready: { label: '전체 발행 준비', help: '모든 원본이 품질 게이트를 통과했습니다.' },
  published_with_holds: { label: '일부 발행 + 보류 남음', help: '발행된 항목이 있지만 배치가 완료된 상태는 아닙니다.' },
};

const REVIEWABLE_STATUSES = new Set(['ai_proposed', 'human_reviewing']);
const PRICE_FIELDS = new Set(['price', 'sale_price', 'offer_price', 'source_price', 'raw_price', 'current_price']);

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

function labelStatus(status) {
  return STATUS_COPY[status]?.label || status || '알 수 없음';
}

function labelStatusHelp(status) {
  return STATUS_COPY[status]?.help || '내부 상태값입니다.';
}

function labelType(type) {
  return TYPE_COPY[type] || type || '기타 제안';
}

function labelField(field) {
  return FIELD_COPY[field] || field || '필드';
}

function labelIssue(code) {
  return ISSUE_COPY[code] || code || '확인 필요';
}

function statusBadgeClass(status) {
  if (status === 'approved' || status === 'published') return 'ok';
  if (status === 'ai_proposed' || status === 'human_reviewing' || status === 'pending_review' || status === 'publishing') return 'warn';
  if (status === 'rejected' || status === 'held' || status === 'publish_failed' || status === 'rolled_back' || status === 'dead_letter' || status === 'needs_rework') return 'err';
  return '';
}

function batchStatusBadgeClass(status) {
  if (status === 'ready') return 'ok';
  if (status === 'partial_only' || status === 'published_with_holds') return 'warn';
  return 'err';
}

function labelBatchStatus(status) {
  return BATCH_STATUS_COPY[status]?.label || status || '상태 없음';
}

function formatBlockerReason(reason) {
  if (!reason) return '보류 사유 없음';
  if (reason.startsWith('pending_review:')) return '검수 미완료';
  if (reason.startsWith('data_quality:')) return '품질/필수값 이슈';
  if (reason.startsWith('keyword:')) return '키워드 미해결';
  if (reason.startsWith('held:')) return '반려/보류';
  if (reason.startsWith('approved:')) return '승인 제안 부족';
  return reason;
}

function issueSeverity(code) {
  if (!code) return 'medium';
  if (code.includes('price') || code.includes('orphan') || code.includes('missing_all')) return 'high';
  if (code.includes('mismatched') || code.includes('confusion')) return 'medium';
  return 'low';
}

function severityRank(severity) {
  return { high: 3, medium: 2, low: 1, none: 0 }[severity] || 0;
}

function severityLabel(severity) {
  return { high: '높음', medium: '중간', low: '낮음', none: '낮음' }[severity] || severity;
}

function confidenceValue(proposal) {
  const value = proposal.provenance?.confidence;
  return typeof value === 'number' ? value : null;
}

function confidenceBucketFor(value) {
  if (value == null) return 'unknown';
  if (value >= 0.85) return 'high';
  if (value >= 0.65) return 'medium';
  return 'low';
}

function confidenceLabel(bucket) {
  return { high: '높은 신뢰도', medium: '보통 신뢰도', low: '낮은 신뢰도', unknown: '신뢰도 없음' }[bucket] || bucket;
}

function confidenceClass(bucket) {
  if (bucket === 'high') return 'ok';
  if (bucket === 'low' || bucket === 'unknown') return 'warn';
  return '';
}

function sourceForProposal(proposal, recordsById) {
  const rawId = proposal.provenance?.raw_record_id;
  return recordsById[rawId]?.source_name || proposal.provenance?.source_field || '출처 미상';
}

function categoryForProposal(proposal) {
  if (proposal.proposal_type === 'category') return pretty(proposal.proposed_value);
  if (proposal.target_field === 'category_id') return pretty(proposal.proposed_value);
  return labelType(proposal.proposal_type);
}

function normalizedKey(value) {
  return pretty(value).toLowerCase().replace(/\s+/g, ' ').trim();
}

function buildDuplicateMap(proposals) {
  const counts = {};
  for (const proposal of proposals) {
    const key = `${proposal.target_field}|${normalizedKey(proposal.proposed_value)}`;
    counts[key] = (counts[key] || 0) + 1;
  }
  return counts;
}

function groupByRecord(proposals) {
  return proposals.reduce((acc, proposal) => {
    const rawId = proposal.provenance?.raw_record_id || '(unlinked)';
    acc[rawId] = acc[rawId] || [];
    acc[rawId].push(proposal);
    return acc;
  }, {});
}

function buildIssueMap(audit) {
  const grouped = {};
  for (const issue of audit?.issues || []) {
    grouped[issue.raw_record_id] = grouped[issue.raw_record_id] || [];
    grouped[issue.raw_record_id].push(issue);
  }
  return grouped;
}

function recordIssuesForProposal(proposal, issuesByRecord) {
  return issuesByRecord[proposal.provenance?.raw_record_id] || [];
}

function proposalSeverity(proposal, issuesByRecord) {
  const issues = recordIssuesForProposal(proposal, issuesByRecord);
  if (!issues.length) return 'none';
  return issues.reduce((highest, issue) => (
    severityRank(issueSeverity(issue.code)) > severityRank(highest) ? issueSeverity(issue.code) : highest
  ), 'low');
}

function whyNeedsReview(proposal, issuesByRecord, duplicateCount) {
  const issues = recordIssuesForProposal(proposal, issuesByRecord);
  const reasons = [];
  const confidence = confidenceValue(proposal);
  if (proposal.status === 'ai_proposed') reasons.push('아직 사람이 확인하지 않은 AI 제안입니다.');
  if (proposal.status === 'human_reviewing') reasons.push('운영자가 확인 대상으로 잡아둔 항목입니다.');
  if (confidence == null) reasons.push('AI 신뢰도 점수가 없어 자동 승인하지 않습니다.');
  else if (confidence < 0.65) reasons.push(`AI 신뢰도가 낮습니다(${Math.round(confidence * 100)}%).`);
  if (issues.length) reasons.push(`감사 이슈: ${issues.map((issue) => labelIssue(issue.code)).join(', ')}`);
  if (duplicateCount > 1) reasons.push(`같은 값 제안이 ${duplicateCount}개 있어 묶어서 확인할 수 있습니다.`);
  if (!reasons.length) reasons.push('문제가 보이지 않는 승인 후보입니다.');
  return reasons.join(' ');
}

function recommendedAction(proposal, issuesByRecord, duplicateCount) {
  const issues = recordIssuesForProposal(proposal, issuesByRecord);
  const hasPriceIssue = issues.some((issue) => issue.code?.includes('price')) || PRICE_FIELDS.has(proposal.target_field);
  const confidence = confidenceValue(proposal);
  if (!REVIEWABLE_STATUSES.has(proposal.status)) return `${labelStatus(proposal.status)} 상태이므로 추가 조치가 필요 없습니다.`;
  if (hasPriceIssue && (proposal.proposed_value == null || proposal.proposed_value === '' || issues.length)) {
    return '가격이 비었거나 원본과 달라요. 원본 가격을 확인한 뒤 보정하거나 반려하세요.';
  }
  if (confidence != null && confidence >= 0.85 && !issues.length) return '같은 조건의 고신뢰 항목은 묶어서 승인해도 안전합니다.';
  if (confidence != null && confidence < 0.65) return '낮은 신뢰도입니다. 보류로 표시하고 원본/근거를 먼저 확인하세요.';
  if (duplicateCount > 1) return '중복 후보입니다. 대표 1개를 열어 값이 같은지 확인한 뒤 묶음 처리하세요.';
  if (issues.length) return '이슈 설명을 먼저 보고, 맞으면 보정 승인·틀리면 반려하세요.';
  return '원본 제목/근거가 자연스러우면 승인하세요.';
}

function buildReviewGroups(proposals, rawRecords, audit) {
  const recordsById = Object.fromEntries(rawRecords.map((record) => [record.raw_record_id, record]));
  const issuesByRecord = buildIssueMap(audit);
  const duplicateMap = buildDuplicateMap(proposals);
  const groups = new Map();

  for (const proposal of proposals) {
    const duplicateKey = `${proposal.target_field}|${normalizedKey(proposal.proposed_value)}`;
    const duplicateCount = duplicateMap[duplicateKey] || 0;
    const severity = proposalSeverity(proposal, issuesByRecord);
    const confidenceBucket = confidenceBucketFor(confidenceValue(proposal));
    const source = sourceForProposal(proposal, recordsById);
    const category = categoryForProposal(proposal);
    const duplicateBucket = duplicateCount > 1 ? '중복 의심' : '단일';
    const key = [severity, confidenceBucket, category, source, duplicateBucket, proposal.status].join('||');

    if (!groups.has(key)) {
      groups.set(key, {
        id: key,
        severity,
        confidenceBucket,
        category,
        source,
        duplicateBucket,
        status: proposal.status,
        proposals: [],
        issueCodes: new Set(),
        duplicateCountMax: duplicateCount,
      });
    }
    const group = groups.get(key);
    group.proposals.push(proposal);
    group.duplicateCountMax = Math.max(group.duplicateCountMax, duplicateCount);
    for (const issue of recordIssuesForProposal(proposal, issuesByRecord)) group.issueCodes.add(issue.code);
  }

  return [...groups.values()].sort((a, b) => (
    severityRank(b.severity) - severityRank(a.severity)
    || a.confidenceBucket.localeCompare(b.confidenceBucket)
    || b.proposals.length - a.proposals.length
  ));
}

function isHighConfidenceSafeGroup(group) {
  return group.confidenceBucket === 'high'
    && group.severity === 'none'
    && group.proposals.every((proposal) => REVIEWABLE_STATUSES.has(proposal.status));
}

function isLowConfidenceGroup(group) {
  return ['low', 'unknown'].includes(group.confidenceBucket)
    && group.proposals.some((proposal) => proposal.status === 'ai_proposed');
}

function isInvalidPriceGroup(group) {
  return [...group.issueCodes].some((code) => code?.includes('price'))
    || group.proposals.some((proposal) => (
      PRICE_FIELDS.has(proposal.target_field)
      && (proposal.proposed_value == null || proposal.proposed_value === '')
    ));
}

function PipelineStatusBar({ rawRecords, items, audit, publishSummary }) {
  const counts = items.reduce((acc, proposal) => {
    acc[proposal.status] = (acc[proposal.status] || 0) + 1;
    return acc;
  }, {});
  const keywordWaiting = items.filter((proposal) => (
    proposal.proposal_type === 'keyword' || proposal.target_field === 'keywords'
  ) && REVIEWABLE_STATUSES.has(proposal.status)).length;
  const stages = [
    { title: '1. 수신됨', count: rawRecords.length, help: '크롤러 원본 상품 수' },
    { title: '2. AI 라벨링', count: items.length, help: 'AI가 만든 전체 제안 수' },
    { title: '3. 키워드 승인 필요', count: keywordWaiting, help: '검색 키워드는 노출 영향이 커서 사람이 봅니다.' },
    { title: '4. 게시 준비', count: counts.approved || 0, help: '승인되어 publish 대기 중' },
    { title: '5. 완료/반려', count: (counts.published || 0) + (counts.rejected || 0), help: '게시되었거나 사용하지 않기로 결정' },
  ];
  return (
    <div className="pipeline-bar" aria-label="AI review pipeline status">
      {stages.map((stage) => (
        <div key={stage.title} className="pipeline-step">
          <div className="pipeline-count">{stage.count}</div>
          <strong>{stage.title}</strong>
          <div className="muted">{stage.help}</div>
        </div>
      ))}
      <div className={`pipeline-step ${audit?.status === 'ok' ? 'pipeline-ok' : 'pipeline-warn'}`}>
        <div className="pipeline-count">{audit?.issue_count ?? '-'}</div>
        <strong>감사 이슈</strong>
        <div className="muted">가격/카테고리/누락 자동 점검</div>
      </div>
      <div className={`pipeline-step ${publishSummary?.batch_status === 'ready' ? 'pipeline-ok' : 'pipeline-warn'}`}>
        <div className="pipeline-count">{publishSummary?.eligible_count ?? 0}/{publishSummary?.raw_count ?? rawRecords.length}</div>
        <strong>배치 게이트: {labelBatchStatus(publishSummary?.batch_status)}</strong>
        <div className="muted">{publishSummary?.quality_verdict || '발행 안전성 요약을 불러오는 중입니다.'}</div>
      </div>
    </div>
  );
}

function WorkflowGuide({ audit, rawCount, proposalCount, visibleGroups, publishSummary }) {
  return (
    <div className="card workflow-card">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <strong>운영자용 검수 방식</strong>
        <span className={`badge ${batchStatusBadgeClass(publishSummary?.batch_status)}`}>{labelBatchStatus(publishSummary?.batch_status)}</span>
      </div>
      <div className="muted">
        원본 {audit?.raw_record_count ?? rawCount}개 · AI 제안 {audit?.proposal_count ?? proposalCount}개 ·
        누락 {audit?.missing_record_count ?? 0}개 · 이슈 {audit?.issue_count ?? 0}개 · 묶음 {visibleGroups}개
      </div>
      {publishSummary && (
        <div className="decision-hint" style={{ marginTop: 8 }}>
          <strong>품질 판정:</strong> {publishSummary.quality_verdict}
          <br />
          원본 {publishSummary.raw_count} · AI 처리 원본 {publishSummary.ai_record_count} ·
          승인/발행 가능 {publishSummary.eligible_count} · 보류/차단 {publishSummary.blocked_count} ·
          미해결 필드 {publishSummary.unresolved_field_proposal_count} · 미해결 키워드 {publishSummary.unresolved_keyword_proposal_count}
        </div>
      )}
      <ol className="workflow-steps">
        <li>먼저 위 파이프라인에서 막힌 단계를 확인합니다.</li>
        <li>배치 게이트가 “부분 발행만 가능”이면 완료가 아닙니다. eligible subset과 남은 보류 사유를 같이 확인하세요.</li>
        <li>아래 묶음 카드에서 “추천 다음 액션”을 따라 대량 처리합니다.</li>
        <li>개별 원본/프롬프트/JSON은 필요할 때만 고급 섹션을 펼칩니다.</li>
      </ol>
    </div>
  );
}

function FirstScreenOperations({ publishSummary, providerSummary, healthCards }) {
  const nextAction = nextOperatorAction(publishSummary || {}, providerSummary || {});
  return (
    <div className="card workflow-card ops-command-center">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <div>
          <strong>오늘 할 일: AI 검수 운영 흐름</strong>
          <div className="muted">개발자 로그 없이 이 순서대로 처리하세요.</div>
        </div>
        <span className={`badge ${batchStatusBadgeClass(publishSummary?.batch_status)}`}>
          {labelBatchStatus(publishSummary?.batch_status)}
        </span>
      </div>
      <div className="next-action" style={{ marginTop: 10 }}>
        <span className="badge warn">다음 액션</span>
        <strong>{nextAction}</strong>
        <span className="muted">DB 최종 반영은 DB-admin 승인 필요</span>
      </div>
      <div className="operator-flow" aria-label="operator workflow">
        {[
          ['1 수신', '원본 상품이 들어왔는지 확인'],
          ['2 AI 라벨', '상품명/가격/카테고리/키워드 제안 확인'],
          ['3 키워드·카테고리', '노출 품질 항목 승인/반려'],
          ['4 행 검수', '보정·보류·반려 사유 기록'],
          ['5 eligible 발행', '안전한 subset만 DB-admin 큐 전송'],
          ['6 DB-admin 승인', '최종 DB 반영은 DB-admin에서 승인'],
        ].map(([title, help]) => (
          <div key={title} className="operator-flow-step">
            <strong>{title}</strong>
            <div className="muted">{help}</div>
          </div>
        ))}
      </div>
      <div className="batch-health-grid" aria-label="batch health counts">
        {healthCards.map((card) => (
          <div key={card.key} className={`batch-health-card ${card.tone ? `health-${card.tone}` : ''}`}>
            <div className="pipeline-count">{card.value}</div>
            <strong>{card.label}</strong>
            <div className="muted">{card.help}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ProviderStatusStrip({ providerSummary, setupError }) {
  if (setupError) {
    return (
      <div className="card workflow-card provider-status-strip">
        <span className="badge err">Provider 상태 불러오기 실패</span>{' '}
        <span className="muted">{setupError}</span>
      </div>
    );
  }
  return (
    <div className="card workflow-card provider-status-strip">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <strong>Provider/모델 상태</strong>
        <span className={`badge ${providerSummary.blocked || providerSummary.modelTrouble ? 'err' : providerSummary.liveReady ? 'ok' : 'warn'}`}>
          {providerSummary.primaryMessage}
        </span>
      </div>
      <div className="muted" style={{ marginTop: 6 }}>
        AI 라벨 실패를 설명할 때 확인: 활성 provider, secret alias, model availability/smoke 상태.
      </div>
      {!!providerSummary.failures?.length && (
        <ul className="compact-list" style={{ marginTop: 8 }}>
          {providerSummary.failures.map((failure) => (
            <li key={`${failure.provider_id}-${failure.reason}`}>
              <span className="badge err">{failure.display_name}</span> {failure.reason}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function PublishControls({ eligibleRows, allRows, publishSummary, reviewerId, loading, onPublish, onRollback }) {
  const count = eligibleRows.length;
  const retryCount = eligibleRows.filter((row) => row.retryable).length;
  const blockedCount = publishSummary?.blocked_count ?? allRows.filter((row) => !row.eligible).length;
  const totalEligible = publishSummary?.eligible_count ?? allRows.filter((row) => row.eligible).length;
  const isSubset = count > 0 && (count < totalEligible || blockedCount > 0);
  const topBlockers = (publishSummary?.blockers || []).slice(0, 4);
  const publishedRows = allRows.filter((row) => row.status === 'published');
  return (
    <div className="card workflow-card">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <strong>DB-admin 큐로 발행</strong>
        <span className={`badge ${batchStatusBadgeClass(publishSummary?.batch_status)}`}>{labelBatchStatus(publishSummary?.batch_status)}</span>
      </div>
      <div className="muted">
        현재 검색/필터에 보이는 원본 중 사람 승인 완료, 키워드 승인 완료, 품질 이슈 없음인 eligible subset만 발행합니다.
        DB-admin 검수/승인 API로 보내므로 최종 DB 검증을 우회하지 않습니다.
      </div>
      <div className="decision-hint" style={{ marginTop: 8 }}>
        <strong>{publishSummary?.quality_verdict || '품질 게이트를 확인 중입니다.'}</strong>
        <br />
        전체 eligible {totalEligible}개 중 현재 필터 eligible {count}개 · 보류/차단 {blockedCount}개 ·
        미해결 필드 {publishSummary?.unresolved_field_proposal_count ?? 0}개 · 미해결 키워드 {publishSummary?.unresolved_keyword_proposal_count ?? 0}개
      </div>
      {!!topBlockers.length && (
        <ul className="compact-list" style={{ marginTop: 8 }}>
          {topBlockers.map((blocker) => (
            <li key={blocker.code}>
              <span className={`badge ${blocker.severity === 'error' ? 'err' : 'warn'}`}>{blocker.count}건</span>{' '}
              {blocker.message}
            </li>
          ))}
        </ul>
      )}
      {!!publishSummary?.held_rows?.length && (
        <details className="inline-details" style={{ marginTop: 8 }} open={publishSummary.batch_status !== 'ready'}>
          <summary>남은 보류 원본/사유 {publishSummary.held_rows.length}개 미리보기</summary>
          <ul className="compact-list">
            {publishSummary.held_rows.map((row) => (
              <li key={row.raw_record_id}>
                <code>{row.raw_record_id}</code> {row.raw_title || ''} ·{' '}
                {(row.blockers || []).slice(0, 3).map(formatBlockerReason).join(', ') || labelStatus(row.status)}
              </li>
            ))}
          </ul>
        </details>
      )}
      {!!publishedRows.length && (
        <details className="inline-details" style={{ marginTop: 8 }} open>
          <summary>DB-admin 전송 완료/롤백 가능 원본 {publishedRows.length}개</summary>
          <ul className="compact-list">
            {publishedRows.map((row) => (
              <li key={row.raw_record_id}>
                <code>{row.raw_record_id}</code> {row.raw_title || row.item?.name || ''} ·
                ingestion <strong>{row.db_ingestion_id || '-'}</strong> ·
                result <code>{row.db_ingestion_result?.status || row.db_ingestion_result?.message || '-'}</code>{' '}
                <button
                  className="danger-outline"
                  disabled={loading || !reviewerId.trim()}
                  onClick={() => onRollback(row)}
                >
                  롤백 요청
                </button>
              </li>
            ))}
          </ul>
          <div className="muted">주의: DB-admin 최종 승인은 별도입니다. 롤백 요청 후 DB-admin pending ingestion을 승인하지 마세요.</div>
        </details>
      )}
      <div className="row" style={{ gap: 8, marginTop: 8 }}>
        <button
          className="primary-button"
          disabled={loading || !count || !reviewerId.trim()}
          onClick={() => onPublish(eligibleRows)}
        >
          {isSubset ? '필터된 eligible subset' : 'eligible'} {count}개 발행{retryCount ? ` (재시도 ${retryCount})` : ''}
        </button>
        {!reviewerId.trim() && <span className="muted">검수자 ID 입력 후 발행 가능</span>}
        {isSubset && <span className="badge warn">부분 발행: 남은 항목은 계속 보류/미해결</span>}
      </div>
    </div>
  );
}

function AutomationGateControls({ reviewerId, loading, onRefresh, onError }) {
  const [ruleId, setRuleId] = useState('exact_catalog_keyword');
  const [confidence, setConfidence] = useState('0.90');
  const [successCount, setSuccessCount] = useState('2');
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const summary = summarizeAutomationPreview(preview || {});
  const config = (enabled) => ({
    enabled,
    selected_rule_ids: [ruleId],
    reviewer_id: reviewerId.trim() || 'automation:review-gates',
    default_min_confidence: Number(confidence) || 0.9,
    learned_alias_min_confidence: Number(confidence) || 0.92,
    learned_alias_min_success_count: Number(successCount) || 2,
  });

  async function previewAutomation() {
    setBusy(true);
    try {
      const result = await requestJson('/api/review/automation-gates/preview', {
        method: 'POST',
        body: { config: config(false) },
      });
      setPreview(result);
      onError(null);
    } catch (err) {
      onError(`자동화 미리보기: ${err.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function applyAutomation() {
    const currentPreview = preview || await requestJson('/api/review/automation-gates/preview', {
      method: 'POST',
      body: { config: config(false) },
    });
    if (!currentPreview.eligible_count) {
      setPreview(currentPreview);
      onError('자동화 적용: 안전 게이트를 통과한 항목이 없습니다.');
      return;
    }
    if (!window.confirm(buildAutomationApplyMessage(currentPreview, ruleId))) return;
    setBusy(true);
    try {
      const result = await requestJson('/api/review/automation-gates/apply', {
        method: 'POST',
        body: { config: config(true) },
      });
      setPreview(result);
      onError(`자동화 승인 완료: ${result.applied_count}개. DB-admin 발행은 하지 않았습니다.`);
      await onRefresh();
    } catch (err) {
      onError(`자동화 적용: ${err.message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card workflow-card">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <div>
          <strong>안전 자동화 게이트</strong>
          <div className="muted">기본은 꺼져 있습니다. 미리보기 후 선택한 안전 규칙만 승인합니다.</div>
        </div>
        <span className={`badge ${summary.tone}`}>{summary.primaryMessage}</span>
      </div>
      <div className="decision-hint" style={{ marginTop: 8 }}>
        자동화는 제안 승인/audit trail만 남깁니다. DB-admin 큐 발행은 아래 발행 버튼으로 운영자가 명시 실행해야 합니다.
      </div>
      <div className="form-grid compact-grid" style={{ marginTop: 8 }}>
        <label>
          안전 규칙
          <select value={ruleId} onChange={(e) => setRuleId(e.target.value)}>
            <option value="exact_catalog_keyword">기존 DB 키워드 정확 매칭</option>
            <option value="learned_alias">학습된 별칭/동의어</option>
            <option value="exact_category">원본/기대 카테고리 정확 일치</option>
          </select>
        </label>
        <label>
          최소 신뢰도
          <input value={confidence} onChange={(e) => setConfidence(e.target.value)} placeholder="0.90" />
        </label>
        <label>
          학습 별칭 최소 성공 횟수
          <input value={successCount} onChange={(e) => setSuccessCount(e.target.value)} placeholder="2" />
        </label>
      </div>
      <div className="row" style={{ gap: 8, marginTop: 8 }}>
        <button disabled={loading || busy} onClick={previewAutomation}>드라이런 미리보기</button>
        <button className="primary-button" disabled={loading || busy || !reviewerId.trim() || !summary.eligible} onClick={applyAutomation}>
          선택 게이트 {summary.eligible}개 승인
        </button>
        {!reviewerId.trim() && <span className="muted">검수자 ID 입력 후 적용 가능</span>}
      </div>
      {preview && (
        <details className="inline-details" style={{ marginTop: 8 }} open>
          <summary>왜 eligible/blocked 인가요? 후보 {summary.candidate}개</summary>
          <ul className="compact-list">
            {(preview.eligible_items || []).slice(0, 8).map((row) => (
              <li key={row.proposal_id}><span className="badge ok">eligible</span> {explainAutomationRow(row)}</li>
            ))}
            {(preview.blocked_items || []).slice(0, 8).map((row) => (
              <li key={row.proposal_id}><span className="badge warn">blocked</span> {explainAutomationRow(row)}</li>
            ))}
          </ul>
          <details className="inline-details" style={{ marginTop: 8 }}>
            <summary>고급: 자동화 규칙/threshold JSON</summary>
            <pre className="json-block">{JSON.stringify(preview.rules || [], null, 2)}</pre>
          </details>
        </details>
      )}
    </div>
  );
}

function BulkGroupActions({ group, reviewerId, setReviewerId, onRefresh, onError }) {
  const [busy, setBusy] = useState(false);
  const reviewable = group.proposals.filter((proposal) => REVIEWABLE_STATUSES.has(proposal.status));
  const aiProposed = group.proposals.filter((proposal) => proposal.status === 'ai_proposed');

  async function runBulk(label, proposals, callback, { confirmText } = {}) {
    if (!reviewerId.trim()) {
      onError(`${label}: 검수자 ID를 입력하세요.`);
      return;
    }
    if (!proposals.length) {
      onError(`${label}: 처리할 항목이 없습니다.`);
      return;
    }
    const preview = buildBulkPreview(proposals).map((line) => `  · ${line}`).join('\n');
    const message = confirmText || `${label} ${proposals.length}개를 처리합니다.\n${preview}${proposals.length > 5 ? '\n  · ...' : ''}\n계속할까요?`;
    if (!window.confirm(message)) return;
    setBusy(true);
    try {
      for (const proposal of proposals) {
        await callback(proposal);
      }
      onError(null);
      await onRefresh();
    } catch (err) {
      onError(`${label}: ${err.message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="bulk-actions">
      <label className="muted reviewer-inline">
        검수자 ID
        <input value={reviewerId} onChange={(e) => setReviewerId(e.target.value)} placeholder="admin" />
      </label>
      <div className="row" style={{ gap: 6 }}>
        {isHighConfidenceSafeGroup(group) && (
          <button
            className="primary-button"
            disabled={busy}
            onClick={() => runBulk('고신뢰 묶음 승인', reviewable, (proposal) => requestJson(`/api/review/proposals/${encodeURIComponent(proposal.proposal_id)}/approve`, {
              method: 'POST',
              body: { reviewer_id: reviewerId.trim() },
            }), {
              confirmText: `고신뢰·이슈 없음 조건의 ${reviewable.length}개만 승인합니다.\n${buildBulkPreview(reviewable).map((line) => `  · ${line}`).join('\n')}\n같은 묶음 값을 확인했나요?`,
            })}
          >
            고신뢰 {reviewable.length}개 승인
          </button>
        )}
        {isLowConfidenceGroup(group) && (
          <button
            disabled={busy}
            onClick={() => runBulk('낮은 신뢰도 보류', aiProposed, (proposal) => requestJson(`/api/review/proposals/${encodeURIComponent(proposal.proposal_id)}/start`, { method: 'POST' }), {
              confirmText: `낮은 신뢰도 ${aiProposed.length}개를 "사람 확인 중"으로 보류 표시합니다.\n${buildBulkPreview(aiProposed).map((line) => `  · ${line}`).join('\n')}\n이후 행별 보정/반려 사유를 남겨야 합니다.`,
            })}
          >
            낮은 신뢰도 {aiProposed.length}개 보류 표시
          </button>
        )}
        {isInvalidPriceGroup(group) && (
          <button
            className="danger-outline"
            disabled={busy}
            onClick={() => runBulk('가격 오류 묶음 반려', reviewable, (proposal) => requestJson(`/api/review/proposals/${encodeURIComponent(proposal.proposal_id)}/reject`, {
              method: 'POST',
              body: { reviewer_id: reviewerId.trim(), reason: '가격 누락 또는 원본 가격과 불일치' },
            }), {
              confirmText: `${reviewable.length}개 제안을 반려합니다. 가격 누락/불일치가 맞나요?`,
            })}
          >
            가격 오류 {reviewable.length}개 반려
          </button>
        )}
        {!isHighConfidenceSafeGroup(group) && !isLowConfidenceGroup(group) && !isInvalidPriceGroup(group) && (
          <span className="muted">이 묶음은 자동 대량 처리보다 대표 항목 확인을 권장합니다.</span>
        )}
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

  async function run(label, callback, { confirmText } = {}) {
    if (confirmText && !window.confirm(confirmText)) return;
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
    }), { confirmText: '이 제안을 반려합니다. 계속할까요?' });
  }

  async function remove() {
    await run('삭제', () => requestJson(`/api/review/proposals/${encodeURIComponent(proposal.proposal_id)}`, { method: 'DELETE' }), {
      confirmText: `${proposal.proposal_id} 제안을 삭제할까요? 삭제는 복구하기 어렵습니다.`,
    });
  }

  const reviewable = REVIEWABLE_STATUSES.has(proposal.status);
  const deletable = ['ai_proposed', 'human_reviewing', 'rejected'].includes(proposal.status);

  return (
    <div className="proposal-actions">
      <div className="row" style={{ gap: 6 }}>
        {proposal.status === 'ai_proposed' && (
          <button disabled={busy} onClick={() => run('검수 시작', () => requestJson(`/api/review/proposals/${encodeURIComponent(proposal.proposal_id)}/start`, { method: 'POST' }))}>
            보류/확인 중으로 표시
          </button>
        )}
        {reviewable && <button className="primary-button" disabled={busy} onClick={approve}>문제 없음: 승인</button>}
      </div>
      {reviewable && (
        <div className="form-grid compact-grid" style={{ marginTop: 8 }}>
          <label>
            검수자 ID
            <input value={reviewerId} onChange={(e) => setReviewerId(e.target.value)} placeholder="admin" />
          </label>
        </div>
      )}
      {reviewable && (
        <details className="inline-details" style={{ marginTop: 8 }}>
          <summary>문제가 있나요? 보정/반려/직접수정 열기</summary>
          <div className="form-grid compact-grid" style={{ marginTop: 8 }}>
            <label>
              보정 값(JSON 또는 문자열)
              <input value={correctedText} onChange={(e) => setCorrectedText(e.target.value)} />
            </label>
            <label>
              반려/보정 사유
              <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="왜 결정했는지" />
            </label>
          </div>
          <div className="row" style={{ gap: 6, marginTop: 8 }}>
            <button disabled={busy} onClick={correct}>보정 승인</button>
            <button disabled={busy} onClick={reject}>반려</button>
            <button disabled={busy} onClick={() => setEditOpen((open) => !open)}>제안 값 직접 수정</button>
            {deletable && <button className="danger-outline" disabled={busy} onClick={remove}>삭제</button>}
          </div>
        </details>
      )}
      {!reviewable && deletable && (
        <details className="inline-details" style={{ marginTop: 8 }}>
          <summary>고급: 삭제 열기</summary>
          <button className="danger-outline" style={{ marginTop: 8 }} disabled={busy} onClick={remove}>삭제</button>
        </details>
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

function ProposalCard({ proposal, reviewerId, setReviewerId, onRefresh, onError, issuesByRecord, duplicateMap, publishRow, onPublishRows, onRollback }) {
  const duplicateKey = `${proposal.target_field}|${normalizedKey(proposal.proposed_value)}`;
  const duplicateCount = duplicateMap[duplicateKey] || 0;
  const reasons = whyNeedsReview(proposal, issuesByRecord, duplicateCount);
  const nextAction = recommendedAction(proposal, issuesByRecord, duplicateCount);
  const confidence = confidenceValue(proposal);
  const issues = recordIssuesForProposal(proposal, issuesByRecord);
  const publishAction = publishRowAction(publishRow || {});

  return (
    <li className="proposal-card">
      <div className="proposal-main">
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <span>
            <code>{proposal.proposal_id}</code>{' '}
            <span className={`badge ${statusBadgeClass(proposal.status)}`}>{labelStatus(proposal.status)}</span>{' '}
            <span className="badge">{labelType(proposal.proposal_type)}</span>
          </span>
          <span className="muted">원본: {proposal.provenance?.raw_record_id || '-'}</span>
        </div>
        {publishRow && (
          <div className="row" style={{ gap: 6, marginTop: 6 }}>
            <span className={`badge ${statusBadgeClass(publishRow.status)}`}>DB 발행: {labelStatus(publishRow.status)}</span>
            {publishRow.db_ingestion_id && <span className="badge">ingestion #{publishRow.db_ingestion_id}</span>}
            {publishRow.db_ingestion_result && <span className="badge">result {publishRow.db_ingestion_result.status || publishRow.db_ingestion_result.message || '-'}</span>}
            {publishRow.last_error && <span className="badge err">{publishRow.last_error}</span>}
            {publishAction.kind === 'rollback' && (
              <button
                className="danger-outline"
                disabled={!reviewerId.trim()}
                onClick={() => onRollback(publishRow)}
              >
                {publishAction.label}
              </button>
            )}
            {['publish', 'retry'].includes(publishAction.kind) && (
              <button
                className="secondary-button"
                disabled={!reviewerId.trim()}
                onClick={() => onPublishRows([publishRow])}
              >
                {publishAction.label}
              </button>
            )}
          </div>
        )}
        <div style={{ marginTop: 6 }}>
          <b>{labelField(proposal.target_field)}</b> = <code>{pretty(proposal.proposed_value)}</code>
        </div>
        <div className="decision-hint">
          <strong>왜 검수하나요?</strong> {reasons}
          <br />
          <strong>추천:</strong> {nextAction}
        </div>
        {!!issues.length && (
          <div className="issue-chip-row">
            {issues.slice(0, 4).map((issue, index) => (
              <span key={`${issue.code}-${index}`} className="badge warn">{labelIssue(issue.code)}</span>
            ))}
          </div>
        )}
        <details className="inline-details" style={{ marginTop: 6 }}>
          <summary>고급: AI 근거/모델/대안 보기</summary>
          <div className="muted" style={{ marginTop: 4 }}>
            역할 {proposal.provenance?.worker_role || '-'} · 신뢰도 {confidence == null ? '없음' : `${Math.round(confidence * 100)}%`} · 모델 {proposal.provenance?.provider?.model_name || '-'}
          </div>
          {proposal.provenance?.evidence_text && (
            <div className="muted" style={{ marginTop: 4 }}>근거: {proposal.provenance.evidence_text}</div>
          )}
          {!!proposal.alternatives?.length && (
            <div className="muted" style={{ marginTop: 4 }}>대안: {proposal.alternatives.map(pretty).join(', ')}</div>
          )}
        </details>
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

function KeywordProposalPanel({ proposals, reviewerId, setReviewerId, onRefresh, onError }) {
  const [edits, setEdits] = useState({});
  const [busyId, setBusyId] = useState('');

  function editFor(proposal) {
    return edits[proposal.proposal_id] || {
      word: proposal.proposed_keyword || '',
      terms: JSON.stringify(proposal.match_terms || []),
      category: proposal.category_suggestion || '',
      reason: '',
    };
  }

  function setEdit(proposal, patch) {
    setEdits((current) => ({
      ...current,
      [proposal.proposal_id]: { ...editFor(proposal), ...patch },
    }));
  }

  async function run(proposal, label, callback) {
    setBusyId(proposal.proposal_id);
    try {
      await callback();
      onError(null);
      await onRefresh();
    } catch (err) {
      onError(`${label}: ${err.message}`);
    } finally {
      setBusyId('');
    }
  }

  async function approve(proposal) {
    if (!reviewerId.trim()) return onError('키워드 승인: 검수자 ID를 입력하세요.');
    const edit = editFor(proposal);
    let terms;
    try {
      terms = JSON.parse(edit.terms || '[]');
      if (!Array.isArray(terms)) throw new Error('match terms must be an array');
    } catch (err) {
      onError(`키워드 승인: match terms JSON 오류 (${err.message})`);
      return;
    }
    await run(proposal, '키워드 승인', () => requestJson(`/api/review/keyword-proposals/${encodeURIComponent(proposal.proposal_id)}/approve`, {
      method: 'POST',
      body: {
        reviewer_id: reviewerId.trim(),
        proposed_keyword: edit.word.trim(),
        match_terms: terms,
        category_suggestion: edit.category.trim() || null,
      },
    }));
  }

  async function reject(proposal) {
    if (!reviewerId.trim()) return onError('키워드 반려: 검수자 ID를 입력하세요.');
    const edit = editFor(proposal);
    if (!edit.reason.trim()) return onError('키워드 반려: 사유를 입력하세요.');
    await run(proposal, '키워드 반려', () => requestJson(`/api/review/keyword-proposals/${encodeURIComponent(proposal.proposal_id)}/reject`, {
      method: 'POST',
      body: { reviewer_id: reviewerId.trim(), reason: edit.reason.trim() },
    }));
  }

  const pending = proposals.filter((proposal) => ['ai_proposed', 'human_reviewing', 'rejected'].includes(proposal.status));

  return (
    <div className="card workflow-card">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <strong>DB 키워드 승인 대기</strong>
        <span className={`badge ${pending.length ? 'warn' : 'ok'}`}>{pending.length}개 상품 발행 차단</span>
      </div>
      <div className="muted" style={{ marginTop: 6 }}>
        AI가 기존 키워드로 매칭하지 못한 경우만 표시합니다. 승인 전에는 해당 원본 상품이 DB-admin 발행 대상에서 제외됩니다.
      </div>
      {proposals.length === 0 && <div className="muted" style={{ marginTop: 8 }}>새 키워드 제안이 없습니다.</div>}
      <ul className="items proposal-list" style={{ marginTop: 8 }}>
        {proposals.map((proposal) => {
          const edit = editFor(proposal);
          const reviewable = ['ai_proposed', 'human_reviewing', 'rejected'].includes(proposal.status);
          return (
            <li key={proposal.proposal_id} className="proposal-card">
              <div className="proposal-main">
                <div className="row" style={{ justifyContent: 'space-between' }}>
                  <span>
                    <code>{proposal.proposal_id}</code>{' '}
                    <span className={`badge ${statusBadgeClass(proposal.status)}`}>{labelStatus(proposal.status)}</span>
                  </span>
                  <span className="muted">confidence {proposal.confidence ?? '-'}</span>
                </div>
                <div style={{ marginTop: 6 }}>
                  keyword <code>{proposal.proposed_keyword}</code> · terms {(proposal.match_terms || []).join(', ') || '-'} · category {proposal.category_suggestion || '-'}
                </div>
                <details className="inline-details" style={{ marginTop: 6 }}>
                  <summary>트리거 상품 전체 필드 보기 ({proposal.triggering_records?.length || 0})</summary>
                  <pre className="json-block">{JSON.stringify(proposal.triggering_records || [], null, 2)}</pre>
                </details>
                {reviewable && (
                  <div className="form-grid compact-grid" style={{ marginTop: 8 }}>
                    <label>
                      검수자 ID
                      <input value={reviewerId} onChange={(e) => setReviewerId(e.target.value)} placeholder="admin" />
                    </label>
                    <label>
                      canonical keyword
                      <input value={edit.word} onChange={(e) => setEdit(proposal, { word: e.target.value })} />
                    </label>
                    <label>
                      match terms JSON
                      <input value={edit.terms} onChange={(e) => setEdit(proposal, { terms: e.target.value })} />
                    </label>
                    <label>
                      category
                      <input value={edit.category} onChange={(e) => setEdit(proposal, { category: e.target.value })} />
                    </label>
                    <label>
                      reject reason
                      <input value={edit.reason} onChange={(e) => setEdit(proposal, { reason: e.target.value })} />
                    </label>
                    <div className="row" style={{ gap: 6 }}>
                      <button className="primary-button" disabled={busyId === proposal.proposal_id || !edit.word.trim()} onClick={() => approve(proposal)}>승인/DB 저장</button>
                      <button disabled={busyId === proposal.proposal_id} onClick={() => reject(proposal)}>반려(상품 보류)</button>
                    </div>
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function GroupCard({ group, rawRecordsById, issuesByRecord, duplicateMap, publishRowsByRawId, onPublishRows, onRollback, reviewerId, setReviewerId, onRefresh, onError }) {
  const [open, setOpen] = useState(false);
  const sample = group.proposals[0];
  const sampleDuplicateKey = `${sample.target_field}|${normalizedKey(sample.proposed_value)}`;
  const sampleDuplicateCount = duplicateMap[sampleDuplicateKey] || 0;
  const groupIssues = [...group.issueCodes].filter(Boolean);
  const nextAction = recommendedAction(sample, issuesByRecord, group.duplicateCountMax);
  const reason = whyNeedsReview(sample, issuesByRecord, sampleDuplicateCount);

  return (
    <div className="review-group-card">
      <div className="row group-header">
        <div>
          <div className="row" style={{ gap: 6 }}>
            <span className={`badge ${group.severity === 'high' ? 'err' : group.severity === 'medium' ? 'warn' : 'ok'}`}>위험도 {severityLabel(group.severity)}</span>
            <span className={`badge ${confidenceClass(group.confidenceBucket)}`}>{confidenceLabel(group.confidenceBucket)}</span>
            <span className="badge">{group.duplicateBucket}</span>
            <span className={`badge ${statusBadgeClass(group.status)}`}>{labelStatus(group.status)}</span>
          </div>
          <h3>{group.source} · {group.category}</h3>
          <div className="muted">{group.proposals.length}개 제안 · 최대 중복 {group.duplicateCountMax || 1}개 · {labelStatusHelp(group.status)}</div>
        </div>
        <button className="secondary-button" type="button" onClick={() => setOpen((value) => !value)}>
          {open ? '대표 항목 접기' : '대표 항목 보기'}
        </button>
      </div>

      <div className="decision-hint">
        <strong>왜 이 묶음인가요?</strong> {reason}
        <br />
        <strong>추천 다음 액션:</strong> {nextAction}
      </div>

      {!!groupIssues.length && (
        <div className="issue-chip-row">
          {groupIssues.slice(0, 6).map((code) => <span key={code} className="badge warn">{labelIssue(code)}</span>)}
          {groupIssues.length > 6 && <span className="badge">+{groupIssues.length - 6}</span>}
        </div>
      )}

      <BulkGroupActions
        group={group}
        reviewerId={reviewerId}
        setReviewerId={setReviewerId}
        onRefresh={onRefresh}
        onError={onError}
      />

      {open && (
        <details className="inline-details group-items" open>
          <summary>대표/전체 항목과 원본 보기</summary>
          <ul className="items proposal-list" style={{ marginTop: 8 }}>
            {group.proposals.slice(0, 25).map((proposal) => {
              const record = rawRecordsById[proposal.provenance?.raw_record_id];
              return (
                <ProposalCard
                  key={proposal.proposal_id}
                  proposal={proposal}
                  reviewerId={reviewerId}
                  setReviewerId={setReviewerId}
                  onRefresh={onRefresh}
                  onError={onError}
                  issuesByRecord={issuesByRecord}
                  duplicateMap={duplicateMap}
                  publishRow={publishRowsByRawId[proposal.provenance?.raw_record_id]}
                  onPublishRows={onPublishRows}
                  onRollback={onRollback}
                  record={record}
                />
              );
            })}
          </ul>
          {group.proposals.length > 25 && <div className="muted">처음 25개만 표시합니다. 검색/필터로 좁혀서 더 확인하세요.</div>}
          <details className="inline-details" style={{ marginTop: 8 }}>
            <summary>고급: 이 묶음 원본 JSON 보기</summary>
            <pre className="json-block">{JSON.stringify(group.proposals.map((proposal) => ({
              proposal,
              raw_record: rawRecordsById[proposal.provenance?.raw_record_id] || null,
              issues: recordIssuesForProposal(proposal, issuesByRecord),
            })), null, 2)}</pre>
          </details>
        </details>
      )}
    </div>
  );
}

export default function ReviewQueuePanel() {
  const [items, setItems] = useState([]);
  const [keywordProposals, setKeywordProposals] = useState([]);
  const [rawRecords, setRawRecords] = useState([]);
  const [publishRows, setPublishRows] = useState([]);
  const [publishSummary, setPublishSummary] = useState(null);
  const [providerSetup, setProviderSetup] = useState([]);
  const [providerSetupError, setProviderSetupError] = useState(null);
  const [audit, setAudit] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState('');
  const [sourceFilter, setSourceFilter] = useState('');
  const [confidenceFilter, setConfidenceFilter] = useState('');
  const [issueFilter, setIssueFilter] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');
  const [search, setSearch] = useState('');
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
      const [proposals, keywordProposalResponse, records, auditReport, publishEligibility, setupResult] = await Promise.all([
        requestJson('/api/review/proposals'),
        requestJson('/api/review/keyword-proposals'),
        requestJson('/api/review/raw-records?include_proposals=true'),
        requestJson('/api/review/audit'),
        requestJson('/api/review/publish-eligibility'),
        requestJson('/api/providers/setup-state')
          .then((body) => ({ ok: true, body }))
          .catch((err) => ({ ok: false, error: err })),
      ]);
      setItems(proposals.items || []);
      setKeywordProposals(keywordProposalResponse.items || []);
      setRawRecords(records.items || []);
      setPublishRows(publishEligibility.items || []);
      setPublishSummary(publishEligibility.summary || null);
      if (setupResult.ok) {
        setProviderSetup(setupResult.body.providers || []);
        setProviderSetupError(null);
      } else {
        setProviderSetup([]);
        setProviderSetupError(setupResult.error.message);
      }
      setAudit(auditReport);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const rawRecordsById = useMemo(() => Object.fromEntries(rawRecords.map((record) => [record.raw_record_id, record])), [rawRecords]);
  const publishRowsByRawId = useMemo(() => Object.fromEntries(publishRows.map((row) => [row.raw_record_id, row])), [publishRows]);
  const issuesByRecord = useMemo(() => buildIssueMap(audit), [audit]);
  const duplicateMap = useMemo(() => buildDuplicateMap(items), [items]);
  const allGroups = useMemo(() => buildReviewGroups(items, rawRecords, audit), [items, rawRecords, audit]);
  const statusCounts = useMemo(() => items.reduce((acc, proposal) => {
    acc[proposal.status] = (acc[proposal.status] || 0) + 1;
    return acc;
  }, {}), [items]);
  const sources = useMemo(() => [...new Set(allGroups.map((group) => group.source))].sort(), [allGroups]);
  const categories = useMemo(() => [...new Set(allGroups.map((group) => group.category))].sort(), [allGroups]);
  const issueCodes = useMemo(() => [...new Set((audit?.issues || []).map((issue) => issue.code))].sort(), [audit]);
  const providerSummary = useMemo(() => summarizeProviderSetup(providerSetup), [providerSetup]);
  const healthCards = useMemo(() => (
    buildBatchHealth(publishSummary || {}, rawRecords, items, keywordProposals)
  ), [publishSummary, rawRecords, items, keywordProposals]);

  const filteredGroups = useMemo(() => {
    const term = search.trim().toLowerCase();
    return allGroups.filter((group) => {
      if (statusFilter && group.status !== statusFilter) return false;
      if (sourceFilter && group.source !== sourceFilter) return false;
      if (confidenceFilter && group.confidenceBucket !== confidenceFilter) return false;
      if (issueFilter && !group.issueCodes.has(issueFilter)) return false;
      if (categoryFilter && group.category !== categoryFilter) return false;
      if (!term) return true;
      const text = [
        group.source,
        group.category,
        group.status,
        group.confidenceBucket,
        group.severity,
        ...[...group.issueCodes].map(labelIssue),
        ...group.proposals.flatMap((proposal) => [
          proposal.proposal_id,
          proposal.target_field,
          labelField(proposal.target_field),
          pretty(proposal.proposed_value),
          proposal.provenance?.raw_record_id,
          rawRecordsById[proposal.provenance?.raw_record_id]?.raw_title,
        ]),
      ].join(' ').toLowerCase();
      return text.includes(term);
    });
  }, [allGroups, statusFilter, sourceFilter, confidenceFilter, issueFilter, categoryFilter, search, rawRecordsById]);

  const visibleRawIds = useMemo(() => new Set(filteredGroups.flatMap((group) => (
    group.proposals.map((proposal) => proposal.provenance?.raw_record_id).filter(Boolean)
  ))), [filteredGroups]);
  const visibleEligiblePublishRows = useMemo(() => publishRows.filter((row) => (
    row.eligible && visibleRawIds.has(row.raw_record_id)
  )), [publishRows, visibleRawIds]);

  const publishRowsToDb = useCallback(async (rows) => {
    if (!reviewerId.trim()) {
      setError('발행: 검수자 ID를 입력하세요.');
      return;
    }
    if (!rows.length) {
      setError('발행: eligible 항목이 없습니다.');
      return;
    }
    const retryCount = rows.filter((row) => row.retryable).length;
    const blockedCount = publishSummary?.blocked_count ?? publishRows.filter((row) => !row.eligible).length;
    const totalEligible = publishSummary?.eligible_count ?? publishRows.filter((row) => row.eligible).length;
    const subsetWarning = (blockedCount > 0 || rows.length < totalEligible)
      ? [
        '',
        '⚠️ 부분 발행 확인:',
        `- 배치 상태: ${labelBatchStatus(publishSummary?.batch_status)}`,
        `- 전체 eligible ${totalEligible}개 중 선택 ${rows.length}개만 발행`,
        `- 보류/차단 ${blockedCount}개, 미해결 필드 ${publishSummary?.unresolved_field_proposal_count ?? 0}개, 미해결 키워드 ${publishSummary?.unresolved_keyword_proposal_count ?? 0}개는 남습니다.`,
        `- 판정: ${publishSummary?.quality_verdict || '배치 완료로 표시하면 안 됩니다.'}`,
      ].join('\n')
      : '';
    const heldPreview = (publishSummary?.held_rows || []).slice(0, 5).map((row) => (
      `  · ${row.raw_record_id}: ${(row.blockers || []).slice(0, 2).map(formatBlockerReason).join(', ') || labelStatus(row.status)}`
    )).join('\n');
    const message = `${buildPublishConfirmationMessage(rows, publishSummary || {})}${retryCount ? `\n재시도 ${retryCount}개 포함.` : ''}${subsetWarning}${heldPreview ? `\n남는 보류 예시:\n${heldPreview}` : ''}`;
    if (!window.confirm(message)) return;
    setLoading(true);
    try {
      const result = await requestJson('/api/review/publish-approved', {
        method: 'POST',
        body: {
          raw_record_ids: rows.map((row) => row.raw_record_id),
          reviewer_id: reviewerId.trim(),
          confirm_count: rows.length,
        },
      });
      setError(`발행 완료: 성공 ${result.published}, 실패 ${result.failed}`);
      await refresh();
    } catch (err) {
      setError(`발행: ${err.message}`);
    } finally {
      setLoading(false);
    }
  }, [reviewerId, refresh, publishRows, publishSummary]);

  const rollbackPublishRow = useCallback(async (row) => {
    if (!reviewerId.trim()) {
      setError('롤백: 검수자 ID를 입력하세요.');
      return;
    }
    if (!window.confirm(buildRollbackConfirmationMessage(row))) return;
    setLoading(true);
    try {
      const result = await requestJson(`/api/review/publish-records/${encodeURIComponent(row.raw_record_id)}/rollback`, {
        method: 'POST',
        body: {
          reviewer_id: reviewerId.trim(),
          reason: `AI-admin operator rollback before DB-admin final approval for ingestion ${row.db_ingestion_id || '-'}`,
        },
      });
      setError(`롤백 요청 완료: ${result.raw_record_id} · ingestion ${result.db_ingestion_id || '-'}`);
      await refresh();
    } catch (err) {
      setError(`롤백: ${err.message}`);
    } finally {
      setLoading(false);
    }
  }, [reviewerId, refresh]);

  return (
    <section id="review" className="panel review-panel anchor-offset">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <h2>AI 검수 대시보드 <span className="muted">({items.length}개 제안 / {keywordProposals.length}개 키워드 제안 / {rawRecords.length}개 원본)</span></h2>
        <button className="secondary-button" onClick={refresh} disabled={loading}>{loading ? '불러오는 중...' : '새로고침'}</button>
      </div>
      {error && <div className="badge err" style={{ marginBottom: 10 }}>오류: {error}</div>}

      <FirstScreenOperations
        publishSummary={publishSummary}
        providerSummary={providerSummary}
        healthCards={healthCards}
      />
      <ProviderStatusStrip providerSummary={providerSummary} setupError={providerSetupError} />
      <PipelineStatusBar rawRecords={rawRecords} items={items} audit={audit} publishSummary={publishSummary} />
      <WorkflowGuide audit={audit} rawCount={rawRecords.length} proposalCount={items.length} visibleGroups={filteredGroups.length} publishSummary={publishSummary} />
      <PublishControls
        eligibleRows={visibleEligiblePublishRows}
        allRows={publishRows}
        publishSummary={publishSummary}
        reviewerId={reviewerId}
        loading={loading}
        onPublish={publishRowsToDb}
        onRollback={rollbackPublishRow}
      />
      <AutomationGateControls
        reviewerId={reviewerId}
        loading={loading}
        onRefresh={refresh}
        onError={setError}
      />
      <KeywordProposalPanel
        proposals={keywordProposals}
        reviewerId={reviewerId}
        setReviewerId={setReviewerId}
        onRefresh={refresh}
        onError={setError}
      />

      <details className="inline-details" style={{ margin: '12px 0' }} open>
        <summary>검색/필터: 출처 · 카테고리 · 이슈 · 신뢰도</summary>
        <div className="filter-grid" style={{ marginTop: 8 }}>
          <label>
            상태
            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="">전체</option>
              {STATUS_OPTIONS.map((status) => (
                <option key={status} value={status}>{labelStatus(status)} ({statusCounts[status] || 0})</option>
              ))}
            </select>
          </label>
          <label>
            출처
            <select value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)}>
              <option value="">전체</option>
              {sources.map((source) => <option key={source} value={source}>{source}</option>)}
            </select>
          </label>
          <label>
            카테고리/제안 종류
            <select value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)}>
              <option value="">전체</option>
              {categories.map((category) => <option key={category} value={category}>{category}</option>)}
            </select>
          </label>
          <label>
            이슈
            <select value={issueFilter} onChange={(e) => setIssueFilter(e.target.value)}>
              <option value="">전체</option>
              {issueCodes.map((code) => <option key={code} value={code}>{labelIssue(code)}</option>)}
            </select>
          </label>
          <label>
            신뢰도
            <select value={confidenceFilter} onChange={(e) => setConfidenceFilter(e.target.value)}>
              <option value="">전체</option>
              <option value="high">높은 신뢰도</option>
              <option value="medium">보통 신뢰도</option>
              <option value="low">낮은 신뢰도</option>
              <option value="unknown">신뢰도 없음</option>
            </select>
          </label>
          <label>
            검색
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="상품명, raw id, 이슈, 값" />
          </label>
        </div>
      </details>

      <div className="review-group-list">
        <div className="row" style={{ justifyContent: 'space-between', marginBottom: 8 }}>
          <strong>검수 묶음</strong>
          <span className="muted">{filteredGroups.length}개 묶음 표시 · 500개도 묶음 단위로 처리</span>
        </div>
        {filteredGroups.length === 0 && <div className="muted">조건에 맞는 검수 묶음이 없습니다.</div>}
        {filteredGroups.map((group) => (
          <GroupCard
            key={group.id}
            group={group}
            rawRecordsById={rawRecordsById}
            issuesByRecord={issuesByRecord}
            duplicateMap={duplicateMap}
            publishRowsByRawId={publishRowsByRawId}
            onPublishRows={publishRowsToDb}
            onRollback={rollbackPublishRow}
            reviewerId={reviewerId}
            setReviewerId={setReviewerId}
            onRefresh={refresh}
            onError={setError}
          />
        ))}
      </div>
    </section>
  );
}
