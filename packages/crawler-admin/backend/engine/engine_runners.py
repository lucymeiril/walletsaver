"""
공통 엔진 5종 추상화 — crawler-FINAL §3-A.

5엔진:
- SsrInitialStateRunner        : __INITIAL_STATE__ / __NEXT_DATA__ JSON
- PaginatedCardRunner          : page param + CSS card
- SearchKeywordRunner          : 키워드 리스트로 search URL 순회
- PlaywrightHeadfulRunner      : SPA / XHR intercept (이미 strategies/playwright_st 존재)
- OccRestApiRunner             : SAP Hybris OCC REST 직접 호출 (NEW — 코스트코)

본 모듈은 *상위 워크플로* 추상화. strategies/* (requests/cloudscraper/...) 는
하위 transport 어댑터로 유지된다 (FINAL §3-A 마지막 문장).

이미 구현된 마트 크롤러들은 capability 기반으로 엔진을 선택할 수 있도록
resolve_engine(NormalizedConfig) 를 통해 매핑된다. 본 추상화는 회피용이 아니다 —
신규 소스를 yaml + 5엔진 선택만으로 추가할 수 있도록 *최소 골격* 을 제공한다.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from .capability_schema import Capabilities, NormalizedConfig


@dataclass
class EngineExecutionContext:
    """Runner 실행 컨텍스트 — 마트별 crawler 가 채워 전달한다."""
    source_id: str
    url: str
    surface: str = "pc_web"
    cookies: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class EngineResult:
    """Runner 산출 — raw record 후보 + 진단."""
    records: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    blocker_signature: Optional[str] = None


class EngineRunner(abc.ABC):
    """5엔진 공통 base — fetch() + parse() 두 단계."""

    name: str = "base"

    @abc.abstractmethod
    def parse(self, payload: Any, ctx: EngineExecutionContext) -> EngineResult:
        """payload(HTML/JSON/intercepted dict 등) → records."""
        ...

    def describe(self) -> dict[str, Any]:
        """진단/UI 노출용."""
        return {"engine": self.name}


# ── 1. SsrInitialStateRunner ─────────────────────────────────────
class SsrInitialStateRunner(EngineRunner):
    """`__INITIAL_STATE__` / `__NEXT_DATA__` 등 SSR JSON 추출."""

    name = "SsrInitialState"

    def __init__(
        self,
        marker: str = "window.__INITIAL_STATE__",
        jsonpath: str = "$.data.products.productEntities",
    ):
        self.marker = marker
        self.jsonpath = jsonpath

    def parse(self, payload: Any, ctx: EngineExecutionContext) -> EngineResult:
        # 실제 selector/parser 는 기존 crawler 가 보유. 본 메서드는 디스패치만.
        records = payload.get(self.jsonpath, []) if isinstance(payload, dict) else []
        return EngineResult(
            records=list(records),
            diagnostics={"marker": self.marker, "jsonpath": self.jsonpath},
        )


# ── 2. PaginatedCardRunner ───────────────────────────────────────
class PaginatedCardRunner(EngineRunner):
    """page param 순회 + CSS card 파싱."""

    name = "PaginatedCard"

    def __init__(
        self,
        url_template: str = "",
        card_selector: str = "",
        max_pages: int = 1,
    ):
        self.url_template = url_template
        self.card_selector = card_selector
        self.max_pages = max_pages

    def parse(self, payload: Any, ctx: EngineExecutionContext) -> EngineResult:
        records = payload if isinstance(payload, list) else []
        return EngineResult(
            records=records,
            diagnostics={
                "card_selector": self.card_selector,
                "max_pages": self.max_pages,
            },
        )

    def iter_pages(self) -> Iterable[str]:
        """page=1..max_pages 의 URL 생성."""
        if not self.url_template:
            return []
        return [self.url_template.format(page=p) for p in range(1, self.max_pages + 1)]


# ── 3. SearchKeywordRunner ───────────────────────────────────────
class SearchKeywordRunner(EngineRunner):
    """키워드 리스트로 search URL 순회 — 단골 probe 에도 활용."""

    name = "SearchKeyword"

    def __init__(
        self,
        url_template: str = "",
        keywords: Optional[list[str]] = None,
        max_pages: int = 1,
    ):
        self.url_template = url_template
        self.keywords = list(keywords or [])
        self.max_pages = max_pages

    def parse(self, payload: Any, ctx: EngineExecutionContext) -> EngineResult:
        records = payload if isinstance(payload, list) else []
        return EngineResult(records=records, diagnostics={"keywords": self.keywords})

    def iter_urls(self) -> Iterable[str]:
        if not self.url_template or not self.keywords:
            return []
        urls: list[str] = []
        for kw in self.keywords:
            for p in range(1, self.max_pages + 1):
                # url_template 에 {keyword} / {page} 자리 둘 다 허용
                urls.append(
                    self.url_template.format(keyword=kw, page=p)
                )
        return urls


# ── 4. PlaywrightHeadfulRunner ───────────────────────────────────
class PlaywrightHeadfulRunner(EngineRunner):
    """SPA / XHR intercept / 마우스 시뮬.

    실제 Playwright 호출은 engine.strategies.playwright_st 가 담당.
    본 클래스는 capability 기반 디스패치 + xhr intercept 결과 정규화 책임만 진다.
    """

    name = "PlaywrightHeadful"

    def __init__(self, intercept_url_substring: str = "", profile_id: Optional[str] = None):
        self.intercept_url_substring = intercept_url_substring
        self.profile_id = profile_id

    def parse(self, payload: Any, ctx: EngineExecutionContext) -> EngineResult:
        records = payload if isinstance(payload, list) else []
        return EngineResult(
            records=records,
            diagnostics={
                "intercept_url_substring": self.intercept_url_substring,
                "profile_id": self.profile_id,
            },
        )


# ── 5. OccRestApiRunner (NEW — 코스트코) ─────────────────────────
class OccRestApiRunner(EngineRunner):
    """SAP Hybris OCC REST 직접 호출. cookie/CSRF 는 워크밴치에서 1회 캡처.

    crawler-FINAL §2-1 — 코스트코 995×3 라이브 검증.
    Playwright/SSR 우회 불필요. OCC endpoint 안정.
    """

    name = "OccRestApi"

    def __init__(
        self,
        base_url: str = "",
        catalog_paths: Optional[list[str]] = None,
        page_param: str = "currentPage",
        max_pages: int = 7,
    ):
        self.base_url = base_url
        self.catalog_paths = list(catalog_paths or [])
        self.page_param = page_param
        self.max_pages = max_pages

    def parse(self, payload: Any, ctx: EngineExecutionContext) -> EngineResult:
        # OCC 응답은 보통 {"products": [...]} 형태. 그 외는 payload 자체 사용.
        if isinstance(payload, dict):
            records = payload.get("products") or payload.get("results") or []
        elif isinstance(payload, list):
            records = payload
        else:
            records = []
        return EngineResult(
            records=list(records),
            diagnostics={
                "base_url": self.base_url,
                "catalog_paths": self.catalog_paths,
                "page_param": self.page_param,
            },
        )

    def iter_urls(self) -> Iterable[str]:
        """카테고리 × 페이지의 URL 조합."""
        urls: list[str] = []
        for path in self.catalog_paths:
            for p in range(1, self.max_pages + 1):
                sep = "&" if "?" in path else "?"
                urls.append(f"{self.base_url.rstrip('/')}{path}{sep}{self.page_param}={p}")
        return urls


ENGINE_REGISTRY: dict[str, type[EngineRunner]] = {
    "SsrInitialState": SsrInitialStateRunner,
    "PaginatedCard": PaginatedCardRunner,
    "SearchKeyword": SearchKeywordRunner,
    "PlaywrightHeadful": PlaywrightHeadfulRunner,
    "OccRestApi": OccRestApiRunner,
}


def resolve_engine(config: NormalizedConfig) -> str:
    """capability set → 권장 엔진명.

    매핑 규칙 (FINAL §3-A 표):
      - render=playwright_headful → PlaywrightHeadful
      - transport=xhr & extraction=jsonpath & session contains cookie_jar → OccRestApi
        (코스트코 OCC 패턴 — base_url + 카테고리 path 명시 시 보강 가능)
      - extraction=jsonpath & transport=html → SsrInitialState
      - pagination=page_param & extraction=css → PaginatedCard
      - pagination=page_param 이고 url_template 에 {keyword} → SearchKeyword
      - 그 외 → PaginatedCard (safe default)
    """
    caps = config.capabilities

    if "playwright_headful" in caps.render:
        return "PlaywrightHeadful"

    if (
        "xhr" in caps.transport
        and "jsonpath" in caps.extraction
        and ("cookie_jar" in caps.session or "persistent_profile" in caps.session)
    ):
        return "OccRestApi"

    # SearchKeyword 우선 (search_keywords 가 yaml 에 명시된 경우, v2 source_map list 안에서만)
    source_map_raw = config.raw.get("source_map")
    if isinstance(source_map_raw, list) and any(
        isinstance(e, dict) and "search_keywords" in e for e in source_map_raw
    ) and "page_param" in caps.pagination:
        return "SearchKeyword"

    if "jsonpath" in caps.extraction and "html" in caps.transport:
        return "SsrInitialState"

    if "page_param" in caps.pagination and "css" in caps.extraction:
        return "PaginatedCard"

    return "PaginatedCard"


def instantiate_engine(name: str, **kwargs: Any) -> EngineRunner:
    cls = ENGINE_REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"unknown engine: {name}")
    return cls(**kwargs)
