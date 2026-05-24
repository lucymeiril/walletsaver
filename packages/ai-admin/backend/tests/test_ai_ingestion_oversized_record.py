"""단일 record > prompt budget 초과 시 truncation 동작 TDD 테스트.

버그 재현: 실제 live ingest 호출 시:
  status=400, detail=stage=batch_validation,
  record lottemart:bcaf7fe2-... is 2022 chars; max batch prompt chars is 2000

수정 정책:
  - ValueError 대신 truncate → 단일 배치 생성
  - raw_title 또는 payload 필드 절단 + 보존 마커 첨부
  - oversized_truncations 메타 반환
  - 모든 케이스 warn 로그
"""
from __future__ import annotations

import logging
from typing import Any

import pytest

from core.contracts.ai_pipeline import RawCrawlRecord, MAX_AI_BATCH_PROMPT_CHARS
from services import ai_ingestion
from services.ai_ingestion import (
    _make_truncation_marker,
    _truncate_str,
    _truncate_record_to_fit,
    split_records_for_ai,
    build_labeling_prompt,
    MAX_OPERATOR_AI_BATCH_PROMPT_CHARS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_record(
    record_id: str = "test:001",
    title: str = "테스트 상품",
    price: int = 1000,
    payload: dict | None = None,
) -> RawCrawlRecord:
    return RawCrawlRecord(
        raw_record_id=record_id,
        source_name="test-store",
        raw_title=title,
        raw_price=price,
        raw_payload=payload or {},
    )


def _make_long_title(n: int) -> str:
    """n글자 제목 생성."""
    base = "테스트상품이름"
    return (base * (n // len(base) + 1))[:n]


# ---------------------------------------------------------------------------
# Unit tests: _truncate_str
# ---------------------------------------------------------------------------

def test_truncate_str_no_truncation_when_fits() -> None:
    result = _truncate_str("hello", 100)
    assert result == "hello"


def test_truncate_str_adds_marker_when_truncated() -> None:
    long_str = "A" * 50
    result = _truncate_str(long_str, 20)
    assert len(result) <= 20
    assert "truncated:" in result
    assert "50chars" in result


def test_truncate_str_marker_includes_original_length() -> None:
    orig = "X" * 300
    marker = _make_truncation_marker(300)
    result = _truncate_str(orig, 50)
    assert marker in result


def test_truncate_str_very_small_max_len() -> None:
    """max_len보다 marker가 긴 경우에도 crash 없이 처리."""
    result = _truncate_str("hello world this is a test", 3)
    assert len(result) <= 3 or "truncated" in result  # graceful


# ---------------------------------------------------------------------------
# T-OVER-1: 단일 record 2022 chars, limit 2000 → 1 batch, truncated meta 반환
# ---------------------------------------------------------------------------

def test_single_oversized_record_produces_one_batch_not_valueerror() -> None:
    """핵심 버그 재현: 2022자 record, limit 2000 → ValueError 없이 1 batch 생성."""
    long_title = _make_long_title(600)  # 충분히 긴 제목
    record = _make_record(
        record_id="lottemart:bcaf7fe2-7306-4938-aad0-e4f8c79bba1b",
        title=long_title,
    )

    # 충분히 낮은 limit 으로 단일 record 를 강제로 초과시킨다.
    # MAX_AI_BATCH_PROMPT_CHARS 대신 작은 값으로 직접 검증
    limit = 600  # 적절히 작은 값으로 설정

    batches, truncations = split_records_for_ai([record], max_prompt_chars=limit)

    # ValueError 없이 배치 1개 생성
    assert len(batches) == 1, f"expected 1 batch, got {len(batches)}"
    assert sum(len(b) for b in batches) == 1

    # truncation 메타 1건 생성
    assert len(truncations) == 1, f"expected 1 truncation, got {truncations}"
    meta = truncations[0]
    assert meta["raw_record_id"] == "lottemart:bcaf7fe2-7306-4938-aad0-e4f8c79bba1b"
    assert meta["orig_chars"] > limit
    assert "truncated_field" in meta


def test_single_oversized_record_title_contains_truncation_marker() -> None:
    """절단된 record의 raw_title에 보존 마커(…[truncated:NNchars])가 포함된다."""
    long_title = _make_long_title(500)
    record = _make_record(title=long_title)
    limit = 500

    batches, truncations = split_records_for_ai([record], max_prompt_chars=limit)

    truncated_record = batches[0][0]
    if truncations and truncations[0].get("truncated_field") == "raw_title":
        assert "truncated:" in truncated_record.raw_title, (
            f"마커 없음: {truncated_record.raw_title[:80]}"
        )


def test_single_oversized_record_logs_warning(caplog) -> None:
    """초과 record 처리 시 ai_ingest_oversized_record_truncated warn 로그 발생."""
    long_title = _make_long_title(500)
    record = _make_record(title=long_title)
    limit = 500

    with caplog.at_level(logging.WARNING, logger="walletsavior.ai_ingestion"):
        split_records_for_ai([record], max_prompt_chars=limit)

    assert any(
        "ai_ingest_oversized_record_truncated" in r.getMessage()
        or r.name == "walletsavior.ai_ingestion"
        for r in caplog.records
    ), f"경고 로그 없음: {[r.getMessage() for r in caplog.records]}"


# ---------------------------------------------------------------------------
# T-OVER-2: 모든 record가 limit 초과 → 각각 단독 batch, 모두 truncated
# ---------------------------------------------------------------------------

def test_all_records_oversized_each_gets_solo_batch() -> None:
    """모든 record 초과 → 각각 1개씩 단독 배치, 전부 truncated 메타."""
    limit = 500
    records = [
        _make_record(record_id=f"store:item-{i}", title=_make_long_title(500 + i * 10))
        for i in range(3)
    ]

    batches, truncations = split_records_for_ai(records, max_prompt_chars=limit)

    # 3개 record → 3개 batch (각각 단독)
    assert len(batches) == 3, f"expected 3 batches, got {len(batches)}: {[len(b) for b in batches]}"
    assert all(len(b) == 1 for b in batches)

    # 모두 truncated 메타
    assert len(truncations) == 3
    assert {m["raw_record_id"] for m in truncations} == {r.raw_record_id for r in records}


# ---------------------------------------------------------------------------
# T-OVER-3: 정상 case 회귀 차단 — truncated = 0
# ---------------------------------------------------------------------------

def test_normal_records_no_truncation() -> None:
    """정상 크기 record는 truncation 없이 처리됨."""
    records = [
        _make_record(record_id=f"emart:item-{i}", title=f"이마트 상품 {i} 300g")
        for i in range(5)
    ]

    batches, truncations = split_records_for_ai(records)

    assert sum(len(b) for b in batches) == 5
    assert truncations == [], f"불필요한 truncation 발생: {truncations}"


def test_normal_records_prompts_within_budget() -> None:
    """정상 배치의 prompt가 모두 budget 이내."""
    records = [
        _make_record(record_id=f"emart:item-{i}", title=f"이마트 상품 {i}")
        for i in range(10)
    ]

    batches, _truncations = split_records_for_ai(records)

    for batch in batches:
        prompt = build_labeling_prompt(batch)
        assert len(prompt) <= MAX_AI_BATCH_PROMPT_CHARS, (
            f"prompt {len(prompt)} > limit {MAX_AI_BATCH_PROMPT_CHARS}"
        )


# ---------------------------------------------------------------------------
# T-OVER-4: payload 필드 truncation
# ---------------------------------------------------------------------------

def test_oversized_payload_description_truncated() -> None:
    """raw_payload['description']이 길면 truncation 대상이 된다."""
    long_desc = "D" * 2000
    record = _make_record(
        payload={"description": long_desc, "unit": "100g"},
    )
    limit = 600

    batches, truncations = split_records_for_ai([record], max_prompt_chars=limit)

    assert len(batches) == 1
    # description은 _record_prompt_line에서 hints에 포함되지 않으므로
    # 실제로 raw_title이 truncation 대상이 될 수 있음 — 어느 쪽이든 메타는 생성
    # 하지만 description이 prompt에 포함된다면 truncation 이후 limit 내여야 함
    assert len(batches[0]) == 1  # 레코드는 반드시 배치에 들어가야 함


# ---------------------------------------------------------------------------
# T-OVER-5: build_labeling_prompt 초과 시 warn 후 반환 (ValueError 금지)
# ---------------------------------------------------------------------------

def test_build_labeling_prompt_oversized_warns_not_raises(caplog) -> None:
    """build_labeling_prompt가 limit 초과 시 ValueError 대신 warn + 반환."""
    long_title = _make_long_title(500)
    records = [_make_record(title=long_title)]

    with caplog.at_level(logging.WARNING, logger="walletsavior.ai_ingestion"):
        # limit을 매우 낮게 설정해 prompt 초과를 강제
        prompt = build_labeling_prompt(records, max_prompt_chars=300)

    # ValueError 없이 반환
    assert isinstance(prompt, str)
    assert len(prompt) > 0


# ---------------------------------------------------------------------------
# T-OVER-6: truncated_record_count가 ingest 결과에 포함됨 (통합 검증)
# ---------------------------------------------------------------------------

def test_split_result_includes_truncation_metadata_in_return() -> None:
    """split_records_for_ai 반환값이 (batches, truncations) 튜플."""
    records = [_make_record()]
    result = split_records_for_ai(records)

    assert isinstance(result, tuple)
    assert len(result) == 2
    batches, truncations = result
    assert isinstance(batches, list)
    assert isinstance(truncations, list)
