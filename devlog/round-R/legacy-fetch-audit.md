# Round R Legacy Fetch Audit

## 조사 기준
- `git log --all --oneline -- packages/crawler-admin/backend/crawlers/marts/` 기준 현재 G1 재작성 직전 참고 커밋은 `17c8329 feat(rd6-pivot): external classification workflow + MCP browser validation`로 식별했다.
- `git grep`/현재 tree grep으로 Playwright, browser context, headers, scroll, User-Agent 패턴을 확인했다.

## 옛 코드 핵심 fetch 방식
- 마트 계열은 requests 단독이 아니라 Playwright 렌더링 fallback을 사용했다.
- 롯데마트는 `async_playwright`로 Chromium을 띄우고 `--disable-blink-features=AutomationControlled`, `--window-size=1920,1080`, `locale=ko-KR`, `timezone_id=Asia/Seoul`, `viewport=1920x1080`, Chrome UA, `Accept-Language`, `sec-ch-ua`, `Referer`를 지정했다.
- 롯데마트 프로모션은 `.product-card-container` 대기 후 500px 단위 점진 스크롤과 XHR `webproductpagews/v6/products` 인터셉트로 추가 상품을 모았다.
- 홈플러스는 Playwright로 `.unitItemInner`를 기다린 뒤 lazy-load 스크롤을 수행했다.
- 기존 `engine.playwright_helper`에는 persistent context/profile 옵션이 있었지만 G1 시드의 live fetch는 requests 기반으로 우회되어 브라우저 쿠키/세션을 활용하지 못했다.
- 다른 working crawler도 동일 계열 패턴을 쓴다: 핫딜은 `AntiDetect.get_random_headers()` + `_retry_request()` + cloudscraper/session backoff를 쓰고, Arca는 필요 시 Playwright `page.goto(..., wait_until="networkidle")`로 전환한다. Opinet은 `requests.Session`, 랜덤 헤더, Referer, Playwright fallback을 함께 둔다. 동네/장소 계열 Naver Place도 PlaywrightHelper와 `page.goto(..., domcontentloaded)` 패턴을 사용한다.

## G1 새 코드 누락/회귀
- G1 seed live path가 `requests.Session` + 정적 헤더만 사용해 SPA/anti-bot 사이트의 실제 브라우저 세션, 쿠키, viewport, locale, 동적 스크롤을 빠뜨렸다.
- 일부 crawler.py는 PlaywrightHelper를 사용했지만 기본 headless 및 제한된 스크롤/헤더로 legacy headed/session 패턴과 분리되어 있었다.
- Costco live path는 requests 중심이라 `/p/<digits>` 파서는 유지되어도 실제 storefront rendering/cookie 흐름을 타지 않았다.

## 통합 계획
- `crawlers/_fetch/browser_session.py`를 공용 fetch 레이어로 추가한다.
- 기본 headed Chromium, Chrome UA, 1920x1080 viewport, `ko-KR`, `Asia/Seoul`, legacy headers, `storage_state.json` 쿠키 캐시를 제공한다.
- `goto_with_retry()`로 202/403/429/503 및 challenge marker를 재시도하고 `scroll_until_stable()`로 SPA/lazy-load 리스트를 안정화한다.
- 4사 G1 crawler.py와 `round_r_g1_seed.py`의 live path는 이 fetch 레이어를 사용하고, 식별자/외부셀러/단위환산/URL 정규화 비즈니스 로직은 보존한다.
