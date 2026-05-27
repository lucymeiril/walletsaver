# WalletSavior Round T — t-homeplus-legacy

## 1. 옛 git 커밋 발굴
- 후보 확인: `483ae4b`, `c1f40de`에서 동일한 19,233B Homeplus requests-first 레거시 베이스를 확인했다.
- `c0b720f`, `9921add`, `54cc7ec`는 해당 경로 파일이 없거나 후보로 쓸 수 없었다.
- 채택: 가장 큰 requests-only 베이스(`483ae4b`/`c1f40de`)의 구조를 현재 R 필드와 병합했다.

## 2. 라이브 sandbox probe
- `py -3` 실측 완료: `https://mfront.homeplus.co.kr/category/100100100?delivery=HYPER_DRCT` → `200`, `9,973 bytes`.
- HTML 셸 확인: `__NEXT_DATA__`, `window.__INITIAL_STATE__`, `dehydratedState`, `.unitItemInner`, `itemNo` 모두 없음.
- Vite JS에서 API 확인 후 실측:
  - `/category/item.json?categoryId=1&categoryDepth=0&page=1&perPage=20&delivery=HYPER_DRCT` → `200 SUCCESS`, `data.dataList`, `totalCount=38`.
  - `/totalsearch/total/search/item.json?keyword=할인&page=1&perPage=20` → `200 SUCCESS`.
  - `/express/category/item.json`은 200이지만 categoryId=1 기준 0건.
- 기록: `devlog/round-T/homeplus-probe.json`.

## 3. 코드 교체
- `packages/crawler-admin/backend/crawlers/marts/homeplus/crawler.py`를 requests-only mfront JSON API 방식으로 교체했다.
- Playwright 실행/의존 추가 없음. 테스트 호환 hook 이름만 남겼고 구현은 requests-only다.
- `delivery=HYPER_DRCT`는 HYPER category API/URL에 강제, `/express` 경로에는 delivery 필터를 넣지 않는다.

## 4. R 기능 병합
- `mart/source=homeplus`, `mart_native_code`, `canon_hash`, `promo_label` (`\d+\+\d+`) 반영.
- 라이브 저장 URL은 `/p/{slug}/{itemNo}` 형태의 영구 URL로 저장한다.
- `promoNo`/`gnbNo` 임시 URL은 legacy HTML fallback에서 저장하지 않는다.

## 5. DB 저장 + SELECT 검증
- 라이브 crawl: `MAX_REQUESTS=1`, `MAX_ITEMS=20` → `CrawlStatus.SUCCESS`, 20건 저장.
- SELECT 캡처: `devlog/round-T/homeplus-live-db-select.json`.
- 확인 SQL: `SELECT mart, mart_native_code, name, price, promo_label, canonical_url AS url FROM products WHERE mart='homeplus' LIMIT 10`.

## 6. 테스트
- 통과: `py -3 -m pytest tests\test_mart_crawlers.py::TestHomeplusParse tests\test_homeplus_crawler_g1.py -q` → 20 passed.
- `test_mart_crawlers.py` 전체는 Homeplus 구간까지 통과 후 기존 `TestCrawlWithMock::test_emart_crawl_success`에서 장시간 대기하여 중단했다. 다른 마트 코드는 수정하지 않았다.
