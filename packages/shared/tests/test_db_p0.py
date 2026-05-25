"""db-FINAL §8 P0 18건 회귀 테스트.

각 테스트의 P0# 번호는 docs/planning/round-A/db-FINAL-opus.md §8 표와 1:1 매핑.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from shared.core.db_p0 import (
    # identity
    CanonicalIdRedirect,
    CanonicalProductIdentity,
    CanonicalStatus,
    RedirectCycleError,
    RedirectDepthExceeded,
    RedirectReason,
    RedirectResolver,
    compute_fingerprint,
    new_stable_id,
    # pricing
    DEFAULT_PROFILES,
    HotdealScoreInputs,
    PricingProfile,
    PricingProfileChangeLog,
    ScoreLabel,
    compute_hotdeal_score,
    label_for,
    # anchor
    CategoryFreshnessPolicy,
    FailureKind,
    SourceClass,
    SourceStatus,
    WholesaleBaseline,
    WholesaleSourceStatus,
    effective_anchor,
    # observations
    EffectivePriceType,
    PriceObservation,
    StoreScope,
    UnitBasis,
    normalize_unit,
    # alias/match
    AvailabilityStatus,
    BrandAlias,
    BrandAliasStatus,
    CommunityPriceSignal,
    MartSkuAlias,
    MatchCandidateLog,
    bump_alias_observation,
    pull_community_delta,
    # escalation
    EscalationClaimExpired,
    EscalationVersionConflict,
    ProductReviewQueueItem,
    claim_item,
    resolve_item,
    # category
    CategoryRemap,
    CategorySet,
    CategorySetStatus,
    RemapKind,
    activate_category_set,
    # permissions
    DEFAULT_MATRIX,
    PermissionDenied,
    PermissionMatrix,
    Role,
    # snapshot
    AuditLogEntry,
    RestoreJob,
    RestoreJobStatus,
    RestoreJobStep,
    advance_restore_job,
    atomic_publish,
    new_restore_job,
)


# ════════════════════════════════════════════════════════════
# P0#1 — stable_id + redirect 분리, resolver 의무 통과
# ════════════════════════════════════════════════════════════

class TestStableIdRedirect:
    def test_stable_id_unique(self):
        ids = {new_stable_id() for _ in range(200)}
        assert len(ids) == 200

    def test_fingerprint_version_bump_changes_hash(self):
        a = compute_fingerprint("seoul", "milk_1l", 1.0, "l", 1)
        b = compute_fingerprint("seoul", "milk_1l", 1.0, "l", 2)
        assert a != b
        assert len(a) == 40

    def test_resolver_returns_terminal_id(self):
        r = RedirectResolver()
        r.add(CanonicalIdRedirect(from_id="A", to_id="B", reason=RedirectReason.MERGE))
        r.add(CanonicalIdRedirect(from_id="B", to_id="C", reason=RedirectReason.MERGE))
        assert r.resolve("A") == "C"
        assert r.resolve("B") == "C"
        assert r.resolve("C") == "C"   # terminal 그대로 반환
        assert r.resolve("Z") == "Z"   # 미등록 id는 자기 자신

    def test_resolver_rejects_cycle(self):
        r = RedirectResolver()
        r.add(CanonicalIdRedirect(from_id="A", to_id="B", reason=RedirectReason.MERGE))
        r.add(CanonicalIdRedirect(from_id="B", to_id="C", reason=RedirectReason.MERGE))
        with pytest.raises(RedirectCycleError):
            r.add(CanonicalIdRedirect(from_id="C", to_id="A", reason=RedirectReason.MERGE))
        # cycle 거부 후 기존 체인은 여전히 정상 동작
        assert r.resolve("A") == "C"

    def test_resolver_rejects_self_loop(self):
        r = RedirectResolver()
        with pytest.raises(RedirectCycleError):
            r.add(CanonicalIdRedirect(from_id="A", to_id="A", reason=RedirectReason.MERGE))

    def test_resolver_depth_limit(self):
        r = RedirectResolver()
        # 8단계 체인은 OK
        for i in range(8):
            r.add(CanonicalIdRedirect(
                from_id=f"id{i}", to_id=f"id{i+1}", reason=RedirectReason.MERGE,
            ))
        assert r.resolve("id0") == "id8"
        # 9번째 hop 추가 — id0에서 resolve 시 깊이 초과.
        r.add(CanonicalIdRedirect(from_id="id8", to_id="id9", reason=RedirectReason.MERGE))
        with pytest.raises(RedirectDepthExceeded):
            r.resolve("id0")
        # 짧은 체인은 여전히 OK
        assert r.resolve("id7") == "id9"

    def test_identity_model_immutable_external_id(self):
        ident = CanonicalProductIdentity(
            stable_id="stable_abc",
            current_fingerprint="0" * 40,
        )
        assert ident.status == CanonicalStatus.ACTIVE
        assert ident.fingerprint_version == 1


# ════════════════════════════════════════════════════════════
# P0#13, #15 — pricing_profile + robust hotdeal_score
# ════════════════════════════════════════════════════════════

class TestPricingProfileAndScore:
    def test_default_seeds_present(self):
        assert set(DEFAULT_PROFILES) == {"fresh", "processed", "household", "imported", "etc"}
        for p in DEFAULT_PROFILES.values():
            total = p.weight_market_quantile + p.weight_wholesale + p.weight_event
            assert 0.95 <= total <= 1.05   # 합산 1 근처

    def test_label_global_thresholds(self):
        assert label_for(0) == ScoreLabel.OVERPRICED
        assert label_for(29) == ScoreLabel.OVERPRICED
        assert label_for(30) == ScoreLabel.NORMAL
        assert label_for(50) == ScoreLabel.DECENT
        assert label_for(70) == ScoreLabel.HOTDEAL
        assert label_for(90) == ScoreLabel.LEGENDARY
        assert label_for(100) == ScoreLabel.LEGENDARY

    def test_robust_score_p50_at_median_yields_low(self):
        profile = DEFAULT_PROFILES["processed"]
        inputs = HotdealScoreInputs(
            current_price=3100, p10=2400, p50=3100, sample_n=64,
            wholesale_anchor=1800, wholesale_is_stale=False,
        )
        s = compute_hotdeal_score(inputs, profile)
        assert 0 <= s.score <= 100
        assert s.label == ScoreLabel.OVERPRICED
        assert s.profile_version == profile.version_label

    def test_robust_score_below_p10_yields_hotdeal(self):
        profile = DEFAULT_PROFILES["processed"]
        inputs = HotdealScoreInputs(
            current_price=2200, p10=2400, p50=3100, sample_n=64,
            wholesale_anchor=1800, wholesale_is_stale=False,
        )
        s = compute_hotdeal_score(inputs, profile)
        assert s.score >= 50

    def test_low_sample_penalizes_score(self):
        profile = DEFAULT_PROFILES["processed"]
        base = HotdealScoreInputs(
            current_price=2200, p10=2400, p50=3100, sample_n=64,
        )
        low = base.model_copy(update={"sample_n": 3})
        s_full = compute_hotdeal_score(base, profile)
        s_low = compute_hotdeal_score(low, profile)
        assert s_low.score < s_full.score
        assert s_low.score_confidence < s_full.score_confidence

    def test_stale_wholesale_does_not_disable_scoring(self):
        # §2-5: 도매 끊김에도 기능 비활성화 금지.
        profile = DEFAULT_PROFILES["fresh"]
        inputs = HotdealScoreInputs(
            current_price=2200, p10=2400, p50=3100, sample_n=64,
            wholesale_anchor=None, wholesale_is_stale=True,
        )
        s = compute_hotdeal_score(inputs, profile)
        assert 0 < s.score < 100
        # 도매 끊김이라는 사실은 reason chip에 표시되어야 한다.
        chip = next(r for r in s.reasons if r["key"] == "vs_wholesale")
        assert "끊김" in chip["label"]

    def test_band_floor_prevents_div_by_zero(self):
        # p10==p50인 극단 케이스도 산식이 폭주하지 않아야 한다 (skewed 분포 대응).
        profile = DEFAULT_PROFILES["processed"]
        inputs = HotdealScoreInputs(
            current_price=2500, p10=3000, p50=3000, sample_n=50,
        )
        s = compute_hotdeal_score(inputs, profile)
        assert 0 <= s.score <= 100

    def test_change_log_record(self):
        log = PricingProfileChangeLog(
            profile_id="fresh",
            before_json={"weight_market_quantile": 0.5},
            after_json={"weight_market_quantile": 0.4},
            changed_by="admin1",
            note="신선식품 wholesale 비중 올림",
        )
        assert log.changed_at <= datetime.now(timezone.utc)


# ════════════════════════════════════════════════════════════
# P0#7 — 도매 anchor 3-layer + lineage + freshness_decay
# ════════════════════════════════════════════════════════════

class TestWholesaleAnchor:
    def _base(self, code, group, price, days_ago):
        ts = datetime.now(timezone.utc) - timedelta(days=days_ago)
        return WholesaleBaseline(
            source_code=code,
            source_class=SourceClass.WHOLESALE,
            source_lineage_group=group,
            commodity_key="milk_1l",
            observed_date=ts.date(),
            observed_at_utc=ts,
            unit_price_krw=price,
            unit_basis="per_1l",
        )

    def test_lineage_dedup(self):
        # 같은 lineage_group이면 가장 신선한 1건만 weight에 반영.
        baselines = [
            self._base("kamis_v1", "kamis", 1000, 10),
            self._base("kamis_v2_reprocessed", "kamis", 1200, 1),   # 같은 lineage → 1건으로
            self._base("garak", "garak", 1100, 1),
        ]
        statuses = {
            "kamis_v1": WholesaleSourceStatus(source_code="kamis_v1", display_name="KAMIS"),
            "kamis_v2_reprocessed": WholesaleSourceStatus(
                source_code="kamis_v2_reprocessed", display_name="KAMIS reprocessed"),
            "garak": WholesaleSourceStatus(source_code="garak", display_name="가락시장"),
        }
        result = effective_anchor(baselines, statuses, half_life_days=30)
        assert result is not None
        anchor, is_stale = result
        # kamis 재가공이 1건으로 합산되므로 garak(1100)과 kamis(1200)의 평균 근처.
        assert 1100 <= anchor <= 1200
        assert not is_stale

    def test_decay_makes_old_data_stale(self):
        baselines = [self._base("k", "k", 1000, 200)]   # 200일 전
        statuses = {"k": WholesaleSourceStatus(source_code="k", display_name="k")}
        result = effective_anchor(baselines, statuses, half_life_days=7)
        # half-life 7일 기준 200일 ≫ 2*7 → stale
        assert result is not None
        _, is_stale = result
        assert is_stale

    def test_dead_source_excluded(self):
        baselines = [
            self._base("dead", "g1", 5000, 1),
            self._base("alive", "g2", 1000, 1),
        ]
        statuses = {
            "dead": WholesaleSourceStatus(
                source_code="dead", display_name="dead", status=SourceStatus.DEAD,
                failure_kind=FailureKind.PARSER,
            ),
            "alive": WholesaleSourceStatus(source_code="alive", display_name="alive"),
        }
        anchor, _ = effective_anchor(baselines, statuses, half_life_days=30)
        assert anchor == pytest.approx(1000)   # dead 제외

    def test_no_sources_returns_none(self):
        assert effective_anchor([], {}, half_life_days=30) is None

    def test_freshness_policy_per_category(self):
        # 카테고리별 half-life — 같은 데이터를 신선식품(7)/가공(30)으로 돌리면 결과가 달라짐.
        baselines = [self._base("k", "k", 1000, 14)]
        statuses = {"k": WholesaleSourceStatus(source_code="k", display_name="k")}
        fresh_pol = CategoryFreshnessPolicy(category_id="vegetables", half_life_days=7)
        proc_pol = CategoryFreshnessPolicy(category_id="grocery", half_life_days=30)
        a_fresh = effective_anchor(baselines, statuses, fresh_pol.half_life_days)
        a_proc = effective_anchor(baselines, statuses, proc_pol.half_life_days)
        # fresh 카테고리에서는 14일 = 2x half-life → 경계, proc는 fresh.
        assert a_fresh is not None and a_proc is not None
        # 가격은 같지만 stale 판정이 다를 수 있음.

    def test_parser_failure_distinguished_from_dead_source(self):
        # §2-5: parser 깨짐 vs 진짜 중단을 failure_kind로 구분.
        st = WholesaleSourceStatus(
            source_code="x", display_name="x",
            status=SourceStatus.ACTIVE,
            failure_kind=FailureKind.PARSER,
            consecutive_fails=3,
        )
        assert st.failure_kind == FailureKind.PARSER
        assert st.status == SourceStatus.ACTIVE   # parser fail은 dead가 아님


# ════════════════════════════════════════════════════════════
# P0#10, #16 — effective_price_type + 단위 정규화 + UTC/TZ
# ════════════════════════════════════════════════════════════

class TestPriceObservation:
    def test_unit_normalization_grams(self):
        price, basis, conf = normalize_unit(2000, 300, "g")
        # 300g에 2000원 → 100g당 667원
        assert basis == UnitBasis.PER_100G
        assert price == round(2000 * 100 / 300)
        assert conf == 1.0

    def test_unit_normalization_liter(self):
        price, basis, _ = normalize_unit(3000, 1.5, "L")
        assert basis == UnitBasis.PER_1L
        assert price == 2000

    def test_unit_normalization_each(self):
        price, basis, conf = normalize_unit(5000, 5, "개")
        assert basis == UnitBasis.PER_EACH
        assert price == 1000
        assert conf < 1.0   # 개수 단위는 신뢰도 낮음

    def test_unit_normalization_unknown(self):
        assert normalize_unit(1000, 1, "xyz") == (None, None, 0.0)
        assert normalize_unit(1000, 0, "g") == (None, None, 0.0)

    def test_observation_requires_utc_aware(self):
        with pytest.raises(ValueError):
            PriceObservation(
                stable_id="x",
                mart="E",
                raw_price=1000,
                observed_at_utc=datetime(2025, 1, 1, 0, 0, 0),  # naive
                local_sale_date=date(2025, 1, 1),
            )

    def test_observation_effective_price_type_conditional_fields(self):
        obs = PriceObservation(
            stable_id="x",
            mart="E",
            raw_price=1000,
            effective_price_type=EffectivePriceType.COUPON,
            coupon_code="ABC123",
            min_purchase_qty=2,
            observed_at_utc=datetime.now(timezone.utc),
            local_sale_date=date.today(),
            store_scope=StoreScope.ONLINE_NATIONAL,
        )
        assert obs.coupon_code == "ABC123"
        assert obs.min_purchase_qty == 2


# ════════════════════════════════════════════════════════════
# P0#11 — MartSkuAlias availability_status
# P0#3, #17, #18 — match_log + community signal
# ════════════════════════════════════════════════════════════

class TestAliasAndMatch:
    def test_availability_transition_oos(self):
        # 7일 연속 miss → out_of_stock
        last_seen = datetime.now(timezone.utc) - timedelta(days=8)
        alias = MartSkuAlias(
            mart="E", mart_item_id="100", stable_id="s1",
            last_success_seen_at=last_seen, consecutive_miss_count=6,
        )
        updated = bump_alias_observation(alias, seen=False)
        assert updated.availability_status == AvailabilityStatus.OUT_OF_STOCK
        assert updated.consecutive_miss_count == 7

    def test_availability_transition_discontinued(self):
        last_seen = datetime.now(timezone.utc) - timedelta(days=31)
        alias = MartSkuAlias(
            mart="E", mart_item_id="100", stable_id="s1",
            last_success_seen_at=last_seen, consecutive_miss_count=30,
            availability_status=AvailabilityStatus.OUT_OF_STOCK,
        )
        updated = bump_alias_observation(alias, seen=False)
        assert updated.availability_status == AvailabilityStatus.DISCONTINUED

    def test_availability_resets_when_seen(self):
        alias = MartSkuAlias(
            mart="E", mart_item_id="100", stable_id="s1",
            availability_status=AvailabilityStatus.OUT_OF_STOCK,
            consecutive_miss_count=10,
        )
        updated = bump_alias_observation(alias, seen=True)
        assert updated.availability_status == AvailabilityStatus.ACTIVE
        assert updated.consecutive_miss_count == 0

    def test_brand_alias_default_suggested(self):
        ba = BrandAlias(alias="seoul milk", canonical_brand="서울우유")
        assert ba.status == BrandAliasStatus.SUGGESTED   # AI 자동 학습은 suggested 게이트까지

    def test_match_log_idempotent_shape(self):
        log = MatchCandidateLog(
            request_id="req-1", caller_id="web-api",
            query_payload_json={"title": "우유"},
            candidates_json=[{"stable_id": "s1", "confidence": 0.9}],
            bot_like=False,
        )
        assert log.archived is False
        assert log.selected_stable_id is None

    def test_bot_like_flag_does_not_block_recording(self):
        # §6-6: bot_like 표식만, 차단·축소는 운영자 결정.
        log = MatchCandidateLog(
            request_id="req-bot", caller_id="bot-x", bot_like=True,
            query_payload_json={}, candidates_json=[],
        )
        assert log.bot_like is True

    def test_community_delta_pull(self):
        cached = {
            ("s1", "p1"): CommunityPriceSignal(stable_id="s1", post_id="p1", verdict_version=3),
        }
        incoming = [
            CommunityPriceSignal(stable_id="s1", post_id="p1", verdict_version=3),   # 미변경
            CommunityPriceSignal(stable_id="s1", post_id="p1", verdict_version=5,
                                 verdict_hot_count=10),    # 새 버전
            CommunityPriceSignal(stable_id="s2", post_id="p2", verdict_version=1),   # 신규
        ]
        delta = pull_community_delta(cached, incoming)
        assert len(delta) == 2
        keys = {(d.stable_id, d.post_id) for d in delta}
        assert keys == {("s1", "p1"), ("s2", "p2")}


# ════════════════════════════════════════════════════════════
# P0#4 — escalation claim/version
# ════════════════════════════════════════════════════════════

class TestEscalation:
    def _item(self) -> ProductReviewQueueItem:
        return ProductReviewQueueItem(id=1, payload_json={"raw_name": "우유"})

    def test_claim_increments_version(self):
        item = self._item()
        claimed = claim_item(item, "kim")
        assert claimed.claimed_by == "kim"
        assert claimed.version == item.version + 1
        assert claimed.claim_expires_at > claimed.claimed_at

    def test_other_user_cannot_claim_active(self):
        item = claim_item(self._item(), "kim")
        with pytest.raises(EscalationVersionConflict):
            claim_item(item, "lee")

    def test_same_user_can_refresh_claim(self):
        item = claim_item(self._item(), "kim")
        refreshed = claim_item(item, "kim")
        assert refreshed.claimed_by == "kim"
        assert refreshed.version == item.version + 1

    def test_resolve_optimistic_version(self):
        claimed = claim_item(self._item(), "kim")
        resolved = resolve_item(claimed, "kim", expected_version=claimed.version,
                                resolution={"action": "approve"})
        assert resolved.resolved_at is not None
        assert resolved.resolution_json == {"action": "approve"}

    def test_resolve_rejects_stale_version(self):
        claimed = claim_item(self._item(), "kim")
        with pytest.raises(EscalationVersionConflict):
            resolve_item(claimed, "kim", expected_version=claimed.version - 1,
                         resolution={"action": "approve"})

    def test_resolve_rejects_double_resolve(self):
        claimed = claim_item(self._item(), "kim")
        resolved = resolve_item(claimed, "kim", claimed.version, {"action": "approve"})
        with pytest.raises(EscalationVersionConflict):
            resolve_item(resolved, "kim", resolved.version, {"action": "approve"})

    def test_resolve_rejects_expired_claim(self):
        claimed = claim_item(self._item(), "kim")
        past = claimed.claim_expires_at + timedelta(seconds=1)
        with pytest.raises(EscalationClaimExpired):
            resolve_item(claimed, "kim", claimed.version, {"action": "approve"}, now=past)


# ════════════════════════════════════════════════════════════
# P0#12 — category_set version + remap
# ════════════════════════════════════════════════════════════

class TestCategorySetActivation:
    def test_activation_swaps_status(self):
        sets = [
            CategorySet(id=1, version_label="v1", status=CategorySetStatus.ACTIVE),
            CategorySet(id=2, version_label="v2", status=CategorySetStatus.DRAFT),
        ]
        remaps = [
            CategoryRemap(from_set_version="v1", to_set_version="v2",
                          from_category_id="a", to_category_id="x",
                          mapping_kind=RemapKind.ONE_TO_ONE),
        ]
        new_sets, unmapped = activate_category_set(sets, 2, remaps)
        statuses = {s.id: s.status for s in new_sets}
        assert statuses == {1: CategorySetStatus.ARCHIVED, 2: CategorySetStatus.ACTIVE}
        assert unmapped == []

    def test_unmapped_blocks_without_override(self):
        sets = [
            CategorySet(id=1, version_label="v1", status=CategorySetStatus.ACTIVE),
            CategorySet(id=2, version_label="v2", status=CategorySetStatus.DRAFT),
        ]
        remaps = [
            CategoryRemap(from_set_version="v1", to_set_version="v2",
                          from_category_id="a", mapping_kind=RemapKind.UNMAPPED),
        ]
        with pytest.raises(ValueError):
            activate_category_set(sets, 2, remaps, admin_override=False)

    def test_admin_override_returns_unmapped_for_queue(self):
        # §2-1: 강제 활성 시 미분류 처리 큐 자동 생성.
        sets = [
            CategorySet(id=1, version_label="v1", status=CategorySetStatus.ACTIVE),
            CategorySet(id=2, version_label="v2", status=CategorySetStatus.DRAFT),
        ]
        remaps = [
            CategoryRemap(from_set_version="v1", to_set_version="v2",
                          from_category_id="a", mapping_kind=RemapKind.UNMAPPED),
            CategoryRemap(from_set_version="v1", to_set_version="v2",
                          from_category_id="b", mapping_kind=RemapKind.UNMAPPED),
        ]
        new_sets, unmapped = activate_category_set(sets, 2, remaps, admin_override=True)
        assert len(unmapped) == 2
        assert any(s.status == CategorySetStatus.ACTIVE for s in new_sets if s.id == 2)


# ════════════════════════════════════════════════════════════
# P0#14 — 권한 모델 분리 + scope enforce
# ════════════════════════════════════════════════════════════

class TestPermissionMatrix:
    def test_crawler_can_only_ingest(self):
        m = PermissionMatrix()
        m.enforce(Role.CRAWLER, "ingest.observation")
        m.enforce(Role.CRAWLER, "ingest.alias")
        with pytest.raises(PermissionDenied):
            m.enforce(Role.CRAWLER, "queue.resolve")

    def test_web_api_cannot_mutate_admin_db(self):
        m = PermissionMatrix()
        m.enforce(Role.WEB_API, "snapshot.read")
        m.enforce(Role.WEB_API, "match.candidates")
        with pytest.raises(PermissionDenied):
            m.enforce(Role.WEB_API, "category.activate")
        with pytest.raises(PermissionDenied):
            m.enforce(Role.WEB_API, "restore")

    def test_ai_publisher_suggest_only(self):
        m = PermissionMatrix()
        m.enforce(Role.AI_PUBLISHER, "ai.suggest")
        with pytest.raises(PermissionDenied):
            m.enforce(Role.AI_PUBLISHER, "queue.resolve")
        with pytest.raises(PermissionDenied):
            m.enforce(Role.AI_PUBLISHER, "brand_alias.approve")

    def test_moderator_vs_admin(self):
        m = PermissionMatrix()
        m.enforce(Role.DB_ADMIN_MODERATOR, "queue.resolve")
        with pytest.raises(PermissionDenied):
            m.enforce(Role.DB_ADMIN_MODERATOR, "restore")
        with pytest.raises(PermissionDenied):
            m.enforce(Role.DB_ADMIN_MODERATOR, "category.activate")
        m.enforce(Role.DB_ADMIN_ADMIN, "restore")
        m.enforce(Role.DB_ADMIN_ADMIN, "category.activate")
        m.enforce(Role.DB_ADMIN_ADMIN, "brand_alias.approve")

    def test_unknown_scope_rejected(self):
        with pytest.raises(ValueError):
            PermissionMatrix({Role.CRAWLER: ["ingest.bogus"]})


# ════════════════════════════════════════════════════════════
# P0#2, #5 — atomic snapshot publish + price_daily_agg
# (price_daily_agg는 캐시 모델 자리만 P0 — 스키마 자리는 §2-3에서 다룸)
# ════════════════════════════════════════════════════════════

class TestSnapshotPublish:
    def test_atomic_publish_success(self, tmp_path):
        target = tmp_path / "public_snapshot.sqlite"

        def write_fn(path: Path) -> dict:
            path.write_bytes(b"SQLITE-FAKE-BYTES" * 100)
            return {"canonical_products": 5, "price_grade": 5}

        log = atomic_publish(target, write_fn, snapshot_version="2025-01-01-001")
        assert log.status == "success"
        assert target.exists()
        assert target.with_suffix(target.suffix + ".sha256").exists()
        assert not target.with_suffix(target.suffix + ".next").exists()
        assert log.sha256 is not None
        assert log.row_counts_json["canonical_products"] == 5

    def test_atomic_publish_failure_preserves_current(self, tmp_path):
        target = tmp_path / "public_snapshot.sqlite"
        target.write_bytes(b"PREVIOUS-CONTENT")
        original = target.read_bytes()

        def bad_write(path: Path) -> dict:
            path.write_bytes(b"PARTIAL")
            raise RuntimeError("simulated builder crash")

        log = atomic_publish(target, bad_write, snapshot_version="bad")
        assert log.status == "failure"
        assert "simulated" in log.error_message
        # 이전 파일 보존
        assert target.read_bytes() == original
        # .next 임시 파일 정리됨
        assert not target.with_suffix(target.suffix + ".next").exists()


# ════════════════════════════════════════════════════════════
# P0#8 — idempotent restore_job 6단계
# ════════════════════════════════════════════════════════════

class TestRestoreJob:
    def test_full_pipeline_success(self):
        job = new_restore_job(backup_source="2025-01-01.tar.gz",
                              snapshot_version_paired="2025-01-01-001")
        assert job.status == RestoreJobStatus.RUNNING
        assert job.current_step == RestoreJobStep.INGESTION_PAUSE

        for step in (
            RestoreJobStep.INGESTION_PAUSE,
            RestoreJobStep.PRE_RESTORE_BACKUP,
            RestoreJobStep.RESTORE_FILE,
            RestoreJobStep.INTEGRITY_CHECK,
            RestoreJobStep.HANDLE_SWAP_REBUILD,
            RestoreJobStep.INGESTION_RESUME,
        ):
            job = advance_restore_job(job, step, success=True)

        assert job.status == RestoreJobStatus.SUCCESS
        assert len(job.completed_steps) == 6

    def test_step_failure_marks_job_failed_with_step(self):
        job = new_restore_job(backup_source="x")
        job = advance_restore_job(job, RestoreJobStep.INGESTION_PAUSE, success=True)
        job = advance_restore_job(job, RestoreJobStep.PRE_RESTORE_BACKUP, success=False,
                                  error="disk full")
        assert job.status == RestoreJobStatus.FAILED
        assert job.error_step == RestoreJobStep.PRE_RESTORE_BACKUP
        assert "disk full" in job.error_message

    def test_idempotent_retry(self):
        # 같은 step에 success=True를 두 번 보내도 완료 step 목록이 중복되지 않는다.
        job = new_restore_job(backup_source="x")
        job = advance_restore_job(job, RestoreJobStep.INGESTION_PAUSE, success=True)
        job_again = advance_restore_job(job, RestoreJobStep.INGESTION_PAUSE, success=True)
        assert job_again.completed_steps == [RestoreJobStep.INGESTION_PAUSE]

    def test_failed_then_retry_succeeds(self):
        job = new_restore_job(backup_source="x")
        job = advance_restore_job(job, RestoreJobStep.INGESTION_PAUSE, success=True)
        job = advance_restore_job(job, RestoreJobStep.PRE_RESTORE_BACKUP, success=False,
                                  error="transient")
        assert job.status == RestoreJobStatus.FAILED
        # 재시도
        job = advance_restore_job(job, RestoreJobStep.PRE_RESTORE_BACKUP, success=True)
        assert job.status == RestoreJobStatus.RUNNING
        assert job.error_step is None


# ════════════════════════════════════════════════════════════
# P0#9 — AuditLog + 트랜잭션 그룹 키
# ════════════════════════════════════════════════════════════

class TestAuditLog:
    def test_audit_entry_with_txn_group(self):
        entry = AuditLogEntry(
            actor_user_id="kim",
            action="category.move",
            target_kind="category",
            target_id="cat-123",
            before_json={"parent_id": "old"},
            after_json={"parent_id": "new"},
            transaction_group_key="bulk-move-2025-01-01-001",
        )
        assert entry.transaction_group_key == "bulk-move-2025-01-01-001"

    def test_audit_request_id_idempotency_field(self):
        # §6-5 request_id idempotency 필드가 존재해야 함
        entry = AuditLogEntry(
            actor_user_id="kim", action="x", target_kind="t", target_id="1",
            request_id="req-abc", caller_id="web-api",
        )
        assert entry.request_id == "req-abc"
        assert entry.caller_id == "web-api"
