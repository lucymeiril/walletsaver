"""
롯데마트 API 패턴 파악 — PUT /api/webproductpagews/v6/products 요청/응답 캡처.
"""
import sys
import os
import json
import re
import time
import datetime

from playwright.sync_api import sync_playwright

ZETTA_BASE = "https://lottemartzetta.com"
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
PROMOTIONS_URL = f"{ZETTA_BASE}/promotions?source=header%20button"


def run_api_recon():
    api_interactions = []
    
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
        
        # Capture PUT /api/webproductpagews/v6/products in detail
        def on_request(request):
            if 'webproductpagews' in request.url or 'recommendations' in request.url:
                try:
                    body_str = request.post_data or ""
                    api_interactions.append({
                        "type": "request",
                        "method": request.method,
                        "url": request.url,
                        "headers": dict(request.all_headers()),
                        "body": body_str,
                    })
                    print(f"  [REQ] {request.method} {request.url[:100]}")
                    if body_str:
                        print(f"    body: {body_str[:300]}")
                except Exception as e:
                    print(f"  [REQ ERR] {e}")
        
        def on_response(response):
            if 'webproductpagews' in response.url or 'recommendations' in response.url:
                try:
                    body = response.body()
                    body_str = body.decode('utf-8', errors='replace')
                    api_interactions.append({
                        "type": "response",
                        "url": response.url,
                        "status": response.status,
                        "content_type": response.headers.get("content-type", ""),
                        "body": body_str[:2000],
                        "body_size": len(body),
                    })
                    print(f"  [RESP] {response.status} {response.url[:100]} ({len(body)} bytes)")
                    # Try to parse product count
                    try:
                        data = json.loads(body_str)
                        if isinstance(data, list):
                            print(f"    → list of {len(data)} items")
                        elif isinstance(data, dict):
                            # Look for products
                            def count_products(d, depth=0):
                                if not isinstance(d, dict) or depth > 5:
                                    return -1
                                for key in ('products', 'items', 'productEntities', 'data'):
                                    val = d.get(key)
                                    if isinstance(val, list):
                                        return len(val)
                                    if isinstance(val, dict):
                                        r = count_products(val, depth+1)
                                        if r > 0:
                                            return r
                                return -1
                            cnt = count_products(data)
                            print(f"    → dict, products≈{cnt}, keys={list(data.keys())[:10]}")
                    except:
                        pass
                except Exception as e:
                    print(f"  [RESP ERR] {e}")
        
        page.on("request", on_request)
        page.on("response", on_response)
        
        print(f"페이지 로드...")
        page.goto(PROMOTIONS_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)
        
        print(f"\n스크롤 10회 (10초씩 대기)...")
        prev_count = 0
        for i in range(12):
            count = page.evaluate("""
                () => document.querySelectorAll('.product-card-container').length
            """)
            print(f"  스크롤 {i}: {count}개")
            if count >= 250:
                break
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(2000)
        
        final_count = page.evaluate("""
            () => document.querySelectorAll('.product-card-container').length
        """)
        print(f"\n최종 상품 수: {final_count}")
        
        # Save final HTML
        html = page.content()
        ts = datetime.datetime.now().strftime("%H%M%S")
        html_path = os.path.join(OUT_DIR, f"promotions_scrolled_full_{ts}.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"HTML 저장: {html_path}")
        
        browser.close()
    
    # Save API interactions
    summary_path = os.path.join(OUT_DIR, "api-recon-summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": datetime.datetime.now().isoformat(),
            "final_product_count": final_count,
            "api_interactions": api_interactions,
        }, f, ensure_ascii=False, indent=2)
    print(f"\nAPI 상세 저장: {summary_path}")
    print(f"\n총 API 인터랙션: {len(api_interactions)}개")
    for ai in api_interactions:
        if ai["type"] == "request":
            print(f"  REQ {ai['method']} {ai['url'][:100]}")
            if ai.get("body"):
                print(f"       body: {ai['body'][:200]}")
        else:
            print(f"  RESP {ai['status']} {ai['url'][:100]} ({ai.get('body_size',0)} bytes)")
    return final_count, api_interactions


if __name__ == "__main__":
    fc, api = run_api_recon()
    print(f"\n=== 결과: {fc}개 상품 ===")
