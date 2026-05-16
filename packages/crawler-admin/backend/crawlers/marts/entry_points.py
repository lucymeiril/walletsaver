"""4-entrypoint protocol for mart crawlers (Phase A spec).

The agent charter requires every mart/marketplace crawler to expose four
intent-tagged collection paths so the operator workbench, scheduler and
ingestion UI can drive incremental refresh without rewriting parsers:

* ``crawl_sale_listing()``       — current sale page, public endpoint, intent=sale
* ``crawl_catalog_page(query)``  — one catalog/search page, intent=catalog (partial refresh)
* ``fetch_single_product(ref)``  — re-collect one product, intent=refresh
* ``ingest_operator_capture()``  — operator workbench / front-end paste, intent=any

Each entry point returns a :class:`CrawlResult` so the rest of the pipeline
does not need to special-case the calling surface. Items emitted by these
paths must carry ``collection_path``, ``crawl_intent`` and
``source_record_key`` inside ``attributes`` — these tags are what the DB
layer uses to merge incremental updates against the previous snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Iterable, Optional

from core.models import CrawlResult, CrawlStatus, DiscountItem


class CollectionPath(str, Enum):
    PUBLIC_ENDPOINT = "public_endpoint"
    CATALOG_PAGE = "catalog_page"
    SINGLE_PRODUCT = "single_product"
    OPERATOR_CAPTURE = "operator_capture"


class CrawlIntent(str, Enum):
    SALE = "sale"
    CATALOG = "catalog"
    REFRESH = "refresh"


@dataclass(frozen=True)
class EntrypointTag:
    collection_path: CollectionPath
    crawl_intent: CrawlIntent
    source_url: str = ""
    operator_capture_id: Optional[str] = None


def tag_items(items: Iterable[DiscountItem], tag: EntrypointTag) -> list[DiscountItem]:
    """Stamp ``collection_path`` / ``crawl_intent`` onto each item's attributes.

    Existing keys are preserved on re-tag — this matters for operator captures
    that already carry an operator_capture_id from a separate code path.
    """
    out: list[DiscountItem] = []
    for item in items:
        attrs = dict(item.attributes or {})
        attrs.setdefault("collection_path", tag.collection_path.value)
        attrs.setdefault("crawl_intent", tag.crawl_intent.value)
        if tag.source_url:
            attrs.setdefault("source_url", tag.source_url)
        if tag.operator_capture_id:
            attrs.setdefault("operator_capture_id", tag.operator_capture_id)
        # source_record_key must already be present from the parser; do not invent.
        item.attributes = attrs
        out.append(item)
    return out


def build_result(
    *,
    crawler_name: str,
    items: list[DiscountItem],
    tag: EntrypointTag,
    started_at: datetime,
    extras: Optional[dict] = None,
    errors: Optional[list] = None,
) -> CrawlResult:
    """Wrap a list of tagged items into a CrawlResult honoring the model quirks.

    * ``items`` are serialised via ``model_dump(mode='json')`` (never raw models).
    * ``errors`` is a list of ``StrategyFailure`` (already), not strings.
    * ``finished_at`` (not ``ended_at``) and ``quality_details`` are used.
    """
    finished = datetime.now()
    quality = {
        "entrypoint": {
            "collection_path": tag.collection_path.value,
            "crawl_intent": tag.crawl_intent.value,
            "source_url": tag.source_url,
            "operator_capture_id": tag.operator_capture_id,
        },
    }
    if extras:
        quality.update(extras)
    status = CrawlStatus.SUCCESS if items else (CrawlStatus.PARTIAL if errors else CrawlStatus.FAILED)
    return CrawlResult(
        crawler_name=crawler_name,
        status=status,
        items=[i.model_dump(mode="json") for i in items],
        items_count=len(items),
        errors=list(errors or []),
        started_at=started_at,
        finished_at=finished,
        quality_details=quality,
    )


__all__ = [
    "CollectionPath",
    "CrawlIntent",
    "EntrypointTag",
    "tag_items",
    "build_result",
]
