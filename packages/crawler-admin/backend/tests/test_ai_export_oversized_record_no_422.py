"""Regression: 단일 record 가 prompt 한도를 넘어도 422 로 전체 배치를 거절하지 않는다.

사용자가 라이브에서 본 증상:
    POST /api/ai-export/raw-records/label HTTP/1.1 422 Unprocessable Content
    ai_ingest_oversized_record_truncated  (×12 연속)

근본 원인:
    - shared MAX_AI_BATCH_PROMPT_CHARS=2000 가 너무 작아 2022자 단일 record 거절
    - crawler-admin split_raw_records_for_ai 가 RawExportError → 422 로 즉시 raise

수정:
    - MAX_AI_BATCH_PROMPT_CHARS 2000 → 8000 (Gemma 4 26B context 활용)
    - split_raw_records_for_ai: 단일 oversized record 는 solo batch 격리
"""
from __future__ import annotations

from core.contracts import MAX_AI_BATCH_PROMPT_CHARS, RawCrawlRecord
from pipeline.ai_export import split_raw_records_for_ai


def _record(rid: str, title_chars: int) -> RawCrawlRecord:
    return RawCrawlRecord(
        raw_record_id=rid,
        source_name="emart",
        raw_title="가" * title_chars,
        raw_payload={},
    )


def test_2022_char_record_no_longer_raises():
    """직전 라운드 (한도 2000) 에선 422 였지만, 8000 한도에서는 정상 통과."""
    rec = _record("R1", 2022)
    batches = split_raw_records_for_ai([rec])
    assert len(batches) == 1
    assert batches[0][0].raw_record_id == "R1"
    assert MAX_AI_BATCH_PROMPT_CHARS >= 2022


def test_oversized_record_goes_to_solo_batch_not_raise():
    """8000자 이상이면 거절 대신 solo batch 로 격리 — ai-admin 가 truncation 메타로 보고."""
    rec = _record("BIG", MAX_AI_BATCH_PROMPT_CHARS + 500)
    batches = split_raw_records_for_ai([rec])
    assert len(batches) == 1
    assert batches[0] == [rec]


def test_mixed_normal_and_oversized_records_isolate_correctly():
    small1 = _record("S1", 100)
    small2 = _record("S2", 100)
    big = _record("BIG", MAX_AI_BATCH_PROMPT_CHARS + 500)
    small3 = _record("S3", 100)
    batches = split_raw_records_for_ai([small1, small2, big, small3])
    # 직전 구현은 BIG 에서 RawExportError. 새 구현은:
    # [S1, S2] flush → [BIG] solo → [S3]
    ids = [[r.raw_record_id for r in b] for b in batches]
    assert ["BIG"] in ids, f"big record must be in its own batch, got {ids}"
    flat = [rid for batch in ids for rid in batch]
    assert flat == ["S1", "S2", "BIG", "S3"]
