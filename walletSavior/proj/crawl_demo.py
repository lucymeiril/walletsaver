"""
크롤링 데모 스크립트.

콘솔에서 실행하여 실제 웹사이트에서 데이터를 크롤링한다.
API 키 없이 동작하는 크롤러만 테스트.

사용법:
    python crawl_demo.py
"""

import asyncio
import json
import sys
import os
import io

# Windows 콘솔 UTF-8 출력 설정
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crawlers.hotdeals.algumon.crawler import AlgumonCrawler


def print_header(text: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}\n")


def print_item(idx: int, item: dict) -> None:
    title = item.get("title", "")[:60]
    price = item.get("price")
    source = item.get("source", "")
    url = item.get("url", "")[:80]

    price_str = f"{price:,}원" if price else "가격 정보 없음"
    source_str = f" [{source}]" if source else ""

    print(f"  {idx:3d}. {title}")
    print(f"       {price_str}{source_str}")
    print(f"       {url}")
    print()


async def run_algumon():
    """알구몬 핫딜 크롤링."""
    print_header("[알구몬] 핫딜 크롤링 시작")

    crawler = AlgumonCrawler()
    print(f"  크롤러: {crawler.info.name}")
    print(f"  대상: {crawler.info.target_url}")
    print(f"  전략: {', '.join(crawler.info.strategies)}")
    print()

    result = await crawler.crawl()

    print(f"  상태: {result.status.value}")
    print(f"  수집 항목: {result.items_count}개")
    print(f"  소요 시간: {result.duration_seconds:.2f}초")

    if result.status.value == "success" and result.items:
        print_header(f"[수집 결과] 핫딜 {result.items_count}개")

        # 가격 있는 항목 먼저
        with_price = [i for i in result.items if i.get("price")]
        without_price = [i for i in result.items if not i.get("price")]

        if with_price:
            print("  -- 가격 추출 성공 --")
            for idx, item in enumerate(with_price[:10], 1):
                print_item(idx, item)

        if without_price:
            print(f"  -- 가격 미추출 ({len(without_price)}개 중 상위 5개) --")
            for idx, item in enumerate(without_price[:5], 1):
                print_item(idx, item)

        # 통계
        prices = [i["price"] for i in with_price if i["price"]]
        if prices:
            print_header("[가격 통계]")
            print(f"  가격 추출 성공: {len(prices)}개 / 전체 {result.items_count}개")
            print(f"  최저가: {min(prices):,}원")
            print(f"  최고가: {max(prices):,}원")
            print(f"  평균가: {sum(prices) // len(prices):,}원")

        # 소스별 분포
        sources = {}
        for item in result.items:
            src = item.get("source", "미확인") or "미확인"
            sources[src] = sources.get(src, 0) + 1

        if sources:
            print_header("[소스별 분포]")
            for src, count in sorted(sources.items(), key=lambda x: -x[1]):
                bar = "#" * min(count, 40)
                print(f"  {src:12s} | {count:3d}개 {bar}")

    elif result.error_msg:
        print(f"\n  [오류] {result.error_msg}")

    return result


async def main():
    print_header("지갑 지키미 - 크롤링 데모 (API 키 불필요)")
    print("  현재 테스트 가능한 크롤러:")
    print("  1. 알구몬 (핫딜 통합)")
    print()

    # 알구몬 크롤링
    result = await run_algumon()

    print_header("[완료] 크롤링 데모 종료")
    print(f"  총 수집: {result.items_count}개 항목")

    # JSON 파일로 저장
    if result.items:
        output_path = os.path.join(os.path.dirname(__file__), "crawled_data.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result.items, f, ensure_ascii=False, indent=2)
        print(f"  데이터 저장: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
