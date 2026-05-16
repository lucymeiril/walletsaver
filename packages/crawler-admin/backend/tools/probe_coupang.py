"""쿠팡 검색 1페이지 운영자 워크밴치 캡처 (TDD Phase A).

목적:
    requests 단독 GET은 Akamai/봇디텍션에 막혀 403이 반환된다(2026-05-16 라이브 확인).
    운영자 본인 PC에서 헤드풀 크롬으로 검색 결과 1페이지를 그대로 캡처해
    fixture로 보관 → 파서를 그 fixture에 묶어 회귀하는 게 정공.

전략 순서:
    1) playwright headful chromium — 표준 크롬 UA, 사람 같은 딜레이/스크롤, 백오프 재시도.
    2) (옵션) undetected-chromedriver — playwright 가 막힐 때만.

산출물:
    tests/fixtures/live_probe/coupang_search_{query}.html  (전체 렌더 HTML)

사용:
    py -3 tools/probe_coupang.py [--query 생수] [--retries 3]
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
FIXTURE_DIR = BACKEND_DIR / "tests" / "fixtures" / "live_probe"
FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_QUERY = "생수"
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _human_sleep(lo: float = 0.6, hi: float = 1.6) -> None:
    time.sleep(random.uniform(lo, hi))


def capture_with_playwright(query: str, *, headless: bool = False, timeout_ms: int = 45000) -> tuple[int, str, str]:
    """Returns (status_code, final_url, html). status_code -1 = no response captured."""
    from playwright.sync_api import sync_playwright

    url = f"https://www.coupang.com/np/search?q={query}&channel=user"
    final_status = -1
    final_url = url
    html = ""
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        ctx = browser.new_context(
            user_agent=DEFAULT_UA,
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            viewport={"width": 1366, "height": 900},
            extra_http_headers={
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            },
        )
        # webdriver flag stealth
        ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        page = ctx.new_page()

        def _on_response(resp):
            nonlocal final_status, final_url
            try:
                if resp.url.startswith("https://www.coupang.com/np/search"):
                    final_status = resp.status
                    final_url = resp.url
            except Exception:
                pass

        page.on("response", _on_response)

        # warm-up: 홈 → 사람처럼 잠시 대기 → 검색
        try:
            page.goto("https://www.coupang.com/", wait_until="domcontentloaded", timeout=timeout_ms)
            _human_sleep(1.0, 2.5)
        except Exception as e:
            print(f"[probe] warm-up failed (continuing): {e}", file=sys.stderr)

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        except Exception as e:
            print(f"[probe] search goto failed: {e}", file=sys.stderr)
            browser.close()
            return final_status, final_url, ""

        _human_sleep(1.5, 3.0)
        try:
            page.mouse.move(400, 400)
            page.mouse.wheel(0, 800)
            _human_sleep(0.5, 1.2)
            page.mouse.wheel(0, 1200)
            _human_sleep(0.8, 1.6)
        except Exception:
            pass

        # 카드 등장 대기 — 셀렉터 미상일 수 있으니 부드럽게
        for sel in ("ul#productList li", "li.search-product", "[data-product-id]"):
            try:
                page.wait_for_selector(sel, timeout=4000)
                break
            except Exception:
                continue

        try:
            html = page.content()
        except Exception as e:
            print(f"[probe] content() failed: {e}", file=sys.stderr)
            html = ""

        browser.close()
    return final_status, final_url, html


def capture_with_undetected(query: str, *, timeout_s: int = 45) -> tuple[int, str, str]:
    """Fallback: undetected-chromedriver. status_code는 selenium에서 직접 못 얻어 -1 표시."""
    try:
        import undetected_chromedriver as uc
    except Exception as e:
        print(f"[probe] undetected-chromedriver 사용 불가: {e}", file=sys.stderr)
        return -1, "", ""

    options = uc.ChromeOptions()
    options.add_argument(f"--user-agent={DEFAULT_UA}")
    options.add_argument("--lang=ko-KR")
    options.add_argument("--window-size=1366,900")
    driver = uc.Chrome(options=options, headless=False, use_subprocess=True)
    url = f"https://www.coupang.com/np/search?q={query}&channel=user"
    try:
        driver.get("https://www.coupang.com/")
        time.sleep(random.uniform(1.0, 2.0))
        driver.get(url)
        time.sleep(random.uniform(3.0, 5.0))
        html = driver.page_source
        final_url = driver.current_url
        return 200 if html else -1, final_url, html
    finally:
        try:
            driver.quit()
        except Exception:
            pass


def looks_like_block(html: str) -> bool:
    if not html:
        return True
    lowered = html.lower()
    if "access denied" in lowered or "akamai" in lowered:
        return True
    if "잠시 후 다시" in html or "비정상적인 접근" in html:
        return True
    # 정상 검색 결과면 productList 또는 search-product 가 보인다
    if "productList" in html or "search-product" in html or "search-product-link" in html:
        return False
    # 페이지가 너무 작으면 차단 의심
    return len(html) < 20000


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", default=DEFAULT_QUERY)
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--out", default=None)
    ap.add_argument("--headless", action="store_true", help="헤드리스로 시도 (보통 비추)")
    ap.add_argument("--use-undetected", action="store_true")
    args = ap.parse_args()

    out_path = Path(args.out) if args.out else FIXTURE_DIR / f"coupang_search_{args.query}.html"

    for attempt in range(1, args.retries + 1):
        backoff = random.uniform(2.0, 5.0) * attempt
        print(f"[probe] attempt {attempt}/{args.retries} (query={args.query!r}) ...", file=sys.stderr)
        try:
            if args.use_undetected:
                status, final_url, html = capture_with_undetected(args.query)
            else:
                status, final_url, html = capture_with_playwright(args.query, headless=args.headless)
        except Exception as e:
            print(f"[probe] attempt {attempt} raised: {e}", file=sys.stderr)
            status, final_url, html = -1, "", ""

        print(f"[probe] status={status} final_url={final_url} bytes={len(html)}", file=sys.stderr)

        if html and not looks_like_block(html):
            out_path.write_text(html, encoding="utf-8")
            print(f"[probe] OK saved -> {out_path}", file=sys.stderr)
            return 0

        if attempt < args.retries:
            print(f"[probe] looks blocked / empty. sleeping {backoff:.1f}s ...", file=sys.stderr)
            time.sleep(backoff)

    # 마지막으로 받은 html이라도 저장(차단 페이지 분석용)
    if html:
        blocked_path = out_path.with_suffix(".blocked.html")
        blocked_path.write_text(html, encoding="utf-8")
        print(f"[probe] BLOCKED — saved last response to {blocked_path}", file=sys.stderr)
    print("[probe] FAILED: 모든 시도가 차단/빈응답으로 보임", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
