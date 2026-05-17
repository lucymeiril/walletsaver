"""배치 크기 축소 재시도 + 단일 아이템 실패 시 인간 큐 폴백 메커니즘 TDD 테스트.

테스트 대상: _call_provider_with_shrink_retries()
동작 명세:
  - 첫 호출 실패(retryable) → N>=2이면 절반 분할 재시도, N==1이면 fallback
  - non-retryable 에러 → 즉시 raise (분할 없음)
  - 성공 시 빈 응답 → retryable로 처리
  - 성공 시 일부 누락 → 누락 아이템에 대해 shrink 재귀 적용
  - shrink_log로 모든 시도 기록
"""
from __future__ import annotations

from typing import Any

import pytest

from core.contracts.ai_pipeline import RawCrawlRecord
from core.contracts.control_plane import ProviderConfigContract
from providers.google_genai import ProviderResponseError
from services import ai_ingestion
from services.ai_ingestion import (
    AIIngestionError,
    _call_provider_with_shrink_retries,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _record(record_id: str) -> RawCrawlRecord:
    return RawCrawlRecord(
        raw_record_id=record_id,
        source_name="test-store",
        raw_title=f"테스트 상품 {record_id}",
        raw_price=1000,
    )


def _item(record_id: str) -> dict[str, Any]:
    """provider 응답 아이템 최소 구조."""
    return {
        "raw_record_id": record_id,
        "canonical_name": f"상품 {record_id}",
        "source_title": f"테스트 상품 {record_id}",
        "sale_price": 1000,
        "category_id": "food.general",
        "keywords": ["테스트"],
        "aliases": [],
        "attributes": {},
        "package_quantity": 1,
        "package_unit": "개",
        "display_unit": "1개",
        "bundle_count": 1,
        "standard_unit": None,
        "standard_unit_price": None,
        "price_per_100g": None,
        "confidence": 0.8,
        "notes": "test",
    }


def _transient_error(msg: str = "quota exceeded 429") -> ProviderResponseError:
    return ProviderResponseError(msg, provider_id="test", model="test-model")


def _non_retryable_error() -> ProviderResponseError:
    # "400" 문자열은 _TRANSIENT_PROVIDER_MARKERS에 없으므로 non-retryable
    return ProviderResponseError(
        "invalid request 400 bad request schema",
        provider_id="test",
        model="test-model",
    )


@pytest.fixture()
def config() -> ProviderConfigContract:
    return ProviderConfigContract(
        provider_id="test-provider",
        provider_kind="gemini",
        display_name="Test Provider",
        default_model="test-model",
    )


@pytest.fixture()
def provider_ref(config: ProviderConfigContract):
    return ai_ingestion._provider_ref(config)


def _make_scripted_provider(config: ProviderConfigContract, side_effects: list):
    """호출 순서에 따라 응답 또는 예외를 돌려주는 provider mock."""

    class ScriptedProvider:
        provider_mode = "offline"

        def __init__(self) -> None:
            self.config = config
            self._effects = list(side_effects)
            self._idx = 0
            self.call_count = 0

        def call(self, *, prompt: str, schema=None) -> dict:
            self.call_count += 1
            if self._idx >= len(self._effects):
                raise AssertionError(
                    f"ScriptedProvider: 예상보다 많은 호출 (call #{self.call_count}); "
                    f"총 {len(self._effects)}개 side_effect만 등록됨"
                )
            effect = self._effects[self._idx]
            self._idx += 1
            if isinstance(effect, Exception):
                raise effect
            return effect

    return ScriptedProvider()


def _call(
    records: list[RawCrawlRecord],
    provider,
    provider_ref,
    monkeypatch: pytest.MonkeyPatch,
):
    """테스트에서 반복 사용하는 shrink_retries 호출 헬퍼.

    build_labeling_prompt를 패치해 프롬프트 크기 제한이 테스트에 영향을 주지 않도록 한다.
    """
    monkeypatch.setattr(ai_ingestion, "_sleep", lambda _: None)
    # 실제 프롬프트 생성은 테스트 관심사가 아니므로 경량 버전으로 대체한다.
    monkeypatch.setattr(
        ai_ingestion,
        "build_labeling_prompt",
        lambda recs, **_kw: "prompt: " + ",".join(r.raw_record_id for r in recs),
    )
    return _call_provider_with_shrink_retries(
        records=records,
        provider=provider,
        provider_ref=provider_ref,
        provider_id="test-provider",
        model="test-model",
        raw_batch_id="raw-test",
        ai_batch_id="ai-test",
        keyword_catalog=[],
        learned_keyword_knowledge=[],
    )


# ---------------------------------------------------------------------------
# T1: 4-아이템, 4→실패, 첫2→ok, 나머지2→실패, 1·1→모두ok → proposals 4건, fallback 없음
# ---------------------------------------------------------------------------
def test_t1_shrink_splits_until_all_succeed(
    config: ProviderConfigContract,
    provider_ref,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T1: 4→실패, [r1,r2]→ok, [r3,r4]→실패, r3→ok, r4→ok.
    최종 4 proposals 반환, shrink_log는 5개 엔트리.
    """
    records = [_record(f"r{i}") for i in range(1, 5)]  # r1..r4
    r1, r2, r3, r4 = records

    side_effects = [
        _transient_error(),                           # 1. N=4 → fail
        {"items": [_item("r1"), _item("r2")]},        # 2. N=2 [r1,r2] → ok
        _transient_error(),                           # 3. N=2 [r3,r4] → fail
        {"items": [_item("r3")]},                     # 4. N=1 [r3] → ok
        {"items": [_item("r4")]},                     # 5. N=1 [r4] → ok
    ]
    provider = _make_scripted_provider(config, side_effects)

    proposals, _kw, shrink_log = _call(records, provider, provider_ref, monkeypatch)

    # 4개 proposals 모두 반환
    returned_ids = {
        p.provenance.raw_record_id
        for p in proposals
    }
    assert returned_ids == {"r1", "r2", "r3", "r4"}, f"returned ids: {returned_ids}"

    # provider는 정확히 5번 호출
    assert provider.call_count == 5

    # shrink_log 내용 확인
    assert len(shrink_log) == 5, f"shrink_log: {shrink_log}"
    assert shrink_log[0] == {"batch_size": 4, "outcome": "retryable_error"}
    assert shrink_log[1] == {"batch_size": 2, "outcome": "ok"}
    assert shrink_log[2] == {"batch_size": 2, "outcome": "retryable_error"}
    assert shrink_log[3] == {"batch_size": 1, "outcome": "ok"}
    assert shrink_log[4] == {"batch_size": 1, "outcome": "ok"}

    # fallback 없음
    assert not any(e.get("fallback") for e in shrink_log)


# ---------------------------------------------------------------------------
# T2: 1-아이템, retryable 실패만 → reviewer-safe fallback 1건, fallback=True
# ---------------------------------------------------------------------------
def test_t2_single_item_retryable_failure_goes_to_fallback(
    config: ProviderConfigContract,
    provider_ref,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T2: N=1, retryable 실패 → confidence=0.42 fallback proposal, shrink_log에 fallback=True."""
    records = [_record("item-1")]

    side_effects = [_transient_error()]  # N=1 → 즉시 fallback (split 없음)
    provider = _make_scripted_provider(config, side_effects)

    proposals, _kw, shrink_log = _call(records, provider, provider_ref, monkeypatch)

    # fallback proposal 1건 반환
    assert len(proposals) > 0
    # fallback은 confidence=0.42로 생성된다
    confidences = {p.provenance.confidence for p in proposals}
    assert 0.42 in confidences, f"expected 0.42 confidence in {confidences}"

    # shrink_log: retryable_error + fallback
    assert len(shrink_log) == 2
    assert shrink_log[0] == {"batch_size": 1, "outcome": "retryable_error"}
    assert shrink_log[1] == {"batch_size": 1, "outcome": "fallback", "fallback": True}

    # manifest에 fallback=True 마킹
    assert any(e.get("fallback") is True for e in shrink_log)


# ---------------------------------------------------------------------------
# T3: non-retryable 에러 → 즉시 raise, 분할 없음
# ---------------------------------------------------------------------------
def test_t3_non_retryable_error_raises_immediately(
    config: ProviderConfigContract,
    provider_ref,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T3: non-retryable 에러(400) → AIIngestionError 즉시 raise, provider 1회만 호출."""
    records = [_record(f"r{i}") for i in range(1, 5)]

    side_effects = [_non_retryable_error()]
    provider = _make_scripted_provider(config, side_effects)

    with pytest.raises(AIIngestionError) as exc_info:
        _call(records, provider, provider_ref, monkeypatch)

    # provider는 1번만 호출 (분할 재시도 없음)
    assert provider.call_count == 1
    assert exc_info.value.stage == "provider_call"


# ---------------------------------------------------------------------------
# T4: 8-아이템, 첫 호출 ok → 1번 호출로 끝 (분할 없음)
# ---------------------------------------------------------------------------
def test_t4_no_failure_no_split(
    config: ProviderConfigContract,
    provider_ref,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T4: N=8, 첫 호출에서 전부 반환 → provider 1번 호출, shrink_log 1엔트리(ok)."""
    records = [_record(f"r{i}") for i in range(1, 9)]

    items_response = {"items": [_item(f"r{i}") for i in range(1, 9)]}
    provider = _make_scripted_provider(config, [items_response])

    proposals, _kw, shrink_log = _call(records, provider, provider_ref, monkeypatch)

    assert provider.call_count == 1
    assert shrink_log == [{"batch_size": 8, "outcome": "ok"}]

    returned_ids = {p.provenance.raw_record_id for p in proposals}
    assert returned_ids == {f"r{i}" for i in range(1, 9)}


# ---------------------------------------------------------------------------
# T5: 2-아이템, 첫 호출 ok지만 1건만 반환 → missing 1건에 대해 fallback
# ---------------------------------------------------------------------------
def test_t5_partial_response_missing_item_goes_to_fallback(
    config: ProviderConfigContract,
    provider_ref,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T5: N=2, 첫 호출 ok지만 r2 누락 → r2에 대해 fallback.
    _provider_response_id_validation과 협력해 누락 감지.
    """
    records = [_record("r1"), _record("r2")]

    side_effects = [
        {"items": [_item("r1")]},   # 1. N=2 → ok, r1만 반환 (r2 누락)
        _transient_error(),          # 2. N=1 [r2] → retryable → fallback
    ]
    provider = _make_scripted_provider(config, side_effects)

    proposals, _kw, shrink_log = _call(records, provider, provider_ref, monkeypatch)

    # r1 proposal + r2 fallback proposal 모두 있어야 한다
    returned_ids = {p.provenance.raw_record_id for p in proposals}
    assert "r1" in returned_ids, f"r1 not in {returned_ids}"
    assert "r2" in returned_ids, f"r2 fallback not in {returned_ids}"

    # r2의 fallback proposal은 confidence=0.42
    r2_confs = {
        p.provenance.confidence
        for p in proposals
        if p.provenance.raw_record_id == "r2"
    }
    assert 0.42 in r2_confs, f"r2 fallback confidence expected 0.42, got {r2_confs}"

    # shrink_log: 2-ok, 1-retryable_error, 1-fallback
    assert shrink_log[0] == {"batch_size": 2, "outcome": "ok"}
    fallback_entries = [e for e in shrink_log if e.get("fallback")]
    assert len(fallback_entries) == 1, f"expected 1 fallback entry, got {shrink_log}"

    # provider는 정확히 2번 호출 (4-item call + 1-item missing retry)
    assert provider.call_count == 2
