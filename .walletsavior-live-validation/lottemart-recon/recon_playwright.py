"""
롯데마트 Playwright 정찰 스크립트.
프로모션 페이지에서 스크롤/페이지네이션으로 추가 상품을 로드하는 API 패턴을 파악한다.
"""
import sys
import os
import json
import re
import time
import datetime

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'packages', 'crawler-admin', 'backend'))

from playwright.sync_api import sync_playwright

ZETTA_BASE = "https://lottemartzetta.com"
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
PROMOTIONS_URL = f"{ZETTA_BASE}/promotions?source=header%20button"


def run_recon():
    api_calls = []
    product_api_calls = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            viewport={"width": 1366, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        
        # Intercept all API requests
        def on_request(request):
            url = request.url
            if any(x in url for x in ['/api/', 'products', 'promotions', 'catalog', 'search']):
                api_calls.append({
                    "url": url,
                    "method": request.method,
                    "resource_type": request.resource_type,
                })
        
        def on_response(response):
            url = response.url
            # Capture product API responses
            if any(x in url for x in ['/api/products', '/api/promotions', '/api/catalog', '/v1/products']):
                try:
                    body = response.body()
                    product_api_calls.append({
                        "url": url,
                        "status": response.status,
                        "content_type": response.headers.get("content-type", ""),
                        "body_preview": body[:500].decode('utf-8', errors='replace'),
                        "body_size": len(body),
                    })
                    print(f"  [API] {response.status} {url[:100]}")
                except Exception as e:
                    pass
        
        page.on("request", on_request)
        page.on("response", on_response)
        
        print(f"[1] 프로모션 페이지 로드: {PROMOTIONS_URL}")
        page.goto(PROMOTIONS_URL, wait_until="networkidle", timeout=30000)
        
        # Wait a bit for initial rendering
        page.wait_for_timeout(3000)
        
        # Count initial products
        initial_count = page.evaluate("""
            () => {
                const cards = document.querySelectorAll('.product-card-container, [class*="productCard"], [class*="ProductCard"], [data-testid*="product"]');
                return cards.length;
            }
        """)
        print(f"  초기 상품 카드 수: {initial_count}")
        
        # Try to find pagination button or load more
        pagination_info = page.evaluate("""
            () => {
                const result = {};
                // Look for page buttons
                const pageButtons = document.querySelectorAll('[class*="pagination"] button, [class*="page"] button');
                result.pageButtons = Array.from(pageButtons).map(b => b.textContent.trim()).filter(t => t).slice(0, 20);
                // Look for load more button
                const loadMore = document.querySelectorAll('[class*="loadMore"], [class*="load-more"], [class*="더보기"]');
                result.loadMoreCount = loadMore.length;
                result.loadMoreText = Array.from(loadMore).map(b => b.textContent.trim()).slice(0, 5);
                // Look for category navigation
                const cats = document.querySelectorAll('[class*="category"] a, [class*="Category"] a, nav a');
                result.catLinks = Array.from(cats).map(a => ({text: a.textContent.trim(), href: a.href})).filter(a => a.text).slice(0, 30);
                return result;
            }
        """)
        print(f"  페이지 버튼: {pagination_info.get('pageButtons', [])[:10]}")
        print(f"  더보기 버튼: {pagination_info.get('loadMoreCount', 0)}개 - {pagination_info.get('loadMoreText', [])}")
        
        # Save category links
        cat_links = pagination_info.get('catLinks', [])
        print(f"  카테고리 링크: {len(cat_links)}개")
        for cl in cat_links[:15]:
            print(f"    {cl['text']}: {cl['href']}")
        
        # Scroll down to trigger lazy loading
        print("\n[2] 스크롤 다운 (상품 추가 로드 시도)")
        prev_count = initial_count
        for scroll_i in range(6):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(2000)
            count = page.evaluate("""
                () => document.querySelectorAll('.product-card-container, [class*="productCard"], [class*="ProductCard"]').length
            """)
            print(f"  스크롤 {scroll_i+1}: {count}개 상품 (이전: {prev_count})")
            if count == prev_count and scroll_i > 1:
                print("  → 더 이상 새 상품 없음, 중단")
                break
            prev_count = count
        
        final_count = prev_count
        print(f"\n  최종 상품 카드 수: {final_count}")
        
        # Save HTML after scrolling
        html = page.content()
        ts = datetime.datetime.now().strftime("%H%M%S")
        scrolled_html_path = os.path.join(OUT_DIR, f"promotions_scrolled_{ts}.html")
        with open(scrolled_html_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"  스크롤 후 HTML 저장: {scrolled_html_path}")
        
        # Also capture __INITIAL_STATE__ entities after scroll
        entities_after = page.evaluate("""
            () => {
                try {
                    const state = window.__INITIAL_STATE__;
                    if (!state) return {count: 0, keys: []};
                    const data = state.data || {};
                    const prods = (data.products || {}).productEntities || {};
                    return {count: Object.keys(prods).length, keys: Object.keys(prods).slice(0, 5)};
                } catch(e) {
                    return {count: 0, error: e.message};
                }
            }
        """)
        print(f"  __INITIAL_STATE__ entities after scroll: {entities_after}")
        
        # Check if there's a JS-accessible products list (React/Redux state)
        redux_count = page.evaluate("""
            () => {
                try {
                    // Try to find Redux store
                    const rootEl = document.getElementById('root') || document.getElementById('__next') || document.getElementById('app');
                    if (!rootEl) return 'no root el';
                    // Check for React fiber
                    const fiber = rootEl._reactFiber || rootEl.__reactFiber || 
                                  Object.keys(rootEl).filter(k => k.startsWith('__reactFiber'))[0];
                    return fiber ? 'react found' : 'no react fiber';
                } catch(e) {
                    return e.message;
                }
            }
        """)
        print(f"  React/Redux: {redux_count}")
        
        # Try to click load more / next page button if exists
        try:
            more_btn = page.query_selector('button:has-text("더보기"), button:has-text("다음"), [class*="loadMore"]')
            if more_btn:
                print(f"\n[3] '더보기' 버튼 발견 — 클릭 시도")
                more_btn.click()
                page.wait_for_timeout(3000)
                count_after_more = page.evaluate("""
                    () => document.querySelectorAll('.product-card-container, [class*="productCard"]').length
                """)
                print(f"  더보기 클릭 후 상품 수: {count_after_more}")
        except Exception as e:
            print(f"  더보기 버튼 없음: {e}")
        
        # Save API calls
        print(f"\n[4] API 호출 목록 (총 {len(api_calls)}개)")
        for call in api_calls[:30]:
            print(f"  [{call['method']}] {call['url'][:120]}")
        
        print(f"\n[5] 상품 API 응답 (총 {len(product_api_calls)}개)")
        for call in product_api_calls[:10]:
            print(f"  {call['status']} {call['url'][:100]}")
            print(f"    body_preview: {call['body_preview'][:100]}")
        
        browser.close()
    
    # Summary
    summary = {
        "timestamp": datetime.datetime.now().isoformat(),
        "promotions_url": PROMOTIONS_URL,
        "initial_product_count": initial_count,
        "final_product_count_after_scroll": final_count,
        "api_calls_captured": api_calls,
        "product_api_calls": product_api_calls,
        "pagination_info": pagination_info,
        "scrolled_html_path": scrolled_html_path,
    }
    summary_path = os.path.join(OUT_DIR, "playwright-recon-summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\n요약 저장: {summary_path}")
    return summary


if __name__ == "__main__":
    run_recon()
