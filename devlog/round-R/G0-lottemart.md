# G0 정찰 — 롯데마트 (lottemartzetta.com)

## 결정적 발견 — UUID 저장 버그 원인 확정
- 사용자가 본 죽은 URL `/products/9f4a776d-108c-47c8-aa28-416123cdb058`의 **범인은 기존 크롤러**:
  `packages/crawler-admin/backend/crawlers/marts/lottemart/crawler.py` 1108–1111줄,
  `data-synthetics="product-id:<uuid>"` 페이지 트래킹 ID를 잡아서 `/products/<uuid>` URL로 만들고 있었음.
- **실 사이트가 주는 안정 URL은 처음부터 `/products/OS<13자리>/details`**. 메인 홈에서 보이는 모든 상품 카드의 `href`도 OS-prefix.
- `OS<13자리>`는 **EAN-13 바코드 형식** (예: `OS8801045440040` = 오뚜기 참기름 450ML). **이게 가장 강력한 영구 식별자** — 동일 바코드 = 절대 동일 상품. 다른 마트와 매칭에도 활용 가능.

## URL 패턴 / 안정 식별자
- 상품: `https://lottemartzetta.com/products/OS<EAN-13>/details`
- `mart_native_code` = OS 뒤 13자리 (= EAN-13 바코드)
- **`canon_hash`로 이중 매칭** 의미가 가장 큰 마트. 다른 마트 상품도 바코드가 같으면 즉시 동일 상품 매칭 가능.

## 단위 환산가 — 사이트 노출
- "450ml 10ml당 278원", "(100g당 2,990원)", "2개씩 담으면, 9,980원 (개당 4,990원)" 등.
- 이마트/홈플과 호환되는 정규식으로 추출 가능.

## 카테고리 경로
- 상품 페이지 어딘가에 풀 경로 노출(예: "홈 → 양념ㆍ오일ㆍ분말류 → 식용유ㆍ참기름ㆍ오일 → 참기름") — DOM 셀렉터는 G1에서 정확히 잡기.
- 메인 nav에 최상위 카테고리 25+개 노출. `__INITIAL_STATE__.data` 안에 카테고리 트리 들어있을 가능성 높음.

## `__INITIAL_STATE__`
- 존재 확인. 최상위 키: `data, session, control, router, retailerSettings, cookieConsent`.
- 기존 크롤러의 `__INITIAL_STATE__` 가정 자체는 맞음. 다만 그 안에서 UUID 키를 product_id로 쓰는 것이 잘못. **`detailUrl`/`code`/`ean` 필드를 우선 추출**해야 함.

## G1에서 해야 할 액션 (롯데마트 슬롯)
1. `data-synthetics="product-id:..."`를 URL/식별자로 쓰는 코드 **삭제**.
2. 카드의 `<a href="/products/OS.../details">`에서 OS코드 추출.
3. `__INITIAL_STATE__.data`에서 EAN/바코드/code 필드 추출 (정확한 키는 G1 작업 시 직접 들어가서 확인).
4. 다른 마트와 공통 — `mart_native_code = EAN-13`이면 `canon_hash` fallback이 거의 필요 없을 정도.
