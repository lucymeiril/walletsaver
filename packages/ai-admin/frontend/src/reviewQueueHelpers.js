export function buildBatchHealth(summary = {}, rawRecords = [], fieldProposals = [], keywordProposals = []) {
  const unresolvedField = summary.unresolved_field_proposal_count ?? fieldProposals.filter((proposal) => (
    ['ai_proposed', 'human_reviewing', 'pending_review', 'needs_rework'].includes(proposal.status)
  )).length;
  const unresolvedKeyword = summary.unresolved_keyword_proposal_count ?? keywordProposals.filter((proposal) => (
    ['ai_proposed', 'human_reviewing', 'pending_review', 'needs_rework'].includes(proposal.status)
  )).length;
  const postPublishAudit = summary.post_publish_audit_count ?? 0;
  const rawCount = summary.raw_count ?? rawRecords.length;
  const aiRecordCount = summary.ai_record_count ?? new Set(fieldProposals.map((proposal) => proposal.provenance?.raw_record_id).filter(Boolean)).size;
  const eligibleCount = summary.eligible_count ?? 0;
  const heldCount = summary.held_count ?? summary.blocked_count ?? 0;
  const publishedCount = summary.published_count ?? 0;
  const unresolvedCount = unresolvedField + unresolvedKeyword;

  return [
    { key: 'raw', label: '1 원본 수신', value: rawCount, tone: rawCount ? 'ok' : 'warn', help: '크롤러에서 들어온 상품 수' },
    { key: 'ai', label: '2 AI 라벨', value: aiRecordCount, tone: aiRecordCount >= rawCount && rawCount ? 'ok' : 'warn', help: rawCount - aiRecordCount > 0 ? `${rawCount - aiRecordCount}개는 AI 제안이 없습니다.` : '모든 원본에 AI 제안이 연결됨' },
    { key: 'eligible', label: '3 발행 가능', value: eligibleCount, tone: eligibleCount ? 'ok' : 'warn', help: postPublishAudit ? `사후 감사 플래그 ${postPublishAudit}건은 DB-admin 검수 큐로 보냄` : '핵심 가격·출처·단위 게이트 통과: 최종 승인 후보' },
    { key: 'held', label: '4 보류/차단', value: heldCount, tone: heldCount ? 'warn' : 'ok', help: heldCount ? '핵심 차단 사유만 해결하면 나머지는 사후 감사' : '남은 핵심 보류 없음' },
    { key: 'published', label: '5 DB 큐 전송', value: publishedCount, tone: publishedCount ? 'ok' : '', help: 'DB-admin 최종 승인은 별도 필요' },
    { key: 'unresolved', label: '미해결 검수', value: unresolvedCount, tone: unresolvedField ? 'err' : (unresolvedKeyword ? 'warn' : 'ok'), help: `핵심 필드 ${unresolvedField} · 키워드 ${unresolvedKeyword}` },
  ];
}

export function buildOpsTriageCounters(summary = {}, publishRows = [], automationPreview = {}) {
  const rowStatusCounts = summary.row_status_counts || {};
  const pendingDbReview = summary.pending_db_review_count ?? rowStatusCounts.pending_db_review ?? publishRows.filter((row) => row.status === 'pending_db_review').length;
  const published = summary.published_count ?? rowStatusCounts.published ?? publishRows.filter((row) => row.status === 'published').length;
  const publishFailed = summary.publish_failed_count ?? rowStatusCounts.publish_failed ?? publishRows.filter((row) => row.status === 'publish_failed').length;
  const rolledBack = summary.rolled_back_count ?? rowStatusCounts.rolled_back ?? publishRows.filter((row) => row.status === 'rolled_back').length;
  const needsReReview = summary.needs_re_review_count ?? publishFailed + rolledBack;
  const rollbackAvailable = summary.rollback_available_count ?? pendingDbReview + published;
  const suspicious = summary.suspicious_count ?? summary.data_quality_issue_count ?? publishRows.filter((row) => (
    (row.audit_issues || []).length || row.audit_issue_count || (row.blockers || []).some((blocker) => String(blocker).startsWith('data_quality:'))
  )).length;
  const autoApproved = summary.auto_approved_count ?? automationPreview.applied_count ?? 0;
  const autoApprovedRows = summary.auto_approved_raw_count ?? 0;

  return [
    {
      key: 'auto-approved',
      label: 'AI 자동 승인',
      value: autoApproved,
      tone: autoApproved ? 'ok' : '',
      help: autoApproved
        ? `${autoApprovedRows || autoApproved}개 원본/제안은 안전 게이트가 승인했습니다. DB 발행은 별도입니다.`
        : '아직 안전 게이트가 자동 승인한 제안이 없습니다.',
    },
    {
      key: 'suspicious',
      label: '의심/품질 이슈',
      value: suspicious,
      tone: suspicious ? 'err' : 'ok',
      help: suspicious ? '가격·카테고리·누락 등 먼저 봐야 할 항목입니다.' : '현재 감사 이슈가 없습니다.',
    },
    {
      key: 'post-publish-audit',
      label: '발행 후 DB-admin 확인',
      value: pendingDbReview + published,
      tone: pendingDbReview + published ? 'warn' : '',
      help: `검수 대기 ${pendingDbReview} · DB 큐 전송 ${published}. 공개 반영 전/후 DB-admin에서 최종 확인합니다.`,
    },
    {
      key: 'rollback-rereview',
      label: '롤백/재검수',
      value: rollbackAvailable + needsReReview,
      tone: rollbackAvailable + needsReReview ? 'warn' : 'ok',
      help: `롤백 가능 ${rollbackAvailable} · 재시도/재검수 ${needsReReview}. 문제가 보이면 행 버튼으로 롤백·재발행하세요.`,
    },
  ];
}

export function auditFlagLabel(flag = {}) {
  const code = typeof flag === 'string' ? flag : flag.code;
  const message = typeof flag === 'string' ? '' : flag.message || flag.reason || flag.field;
  const copy = {
    ai_suggested_category: '새 카테고리 제안',
    ai_suggested_category_id: '새 카테고리 ID',
    ai_suggested_category_hint: '카테고리 힌트 확인',
    ai_suggested_category_name: '카테고리명 확인',
    ai_suggested_keywords: '새 키워드 제안',
    ai_suggested_aliases: '새 별칭 제안',
    db_keyword_proposal_unresolved: '키워드 미해결',
    hotdeal_claim_blocked: '할인 근거 부족',
  };
  return [copy[code] || code || '사후 감사 필요', message].filter(Boolean).join(' · ');
}

export function buildMutationPreflightChecklist(summary = {}, rows = []) {
  const finalApproveCount = summary.ai_safe_final_approve_count
    ?? rows.filter((row) => row.ai_safe_final_approve_eligible).length;
  const preflight = summary.safety?.mutation_preflight
    || rows.find((row) => row.db_ingestion_result?.mutation_preflight)?.db_ingestion_result?.mutation_preflight
    || null;
  const snapshot = preflight?.snapshot || {};
  const ready = preflight
    ? preflight.status === 'ready' && preflight.ready_to_mutate === true && snapshot.verified === true
    : false;
  const blockedMessage = preflight?.error?.message || preflight?.error || '';

  if (!finalApproveCount) {
    return {
      key: 'db-review-only',
      tone: 'warn',
      label: 'DB-admin 검수 큐',
      help: '최종 DB 저장 전 DB-admin에서 사람이 다시 승인합니다.',
      backupRequired: false,
      latestBackup: snapshot.latest_backup || null,
    };
  }
  return {
    key: ready ? 'preflight-ready' : 'preflight-required',
    tone: ready ? 'ok' : 'warn',
    label: ready ? '백업 확인됨' : '백업 확인 필요',
    help: ready
      ? `DB-admin 백업 스냅샷이 확인되어 최종 승인 후보 ${finalApproveCount}개를 시도할 수 있습니다.`
      : `최종 승인 후보 ${finalApproveCount}개는 DB-admin 읽기 상태와 롤백 백업 스냅샷 확인이 먼저 필요합니다.${blockedMessage ? ` (${blockedMessage})` : ''}`,
    backupRequired: true,
    latestBackup: snapshot.latest_backup || null,
    createEndpoint: snapshot.create_endpoint || '/api/admin/backup',
    rollbackPath: snapshot.rollback_path || '검증된 백업으로 복구 후 재시도',
  };
}

export function buildPublishRowNextAction(row = {}) {
  if (!row.raw_record_id && !row.status && !row.eligible && !(row.blockers || []).length) return '행을 선택하면 다음 조치를 안내합니다.';
  if (row.status === 'published') {
    const verified = row.db_ingestion_result?.ai_safe_final_approve?.public_db_verification?.verified;
    return verified
      ? '공개 DB 반영 확인됨. 이후 이상 징후가 보이면 롤백 후 재검수하세요.'
      : 'DB-admin 결과 확인 후 이상하면 롤백/재검수로 보내세요.';
  }
  if (row.status === 'pending_db_review') return 'DB-admin에서 승인하거나, 의심되면 승인하지 말고 롤백 요청하세요.';
  if (row.status === 'publish_failed') return '오류와 백업 preflight를 확인한 뒤 DB 발행 재시도 또는 보류하세요.';
  if (row.status === 'rolled_back') return 'DB-admin ingestion을 reject/delete한 뒤 원본·제안을 재검수하세요.';
  if (row.eligible && row.ai_safe_final_approve_eligible) return '원본·정규화·감사 플래그를 확인하고 최종 승인 요청하세요.';
  if (row.eligible) return '사후 감사 플래그를 확인하고 DB-admin 검수 큐로 보내세요.';
  if ((row.blockers || []).length) return `차단 사유를 해결하세요: ${(row.blockers || []).slice(0, 2).join(', ')}`;
  return '검수 묶음에서 승인/보정/반려를 먼저 완료하세요.';
}

export function summarizeNormalizedPublishRow(row = {}) {
  const metadata = row.normalized_metadata || row.item?.normalized_metadata || row.item?.raw_data?.normalized || {};
  const canonical = metadata.canonical_product || {};
  const variant = metadata.product_variant || {};
  const listing = metadata.source_listing || {};
  const offer = metadata.offer_event || {};
  return [
    {
      key: 'canonical',
      label: '상품 카드',
      value: canonical.canonical_name || row.item?.name || row.raw_title || '-',
      help: [canonical.category_name || row.item?.category, canonical.category_id || row.item?.category_id].filter(Boolean).join(' · ') || '카테고리 없음',
    },
    {
      key: 'variant',
      label: '용량/단위',
      value: variant.package_signature || row.item?.display_unit || row.item?.unit || '-',
      help: variant.package_match_status === 'source_confirmed'
        ? '원본 출처 단위와 일치'
        : variant.package_match_status || '단위 확인 필요',
    },
    {
      key: 'listing',
      label: '출처 상품',
      value: listing.source_title || row.raw_title || '-',
      help: [listing.source_name || row.source_name, listing.source_record_key].filter(Boolean).join(' · ') || '출처 정보 없음',
    },
    {
      key: 'offer',
      label: '가격/이벤트',
      value: offer.price ?? row.item?.sale_price ?? row.item?.price ?? '-',
      help: [offer.price_state || row.item?.price_state, offer.event_name || row.item?.event_name].filter(Boolean).join(' · ') || '가격 상태 확인',
    },
  ];
}

export function buildOperatorDashboardReport(operatorSummary = {}) {
  const stats = operatorSummary.stats || {};
  const publishBlockers = operatorSummary.publish_blockers || [];
  const anomalyBuckets = (operatorSummary.anomaly_buckets || []).filter((bucket) => (
    (bucket.count || 0) > 0 || (bucket.rows || []).length > 0
  ));
  const blockerReasonCounts = operatorSummary.publish_blocker_counts_by_reason || {};
  const unresolvedReview = (
    (stats.unresolved_field_proposal_count || 0)
    + (stats.unresolved_keyword_proposal_count || 0)
  );
  const dbHandoff = (
    (stats.pending_db_review_count || 0)
    + (stats.published_count || 0)
    + (stats.publish_failed_count || 0)
  );
  const suspiciousRows = operatorSummary.anomaly_summary?.suspicious_row_count
    ?? anomalyBuckets.reduce((total, bucket) => total + (bucket.count || 0), 0);

  return {
    cards: [
      {
        key: 'publish-blockers',
        label: '발행 차단 행',
        value: stats.blocked_count ?? publishBlockers.length,
        tone: (stats.blocked_count ?? publishBlockers.length) ? 'err' : 'ok',
        help: `차단 사유 ${Object.keys(blockerReasonCounts).length}종 · 보류 ${stats.held_count ?? 0}개`,
      },
      {
        key: 'review-queue',
        label: '미해결 검수 큐',
        value: unresolvedReview,
        tone: unresolvedReview ? 'warn' : 'ok',
        help: `필드 ${stats.unresolved_field_proposal_count ?? 0} · 키워드 ${stats.unresolved_keyword_proposal_count ?? 0}`,
      },
      {
        key: 'anomalies',
        label: 'Anomaly 의심 행',
        value: suspiciousRows,
        tone: suspiciousRows ? 'err' : 'ok',
        help: `버킷 ${anomalyBuckets.length}개 · retained ${operatorSummary.anomaly_summary?.retained_row_count ?? '-'}`,
      },
      {
        key: 'db-handoff',
        label: 'DB 핸드오프 확인',
        value: dbHandoff,
        tone: (stats.publish_failed_count || stats.pending_db_review_count) ? 'warn' : (dbHandoff ? 'ok' : ''),
        help: `검수 대기 ${stats.pending_db_review_count ?? 0} · 발행 ${stats.published_count ?? 0} · 실패 ${stats.publish_failed_count ?? 0}`,
      },
    ],
    topBlockers: publishBlockers.slice(0, 5),
    topAnomalies: anomalyBuckets.slice(0, 5),
  };
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
  if (summary.eligible_count) {
    if (summary.ai_safe_final_approve_count) {
      return `최종 승인 후보 ${summary.ai_safe_final_approve_count}개는 한 번의 운영자 확인으로 DB-admin 안전 승인까지 요청하고, 나머지는 DB-admin 검수 큐로 보내세요.`;
    }
    if (summary.post_publish_audit_count || summary.unresolved_keyword_proposal_count || summary.unresolved_relaxed_field_proposal_count) {
      return '발행 가능 항목을 DB-admin 큐로 보내고, 키워드/카테고리 불확실성은 사후 anomaly audit로 추적하세요.';
    }
    return 'eligible 항목을 DB-admin 큐로 발행하고, 남은 보류 사유를 확인하세요.';
  }
  if (summary.unresolved_keyword_proposal_count) return '키워드/카테고리 제안은 사후 감사 가능하지만, 먼저 핵심 가격·출처·단위 게이트를 확인하세요.';
  if (summary.unresolved_field_proposal_count || summary.data_quality_issue_count) return '검수 묶음에서 행별 승인·보정·반려 사유를 남기세요.';
  if (summary.published_count && summary.blocked_count) return '이미 발행된 항목과 남은 보류를 분리해 마감하세요.';
  return '원본 수신 → AI 라벨 → 키워드/카테고리 승인 → 행 검수 → 발행 순서로 진행하세요.';
}

export function buildBulkPreview(proposals = [], limit = 5) {
  return proposals.slice(0, limit).map((proposal) => (
    `${proposal.proposal_id} (${proposal.provenance?.raw_record_id || 'raw 없음'}: ${proposal.target_field})`
  ));
}

export function publishRowAction(row = {}) {
  if (row.status === 'pending_db_review') return { kind: 'rollback', label: 'DB 검수 대기/롤백', danger: true };
  if (row.status === 'published') return { kind: 'rollback', label: '롤백 요청', danger: true };
  if (row.status === 'publish_failed') return { kind: 'retry', label: 'DB 발행 재시도', danger: false };
  if (row.eligible && row.ai_safe_final_approve_eligible) return { kind: 'publish', label: '최종 승인 요청', danger: false };
  if (row.eligible) return { kind: 'publish', label: 'DB-admin 검수 큐로 발행', danger: false };
  if (row.status === 'rolled_back') return { kind: 'blocked', label: '롤백 요청됨', danger: false };
  return { kind: 'blocked', label: '발행 불가', danger: false };
}

export function buildPublishConfirmationMessage(rows = [], summary = {}) {
  const finalApproveCount = rows.filter((row) => row.ai_safe_final_approve_eligible).length;
  const dbReviewCount = rows.length - finalApproveCount;
  const preview = rows.map((row) => (
    `  · ${row.raw_record_id}: ${row.raw_title || row.item?.name || '-'} (${row.ai_safe_final_approve_eligible ? 'AI 안전 최종 승인 후보' : row.retryable ? 'retry' : 'DB 검수 큐'})`
  )).join('\n');
  const heldCount = summary.held_rows?.length ?? summary.blocked_count ?? 0;
  const approvedCount = summary.approved_rows?.length ?? rows.length;
  return [
    `DB-admin으로 ${rows.length}개를 보냅니다. 최종 승인 후보 ${finalApproveCount}개 · DB 검수 큐 ${dbReviewCount}개.`,
    `화면 기준 승인/발행 가능 ${approvedCount}개 · 보류/차단 ${heldCount}개를 분리해 표시합니다.`,
    preview,
    finalApproveCount
      ? `최종 승인 후보는 이 클릭 후 DB-admin ai-safe-final-approve까지 요청합니다. 제출만으로는 공개 DB 저장이 아니며, 최종 승인 성공 때만 DB save complete입니다. 실패하면 검수 큐 대기로 남습니다.`
      : `DB-admin 최종 승인은 별도이며, 제출만으로는 공개 DB 저장이 아닙니다. 공개 DB 반영 전 DB-admin에서 검수해야 합니다.`,
    summary.post_publish_audit_count ? `사후 anomaly audit 플래그 ${summary.post_publish_audit_count}건은 발행 후 보정/롤백 대상으로 추적합니다.` : '',
    `이미 pending_db_review인 행은 중복 발행하지 않습니다. 필요하면 롤백 요청 후 DB-admin ingestion을 reject/delete 하세요.`,
    `API 안전 상태: operator_final_approval_required · no silent DB mutation before final approve.`,
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

export const SAFE_SEED_CATEGORY_LABELS = {
  'prepared_food.meal_kit.kimbap': '밀키트/델리/김밥',
  'prepared_food.meal_kit': '밀키트/델리',
  'prepared_food.deli.kimbap': '델리/김밥',
  'seafood.frozen': '수산/냉동',
  'seafood.fish': '수산/생선',
  'seafood.squid': '수산/오징어',
  'seafood.shrimp': '수산/새우',
  'snack.nut': '간식/견과',
  'snack.chip': '간식/칩',
  'snack.chocolate': '간식/초콜릿',
  'snack.general': '간식/일반',
  'dairy.milk': '유제품/우유',
  'dairy.milk.chocolate': '유제품/초코우유',
  'dairy.cheese': '유제품/치즈',
  'dairy.yogurt': '유제품/요거트',
  'dairy.egg': '유제품/계란',
  'meat.pork.belly': '축산/돼지고기/삼겹살',
  'meat.pork': '축산/돼지고기',
  'meat.beef': '축산/소고기',
  'meat.beef.hanwoo': '축산/한우',
  'meat.chicken': '축산/닭고기',
  'meat.chicken.breast': '축산/닭가슴살',
  'produce.fruit': '농산/과일',
  'produce.vegetable': '농산/채소',
  'grain.rice': '곡류/쌀',
  'instant.noodle': '즉석/라면',
  'instant.rice': '즉석/밥',
  'beverage.water': '음료/생수',
  'beverage.juice': '음료/주스',
  'beverage.soda': '음료/탄산',
  'beverage.coffee': '음료/커피',
  'processed.tofu.firm': '가공식품/두부',
  'daily.detergent': '생활용품/세제',
};

const SAFE_SEED_CATEGORY_ALIASES = {
  밀키트델리: 'prepared_food.meal_kit',
  델리밀키트: 'prepared_food.meal_kit',
  밀키트: 'prepared_food.meal_kit',
  mealkit: 'prepared_food.meal_kit',
  mealkitdeli: 'prepared_food.meal_kit',
  preparedfoodmealkit: 'prepared_food.meal_kit',
  preparedfooddelimealkit: 'prepared_food.meal_kit',
  수산냉동: 'seafood.frozen',
  냉동수산: 'seafood.frozen',
  수산물냉동: 'seafood.frozen',
  해산물냉동: 'seafood.frozen',
  냉동해산물: 'seafood.frozen',
  seafoodfrozen: 'seafood.frozen',
};

export function normalizeCategoryId(value) {
  const raw = String(value ?? '').trim().toLowerCase();
  const compact = [...raw].filter((ch) => /[a-z0-9가-힣]/i.test(ch)).join('');
  return SAFE_SEED_CATEGORY_ALIASES[compact] || raw;
}

export function categoryDisplayLabel(value) {
  const categoryId = normalizeCategoryId(value);
  return SAFE_SEED_CATEGORY_LABELS[categoryId] || categoryId || '-';
}

export function formatCategoryDisplay(value) {
  const categoryId = normalizeCategoryId(value);
  const label = categoryDisplayLabel(value);
  return label && label !== categoryId ? `${label} (${categoryId})` : label;
}
