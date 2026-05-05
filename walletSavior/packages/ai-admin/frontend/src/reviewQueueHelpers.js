export function buildBatchHealth(summary = {}, rawRecords = [], fieldProposals = [], keywordProposals = []) {
  const unresolvedField = summary.unresolved_field_proposal_count ?? fieldProposals.filter((proposal) => (
    ['ai_proposed', 'human_reviewing', 'pending_review', 'needs_rework'].includes(proposal.status)
  )).length;
  const unresolvedKeyword = summary.unresolved_keyword_proposal_count ?? keywordProposals.filter((proposal) => (
    ['ai_proposed', 'human_reviewing', 'pending_review', 'needs_rework'].includes(proposal.status)
  )).length;
  const rawCount = summary.raw_count ?? rawRecords.length;
  const aiRecordCount = summary.ai_record_count ?? new Set(fieldProposals.map((proposal) => proposal.provenance?.raw_record_id).filter(Boolean)).size;
  const eligibleCount = summary.eligible_count ?? 0;
  const heldCount = summary.held_count ?? summary.blocked_count ?? 0;
  const publishedCount = summary.published_count ?? 0;
  const unresolvedCount = unresolvedField + unresolvedKeyword;

  return [
    { key: 'raw', label: '1 원본 수신', value: rawCount, tone: rawCount ? 'ok' : 'warn', help: '크롤러에서 들어온 상품 수' },
    { key: 'ai', label: '2 AI 라벨', value: aiRecordCount, tone: aiRecordCount >= rawCount && rawCount ? 'ok' : 'warn', help: rawCount - aiRecordCount > 0 ? `${rawCount - aiRecordCount}개는 AI 제안이 없습니다.` : '모든 원본에 AI 제안이 연결됨' },
    { key: 'eligible', label: '3 발행 가능', value: eligibleCount, tone: eligibleCount ? 'ok' : 'warn', help: '사람 승인·키워드·품질 게이트 통과' },
    { key: 'held', label: '4 보류/차단', value: heldCount, tone: heldCount ? 'warn' : 'ok', help: heldCount ? '아래 보류 사유를 해결해야 배치 완료' : '남은 보류 없음' },
    { key: 'published', label: '5 DB 큐 전송', value: publishedCount, tone: publishedCount ? 'ok' : '', help: 'DB-admin 최종 승인은 별도 필요' },
    { key: 'unresolved', label: '미해결 검수', value: unresolvedCount, tone: unresolvedCount ? 'err' : 'ok', help: `필드 ${unresolvedField} · 키워드 ${unresolvedKeyword}` },
  ];
}

export function summarizeProviderSetup(providers = []) {
  const enabled = providers.filter((provider) => provider.is_enabled);
  const liveReady = providers.filter((provider) => provider.can_call_live);
  const blocked = providers.filter((provider) => provider.is_enabled && provider.requires_secret && !provider.can_call_live);
  const modelTrouble = providers.filter((provider) => {
    const cap = provider.model_capability || {};
    return ['missing_secret', 'error', 'unavailable'].includes(cap.availability_status)
      || ['failed', 'error'].includes(cap.smoke_status);
  });

  return {
    total: providers.length,
    enabled: enabled.length,
    liveReady: liveReady.length,
    blocked: blocked.length,
    modelTrouble: modelTrouble.length,
    primaryMessage: providers.length
      ? `${enabled.length}/${providers.length} provider 활성 · LIVE 가능 ${liveReady.length}개`
      : '등록된 provider 상태가 없습니다.',
    failures: [...blocked, ...modelTrouble].slice(0, 4).map((provider) => ({
      provider_id: provider.provider_id,
      display_name: provider.display_name || provider.provider_id,
      reason: provider.can_call_live
        ? `model ${provider.model_capability?.model_name || '-'} 상태 ${provider.model_capability?.availability_status || provider.model_capability?.smoke_status || '확인 필요'}`
        : `secret alias ${provider.secret_alias || '-'} 확인 필요`,
    })),
  };
}

export function nextOperatorAction(summary = {}, providerSummary = {}) {
  if (providerSummary.blocked || providerSummary.modelTrouble) {
    return 'Provider/API 상태를 먼저 확인하세요. AI 라벨 실패 원인을 운영 화면에서 설명할 수 있어야 합니다.';
  }
  if (summary.raw_without_ai_count) return 'AI 제안이 없는 원본을 재처리하거나 provider 설정을 확인하세요.';
  if (summary.unresolved_keyword_proposal_count) return '키워드/카테고리 제안을 먼저 승인 또는 반려하세요.';
  if (summary.unresolved_field_proposal_count || summary.data_quality_issue_count) return '검수 묶음에서 행별 승인·보정·반려 사유를 남기세요.';
  if (summary.eligible_count) return 'eligible 항목을 DB-admin 큐로 발행하고, 남은 보류 사유를 확인하세요.';
  if (summary.published_count && summary.blocked_count) return '이미 발행된 항목과 남은 보류를 분리해 마감하세요.';
  return '원본 수신 → AI 라벨 → 키워드/카테고리 승인 → 행 검수 → 발행 순서로 진행하세요.';
}

export function buildBulkPreview(proposals = [], limit = 5) {
  return proposals.slice(0, limit).map((proposal) => (
    `${proposal.proposal_id} (${proposal.provenance?.raw_record_id || 'raw 없음'}: ${proposal.target_field})`
  ));
}

export function publishRowAction(row = {}) {
  if (row.status === 'published') return { kind: 'rollback', label: '롤백 요청', danger: true };
  if (row.status === 'publish_failed') return { kind: 'retry', label: 'DB 발행 재시도', danger: false };
  if (row.eligible) return { kind: 'publish', label: 'DB-admin 큐로 발행', danger: false };
  if (row.status === 'rolled_back') return { kind: 'blocked', label: '롤백 요청됨', danger: false };
  return { kind: 'blocked', label: '발행 불가', danger: false };
}

export function buildPublishConfirmationMessage(rows = [], summary = {}) {
  const preview = rows.map((row) => (
    `  · ${row.raw_record_id}: ${row.raw_title || row.item?.name || '-'} (${row.retryable ? 'retry' : 'new'})`
  )).join('\n');
  return [
    `DB-admin 큐로 ${rows.length}개를 발행합니다.`,
    preview,
    `DB-admin 최종 승인은 별도이며, 공개 DB 반영 전 DB-admin에서 검수해야 합니다.`,
    `보류/차단 ${summary.blocked_count ?? 0}개는 남습니다.`,
    `계속할까요?`,
  ].filter(Boolean).join('\n');
}

export function buildRollbackConfirmationMessage(row = {}) {
  return [
    `AI 발행 기록을 롤백 요청 상태로 바꿉니다.`,
    `  · raw_record_id: ${row.raw_record_id}`,
    `  · 상품: ${row.raw_title || row.item?.name || '-'}`,
    `  · DB-admin ingestion: ${row.db_ingestion_id || '(없음)'}`,
    `DB-admin에는 hard retract API가 없으므로, 운영자가 해당 ingestion을 승인하지 말고 reject/delete 해야 공개 노출을 막을 수 있습니다.`,
    `계속할까요?`,
  ].join('\n');
}

export function summarizeAutomationPreview(preview = {}) {
  const eligible = preview.eligible_count ?? preview.eligible_items?.length ?? 0;
  const blocked = preview.blocked_count ?? preview.blocked_items?.length ?? 0;
  const candidate = preview.candidate_count ?? eligible + blocked;
  return {
    eligible,
    blocked,
    candidate,
    tone: eligible ? 'ok' : 'warn',
    primaryMessage: eligible
      ? `안전 게이트 통과 ${eligible}개 · 차단 ${blocked}개`
      : `자동 승인 가능한 항목 없음 · 차단 ${blocked}개`,
    help: '자동화는 검수 승인만 기록하며 DB-admin 발행은 운영자가 별도로 실행합니다.',
  };
}

export function explainAutomationRow(row = {}) {
  if (row.eligible) {
    return `${row.raw_record_id}: ${row.target_field} · ${row.rule_id} 통과 (${row.reason})`;
  }
  const blockers = (row.blockers || []).slice(0, 3).join(', ') || row.reason || '선택한 안전 게이트 불일치';
  return `${row.raw_record_id || '-'}: ${row.target_field || '-'} 차단 · ${blockers}`;
}

export function buildAutomationApplyMessage(preview = {}, ruleId = '') {
  const summary = summarizeAutomationPreview(preview);
  const rows = (preview.eligible_items || []).slice(0, 5).map((row) => `  · ${explainAutomationRow(row)}`).join('\n');
  return [
    `${ruleId || '선택한 안전 게이트'}로 ${summary.eligible}개 AI 제안을 자동 승인합니다.`,
    rows,
    summary.eligible > 5 ? `  · ...` : '',
    '감사 기록에는 rule id, 사유, threshold, field/proposal id가 남습니다.',
    'DB-admin 발행은 하지 않습니다. 발행은 별도 버튼으로 운영자가 실행해야 합니다.',
    '계속할까요?',
  ].filter(Boolean).join('\n');
}
