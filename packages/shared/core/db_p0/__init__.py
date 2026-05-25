"""db-FINAL P0 18-item implementation surface.

이 패키지는 docs/planning/round-A/db-FINAL-opus.md §8 P0 표의 계약을 코드로 박는다.
운영 UI는 P1로 미루더라도 *계약*(스키마/모델/리졸버/계산식/권한 표/idempotency)은
라이브 직전 풀세트로 가야 한다는 §S-3 Q2 결단에 따른다.

각 모듈이 담당하는 P0 항목 번호는 모듈 docstring에 기재돼 있다.
"""

from .identity import (
    CanonicalProductIdentity,
    CanonicalIdRedirect,
    RedirectReason,
    CanonicalStatus,
    RedirectResolver,
    RedirectCycleError,
    RedirectDepthExceeded,
    compute_fingerprint,
    new_stable_id,
)
from .pricing import (
    PricingProfile,
    PricingProfileChangeLog,
    HotdealScoreInputs,
    HotdealScore,
    ScoreLabel,
    compute_hotdeal_score,
    label_for,
    DEFAULT_PROFILES,
)
from .anchor import (
    WholesaleBaseline,
    WholesaleSourceStatus,
    SourceClass,
    FailureKind,
    SourceStatus,
    CategoryFreshnessPolicy,
    effective_anchor,
)
from .observations import (
    PriceObservation,
    EffectivePriceType,
    UnitBasis,
    StoreScope,
    normalize_unit,
)
from .alias_match import (
    MartSkuAlias,
    AvailabilityStatus,
    BrandAlias,
    BrandAliasStatus,
    MatchCandidateLog,
    CommunityPriceSignal,
    bump_alias_observation,
    pull_community_delta,
)
from .escalation import (
    ProductReviewQueueItem,
    EscalationVersionConflict,
    EscalationClaimExpired,
    claim_item,
    resolve_item,
)
from .category_tree import (
    CategorySet,
    CategorySetStatus,
    CategoryRemap,
    RemapKind,
    activate_category_set,
)
from .permissions import (
    Role,
    PermissionMatrix,
    DEFAULT_MATRIX,
    PermissionDenied,
)
from .snapshot import (
    SnapshotBuildLog,
    RestoreJob,
    RestoreJobStep,
    RestoreJobStatus,
    AuditLogEntry,
    atomic_publish,
    new_restore_job,
    advance_restore_job,
)

__all__ = [
    # identity (P0#1)
    "CanonicalProductIdentity",
    "CanonicalIdRedirect",
    "RedirectReason",
    "CanonicalStatus",
    "RedirectResolver",
    "RedirectCycleError",
    "RedirectDepthExceeded",
    "compute_fingerprint",
    "new_stable_id",
    # pricing (P0#13, #15)
    "PricingProfile",
    "PricingProfileChangeLog",
    "HotdealScoreInputs",
    "HotdealScore",
    "ScoreLabel",
    "compute_hotdeal_score",
    "label_for",
    "DEFAULT_PROFILES",
    # anchor (P0#7)
    "WholesaleBaseline",
    "WholesaleSourceStatus",
    "SourceClass",
    "FailureKind",
    "SourceStatus",
    "CategoryFreshnessPolicy",
    "effective_anchor",
    # observations (P0#10, #16)
    "PriceObservation",
    "EffectivePriceType",
    "UnitBasis",
    "StoreScope",
    "normalize_unit",
    # alias/match (P0#3, #11, #17, #18)
    "MartSkuAlias",
    "AvailabilityStatus",
    "BrandAlias",
    "BrandAliasStatus",
    "MatchCandidateLog",
    "CommunityPriceSignal",
    "bump_alias_observation",
    "pull_community_delta",
    # escalation (P0#4)
    "ProductReviewQueueItem",
    "EscalationVersionConflict",
    "EscalationClaimExpired",
    "claim_item",
    "resolve_item",
    # category (P0#12)
    "CategorySet",
    "CategorySetStatus",
    "CategoryRemap",
    "RemapKind",
    "activate_category_set",
    # permissions (P0#14)
    "Role",
    "PermissionMatrix",
    "DEFAULT_MATRIX",
    "PermissionDenied",
    # snapshot/audit (P0#2, #8, #9)
    "SnapshotBuildLog",
    "RestoreJob",
    "RestoreJobStep",
    "RestoreJobStatus",
    "AuditLogEntry",
    "atomic_publish",
    "new_restore_job",
    "advance_restore_job",
]
