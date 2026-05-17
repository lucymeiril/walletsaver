"""
롯데마트 lottemartzetta.com 사이트 정찰 스크립트.
URL 패턴별로 HTTP GET을 수행하고 __INITIAL_STATE__ productEntities 수를 파악한다.
"""
import sys
import os
import json
import re
import time
import datetime
import random
import requests

ZETTA_BASE = "https://lottemartzetta.com"
OUT_DIR = os.path.dirname(os.path.abspath(__file__))

HEADERS_BASE = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    "Referer": f"{ZETTA_BASE}/",
}


def extract_initial_state_count(html: str) -> int:
    match = re.search(r"window\.__INITIAL_STATE__\s*=\s*", html)
    if not match:
        return -1  # no marker
    start = match.end()
    script_end = html.find("</script>", start)
    candidate = html[start:script_end if script_end >= 0 else len(html)].strip()
    if not candidate:
        return 0
    try:
        decoder = json.JSONDecoder()
        data, _ = decoder.raw_decode(candidate)
    except Exception:
        try:
            data = json.loads(candidate.rstrip().rstrip(";"))
        except Exception:
            return 0
    # find productEntities
    def find_entities(d, depth=0):
        if not isinstance(d, dict) or depth > 10:
            return {}
        direct_data = d.get("data") if isinstance(d.get("data"), dict) else {}
        products = direct_data.get("products") if isinstance(direct_data.get("products"), dict) else {}
        if isinstance(products.get("productEntities"), dict):
            return products["productEntities"]
        if isinstance(d.get("productEntities"), dict):
            return d["productEntities"]
        for v in d.values():
            if isinstance(v, dict):
                found = find_entities(v, depth + 1)
                if found:
                    return found
        return {}
    entities = find_entities(data)
    return len(entities)


def extract_total_products(html: str) -> int:
    """Try to find total product count from initial state."""
    match = re.search(r"window\.__INITIAL_STATE__\s*=\s*", html)
    if not match:
        return -1
    start = match.end()
    script_end = html.find("</script>", start)
    candidate = html[start:script_end if script_end >= 0 else len(html)].strip()
    try:
        decoder = json.JSONDecoder()
        data, _ = decoder.raw_decode(candidate)
    except Exception:
        return -1
    # Look for totalCount, total, count patterns
    def find_total(d, depth=0):
        if not isinstance(d, dict) or depth > 15:
            return -1
        for key in ("totalCount", "total", "totalItems", "count", "totalProducts"):
            if key in d and isinstance(d[key], int) and d[key] > 0:
                return d[key]
        for v in d.values():
            if isinstance(v, dict):
                r = find_total(v, depth + 1)
                if r > 0:
                    return r
        return -1
    return find_total(data)


def probe_url(session, url: str, delay: float = 2.0) -> dict:
    time.sleep(delay)
    result = {"url": url, "status": None, "entities_count": -1, "total_count": -1, 
              "has_initial_state": False, "is_waf": False, "error": None,
              "html_size": 0}
    try:
        resp = session.get(url, headers=HEADERS_BASE, timeout=20, allow_redirects=True)
        result["status"] = resp.status_code
        result["final_url"] = resp.url
        html = resp.text
        result["html_size"] = len(html)
        result["has_initial_state"] = "__INITIAL_STATE__" in html
        result["is_waf"] = "awswaf" in html[:3000].lower() or "aws-waf" in html[:3000].lower()
        if result["has_initial_state"]:
            result["entities_count"] = extract_initial_state_count(html)
            result["total_count"] = extract_total_products(html)
        print(f"  {resp.status_code} | entities={result['entities_count']} total={result['total_count']} waf={result['is_waf']} size={len(html)//1024}KB | {url}")
        # Save HTML if has data
        if result["entities_count"] > 0:
            slug = url.replace(ZETTA_BASE, "").replace("/", "_").replace("?", "_").replace("&", "_").replace("=", "_").replace("%", "_").replace(" ", "_")[:80]
            ts = datetime.datetime.now().strftime("%H%M%S")
            fname = os.path.join(OUT_DIR, f"page_{ts}_{slug}.html")
            with open(fname, "w", encoding="utf-8") as f:
                f.write(html)
            result["saved_to"] = fname
            print(f"    → saved {fname}")
    except Exception as e:
        result["error"] = str(e)
        print(f"  ERROR | {url} : {e}")
    return result


def main():
    session = requests.Session()
    results = []
    
    print("=== Step 1: robots.txt / sitemap ===")
    for url in [f"{ZETTA_BASE}/robots.txt", f"{ZETTA_BASE}/sitemap.xml"]:
        r = probe_url(session, url, delay=1.0)
        results.append(r)
    
    print("\n=== Step 2: 주요 페이지 탐색 ===")
    probe_urls = [
        # 프로모션 페이지 (사용자 제시 URL)
        f"{ZETTA_BASE}/promotions",
        f"{ZETTA_BASE}/promotions?source=header%20button",
        # 프로모션 페이지네이션
        f"{ZETTA_BASE}/promotions?page=1",
        f"{ZETTA_BASE}/promotions?page=2",
        f"{ZETTA_BASE}/promotions?page=3",
        f"{ZETTA_BASE}/promotions?page=4",
        # 검색 페이지네이션 (기존 코드)
        f"{ZETTA_BASE}/search?query=%ED%95%A0%EC%9D%B8&page=1",
        f"{ZETTA_BASE}/search?query=%ED%95%A0%EC%9D%B8&page=2",
        f"{ZETTA_BASE}/search?query=%ED%95%A0%EC%9D%B8&page=3",
        # 베스트/특가
        f"{ZETTA_BASE}/best",
        f"{ZETTA_BASE}/sale",
        f"{ZETTA_BASE}/event",
        # 카테고리
        f"{ZETTA_BASE}/categories",
        f"{ZETTA_BASE}/categories/food",
        f"{ZETTA_BASE}/categories/fresh",
    ]
    for url in probe_urls:
        r = probe_url(session, url, delay=2.0)
        results.append(r)
    
    print("\n=== Step 3: 카테고리 탐색 (초기 상태에서 카테고리 트리 추출) ===")
    # Try to extract category URLs from a successful page
    for r in results:
        if r.get("entities_count", 0) > 0 and r.get("saved_to"):
            with open(r["saved_to"], encoding="utf-8") as f:
                html = f.read()
            # Extract category paths from initial state
            match = re.search(r"window\.__INITIAL_STATE__\s*=\s*", html)
            if match:
                start = match.end()
                script_end = html.find("</script>", start)
                candidate = html[start:script_end if script_end >= 0 else len(html)].strip()
                try:
                    decoder = json.JSONDecoder()
                    data, _ = decoder.raw_decode(candidate)
                    # Extract all URLs/paths from the state
                    cat_paths = set()
                    state_str = json.dumps(data)
                    # Find category-like paths
                    cat_matches = re.findall(r'"(/categories/[^"]+)"', state_str)
                    for cm in cat_matches[:20]:
                        cat_paths.add(cm)
                    # Find pagination info
                    page_matches = re.findall(r'"(page(?:Size|Count|Total|Num|Number|s)?)"\s*:\s*(\d+)', state_str)
                    print(f"  Page-related fields: {page_matches[:10]}")
                    
                    if cat_paths:
                        print(f"  Found {len(cat_paths)} category paths: {list(cat_paths)[:10]}")
                        for cp in list(cat_paths)[:10]:
                            cat_url = f"{ZETTA_BASE}{cp}"
                            cr = probe_url(session, cat_url, delay=3.0)
                            results.append(cr)
                except Exception as e:
                    print(f"  Category extract error: {e}")
            break

    # Summary
    print("\n=== 결과 요약 ===")
    working = [r for r in results if r.get("entities_count", 0) > 0]
    print(f"데이터 있는 URL: {len(working)}/{len(results)}")
    for r in working:
        print(f"  {r['entities_count']} entities, total={r['total_count']}: {r['url']}")
    
    summary = {
        "timestamp": datetime.datetime.now().isoformat(),
        "total_probed": len(results),
        "working_urls": len(working),
        "results": results,
    }
    summary_path = os.path.join(OUT_DIR, "lottemart-recon-summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\n요약 저장: {summary_path}")
    return results


if __name__ == "__main__":
    main()
