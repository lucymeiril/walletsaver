"""실제 크롤링 테스트 — 라이브 사이트에서 데이터 수집 검증.

뽐뿌(핫딜)와 이마트(마트) 크롤러를 실제 사이트에 대해 실행하고
데이터 스키마와 수집 결과를 검증한다.
"""

import asyncio
import json
import sys
import os
import traceback
from datetime import datetime

# sys.path 설정: backend/ 와 shared/core/ 를 import 경로에 추가
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PACKAGES_DIR = os.path.dirname(os.path.dirname(BACKEND_DIR))
sys.path.insert(0, BACKEND_DIR)
sys.path.insert(0, os.path.join(PACKAGES_DIR, "shared"))

# SSL 경고 억제
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

import logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


async def test_crawler(crawler_class, name: str) -> dict:
    """크롤러 하나를 실행하고 결과를 검증한다."""
    print(f"\n{'='*60}")
    print(f"🕷️  테스트: {name}")
    print(f"{'='*60}")

    result_info = {"name": name, "success": False, "items": [], "errors": []}

    try:
        crawler = crawler_class()
        print(f"  대상 URL: {crawler.info.target_url}")
        print(f"  전략: {crawler.info.strategies}")
        print(f"  크롤링 시작...")

        result = await crawler.crawl()

        print(f"\n  📊 결과:")
        print(f"    상태: {result.status}")
        print(f"    전략: {result.strategy_used}")
        print(f"    수집 건수: {result.items_count}")
        print(f"    소요 시간: {result.duration_seconds:.1f}초")

        if result.error_msg:
            print(f"    에러 메시지: {result.error_msg}")
            result_info["errors"].append(result.error_msg)

        if result.errors:
            print(f"\n  ⚠️  전략 에러:")
            for err in result.errors:
                msg = f"{err.strategy_name}: {err.error_type} — {err.error_msg[:100]}"
                print(f"    - {msg}")
                result_info["errors"].append(msg)

        if result.items_count > 0:
            result_info["success"] = True
            result_info["items_count"] = result.items_count

            # 스키마 검증
            print(f"\n  🔍 스키마 검증 (첫 번째 아이템):")
            item = result.items[0]
            for key, val in item.items():
                val_str = str(val)[:80] if val is not None else "None"
                print(f"    {key}: {type(val).__name__} = {val_str}")

            # 샘플 데이터
            print(f"\n  📋 샘플 데이터 (처음 5개):")
            for i, item in enumerate(result.items[:5]):
                title = item.get("title", item.get("name", "N/A"))
                price = item.get("price", item.get("sale_price", "N/A"))
                url = item.get("url", item.get("detail_url", ""))
                print(f"    [{i+1}] {title}")
                print(f"        가격: {price}원  |  URL: {url[:70]}...")

            result_info["items"] = result.items[:5]
            result_info["schema_keys"] = list(result.items[0].keys())
        else:
            print(f"\n  ❌ 수집된 데이터 없음")
            # raw_data 확인
            if result.raw_data:
                print(f"    raw_data 길이: {len(result.raw_data)} 문자")
                print(f"    raw_data 미리보기: {result.raw_data[:300]}")

        return result_info

    except Exception as e:
        print(f"  ❌ 예외 발생: {e}")
        traceback.print_exc()
        result_info["errors"].append(str(e))
        return result_info


def validate_hotdeal_schema(items: list[dict]) -> list[str]:
    """HotdealPost 스키마 검증."""
    errors = []
    required = ["title", "url", "source_community"]
    for i, item in enumerate(items):
        for field in required:
            if field not in item or not item[field]:
                errors.append(f"아이템[{i}]: {field} 누락 또는 비어있음")
        if "title" in item and len(str(item["title"])) < 3:
            errors.append(f"아이템[{i}]: title 너무 짧음 ({item['title']})")
        if "url" in item and not str(item["url"]).startswith("http"):
            errors.append(f"아이템[{i}]: url 형식 오류 ({item['url'][:50]})")
    return errors


def validate_discount_schema(items: list[dict]) -> list[str]:
    """DiscountItem 스키마 검증."""
    errors = []
    required = ["name", "store", "sale_price"]
    for i, item in enumerate(items):
        for field in required:
            if field not in item:
                errors.append(f"아이템[{i}]: {field} 누락")
            elif field == "sale_price" and (not isinstance(item[field], (int, float)) or item[field] <= 0):
                errors.append(f"아이템[{i}]: sale_price 유효하지 않음 ({item[field]})")
            elif field == "name" and len(str(item[field])) < 2:
                errors.append(f"아이템[{i}]: name 너무 짧음 ({item[field]})")
    return errors


async def main():
    print("=" * 60)
    print("🚀 WalletSavior 실제 크롤링 테스트")
    print(f"   시작 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    results = {}

    # ── 1) 뽐뿌 핫딜 크롤러 ──
    try:
        from crawlers.hotdeals.ppomppu.crawler import PpomppuCrawler
        results["ppomppu"] = await test_crawler(PpomppuCrawler, "뽐뿌 핫딜 (ppomppu)")
    except ImportError as e:
        print(f"\n❌ 뽐뿌 크롤러 import 실패: {e}")
        traceback.print_exc()
        results["ppomppu"] = {"name": "뽐뿌", "success": False, "errors": [str(e)]}

    # ── 2) 이마트 크롤러 ──
    try:
        from crawlers.marts.emart.crawler import EmartCrawler
        results["emart"] = await test_crawler(EmartCrawler, "이마트 (emart)")
    except ImportError as e:
        print(f"\n❌ 이마트 크롤러 import 실패: {e}")
        traceback.print_exc()
        results["emart"] = {"name": "이마트", "success": False, "errors": [str(e)]}

    # ── 3) 스키마 검증 ──
    print(f"\n\n{'='*60}")
    print("🔬 스키마 검증 결과")
    print(f"{'='*60}")

    if results.get("ppomppu", {}).get("items"):
        errors = validate_hotdeal_schema(results["ppomppu"]["items"])
        if errors:
            print(f"\n  뽐뿌 스키마 오류:")
            for e in errors:
                print(f"    ❌ {e}")
        else:
            print(f"\n  ✅ 뽐뿌 HotdealPost 스키마 검증 통과 ({len(results['ppomppu']['items'])}건)")

    if results.get("emart", {}).get("items"):
        errors = validate_discount_schema(results["emart"]["items"])
        if errors:
            print(f"\n  이마트 스키마 오류:")
            for e in errors:
                print(f"    ❌ {e}")
        else:
            print(f"\n  ✅ 이마트 DiscountItem 스키마 검증 통과 ({len(results['emart']['items'])}건)")

    # ── 4) 종합 요약 ──
    print(f"\n\n{'='*60}")
    print("📊 종합 결과")
    print(f"{'='*60}")
    for key, res in results.items():
        status = "✅ 성공" if res.get("success") else "❌ 실패"
        count = res.get("items_count", 0)
        print(f"  {res['name']}: {status} ({count}건)")
        if res.get("errors"):
            for err in res["errors"][:3]:
                print(f"    ⚠️  {err[:100]}")

    print(f"\n완료 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # ── 5) 파이프라인 통합 테스트 ──
    print(f"\n\n{'='*60}")
    print("🔗 파이프라인 통합 테스트")
    print(f"{'='*60}")
    await test_pipeline(results)

    return results


async def test_pipeline(crawl_results: dict):
    """파이프라인 (검증→변환→저장) 통합 테스트."""
    try:
        from pipeline.validator import validate_items, validate_price_range, deduplicate, normalize_prices
        from pipeline.transformer import to_discount_history, to_hotdeal_prices, enrich_with_category

        # 뽐뿌 핫딜 파이프라인
        ppomppu = crawl_results.get("ppomppu", {})
        if ppomppu.get("items"):
            print("\n  📦 뽐뿌 파이프라인:")
            items = list(ppomppu["items"])
            items = normalize_prices(items)
            items = enrich_with_category(items)
            records = to_hotdeal_prices(items, source="hotdeal")
            print(f"    변환 완료: {len(records)}개 레코드")
            if records:
                print(f"    샘플: {json.dumps(records[0], ensure_ascii=False, indent=2)[:300]}")

        # 이마트 파이프라인
        emart = crawl_results.get("emart", {})
        if emart.get("items"):
            print("\n  📦 이마트 파이프라인:")
            items = list(emart["items"])
            items = normalize_prices(items, price_field="sale_price")
            items = deduplicate(items, key_fields=["name", "sale_price"])
            items = enrich_with_category(items)
            records = to_discount_history(items, source="mart_discount")
            print(f"    변환 완료: {len(records)}개 레코드")
            if records:
                print(f"    샘플: {json.dumps(records[0], ensure_ascii=False, indent=2)[:300]}")

        # DB-Admin ingestion API 테스트
        print("\n  🗄️  DB-Admin 대기열 연결 테스트:")
        try:
            import requests as req
            # 기존 대기열 확인
            r = req.get("http://localhost:8002/api/ingestions", timeout=5)
            if r.status_code == 200:
                data = r.json()
                print(f"    ✅ DB-Admin API 연결 성공 (상태: {r.status_code})")
                if isinstance(data, list):
                    print(f"    대기열 항목: {len(data)}개")
                elif isinstance(data, dict):
                    print(f"    응답: {json.dumps(data, ensure_ascii=False)[:200]}")
            else:
                print(f"    ⚠️  DB-Admin API 응답: {r.status_code}")
        except Exception as e:
            print(f"    ❌ DB-Admin API 연결 실패: {e}")
            print(f"       (db-admin이 포트 8002에서 실행 중인지 확인)")

    except Exception as e:
        print(f"  ❌ 파이프라인 테스트 실패: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    results = asyncio.run(main())
