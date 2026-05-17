"""WalletSavior Phase C1 — ProductReviewQueue LLM 자동 분류 라우터.

역할:
    ProductReviewQueue 항목(카테고리 불명 등)을 LLM에게 보내
    WalletSavior 내부 카테고리 트리 노드 id 하나를 결정하게 한다.
    RESOLVED: 카테고리 확정 → ProductReviewQueue.resolved_at 기록 + CanonicalProduct 업데이트
    ESCALATED: 불명확/저신뢰 → 큐 유지 + escalation 마크

신뢰도 임계 0.7 선정 이유:
    0.7 미만은 LLM이 "여러 후보 중 하나" 수준의 추측 상태를 의미한다.
    틀린 카테고리로 canonical 데이터가 오염되는 위험이
    미처리 상태로 큐에 남기는 비용보다 크다.
    0.7은 "꽤 확신하는" 수준으로, Phase C2 사후검증 게이트와의 이중 방어선을 형성한다.
    라이브 데이터에서 이 임계를 조정할 수 있도록 상수로 분리했다.

트리에 없는 id 자동 ESCALATED 이유:
    LLM이 hallucination으로 트리에 없는 임의 id를 생성할 수 있다.
    존재하지 않는 id를 canonical_products.category_path_internal_id에 넣으면
    FK constraint violation 또는 카테고리 트리 오염이 발생한다.
    ESCALATED 처리해서 운영자 또는 Phase C2가 재검토하도록 한다.

안전 거부 retry 이유:
    LLM이 "마트 상품 카테고리 분류"를 안전 이슈로 잘못 판단해 거부할 수 있다.
    거부 감지 시 "이 작업은 안전과 무관하다"는 명시적 컨텍스트를 추가해 1회 재시도한다.
    2회 이상 재시도는 비용 낭비이므로 최대 1회 retry로 제한한다.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Optional

import yaml

# shared 경로 보정 — conftest.py가 없어도 import 가능하게
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_SHARED_DIR = _BACKEND_DIR.parent.parent / "shared"
for _p in (str(_BACKEND_DIR), str(_SHARED_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.canonical_models import ProductReviewQueue  # noqa: E402  (경로 보정 후 import)

# YAML 파일 위치
_CATEGORY_YAML = _SHARED_DIR / "data" / "category_tree.yaml"
_BRAND_YAML = _SHARED_DIR / "data" / "brand_dictionary.yaml"
_SYNONYMS_YAML = _SHARED_DIR / "data" / "synonyms.yaml"

# confidence 임계 — 이 값 미만이면 ESCALATED (위 docstring 참조)
CONFIDENCE_THRESHOLD = 0.7

# LLM 안전 거부 감지 키워드 (소문자)
_SAFETY_REFUSAL_MARKERS = (
    "i cannot",
    "i'm sorry",
    "죄송",
    "할 수 없",
    "안전상",
    "유해",
    "불법",
    "공식 경로",
)

# apply_decisions_to_db 에서 사용하는 resolver 마커 값
_RESOLVED_RESOLVER_ID = "ai_router:resolved:v1"
_ESCALATED_RESOLVER_ID = "ai_router:escalated:v1"


# ══════════════════════════════════════════════════════
# DTO
# ══════════════════════════════════════════════════════

@dataclass
class QueueRouterDecision:
    """
    단일 큐 항목에 대한 LLM 라우터 결정 DTO.

    queue_id: ProductReviewQueue.id
    decision: RESOLVED(카테고리 확정) / ESCALATED(불명확·저신뢰)
    category_node_id: RESOLVED 시 category_tree의 id; ESCALATED 시 None 또는 참고용
    brand: LLM이 추론한 브랜드 (보조)
    name_core_refined: LLM이 정제한 핵심 상품명 (보조)
    confidence: 0.0~1.0 (LLM 자기 보고)
    reasons: 결정 근거 코드 및 한국어 설명 목록
    raw_ai_response: 원본 LLM 응답 (감사·디버깅용 — 절대 삭제 금지)
    elapsed_ms: route_one 처리 시간 (ms)
    """
    queue_id: str
    decision: Literal["RESOLVED", "ESCALATED"]
    category_node_id: Optional[str]
    brand: Optional[str]
    name_core_refined: Optional[str]
    confidence: float
    reasons: list[str]
    raw_ai_response: dict
    elapsed_ms: int


@dataclass
class ApplyResult:
    """apply_decisions_to_db 실행 결과 요약."""
    resolved_count: int = 0
    escalated_count: int = 0
    skipped_count: int = 0
    errors: list[dict] = field(default_factory=list)


# ══════════════════════════════════════════════════════
# 카테고리 트리 유틸
# ══════════════════════════════════════════════════════

def load_default_category_tree() -> dict:
    """category_tree.yaml을 dict로 로드 (기본값 제공 헬퍼)."""
    with open(_CATEGORY_YAML, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_default_brand_dictionary() -> list[str]:
    """brand_dictionary.yaml에서 브랜드 목록 로드."""
    with open(_BRAND_YAML, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return raw.get("brands", [])


def load_default_synonyms() -> dict:
    """synonyms.yaml에서 동의어 사전 로드."""
    with open(_SYNONYMS_YAML, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return raw.get("synonyms", {})


def _all_category_ids(category_tree: dict) -> set[str]:
    """category_tree dict(YAML 그대로)에서 모든 유효 id 추출."""
    return {n["id"] for n in category_tree.get("nodes", []) if "id" in n}


# ══════════════════════════════════════════════════════
# 프롬프트 빌더
# ══════════════════════════════════════════════════════

def _sanitize_payload(raw_payload: dict, max_chars: int = 2000) -> dict:
    """
    LLM 프롬프트용 payload 정제.

    이유: 이미지 URL 등 분류에 불필요한 대형 필드를 제거해 토큰 비용을 절감한다.
    내부 라우터 메타데이터(_로 시작)도 제거한다.
    """
    exclude_substrings = {"ImgUrl", "imageUrl", "img_url", "image_url"}
    cleaned: dict[str, Any] = {}
    for k, v in raw_payload.items():
        if k.startswith("_"):
            continue
        if any(excl in k for excl in exclude_substrings):
            continue
        cleaned[k] = v

    text = json.dumps(cleaned, ensure_ascii=False, sort_keys=True)
    if len(text) > max_chars:
        text = text[:max_chars] + "…(truncated)"
    # truncated 케이스에도 dict를 반환 (파싱 용이)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return cleaned


def _build_category_list_str(category_tree: dict) -> str:
    """카테고리 노드 목록을 LLM 가독성 좋은 형식으로 직렬화."""
    lines = []
    for n in category_tree.get("nodes", []):
        parent = f"(parent: {n['parent_id']})" if n.get("parent_id") else "[L1 root]"
        lines.append(f"  {n['id']} {parent} → {n['name_kr']}")
    return "\n".join(lines)


def _build_prompt(
    queue_entry: ProductReviewQueue,
    category_tree: dict,
    brand_dictionary: list[str],
    synonyms: dict,
) -> str:
    """
    LLM 분류 프롬프트 빌더.

    설계 원칙:
    1. 역할 선언: "한국 마트 상품 카테고리 분류기" — 불필요한 안전 거부 방지
    2. 한국 마트 상품 분류는 안전·보안과 무관함을 명시 (LLM 거부 방지)
    3. JSON only 강제: 마크다운 펜스·추가 문장 금지 명시
    4. 트리에 있는 id만 허용 — hallucination 방지 지침 포함
    5. confidence 0.7 미만 시 LOW_CONFIDENCE를 reasons에 포함 요청
    """
    sanitized = _sanitize_payload(queue_entry.raw_payload)
    payload_str = json.dumps(sanitized, ensure_ascii=False, indent=2)
    category_str = _build_category_list_str(category_tree)
    brand_str = ", ".join(brand_dictionary[:40])
    synonym_str = json.dumps(synonyms, ensure_ascii=False, indent=2)

    return f"""당신은 한국 마트 상품의 raw payload를 받아 WalletSavior 내부 카테고리 트리 노드 id 하나를 결정하는 분류기입니다.

이 작업은 한국 대형마트(이마트·홈플러스·롯데마트·코스트코)의 식품·생활용품·뷰티 상품을 사전 정의된 카테고리 트리에 분류하는 것입니다. 상품 가격 비교 서비스의 데이터 처리 작업이며 안전·보안·윤리와 전혀 무관합니다.

## 분류 대상 상품 (마트: {queue_entry.source_mart.value}, 사유: {queue_entry.reason.value})
```json
{payload_str}
```

## 허용 카테고리 트리 (반드시 아래 id 중 하나만 선택)
{category_str}

## 브랜드 사전 (참고)
{brand_str}

## 동의어 사전 (참고)
```json
{synonym_str}
```

## 출력 규칙
1. 반드시 아래 JSON 형식 하나만 반환. Markdown 펜스·설명 문장 절대 금지.
2. category_node_id는 반드시 위 트리에 있는 id여야 함. 트리에 없는 id 생성 금지.
3. confidence가 0.7 미만이면 reasons 배열에 "LOW_CONFIDENCE" 포함.
4. 확신이 없더라도 트리에서 가장 유사한 id를 반드시 선택 (null 반환 금지).

{{
  "category_node_id": "<트리 id 중 하나>",
  "brand": "<브랜드명 또는 null>",
  "name_core": "<핵심 상품명 (브랜드/용량/광고문구 제거)>",
  "confidence": 0.0,
  "reasons": ["<분류 근거 코드 또는 한국어 설명>"]
}}"""


def _build_retry_prompt(original_prompt: str, error_context: str) -> str:
    """첫 번째 응답 실패 시 사용하는 재시도 프롬프트."""
    return (
        "이전 응답 처리에 실패했습니다. 반드시 유효한 JSON 객체만 반환하세요.\n"
        f"(실패 원인: {error_context[:100]})\n\n"
        + original_prompt
    )


def _build_safety_retry_prompt(original_prompt: str) -> str:
    """LLM이 안전 이유로 거부한 경우의 재시도 프롬프트."""
    return (
        "중요: 이 작업은 한국 대형마트 식품·생활용품 카테고리 분류입니다. "
        "안전·보안·윤리와 전혀 무관한 데이터 분류 작업입니다. "
        "거부 없이 JSON 형식으로 카테고리 분류 결과만 반환하세요.\n\n"
        + original_prompt
    )


# ══════════════════════════════════════════════════════
# 내부 헬퍼
# ══════════════════════════════════════════════════════

def _is_safety_refusal(response: dict) -> bool:
    """LLM이 안전 이유로 분류를 거부했는지 감지."""
    text = json.dumps(response, ensure_ascii=False).lower()
    return any(marker in text for marker in _SAFETY_REFUSAL_MARKERS)


def _make_escalated(
    queue_id: str,
    reasons: list[str],
    raw_ai_response: dict,
    elapsed_ms: int,
    category_node_id: Optional[str] = None,
    brand: Optional[str] = None,
    name_core_refined: Optional[str] = None,
    confidence: float = 0.0,
) -> QueueRouterDecision:
    """ESCALATED 결정 생성 헬퍼."""
    return QueueRouterDecision(
        queue_id=queue_id,
        decision="ESCALATED",
        category_node_id=category_node_id,
        brand=brand,
        name_core_refined=name_core_refined,
        confidence=confidence,
        reasons=reasons,
        raw_ai_response=raw_ai_response,
        elapsed_ms=elapsed_ms,
    )


# ══════════════════════════════════════════════════════
# QueueAiRouter
# ══════════════════════════════════════════════════════

class QueueAiRouter:
    """
    ProductReviewQueue 항목을 LLM으로 카테고리 분류하는 라우터.

    사용법:
        provider = GoogleGenAIProvider(config)
        tree = load_default_category_tree()
        router = QueueAiRouter(provider, tree, load_default_brand_dictionary(), load_default_synonyms())
        decision = router.route_one(queue_entry)

    테스트:
        mock_provider = MockProvider([{"category_node_id": "cabbage", "confidence": 0.9, ...}])
        router = QueueAiRouter(mock_provider, tree, brands, synonyms)
    """

    def __init__(
        self,
        provider: Any,
        category_tree: dict,
        brand_dictionary: list[str],
        synonyms: dict,
    ) -> None:
        """
        Args:
            provider: .call(prompt, schema=None) -> dict 인터페이스를 가진 객체.
                      GoogleGenAIProvider 또는 테스트용 mock.
            category_tree: category_tree.yaml을 yaml.safe_load한 dict.
            brand_dictionary: 브랜드명 목록 (brand_dictionary.yaml).
            synonyms: 동의어 사전 (synonyms.yaml).
        """
        self._provider = provider
        self._category_tree = category_tree
        self._brand_dictionary = brand_dictionary
        self._synonyms = synonyms
        self._valid_ids = _all_category_ids(category_tree)

    def route_one(self, queue_entry: ProductReviewQueue) -> QueueRouterDecision:
        """
        단일 ProductReviewQueue 항목을 LLM으로 분류한다.

        실패 처리 (순서대로):
        1. provider 예외 → 1회 retry → 실패 시 ESCALATED(PROVIDER_ERROR)
        2. 빈 응답 → ESCALATED(EMPTY_RESPONSE)
        3. 안전 거부 감지 → 1회 retry (더 명확한 프롬프트)
        4. category_node_id가 트리에 없음 → ESCALATED(INVALID_CATEGORY_ID)
        5. confidence < 0.7 → ESCALATED(LOW_CONFIDENCE)
        6. 통과 → RESOLVED
        """
        start = time.perf_counter()
        prompt = _build_prompt(
            queue_entry,
            self._category_tree,
            self._brand_dictionary,
            self._synonyms,
        )

        # ── 1. Provider 호출 (최대 2회) ───────────────────────────────────
        raw_response: dict = {}
        for attempt in range(1, 3):  # attempt 1, 2
            try:
                raw_response = self._provider.call(prompt=prompt)
                break
            except Exception as exc:
                if attempt >= 2:
                    elapsed_ms = int((time.perf_counter() - start) * 1000)
                    return _make_escalated(
                        queue_entry.id,
                        [f"PROVIDER_ERROR: {type(exc).__name__}", str(exc)[:200]],
                        {},
                        elapsed_ms,
                    )
                # 첫 번째 실패 → 재시도 프롬프트로 교체
                prompt = _build_retry_prompt(prompt, str(exc))

        elapsed_ms = int((time.perf_counter() - start) * 1000)

        # ── 2. 빈 응답 감지 ──────────────────────────────────────────────
        if not raw_response:
            return _make_escalated(
                queue_entry.id,
                ["EMPTY_RESPONSE: LLM이 빈 응답을 반환했습니다."],
                raw_response,
                elapsed_ms,
            )

        # ── 3. 안전 거부 감지 → 1회 retry ────────────────────────────────
        if _is_safety_refusal(raw_response):
            safety_prompt = _build_safety_retry_prompt(prompt)
            try:
                raw_response = self._provider.call(prompt=safety_prompt)
            except Exception:
                pass  # retry 실패해도 아래 로직으로 계속 (ESCALATED 처리됨)
            elapsed_ms = int((time.perf_counter() - start) * 1000)

        # ── 응답 파싱 ─────────────────────────────────────────────────────
        category_node_id: Optional[str] = raw_response.get("category_node_id") or None
        confidence = float(raw_response.get("confidence", 0.0))
        brand: Optional[str] = raw_response.get("brand") or None
        name_core: Optional[str] = raw_response.get("name_core") or None
        ai_reasons_raw = raw_response.get("reasons", [])
        ai_reasons: list[str] = (
            [ai_reasons_raw] if isinstance(ai_reasons_raw, str)
            else list(ai_reasons_raw) if isinstance(ai_reasons_raw, list)
            else []
        )

        # ── 4. 트리에 없는 id → ESCALATED ────────────────────────────────
        # 이유: LLM hallucination 방지. 트리 외 id는 FK violation 또는 오염 유발.
        if not category_node_id or category_node_id not in self._valid_ids:
            return _make_escalated(
                queue_entry.id,
                [f"INVALID_CATEGORY_ID: '{category_node_id}'는 카테고리 트리에 없습니다."]
                + ai_reasons,
                raw_response,
                elapsed_ms,
                category_node_id=None,
                brand=brand,
                name_core_refined=name_core,
                confidence=confidence,
            )

        # ── 5. confidence 임계 미달 → ESCALATED ──────────────────────────
        # 이유: 0.7 미만은 불확실. Phase C2 사후검증이 더 정밀하게 판단한다.
        if confidence < CONFIDENCE_THRESHOLD:
            return _make_escalated(
                queue_entry.id,
                [f"LOW_CONFIDENCE: {confidence:.2f} < {CONFIDENCE_THRESHOLD}"] + ai_reasons,
                raw_response,
                elapsed_ms,
                category_node_id=category_node_id,
                brand=brand,
                name_core_refined=name_core,
                confidence=confidence,
            )

        # ── 6. RESOLVED ──────────────────────────────────────────────────
        return QueueRouterDecision(
            queue_id=queue_entry.id,
            decision="RESOLVED",
            category_node_id=category_node_id,
            brand=brand,
            name_core_refined=name_core,
            confidence=confidence,
            reasons=ai_reasons,
            raw_ai_response=raw_response,
            elapsed_ms=elapsed_ms,
        )

    def route_batch(
        self,
        entries: list,
        max_concurrency: int = 1,
        dry_run_with_mock_provider: bool = False,
    ) -> list[QueueRouterDecision]:
        """
        배치 처리 — 현재 구현은 순차(max_concurrency=1).

        dry_run_with_mock_provider:
            True로 설정하면 "이 배치는 mock provider 모드"임을 외부에 알린다.
            실제 provider 교체는 __init__의 provider 인자로 한다.
            테스트에서는 MockProvider를 provider로 전달하고 이 플래그를 True로 설정한다.
            라이브에서는 False로 설정하고 실제 GoogleGenAIProvider를 전달한다.

        라이브 비용 추산:
            1건당 ~2000 input tokens + ~200 output tokens.
            Gemini 1.5 Flash 기준 ~$0.0003/건.
            배치 100건 = ~$0.03. 운영 비용 허용 범위 내.
        """
        return [self.route_one(entry) for entry in entries]

    def apply_decisions_to_db(
        self,
        decisions: list[QueueRouterDecision],
        session: Any,
    ) -> ApplyResult:
        """
        QueueRouterDecision 목록을 DB에 반영한다.

        RESOLVED:
            - ProductReviewQueue.resolved_at = now
            - ProductReviewQueue.resolver_user_id = "ai_router:resolved:v1"
            - (suggested_canonical_id가 있는 경우) CanonicalProduct.category_path_internal_id 업데이트

        ESCALATED:
            - ProductReviewQueue.resolver_user_id = "ai_router:escalated:v1"
            - resolved_at 건드리지 않음 (큐 유지)

        멱등성:
            같은 결정을 두 번 적용해도 동일한 결과가 된다.
            RESOLVED를 두 번 적용 → resolved_at이 갱신될 뿐 오류 없음.

        테이블 이름은 SQLAlchemy text()를 통해 직접 참조하므로
        db-admin ORM 모듈을 import하지 않아도 동작한다.
        """
        from sqlalchemy import text  # SQLAlchemy Core import (이미 의존성에 있음)

        result = ApplyResult()
        now = datetime.now()

        for decision in decisions:
            try:
                # 큐 행 존재 확인
                row = session.execute(
                    text(
                        "SELECT id, suggested_canonical_id "
                        "FROM canonical_product_review_queue WHERE id = :id"
                    ),
                    {"id": decision.queue_id},
                ).fetchone()

                if row is None:
                    result.skipped_count += 1
                    continue

                _queue_id, suggested_canonical_id = row[0], row[1]

                if decision.decision == "RESOLVED":
                    # 큐 행 resolved 마킹
                    session.execute(
                        text(
                            "UPDATE canonical_product_review_queue "
                            "SET resolved_at = :now, resolver_user_id = :uid "
                            "WHERE id = :id"
                        ),
                        {
                            "now": now,
                            "uid": _RESOLVED_RESOLVER_ID,
                            "id": decision.queue_id,
                        },
                    )
                    # canonical 카테고리 업데이트 (suggested_canonical_id가 있는 경우)
                    if suggested_canonical_id and decision.category_node_id:
                        session.execute(
                            text(
                                "UPDATE canonical_products "
                                "SET category_path_internal_id = :cat_id, updated_at = :now "
                                "WHERE id = :id"
                            ),
                            {
                                "cat_id": decision.category_node_id,
                                "now": now,
                                "id": suggested_canonical_id,
                            },
                        )
                    result.resolved_count += 1

                elif decision.decision == "ESCALATED":
                    # 큐 유지 — escalation 마커만 기록
                    session.execute(
                        text(
                            "UPDATE canonical_product_review_queue "
                            "SET resolver_user_id = :uid "
                            "WHERE id = :id"
                        ),
                        {"uid": _ESCALATED_RESOLVER_ID, "id": decision.queue_id},
                    )
                    result.escalated_count += 1

            except Exception as exc:
                result.errors.append(
                    {
                        "queue_id": decision.queue_id,
                        "error": type(exc).__name__,
                        "message": str(exc)[:300],
                    }
                )

        return result
