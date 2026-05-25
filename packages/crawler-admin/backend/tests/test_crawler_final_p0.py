"""crawler-FINAL P0 — drift 감지 4-라벨 / min count gate / tracked_urls / workbench capture / circuit breaker 확장 테스트."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from pipeline.circuit_breaker import (
    AttemptCostInputs,
    BreakerKey,
    CircuitBreakerRegistry,
    attempt_cost_allows,
    get_global_registry,
)
from pipeline.drift_detector import (
    DriftLabel,
    DriftSignals,
    classify,
)
from pipeline.min_count_gate import (
    GateStatus,
    LIVE_THRESHOLDS,
    check,
    threshold_for,
)
from pipeline.tracked_urls import (
    DemotionRule,
    RefreshTier,
    RegisteredBy,
    TrackedUrl,
    TrackedUrlStatus,
    TrackedUrlStore,
    auto_demote,
)
from pipeline.workbench_capture import (
    CaptureGrade,
    Fixture,
    InstantHarvest,
    SessionAsset,
    TrackedUrlEntry,
    WorkbenchCapture,
    WorkbenchCaptureStore,
)


# ── drift_detector 4-라벨 ─────────────────────────────────────────


def test_drift_parser_drift_when_selector_drop_and_fixture_fail():
    s = DriftSignals(
        source_id="lm",
        selector_hit_rate=0.4,
        baseline_selector_hit_rate=0.9,
        fixture_passes=False,
    )
    assert classify(s).label == DriftLabel.PARSER_DRIFT


def test_drift_session_state_loss_when_login_probe_fails():
    s = DriftSignals(source_id="arca", login_probe_ok=False)
    v = classify(s)
    assert v.label == DriftLabel.SESSION_STATE_LOSS
    assert "login_probe" in v.reasons[0]


def test_drift_catalog_business_change_when_titles_shift():
    s = DriftSignals(source_id="em", title_change_ratio=0.5)
    assert classify(s).label == DriftLabel.CATALOG_BUSINESS_CHANGE


def test_drift_source_volume_anomaly_row_drop_but_selectors_ok():
    """행사 종료 패턴 — selector hit 유지 + row count 만 ↓."""
    s = DriftSignals(
        source_id="em",
        row_count=100,
        baseline_row_count=300,
        selector_hit_rate=0.95,
        baseline_selector_hit_rate=0.96,
    )
    assert classify(s).label == DriftLabel.SOURCE_VOLUME_ANOMALY


def test_drift_none_when_signals_healthy():
    s = DriftSignals(
        source_id="x",
        row_count=300,
        baseline_row_count=290,
        selector_hit_rate=0.95,
        baseline_selector_hit_rate=0.96,
    )
    assert classify(s).label == DriftLabel.NONE


def test_drift_parser_priority_over_volume():
    """parser_drift 가 volume anomaly 보다 우선 (FINAL §4-B 표 순서)."""
    s = DriftSignals(
        source_id="x",
        row_count=10, baseline_row_count=300,
        selector_hit_rate=0.1, baseline_selector_hit_rate=0.95,
        fixture_passes=False,
    )
    assert classify(s).label == DriftLabel.PARSER_DRIFT


# ── min_count_gate ───────────────────────────────────────────────


@pytest.mark.parametrize("mart,th", [("emart", 270), ("lottemart", 240), ("homeplus", 195), ("costco", 900), ("cocodalin", 50)])
def test_min_count_gate_live_thresholds(mart, th):
    assert LIVE_THRESHOLDS[mart] == th


def test_min_count_gate_yaml_overrides_live_baseline():
    assert threshold_for("costco", yaml_minimum=1000) == 1000


def test_min_count_gate_pass_below_and_missing_baseline():
    assert check("lottemart", 250).status == GateStatus.PASS
    assert check("lottemart", 100).status == GateStatus.BELOW
    assert check("unknown_source", 5).status == GateStatus.BASELINE_MISSING


# ── tracked_urls ──────────────────────────────────────────────────


@pytest.fixture
def store(tmp_path: Path) -> TrackedUrlStore:
    return TrackedUrlStore(tmp_path / "tracked.db")


def test_tracked_url_register_and_get(store: TrackedUrlStore):
    e = TrackedUrl(url="https://x/p/1", source_id="coupang", registered_by=RegisteredBy.WORKBENCH.value)
    store.register(e)
    got = store.get("https://x/p/1")
    assert got is not None
    assert got.source_id == "coupang"
    assert got.status == TrackedUrlStatus.ACTIVE.value


def test_tracked_url_status_and_tier_updates(store: TrackedUrlStore):
    e = TrackedUrl(url="https://y/p/2", source_id="coupang")
    store.register(e)
    assert store.update_status("https://y/p/2", TrackedUrlStatus.REVIEW_REQUIRED)
    assert store.update_tier("https://y/p/2", RefreshTier.WEEKLY)
    got = store.get("https://y/p/2")
    assert got.status == TrackedUrlStatus.REVIEW_REQUIRED.value
    assert got.refresh_tier == RefreshTier.WEEKLY.value


def test_tracked_url_auto_demote_no_change_and_failures(store: TrackedUrlStore):
    """30일 가격 변화 없음 → weekly. 14일 연속 failures → stale (자동 삭제 X)."""
    now = time.time()
    store.register(TrackedUrl(
        url="https://a", source_id="s",
        last_price_change_at=now - 31 * 86400,
        refresh_tier=RefreshTier.DAILY.value,
    ))
    store.register(TrackedUrl(
        url="https://b", source_id="s",
        consecutive_failures=14,
    ))
    rep = auto_demote(store, now=now)
    assert rep["demoted_to_weekly"] == 1
    assert rep["moved_to_stale"] == 1
    assert store.get("https://b").status == TrackedUrlStatus.STALE.value
    # 자동 삭제 안 했는지 — record 는 그대로 존재
    assert store.get("https://b") is not None


def test_tracked_url_list_filters(store: TrackedUrlStore):
    store.register(TrackedUrl(url="https://1", source_id="a", status=TrackedUrlStatus.STALE.value))
    store.register(TrackedUrl(url="https://2", source_id="a"))
    store.register(TrackedUrl(url="https://3", source_id="b"))
    assert len(store.list(source_id="a")) == 2
    assert len(store.list(status=TrackedUrlStatus.STALE.value)) == 1


# ── workbench capture 4등급 ───────────────────────────────────────


def test_workbench_capture_has_four_grade_slots():
    c = WorkbenchCapture.new(source_id="s", url="https://x")
    assert c.grades_present() == []
    c.instant_harvest = InstantHarvest(items=[{"name": "a"}])
    c.tracked_url_entries.append(TrackedUrlEntry(url="https://y"))
    c.session_asset = SessionAsset(profile_id="p1")
    c.fixture = Fixture(fixture_id="f1", content_path="/tmp/x.html")
    grades = set(c.grades_present())
    assert grades == {
        CaptureGrade.INSTANT_HARVEST,
        CaptureGrade.TRACKED_URL_ENTRY,
        CaptureGrade.SESSION_ASSET,
        CaptureGrade.FIXTURE,
    }


def test_workbench_capture_store_roundtrip(tmp_path: Path):
    store = WorkbenchCaptureStore(tmp_path / "wb")
    c = WorkbenchCapture.new(source_id="lm", url="https://lottemartzetta.com")
    c.instant_harvest = InstantHarvest(items=[{"name": "milk"}])
    store.save(c)
    loaded = store.load("lm", c.capture_id)
    assert loaded is not None
    assert loaded.instant_harvest.items == [{"name": "milk"}]


def test_instant_harvest_ttl():
    h = InstantHarvest(items=[], captured_at=time.time() - 25 * 3600)
    assert h.is_expired() is True


# ── circuit breaker 확장 — 4-튜플 / attempt_cost ─────────────────


def test_breaker_key_label_includes_all_four_dims():
    k = BreakerKey(source_id="cc", domain="costco.co.kr", egress_ip="10.0.0.1", blocker_signature="akamai_403")
    assert "cc" in k.as_label()
    assert "akamai_403" in k.as_label()
    assert k.as_label().count("|") == 3


def test_attempt_cost_allows_under_budget_and_blocks_over():
    low = AttemptCostInputs(domain_pressure=0.1, worker_pressure=0.1, profile_age=0.1, blocker_severity=0.1, shard_scope=0.1)
    high = AttemptCostInputs(domain_pressure=0.8, worker_pressure=0.8, profile_age=0.8, blocker_severity=0.8, shard_scope=0.8)
    assert attempt_cost_allows(low) is True
    assert attempt_cost_allows(high) is False


@pytest.mark.asyncio
async def test_breaker_registry_returns_same_instance_for_same_key():
    reg = CircuitBreakerRegistry()
    k = BreakerKey(source_id="cc", domain="costco.co.kr")
    b1 = await reg.acquire(k)
    b2 = await reg.acquire(k)
    assert b1 is b2


@pytest.mark.asyncio
async def test_breaker_registry_distinct_for_different_blocker_signatures():
    """같은 source 라도 blocker_signature 가 다르면 별개 breaker — 무한 핑퐁 차단 (FINAL §4-A)."""
    reg = CircuitBreakerRegistry()
    b_waf = await reg.acquire(BreakerKey(source_id="lm", domain="lm.com", blocker_signature="aws_waf_202"))
    b_akamai = await reg.acquire(BreakerKey(source_id="lm", domain="lm.com", blocker_signature="akamai_403"))
    assert b_waf is not b_akamai


def test_get_global_registry_returns_singleton():
    r1 = get_global_registry()
    r2 = get_global_registry()
    assert r1 is r2
