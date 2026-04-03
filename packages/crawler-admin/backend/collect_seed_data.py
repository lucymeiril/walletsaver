"""실제 크롤링 데이터를 수집하여 프론트엔드 시드 데이터로 저장"""
import sys, os, json, asyncio
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))

from datetime import datetime

all_hotdeals = []
all_mart_deals = []

crawlers_to_run = [
    ('뽐뿌',     'crawlers.hotdeals.ppomppu.crawler',    'PpomppuCrawler',    'hotdeal'),
    ('FM코리아',  'crawlers.hotdeals.fmkorea.crawler',    'FmkoreaCrawler',    'hotdeal'),
    ('클리앙',    'crawlers.hotdeals.clien.crawler',      'ClienCrawler',      'hotdeal'),
    ('퀘이사존',  'crawlers.hotdeals.quasarzone.crawler',  'QuasarzoneCrawler', 'hotdeal'),
    ('알구몬',    'crawlers.hotdeals.algumon.crawler',     'AlgumonCrawler',    'hotdeal'),
    ('이마트',    'crawlers.marts.emart.crawler',          'EmartCrawler',      'mart'),
    ('코코달인',  'crawlers.marts.cocodalin.crawler',      'CocodalinCrawler',  'mart'),
]

async def collect():
    for name, module, cls_name, dtype in crawlers_to_run:
        print(f"수집 중: {name}...")
        try:
            mod = __import__(module, fromlist=[cls_name])
            cls = getattr(mod, cls_name)
            result = await cls().crawl()
            if result.items_count > 0:
                for item in result.items:
                    item['_source'] = name
                    item['_crawled_at'] = datetime.now().isoformat()
                if dtype == 'hotdeal':
                    all_hotdeals.extend(result.items)
                else:
                    all_mart_deals.extend(result.items)
                print(f"  ✅ {result.items_count}건")
            else:
                print(f"  ⚠️ 0건 수집됨")
        except Exception as e:
            print(f"  ❌ {e}")
        await asyncio.sleep(2)

asyncio.run(collect())

# Save as JSON
output_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'website', 'frontend', 'src', 'data')
os.makedirs(output_dir, exist_ok=True)

with open(os.path.join(output_dir, 'realHotdeals.json'), 'w', encoding='utf-8') as f:
    json.dump(all_hotdeals, f, ensure_ascii=False, indent=2, default=str)

with open(os.path.join(output_dir, 'realMartDeals.json'), 'w', encoding='utf-8') as f:
    json.dump(all_mart_deals, f, ensure_ascii=False, indent=2, default=str)

print(f"\n총 핫딜: {len(all_hotdeals)}건, 마트: {len(all_mart_deals)}건")
print(f"저장 위치: {output_dir}")
