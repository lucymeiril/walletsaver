"""쿠팡 entrypoints — operator-capture path is the only verified one.

라이브 캡처 진본 진단
---------------------
* tests/fixtures/live_probe/coupang_search.html             (397 B, Akamai Access Denied)
* tests/fixtures/live_probe/coupang_search_생수.blocked.html (313 B, Akamai 챌린지)
두 캡처 모두 자동화로는 PLP HTML 을 받을 수 없다는 직접 증거다. 따라서:

* crawl_sale_listing / crawl_catalog_page / fetch_single_product 는 라이브
  응답을 받았을 때 ``akamai_access_denied`` / ``empty_challenge_payload``
  blocker 를 정확히 보고하는지 회귀.
* ingest_operator_capture 는 marketplace_skeleton 의 검증된 fixture
  (``tests/fixtures/marketplace_skeleton/coupang.html``) 를 그대로 받아
  파싱할 수 있는지 회귀.
"""

from __future__ import annotations

import pathlib

import pytest

from crawlers.marts.entry_points import CollectionPath, CrawlIntent
from crawlers.shopping.coupang.entrypoints import (
    CATALOG_SEEDS,
    CoupangEntrypoints,
    SALE_QUERY,
    _detect_blocker,
)


SKELETON_FIXTURE = (
    pathlib.Path(__file__).parent / "fixtures" / "marketplace_skeleton" / "coupang.html"
)
LIVE_BLOCKED_CANDIDATES = [
    "coupang_search.html",
    "coupang_search_생수.blocked.html",
    "coupang_persistent_blocked.html",
    "coupang_uc_blocked.html",
]
LIVE_PROBE_DIR = pathlib.Path(__file__).parent / "fixtures" / "live_probe"
TRACEID_DIAG = LIVE_PROBE_DIR / "coupang_traceId_diag.json"


@pytest.fixture
def skeleton_html() -> str:
    assert SKELETON_FIXTURE.exists(), f"missing skeleton fixture: {SKELETON_FIXTURE}"
    return SKELETON_FIXTURE.read_text(encoding="utf-8")


# ---------- Akamai 차단 진단 회귀 ----------
def test_detect_blocker_recognises_real_access_denied_capture():
    for name in LIVE_BLOCKED_CANDIDATES:
        p = LIVE_PROBE_DIR / name
        if not p.exists():
            continue
        body = p.read_text(encoding="utf-8", errors="ignore")
        blocker = _detect_blocker(body)
        assert blocker in {"akamai_access_denied", "empty_challenge_payload"}, (
            f"{name}: 감지 실패 → blocker={blocker!r}, head={body[:120]!r}"
        )


def test_detect_blocker_returns_none_on_real_marketplace_html(skeleton_html):
    assert _detect_blocker(skeleton_html) is None


def test_detect_blocker_flags_empty_and_short_responses():
    assert _detect_blocker("") == "empty_response"
    assert _detect_blocker(None) == "no_response_body"
    assert _detect_blocker("<html><body>x</body></html>") == "empty_challenge_payload"


# ---------- 4 entrypoints ----------
@pytest.mark.asyncio
async def test_ingest_operator_capture_parses_real_fixture(skeleton_html):
    ep = CoupangEntrypoints()
    result = await ep.ingest_operator_capture(
        skeleton_html,
        source_url="https://www.coupang.com/np/search?q=operator",
        capture_id="op-coupang-001",
    )
    assert result.status.name == "SUCCESS"
    assert result.items_count >= 1
    for it in result.items:
        assert it["attributes"]["collection_path"] == CollectionPath.OPERATOR_CAPTURE.value
        assert it["attributes"]["operator_capture_id"] == "op-coupang-001"
    assert result.quality_details["operator_capture"] is True
    assert result.quality_details["source_host"] == "www.coupang.com"


@pytest.mark.asyncio
async def test_sale_listing_against_real_live_blocked_reports_blocker():
    """Akamai 차단 응답을 받았을 때 PARTIAL/FAILED + 정확한 blocker."""
    body = None
    for name in LIVE_BLOCKED_CANDIDATES:
        p = LIVE_PROBE_DIR / name
        if p.exists():
            body = p.read_text(encoding="utf-8", errors="ignore")
            break
    if body is None:
        pytest.skip("라이브 차단 캡처 없음 (live_probe/) — gitignored 환경")
    ep = CoupangEntrypoints()
    result = await ep.crawl_sale_listing(fetch=lambda url: body)
    assert result.items_count == 0
    assert result.status.name in {"FAILED", "PARTIAL"}
    assert result.errors
    msg = result.errors[0].error_msg
    assert "akamai_access_denied" in msg or "empty_challenge_payload" in msg


# ---------- traceId 변형 진단 회귀 (Phase A 2차 슬라이스 정직 진단) ----------
def test_traceId_diag_when_present_confirms_uniform_akamai_block():
    """Phase A 2차 슬라이스에서 traceId 3종 (empty / random 16-hex / 고정 16-hex)
    을 직접 비교한 결과가 *모두* Akamai 차단으로 동일하게 분류돼야 한다.
    이 진단 자체가 '운영자 캡처가 유일한 경로' 라는 결론의 직접 증거다.
    """
    import json as _json
    if not TRACEID_DIAG.exists():
        pytest.skip("coupang_traceId_diag.json 없음 (live_probe gitignored)")
    diag = _json.loads(TRACEID_DIAG.read_text(encoding="utf-8"))
    variants = diag["variants"]
    assert {v["label"] for v in variants} == {"empty", "random_16hex", "spec_fixed_16hex"}
    for v in variants:
        assert v["classification"] in {"akamai_access_denied", "akamai_403"}, (
            f"traceId={v['label']} 가 Akamai 차단 분류가 아님: {v['classification']!r} "
            f"-- 이 경우 plugin.yaml::coupang_traceId_note 와 status='blocked' 결정을 재검토 필요"
        )
    # 분류가 모두 동일 == traceId 자체로 차단 분기를 트지 못함
    assert not diag["summary"]["differs_across_variants"], (
        "traceId variation 이 분기를 야기함 — plugin.yaml note 갱신 필요"
    )


# ---------- 가짜 통과 방지: operator capture fixture 가 'fake/empty' 면 빌드 깨야 함 ----------
def test_skeleton_fixture_contains_real_card_markers(skeleton_html):
    """ingest_operator_capture 의 신뢰성 근거가 되는 marketplace_skeleton/coupang.html
    이 실제 상품 카드 마커를 갖고 있어야 한다 — 빈 셸/차단 페이지였다면 빌드 즉시 실패.
    """
    lo = skeleton_html.lower()
    # 다음 마커 중 적어도 하나는 있어야 한다 — 둘 다 없으면 fake fixture 다
    real_markers = ["search-product", "product-card", "vp/products/", "data-product-id", '"productlist"', '"products"']
    found = [m for m in real_markers if m in lo]
    assert found, (
        f"coupang skeleton fixture 가 실제 상품 카드 마커를 0개 가지고 있음. "
        f"빈 셸 또는 Akamai 차단 응답이 fixture 로 들어갔을 가능성. 검색된 마커: {found!r}"
    )
    assert len(skeleton_html) > 200, "fixture 크기가 너무 작음 (차단 페이지/완전 셸 의심)"


def test_negative_blocked_fixture_cannot_become_operator_capture_source():
    """직접 차단된 응답을 operator capture 로 잘못 사용했을 때 detect_blocker 가
    이를 인식하지 못하면 안된다 — 다음 AI 가 또 차단 응답을 fake operator capture
    로 통과시키지 못하도록."""
    for name in LIVE_BLOCKED_CANDIDATES:
        p = LIVE_PROBE_DIR / name
        if not p.exists():
            continue
        body = p.read_text(encoding="utf-8", errors="ignore")
        if not body.strip():
            # 빈 파일도 잘못된 fixture 후보지만 detect_blocker 측에서 empty 로 잡혀야 함
            assert _detect_blocker(body) in {"empty_response", "empty_challenge_payload", "no_response_body"}
            continue
        assert _detect_blocker(body) in {
            "akamai_access_denied",
            "empty_challenge_payload",
            "empty_response",
        }, f"{name} 차단 응답이 blocker 미인식 — fake operator capture 통과 위험"


@pytest.mark.asyncio
async def test_sale_listing_tags_public_endpoint_when_operator_supplied(skeleton_html):
    """fetch 콜백이 operator-rendered HTML 을 돌려주면 public_endpoint 로 태깅된다."""
    ep = CoupangEntrypoints()
    result = await ep.crawl_sale_listing(fetch=lambda url: skeleton_html, trace_id="abcd1234")
    assert result.items_count >= 1
    for it in result.items:
        assert it["attributes"]["collection_path"] == "public_endpoint"
        assert it["attributes"]["crawl_intent"] == "sale"
    from urllib.parse import quote
    qd = result.quality_details["entrypoint"]
    assert quote(SALE_QUERY) in qd["source_url"]
    assert "traceId=abcd1234" in qd["source_url"]


@pytest.mark.asyncio
async def test_catalog_page_uses_seed_query_and_tags_catalog_intent(skeleton_html):
    ep = CoupangEntrypoints()
    seed = CATALOG_SEEDS[0]  # "생수 2L"
    result = await ep.crawl_catalog_page(seed, page=2, fetch=lambda url: skeleton_html, trace_id="")
    assert result.quality_details["query"] == seed
    assert result.quality_details["page"] == 2
    # 빈 traceId 도 허용
    assert "traceId=&" in result.quality_details["entrypoint"]["source_url"]
    for it in result.items:
        assert it["attributes"]["collection_path"] == "catalog_page"
        assert it["attributes"]["crawl_intent"] == "catalog"


@pytest.mark.asyncio
async def test_fetch_single_product_constructs_vp_products_url(skeleton_html):
    ep = CoupangEntrypoints()
    result = await ep.fetch_single_product("fixture-coupang", fetch=lambda url: skeleton_html)
    qd = result.quality_details["entrypoint"]
    assert qd["source_url"] == "https://www.coupang.com/vp/products/fixture-coupang"
    for it in result.items:
        assert it["attributes"]["collection_path"] == "single_product"
        assert it["attributes"]["crawl_intent"] == "refresh"


# ---------- catalog seeds & 모델 quirk ----------
def test_catalog_seeds_cover_mart_comparable_categories():
    # 생수/우유/계란/라면/세제 — 마트 비교용 핵심 SKU 5종
    keywords = " ".join(CATALOG_SEEDS)
    for kw in ["생수", "우유", "계란", "라면", "세제"]:
        assert kw in keywords, f"누락된 비교 SKU: {kw!r}"


@pytest.mark.asyncio
async def test_crawl_result_uses_finished_at_and_items_are_dicts(skeleton_html):
    ep = CoupangEntrypoints()
    result = await ep.ingest_operator_capture(skeleton_html, source_url="https://www.coupang.com/np/search?q=op")
    assert result.finished_at is not None
    assert "quality_details" in result.model_dump()
    assert all(isinstance(it, dict) for it in result.items)
