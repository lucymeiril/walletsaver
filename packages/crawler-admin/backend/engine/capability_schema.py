"""
Capability YAML schema v2 정규화기 — crawler-FINAL §3-B / §3-C 구현.

설계 의도:
- v1 plugin.yaml (느슨한 name/version/category 만 강제) 과
  v2 plugin.yaml (capabilities/source_map/output/waf_strategy 명시) 를
  하나의 NormalizedConfig 로 컴파일한다.
- read-compat: v1·v2 둘 다 로드 가능. v1 은 자동 저장 안 함.
- write-policy: UI 저장은 v2 만 (별도 PR 에서 UI 묶음).
- 본 모듈은 검증/정규화만. 디스크 IO 는 PluginLoader 가 담당.

5엔진 매핑은 engine_runners.resolve_engine_from_capabilities 가 사용한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Literal, Optional

# capability 어휘 — FINAL §3-B 표 그대로
TRANSPORTS = {"html", "xhr", "graphql", "websocket", "app_api"}
RENDERS = {"none", "playwright_headless", "playwright_headful"}
PAGINATIONS = {"none", "page_param", "cursor", "infinite_scroll", "load_more"}
EXTRACTIONS = {"css", "jsonpath", "regex", "intercepted_response"}
SESSIONS = {"stateless", "cookie_jar", "persistent_profile", "operator_capture"}
ANTI_BLOCKERS = {
    "ua_rotation", "referer_chain", "sleep", "headful_fallback",
    "cookie_warmup", "csrf_token", "none",
}
SURFACES = {"pc_web", "mobile_web", "mobile_app_api"}


class CapabilitySchemaError(ValueError):
    """capability schema 검증 실패."""


@dataclass(frozen=True)
class SourceMapEntry:
    id: str
    surface: str
    url_template: str
    parser_inputs: tuple[str, ...] = ()
    selectors: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OutputContract:
    minimum_rows: int = 0
    required_fields: tuple[str, ...] = ()
    field_coverage_thresholds: dict[str, float] = field(default_factory=dict)
    optional_recommended: tuple[str, ...] = ()


@dataclass(frozen=True)
class EscalationStep:
    from_state: str
    to_state: str
    after_failures: int = 2
    cooldown_sec: int = 60


@dataclass(frozen=True)
class WafStrategy:
    detect: tuple[str, ...] = ()
    escalation: tuple[EscalationStep, ...] = ()


@dataclass(frozen=True)
class Capabilities:
    transport: frozenset[str] = field(default_factory=frozenset)
    render: frozenset[str] = field(default_factory=frozenset)
    pagination: frozenset[str] = field(default_factory=frozenset)
    extraction: frozenset[str] = field(default_factory=frozenset)
    session: frozenset[str] = field(default_factory=frozenset)
    anti_blocker: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class NormalizedConfig:
    name: str
    version: str
    category: str
    schema_version: int               # 1 또는 2
    capabilities: Capabilities
    source_map: tuple[SourceMapEntry, ...]
    output: OutputContract
    waf_strategy: WafStrategy
    raw: dict[str, Any]               # 디스크 원본 dict (선택적 추가 필드용)

    @property
    def is_v2(self) -> bool:
        return self.schema_version >= 2


def _coerce_set(value: Any, vocabulary: set[str], field_name: str) -> frozenset[str]:
    if value is None:
        return frozenset()
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        raise CapabilitySchemaError(f"{field_name} 은 리스트여야 합니다 (got {type(value).__name__})")
    out: set[str] = set()
    for v in value:
        if not isinstance(v, str):
            raise CapabilitySchemaError(f"{field_name} 항목은 문자열이어야 합니다")
        if v not in vocabulary:
            raise CapabilitySchemaError(
                f"{field_name} 값 '{v}' 은 어휘 외 — 허용: {sorted(vocabulary)}"
            )
        out.add(v)
    return frozenset(out)


def _coerce_source_map(value: Any) -> tuple[SourceMapEntry, ...]:
    if value is None:
        return ()
    # v1 legacy: source_map 이 dict 형태인 마트(emart/homeplus 등) 도 있다.
    # read-compat 원칙 — 빈 tuple 로 떨어뜨리고 v2 schema 마이그레이션 시 list 로 채움.
    if isinstance(value, dict):
        return ()
    if not isinstance(value, list):
        raise CapabilitySchemaError("source_map 은 리스트여야 합니다")
    out: list[SourceMapEntry] = []
    for i, entry in enumerate(value):
        if not isinstance(entry, dict):
            continue  # v1 source_map 은 dict 형태이므로 무시
        sid = entry.get("id") or f"entry_{i}"
        surface = entry.get("surface", "pc_web")
        if surface not in SURFACES:
            raise CapabilitySchemaError(
                f"source_map[{sid}].surface '{surface}' 은 허용 외 — {sorted(SURFACES)}"
            )
        url_template = entry.get("url_template", "")
        parser_inputs = tuple(entry.get("parser_inputs", []) or [])
        selectors = entry.get("selectors") or {}
        out.append(
            SourceMapEntry(
                id=sid,
                surface=surface,
                url_template=url_template,
                parser_inputs=parser_inputs,
                selectors=selectors if isinstance(selectors, dict) else {},
            )
        )
    return tuple(out)


def _coerce_output(value: Any) -> OutputContract:
    if not isinstance(value, dict):
        return OutputContract()
    thresholds = value.get("field_coverage_thresholds") or {}
    if not isinstance(thresholds, dict):
        thresholds = {}
    return OutputContract(
        minimum_rows=int(value.get("minimum_rows") or value.get("min_rows") or 0),
        required_fields=tuple(value.get("required_fields") or []),
        field_coverage_thresholds={k: float(v) for k, v in thresholds.items()},
        optional_recommended=tuple(value.get("optional_recommended") or []),
    )


def _coerce_waf(value: Any) -> WafStrategy:
    if not isinstance(value, dict):
        return WafStrategy()
    detect = tuple(value.get("detect") or [])
    escalation_raw = value.get("escalation") or []
    steps: list[EscalationStep] = []
    if isinstance(escalation_raw, list):
        for step in escalation_raw:
            if not isinstance(step, dict):
                continue
            steps.append(
                EscalationStep(
                    from_state=str(step.get("from", "")),
                    to_state=str(step.get("to", "")),
                    after_failures=int(step.get("after_failures", 2)),
                    cooldown_sec=int(step.get("cooldown_sec", 60)),
                )
            )
    return WafStrategy(detect=detect, escalation=tuple(steps))


def normalize(raw: dict[str, Any]) -> NormalizedConfig:
    """plugin.yaml dict → NormalizedConfig.

    v1 (capabilities 키 없음) 도 받아 빈 capabilities 로 컴파일한다.
    """
    if not isinstance(raw, dict):
        raise CapabilitySchemaError("plugin.yaml 은 dict 여야 합니다")

    schema_version = int(raw.get("schema_version") or 1)
    if schema_version not in (1, 2):
        raise CapabilitySchemaError(f"schema_version 은 1 또는 2 (got {schema_version})")

    name = raw.get("name")
    version = raw.get("version")
    category = raw.get("category", "mart")
    if not name or not isinstance(name, str):
        raise CapabilitySchemaError("name 필수")
    if not version or not isinstance(version, str):
        raise CapabilitySchemaError("version 필수")

    caps_raw = raw.get("capabilities") or {}
    if not isinstance(caps_raw, dict):
        raise CapabilitySchemaError("capabilities 는 dict 여야 합니다")
    caps = Capabilities(
        transport=_coerce_set(caps_raw.get("transport"), TRANSPORTS, "capabilities.transport"),
        render=_coerce_set(caps_raw.get("render"), RENDERS, "capabilities.render"),
        pagination=_coerce_set(caps_raw.get("pagination"), PAGINATIONS, "capabilities.pagination"),
        extraction=_coerce_set(caps_raw.get("extraction"), EXTRACTIONS, "capabilities.extraction"),
        session=_coerce_set(caps_raw.get("session"), SESSIONS, "capabilities.session"),
        anti_blocker=_coerce_set(caps_raw.get("anti_blocker"), ANTI_BLOCKERS, "capabilities.anti_blocker"),
    )

    return NormalizedConfig(
        name=name,
        version=version,
        category=category,
        schema_version=schema_version,
        capabilities=caps,
        source_map=_coerce_source_map(raw.get("source_map")),
        output=_coerce_output(raw.get("output")),
        waf_strategy=_coerce_waf(raw.get("waf_strategy")),
        raw=raw,
    )


def schema_validate_minimal(raw: dict[str, Any]) -> list[str]:
    """UI 저장 전 미리 검증 — 오류 목록 반환 (빈 리스트면 통과).

    crawler-FINAL §3-C 의 6단계 상태 카드 중 첫 단계 (config_schema_valid) 에 사용.
    """
    errors: list[str] = []
    try:
        normalize(raw)
    except CapabilitySchemaError as e:
        errors.append(str(e))
    return errors
