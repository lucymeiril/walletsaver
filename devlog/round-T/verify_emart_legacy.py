"""옛 EmartCrawler 라이브 실행 — DiscountItem 추출 검증."""
import sys, asyncio, logging
sys.path.insert(0, 'packages/crawler-admin/backend')
sys.path.insert(0, 'packages/shared')
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s: %(message)s')

from crawlers.marts.emart.crawler import EmartCrawler

async def main():
    c = EmartCrawler()
    # 빠른 검증을 위해 검색어 수 제한
    EmartCrawler.SEARCH_QUERIES = ["행사"]
    EmartCrawler.CATEGORY_QUERIES = []
    EmartCrawler.MAX_PAGES = 1
    result = await c.crawl()
    print('STATUS:', result.status)
    items = getattr(result, 'items', None) or getattr(result, 'data', None) or []
    print('ITEMS:', len(items))
    for it in items[:5]:
        if isinstance(it, dict):
            print(' -', it.get('name','')[:50], '|', it.get('sale_price'), '|', it.get('unit',''), '|', (it.get('detail_url','') or '')[:80])
            print('     attrs:', {k:it.get('attributes',{}).get(k) for k in ('category','category_hint','source','source_record_key')})
        else:
            print(' -', it.name[:50], '|', it.sale_price)
    print('VALID via .validate skipped (dict items)')

asyncio.run(main())
