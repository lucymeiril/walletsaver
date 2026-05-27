# Round R Fix Legacy Fetch Report

## legacy fetch 핵심 발견
- G1 이전 working layer는 requests만 쓰지 않고 Playwright browser context, Chrome UA/headers, `ko-KR` locale, 1920x1080 viewport, headed/headful escalation, 동적 스크롤, XHR 인터셉트를 조합했다.
- 롯데마트는 `/promotions`에서 `.product-card-container` 대기 후 스크롤하며 `webproductpagews/v6/products` XHR을 수집했고, 홈플러스는 `.unitItemInner` 안정화 스크롤이 필요했다.

## 통합 결정
- 공용 모듈 `packages/crawler-admin/backend/crawlers/_fetch/browser_session.py` 신설.
- 기본 headed Chromium, storage-state 쿠키 캐시, Korean locale/timezone, legacy headers, retry/backoff, stable-scroll helper를 제공.
- 4사 crawler.py는 fetch 부분만 공용 browser session으로 교체하고 기존 G1 비즈니스 로직을 보존.
- `round_r_g1_seed.py`는 `--live --marts <mart> --limit <n>`를 지원하고 fixture fallback은 `--fixture-fallback`로 옵셔널화.

## 통합 파일 목록
- `packages/crawler-admin/backend/crawlers/_fetch/__init__.py`
- `packages/crawler-admin/backend/crawlers/_fetch/browser_session.py`
- `packages/crawler-admin/backend/crawlers/marts/emart/crawler.py`
- `packages/crawler-admin/backend/crawlers/marts/homeplus/crawler.py`
- `packages/crawler-admin/backend/crawlers/marts/lottemart/crawler.py`
- `packages/crawler-admin/backend/crawlers/marts/costco/crawler.py`
- `packages/crawler-admin/backend/scripts/round_r_g1_seed.py`
- `packages/crawler-admin/backend/tests/test_g1_browser_session.py`

## 라이브 smoke 결과
- `py -3 packages\\crawler-admin\\backend\\scripts\\round_r_g1_seed.py --live --marts emart --limit 5` → `live-blocked`, parsed=0. 서버 환경에서 parseable product 없음.
- `--marts homeplus --limit 5` → `live-blocked`, parsed=0. `bot` marker 감지.
- `--marts lottemart --limit 5` → `live-blocked`, parsed=0. `awswaf` marker 및 retry 로그 확인.
- `--marts costco --limit 5` → `live-blocked`, parsed=0. `bot` marker 감지.
- 현재 실행 환경은 사이트 anti-bot에 계속 차단된다. 사용자 PC에서 headed browser로 같은 명령을 재실행해야 한다. 차단 시 fixture fallback은 자동이 아니며 `--fixture-fallback`를 명시해야 한다.

## 남은 한계
- 공용 fetch는 합법적인 일반 브라우저 세션/쿠키 재사용만 수행하며 CAPTCHA 풀이, 계정 우회, WAF bypass는 하지 않는다.
- 일부 사이트는 사용자 PC의 기존 브라우저 신뢰도/네트워크 평판에 따라 결과가 달라질 수 있다.
