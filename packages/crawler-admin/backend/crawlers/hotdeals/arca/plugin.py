"""아카라이브 핫딜 — F1 플러그인 등록 (manual_only=True)."""
from __future__ import annotations

from crawlers.hotdeals.arca.crawler import ArcaCrawler


class ArcaliveHotdealPlugin:
    name = "arcalive_hotdeal"
    mart_kind = "hotdeal_aggregator"
    supports_targeted_search = False
    # Cloudflare로 자동 접근 불가 — 운영자가 브라우저로 로그인 후 HTML 파일 제출
    manual_only = True
    crawler_class = ArcaCrawler
    dashboard_badge = "운영자 캡처 필요"

    def crawl(self, targets=None):
        import asyncio
        crawler = ArcaCrawler()
        return asyncio.run(crawler.crawl())

    def crawl_from_file(self, html_path: str):
        """운영자 캡처 파일 → CrawlResult."""
        import asyncio
        from pathlib import Path
        from datetime import datetime
        from core.models import CrawlResult, CrawlStatus
        crawler = ArcaCrawler()
        raw_data = Path(html_path).read_text(encoding="utf-8")
        started_at = datetime.now()
        items = asyncio.run(crawler.parse(raw_data))
        valid_items = asyncio.run(crawler.validate(items))
        finished_at = datetime.now()
        return CrawlResult(
            status=CrawlStatus.SUCCESS,
            crawler_name=crawler.info.name,
            strategy_used="operator_capture",
            items_count=len(valid_items),
            items=[item.model_dump(mode="json") for item in valid_items],
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=(finished_at - started_at).total_seconds(),
        )


try:
    from crawler_admin.services.crawl_orchestrator import register_plugin, CrawlerPlugin  # type: ignore[import]  # noqa: F401
    register_plugin(ArcaliveHotdealPlugin())
except ImportError:
    # F1 오케스트레이터 미완성 — 플러그인 등록 보류
    pass
