# Checkpoint after strict review of pending 036

상태: `proposal_only`. DB import/rebuild, taxonomy code edit, pytest, verify scripts는 실행하지 않았다. pass41 baseline `5,280 loaded / 3,916 pending`은 그대로다.

## pending 036 — emart 베이커리/잼

- files read: `pending/036/001.json`, `pending/036/002.json`
- observations opened: **27**
- already classification-complete exclusions: **4**
- new classification reviews: **23 observations / 23 listings**
- existing-leaf proposals: **2**
  - 샌드위치용 샐러드 계란 -> `food.meals.prepared.salad`
  - 오뚜기 딸기버터잼 -> `food.bakery.spreads.fruit`
- held: **21**
- proposal: `proposals/emart-bakery-jam-036.json`

### 주요 hold
- promotion/deal surfaces 6건: `8월 베이커리 최대 50% 특가`, `식빵/마들렌 최대 15% 단독 특가`, `식사빵 & 간식빵 최대 50% 특가전`, `베이커리/디저트/간편식 ~20% 특가`, `달콤한 디저트 할인전 ~50%`, `식사빵 최대 30% 특가전`. 단일 상품이 아니므로 leaf 배정 금지.
- 이전 bakery 정책 재사용: 단팥/충전형 빵 -> `food.bakery.bread.sweet_bun` 후보, 호떡 -> `food.bakery.bread.hotteok` 후보.
- 신규 형태 후보: 만주, 도넛, 치아바타, 쿠키슈/choux.
- mixed/product-form conflict: 츄러스+미니크라상 혼합팩, savory filled ciabatta, 사라다크라상 등은 기존 pastry/sandwich leaf로 강제하지 않음.

### already-classified 4
- 베스트픽 페스츄리 -> `food.bakery.bread.pastry`
- 편안한유산균쌀식빵 -> `food.bakery.bread.sliced`
- 스윗초코롤케익 -> `food.bakery.dessert.cake`
- 크랜베리 치킨 샌드위치 -> `food.meals.prepared.sandwich`

## collision screen

23 source_record_key를 세 묶음으로 repository search. `review-decisions-input.json` hit 0; pending/raw/unresolved 자료만 검색됨. proposal-stage screen이며 explicit decision 파일은 수정하지 않았다.

## strict reverse 누계

pending `036~043`:
- observations opened: **202**
- already-classified exclusions: **15**
- new classification reviews: **187**
- distinct newly reviewed listings: **175**
- existing leaf: **53**
- hold: **122**

남은 strict-audit 상한: `pending 001~035` **1,681 observations**, pass41 pending 3,916 대비 약 **42.9%**. 실제 새 판단량은 과거 proposal 중복 때문에 이보다 작을 수 있다.

## next resume point

**pending 035**. 먼저 디렉터리의 모든 파일 조각을 확인하고, 전체 observation에서 already-classified를 제외한 뒤 classification-pending만 처리한다. 완료 즉시 `CURRENT_STATUS.md`를 034로 넘길 것.
