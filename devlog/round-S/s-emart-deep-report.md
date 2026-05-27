# s-emart-deep report

## shpp 필터 URL 예시
- `https://emart.ssg.com/disp/category.ssg?dispCtgId=6000095494&shpp=ssgem`
- `https://emart.ssg.com/disp/category.ssg?dispCtgId=6000095494&shpp=smon`
- `https://emart.ssg.com/disp/category.ssg?dispCtgId=6000095495&shpp=ssgem`

## 1+1 배지 fixture 매치
- fixture: `packages/crawler-admin/backend/tests/fixtures/emart_category_sample.html`
- 매치 결과: `1001234567890 -> promo_label=1+1, promo_type=buy_x_get_y`
- selector: `.mnemitem_tag_benefit`; regex: `\d+\+\d+`

## 동시성 적용
- Playwright: `_fetch_category_pages()`에서 category+shpp 시퀀스를 `asyncio.gather`로 실행.
- requests: `_fetch_category_pages_via_requests()`에서 같은 시퀀스를 `asyncio.gather` + `asyncio.to_thread`로 실행.
- Semaphore 값: `3`. 사용자 사양의 최대 3~4 범위 중 보수값이며, 각 시퀀스 내부 page는 순차 실행해 0건 페이지에서 즉시 break.

## 통과 테스트
실행 명령:
```powershell
py -m pytest packages\crawler-admin\backend\tests\test_mart_crawlers.py packages\crawler-admin\backend\tests\test_emart_crawler_g1.py packages\shared\tests\test_price_models.py -q
```
결과: `90 passed, 3 skipped`.
