# s-homeplus-deep report

## URL 변경 사양
- 기본 마트 카테고리(HYPER): `https://mfront.homeplus.co.kr/list?categoryDepth={depth}&categoryId={id}&delivery=HYPER_DRCT`
- 홈플러스 익스프레스(EXP): `https://mfront.homeplus.co.kr/express/list?categoryDepth={depth}&categoryId={id}`
- 동일 URL 빌더를 Playwright source requests, category tree fixture, requests category fallback에서 사용한다.

## 동적 스크롤
- 적용 위치: `HomeplusCrawler._render_homeplus_category_page()`
- 호출: `browser_session.render_html(..., scroll=True, scroll_selector=".unitItemInner")`
- 근거 셀렉터: fixture와 파서에서 사용하는 상품 카드 `.unitItemInner`

## promo_label 파싱
- 근거 마크업: `homeplus_probe_search.html`의 `<ul class="promotionFlag"><span class="flag">...` 및 `<div class="moreBtnWrap"><button class="list-btn" title="...">`
- 셀렉터: `.promotionFlag .flag`, `.moreBtnWrap .list-btn`, `.recomComment`
- 정규식: `(?:[12]\s*\+\s*1)|(?:\d+\s*개\s*담(?:고|으면)\s*[^|]{1,20})`
- 결과 필드: `DiscountItem.promo_label`, 임시 호환용 `attributes["promo_label"]`

## 통과 테스트
- `py -m pytest tests\test_mart_crawlers.py tests\test_homeplus_crawler_g1.py tests\test_homeplus_crawler.py -q`
- 결과: 95 passed, 3 skipped
