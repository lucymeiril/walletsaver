# WalletSaver 분류 체크포인트 — pending 065 완료 후

## 현재 기준

- 기준 브랜치: `cleanup/remove-legacy-ai-admin-coupling`
- 기준 데이터/분류 pass: `pass41`
- 기준 pending 관측 수: 3,916
- 기존 explicit review decision 수: 431
- 현재 작업은 GitHub read/write 기반 `proposal_only` 검토이며 DB/운영 반영이 아니다.

## 최신 유효 진행 회계

직전 최신 체크포인트 `checkpoint-after-pending-061.md`에서 누적 proposal-only 검토량은 788 / 3,916이었다. 이번 세션에서 PENDING_INDEX 순서를 그대로 이어 pending 062~065를 검토했다.

- pending 061 완료: 788 / 3,916
- pending 062 proposal: 788 -> 803
- pending 063 proposal: 803 -> 818
- pending 064 proposal: 818 -> 832
- pending 065 proposal: 832 -> 846

## 이번 세션에서 이어서 완료한 proposal_only

### pending 062

- 파일: `handoff/2026-09-11/proposals/homeplus-baked-snacks-062.json`
- 15관측 / 8상품
- 크래커 6상품 / 11관측 -> 기존 `food.snacks.baked.cracker`
- `해태 샌드에이스 크림라떼 204G` 1상품 / 2관측 -> 기존 `food.snacks.baked.sandwich`
- `롯데 엄마손파이 254G` 1상품 / 2관측 -> 기존 `food.snacks.baked.pie`
- 원본 `버터비스켓` 진열보다 상품명에 직접 드러난 제품형태를 우선
- 신규 taxonomy 후보 없음

### pending 063

- 파일: `handoff/2026-09-11/proposals/homeplus-fruit-jam-063.json`
- 15관측 / 9상품
- 딸기·블루베리·라즈베리·사과 잼 전부 기존 `food.bakery.spreads.fruit`
- 과일 종류, 라이트슈가 여부, 규격 차이를 별도 taxonomy나 상품 병합으로 만들지 않음
- 같은 판매페이지의 반복 관측만 하나의 결정에 묶음
- 신규 taxonomy 후보 없음

### pending 064

- 파일: `handoff/2026-09-11/proposals/costco-bread-shelf-064.json`
- 14관측 / 14상품
- 포장 케이크/바움쿠헨 4상품 -> 기존 `food.snacks.baked.cake`
- 냉동 완제품 초콜릿케이크 1상품 -> 기존 `food.bakery.dessert.cake`
- 아몬드가루 1상품 -> 기존 `food.seasonings.baking.almond_flour`
- 단팥/소보루 계열 빵 3상품 -> 신규 후보 `food.bakery.bread.sweet_bun`
- 완제품 호떡 1상품 -> 신규 후보 `food.bakery.bread.hotteok`
- 초콜릿무스 1상품 -> 신규 후보 `food.bakery.dessert.mousse`
- 와플믹스 2상품 -> 신규 후보 `food.seasonings.baking.waffle_mix`
- 샌드위치 메이커 1상품 -> 신규 후보 `household.kitchen.appliances.sandwich_maker`
- Costco 원본 `빵` shelf에 비식품·제빵재료·냉장디저트가 섞여 있으므로 원본 경로를 그대로 복사하지 않음

### pending 065

- 파일: `handoff/2026-09-11/proposals/homeplus-braise-stirfry-065.json`
- 14관측 / 7상품
- 고기순대 1상품 / 2관측 -> 기존 `food.meat.processed.sundae`
- 닭볶음탕 1상품 / 2관측 -> 기존 `food.meals.prepared.soup_stew`
- 뼈찜 2상품 + 돼지등뼈 김치찜 1상품 / 6관측 -> 신규 후보 `food.meals.prepared.braised_meat`
- 낙지볶음·쭈꾸미볶음 2상품 / 4관측 -> 신규 후보 `food.meals.prepared.seafood_stir_fry`
- 1+1 등 기존 promotion evidence는 분류와 분리해 그대로 보존

## 누적 진행률

- 세션 시작 전 최신 유효 누적: 788 / 3,916
- 이번 세션 추가 검토: 58
- 현재 누적 검토: 846 / 3,916 (약 21.6%)
- 남은 미검토: 3,070 / 3,916 (약 78.4%)

이 수치는 `proposal_only` 검토 진행량 회계다. pass41 DB의 실제 5,280 적재 / 3,916 보류 기준선은 그대로 유지한다.

## 보존한 원칙

- 실제 상품명과 구체적인 판매 URL 제품형태를 광범위 원본 진열 경로보다 우선한다.
- 기존 leaf가 제품형태와 명확히 맞을 때만 기존 taxonomy에 제안한다.
- 대응 leaf가 없으면 비슷한 기존 leaf에 강제하지 않고 신규 taxonomy 후보로 보존한다.
- 동일 `source_record_key`의 반복 관측만 하나의 결정에 묶고, 맛·규격·판매페이지가 다른 상품은 병합하지 않는다.
- 수량, 행사조건, 원본 관측, 상품 병합은 classification-only 검토에서 수정하지 않는다.
- promotion 관련 unresolved 사유는 분류 제안만으로 해소된 것으로 세지 않는다.
- 기존 431개 explicit review decision을 덮어쓰지 않는다.

## 실제로 실행하지 않은 검증/반영

이번 작업에서는 다음 항목을 실행하지 않았으며 완료로 간주하지 않는다.

- staging SQLite import 또는 재구축
- proposal을 explicit review decision으로 승격/적용
- catalog rebuild
- taxonomy 코드 수정
- `verify_initial_stage.py`
- pytest / 전체 회귀 테스트
- 멱등 import 검사
- 새 pass DB 생성 및 데이터 무결성 검증

따라서 이번 결과는 분류 제안이며 운영/DB 반영 상태가 아니다.

## 다음 재개점

- 다음 대상: `handoff/2026-09-11/pending/066/001.json`
- PENDING_INDEX 순서를 그대로 이어 검토한다.
- 재개 시 먼저 실제 제목/판매페이지 키/raw record ID를 확인한다.
- 기존 proposal 중복과 431개 explicit review decision 충돌을 다시 검사한다.
- 분류가 이미 resolved이고 행사/수량 등 다른 pending 사유만 남은 관측은 classification-only 해소로 세지 않는다.
- 새 taxonomy leaf가 필요하면 기존 leaf에 억지로 넣지 말고 신규 후보로 보존한다.
