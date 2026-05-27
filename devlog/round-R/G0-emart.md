# G0 정찰 — 이마트 (emart.ssg.com)

캡쳐: `devlog/round-R/captures/G0-emart-itempage.png`

## 핵심 발견 (기존 크롤러 가정과의 차이)
- **`__NEXT_DATA__` 없음**. 기존 크롤러(`packages/crawler-admin/backend/crawlers/marts/emart/crawler.py`)가 `__NEXT_DATA__` 기반으로 짜여 있는데 이게 **잘못된 전제**. SSR이 아니라 CSR 기반에 GTM dataLayer가 핵심.
- 검색 페이지(`/search.ssg`)는 봇 차단(`net::ERR_HTTP_RESPONSE_CODE_FAILURE`). 카테고리 페이지(`/disp/category.ssg?dispCtgId=...`)는 정상 접근.
- 카테고리 페이지에서 상품 컨테이너는 CSR로 비동기 로딩됨. 3초 대기 후 `a[href*="itemView.ssg"]` 206건 확보.

## URL 패턴 / 안정 식별자
- 상품 URL: `https://emart.ssg.com/item/itemView.ssg?itemId=<13자리>&siteNo=<4자리>&salestrNo=<4자리>`
- **`itemId`** = 이마트 안정 상품 코드 → `mart_native_code` 1순위.
  - GTM `view_item` 이벤트에도 `id`로 동일하게 들어감 (`window.dataLayer`에서 검증).
- `siteNo=7009` = 이마트몰 사이트 ID.
- `salestrNo` = 판매점(salestore) 번호. **외부업자 판별 키 후보** — 자체상품과 외부셀러를 구분할 수 있을 가능성. G1에서 다양한 상품의 salestrNo 분포 수집해 자체상품 화이트리스트 확보 필요.
- 카테고리 URL: `/disp/category.ssg?dispCtgId=<10자리>` — `dispCtgId`가 안정 카테고리 코드.

## 자체상품/배송 마커 (외부업자 처리)
- `<span class="cdtl_ico_item">새벽배송</span>` — 자체상품에 붙는 배송 라벨.
- 사용자 지적대로 **"새벽배송" / "주간배송" / "트레이더스"** 등 여러 자체상품 하위 라벨이 같은 `cdtl_ico_item` 클래스로 등장 — 화이트리스트로 잘라내면 누락 위험.
- **결정**: 옵션 B(플래그). `cdtl_ico_item` 클래스에 들어 있는 라벨 텍스트와 `salestrNo`를 모두 저장하고 `external_seller=true/false`만 매김.

## 단위 환산가 — 사이트가 이미 노출
- 상품 페이지 텍스트: `"10g 당 : 314원, 총 용량 : 270g"` / `"100g 당 2,447원"` 등.
- 추출 가능. G1에서 정규식으로 파싱:
  - `(?P<basis>\d+\s*(?:g|ml|개))\s*당\s*:?\s*(?P<price>[\d,]+)\s*원`
  - `총\s*용량\s*:?\s*(?P<total>[\d.,]+)\s*(?P<unit>g|ml|개|봉|팩)`
- **저장 스키마 결정**: `unit_price` (정수, 원) + `unit_price_basis_qty` (예: 10, 100) + `unit_price_basis_unit` ("g"/"ml"/"개"), `total_qty` + `total_unit`.

## 카테고리 트리 수집 전략
- 메인 페이지 nav `a[href*="dispCtgId"]` 14개가 1차 분류(과일·채소·...·건강식품).
- 카테고리 페이지에서 하위 카테고리 nav도 같은 패턴 — 재귀 크롤로 트리 추출 가능.
- 각 상품 상세에서 카테고리 breadcrumb은 별도 셀렉터 필요(이번 정찰에서 발견 못함 — G1에서 추가 조사).

## G1에서 해야 할 액션 (이마트 슬롯)
1. `__NEXT_DATA__` 기반 로직 **전부 삭제**, 카테고리 페이지 CSR 대기 + `a[href*="itemView.ssg"]` 수집 방식으로 재작성.
2. 카테고리 트리 export (별도 endpoint/스크립트).
3. 상품 페이지 텍스트에서 단위환산가 파싱.
4. `cdtl_ico_item` 텍스트 라벨 + `salestrNo` 둘 다 저장.
5. 페이지네이션 — 카테고리 페이지 끝까지 (현재 206건은 카테고리 1페이지 분).
