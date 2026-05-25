"""crawler-FINAL P0 — capability yaml schema v2 + 5엔진 매핑 단위 테스트."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from engine.capability_schema import (
    CapabilitySchemaError,
    normalize,
    schema_validate_minimal,
)
from engine.engine_runners import (
    ENGINE_REGISTRY,
    OccRestApiRunner,
    PlaywrightHeadfulRunner,
    SsrInitialStateRunner,
    instantiate_engine,
    resolve_engine,
)


MART_YAML_ROOT = Path(__file__).parent.parent / "crawlers" / "marts"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_capability_schema_v1_loads_with_empty_capabilities():
    """v1 yaml (capabilities 키 없음) 도 NormalizedConfig 로 컴파일된다 (read-compat)."""
    raw = {"name": "x", "version": "1.0.0", "category": "mart"}
    cfg = normalize(raw)
    assert cfg.schema_version == 1
    assert cfg.capabilities.transport == frozenset()
    assert cfg.output.minimum_rows == 0


def test_capability_schema_v2_validates_vocabulary():
    raw = {
        "name": "x", "version": "1.0.0", "category": "mart",
        "schema_version": 2,
        "capabilities": {
            "transport": ["xhr"],
            "render": ["playwright_headful"],
            "pagination": ["page_param"],
            "extraction": ["css", "jsonpath"],
            "session": ["cookie_jar"],
            "anti_blocker": ["ua_rotation", "sleep"],
        },
        "output": {"minimum_rows": 240, "required_fields": ["name", "sale_price"]},
    }
    cfg = normalize(raw)
    assert cfg.is_v2
    assert "xhr" in cfg.capabilities.transport
    assert "playwright_headful" in cfg.capabilities.render
    assert cfg.output.minimum_rows == 240


def test_capability_schema_rejects_unknown_vocabulary_term():
    raw = {
        "name": "x", "version": "1.0.0",
        "schema_version": 2,
        "capabilities": {"transport": ["telepathy"]},
    }
    with pytest.raises(CapabilitySchemaError):
        normalize(raw)


def test_schema_validate_minimal_returns_errors():
    errs = schema_validate_minimal({"name": "x"})  # version 누락
    assert errs and "version" in errs[0]


def test_resolve_engine_playwright_headful():
    raw = {
        "name": "lm", "version": "1.0.0", "schema_version": 2,
        "capabilities": {"render": ["playwright_headful"], "transport": ["html"]},
    }
    assert resolve_engine(normalize(raw)) == "PlaywrightHeadful"


def test_resolve_engine_occ_rest_api():
    raw = {
        "name": "cc", "version": "1.0.0", "schema_version": 2,
        "capabilities": {
            "transport": ["xhr"], "extraction": ["jsonpath"], "session": ["cookie_jar"],
        },
    }
    assert resolve_engine(normalize(raw)) == "OccRestApi"


def test_resolve_engine_ssr_initial_state():
    raw = {
        "name": "em", "version": "1.0.0", "schema_version": 2,
        "capabilities": {"transport": ["html"], "extraction": ["jsonpath"]},
    }
    assert resolve_engine(normalize(raw)) == "SsrInitialState"


def test_resolve_engine_paginated_card_default():
    raw = {
        "name": "h", "version": "1.0.0", "schema_version": 2,
        "capabilities": {"pagination": ["page_param"], "extraction": ["css"]},
    }
    assert resolve_engine(normalize(raw)) == "PaginatedCard"


def test_instantiate_engine_returns_correct_class():
    e = instantiate_engine("OccRestApi", base_url="https://x", catalog_paths=["/a"], max_pages=2)
    assert isinstance(e, OccRestApiRunner)
    urls = list(e.iter_urls())
    assert len(urls) == 2
    assert "currentPage=1" in urls[0]


def test_occ_rest_api_runner_parses_products_list():
    e = OccRestApiRunner()
    r = e.parse({"products": [{"name": "a"}, {"name": "b"}]}, ctx=None)  # type: ignore[arg-type]
    assert len(r.records) == 2


def test_ssr_initial_state_runner_parses_jsonpath_key():
    e = SsrInitialStateRunner(jsonpath="items")
    r = e.parse({"items": [1, 2, 3]}, ctx=None)  # type: ignore[arg-type]
    assert r.records == [1, 2, 3]


# ── 라이브 마트 yaml 회귀 ─────────────────────────────────────────


@pytest.mark.parametrize(
    "mart,expected_engine,expected_min_rows",
    [
        ("lottemart", "PlaywrightHeadful", 240),
        ("costco", "OccRestApi", 900),
    ],
)
def test_mart_yaml_v2_resolves_to_expected_engine(mart, expected_engine, expected_min_rows):
    """costco/lottemart 가 capability schema v2 로 마이그레이션됐고 엔진 매핑이 맞는지."""
    raw = _load(MART_YAML_ROOT / mart / "plugin.yaml")
    cfg = normalize(raw)
    assert cfg.is_v2, f"{mart} schema_version != 2"
    assert resolve_engine(cfg) == expected_engine
    assert cfg.output.minimum_rows == expected_min_rows


@pytest.mark.parametrize(
    "mart,expected_min_rows",
    [
        ("emart", 270),
        ("homeplus", 195),
        ("cocodalin", 50),
    ],
)
def test_mart_yaml_v1_compat_has_minimum_rows(mart, expected_min_rows):
    """v1 yaml (emart/homeplus/cocodalin) 도 minimum_rows 가 박혀 있다 — 게이트 작동 보장."""
    raw = _load(MART_YAML_ROOT / mart / "plugin.yaml")
    cfg = normalize(raw)
    assert cfg.output.minimum_rows == expected_min_rows
