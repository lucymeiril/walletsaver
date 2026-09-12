# WalletSaver 분류 체크포인트 — pending 101 완료 후

## 현재 기준

- 기준 브랜치: `cleanup/remove-legacy-ai-admin-coupling`
- 기준 데이터/분류 pass: `pass41`
- 기준 pending 관측 수: 3,916
- 기존 explicit review decision 수: 431
- 현재 작업은 GitHub read/write 기반 `proposal_only` 검토이며 DB/운영 반영이 아니다.
- pass41 실제 기준선(5,280 적재 / 3,916 pending)은 변경하지 않았다.

## 최신 유효 진행 회계

- pending 097 완료: 1,209 / 3,916
- pending 098 proposal: 1,209 -> 1,219
- pending 099 proposal: 1,219 -> 1,229
- pending 100 proposal: 1,229 -> 1,239
- pending 101 proposal: 1,239 -> 1,249

## 이번 구간에서 완료한 proposal_only

### pending 098

- 파일: `handoff/2026-09-11/proposals/homeplus-flavored-milk-yogurt-098.json`
- 10관측 / 5상품
- 서울우유 커피포리 -> 기존 `food.dairy.milk.coffee`
- 부산우유 초코가득 -> 기존 `food.dairy.milk.chocolate`
- 부산우유 딸기가득 -> 기존 `food.dairy.milk.strawberry`
- 부산우유 바나나가득 -> 기존 `food.dairy.milk.banana`
- 매일 바이오그릭드링크바나나 -> 기존 `food.dairy.yogurt.drink`
- broad flavored-milk shelf보다 실제 product form을 우선했다. 그릭드링크는 우유로 강제하지 않았고, `드링크` 형태를 spoonable Greek yogurt보다 우선했다.

### pending 099

- 파일: `handoff/2026-09-11/proposals/homeplus-kitchen-gloves-099.json`
- 10관측 / 5상품
- simplus 고무장갑 대/중 및 1입/3입 -> 신규 후보 `household.kitchen.gloves.rubber`
- 뉴랩 니트릴 장갑 S/M 100매 -> 신규 후보 `household.kitchen.gloves.nitrile`
- 현재 taxonomy에 주방장갑 exact leaf가 없어 기존 청소용품 등에 강제하지 않았다.
- 재질/사용형태는 product-form 차이로 분리했고 크기, 색상, 팩 수량은 속성으로 유지했다.

### pending 100

- 파일: `handoff/2026-09-11/proposals/homeplus-dried-vegetables-100.json`
- 10관측 / 5상품
- 무말랭이, 건고사리, 건곤드레, 건시래기, 건취나물 -> 모두 기존 `food.produce.processed_vegetables.dried`
- 전부 명시적인 건채소/건나물이며 건버섯 상품은 없다.
- 채소 종류, 산지, 중량은 속성으로 유지했다.

### pending 101

- 파일: `handoff/2026-09-11/proposals/homeplus-samgyetang-herbs-101.json`
- 10관측 / 5상품
- 온가족 삼계재료 모음, 간편 삼계재료 티백, 상황 삼계재료, 찹쌀 누룽지 품은 삼계재료 -> 신규 후보 `food.ingredients.herbal.samgyetang_mix`
- 국산 황기 -> 신규 후보 `food.ingredients.herbal.astragalus`
- 현재 taxonomy에 황기/삼계재료 exact leaf가 없으며 이를 건채소나 일반 향신료로 강제하지 않았다.
- 티백, 상황 배합, 찹쌀/누룽지 포함은 포장·배합 속성으로 보고 공통 삼계재료 product type을 유지했다.

## 누적 진행률

- 이전 체크포인트 누적: 1,209 / 3,916
- 이번 구간 신규 classification 검토: 40
- 현재 누적 검토: 1,249 / 3,916 (약 31.9%)
- 남은 미검토: 2,667 / 3,916 (약 68.1%)

이 수치는 `proposal_only` classification 검토 진행량 회계다. 이미 classification이 resolved이고 수량/행사/단위 등 다른 사유만 남은 행은 새 classification 검토로 중복 계산하지 않는다.

## 충돌 검사

- pending 098~101의 20개 source_record_key를 기존 431개 explicit review decision과 개별 대조했으며 일치 항목은 0건이다.
- current taxonomy에서 flavored milk 4개 leaf, `food.dairy.yogurt.drink`, `food.produce.processed_vegetables.dried` 존재를 재확인했다.
- current taxonomy에는 kitchen glove, 황기, 삼계재료 exact leaf가 없음을 확인했다.
- repository 검색에서 `household.kitchen.gloves` 및 `samgyetang_mix`/`astragalus` 기존 candidate precedent는 찾지 못했다.
- 기존 431개 explicit review decision은 수정하거나 덮어쓰지 않았다.

## 보존한 원칙

- 실제 제품형태를 broad retail shelf보다 우선한다.
- 기존 leaf가 정확히 맞는 경우에만 재사용한다.
- 맛, 크기, 색상, 산지, 중량, 팩 수량, 포장형태는 불필요한 taxonomy 분기로 만들지 않는다.
- 수량, 행사조건, 가격, 원본 관측, 상품 병합은 classification-only 검토에서 수정하지 않는다.
- 새 taxonomy가 필요한 상품은 비슷해 보이는 기존 leaf에 억지로 넣지 않고 후보로 보존한다.

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

- 다음 대상: `handoff/2026-09-11/pending/102/001.json`
- pending 102: 홈플러스 `커피/차 > 녹차/보리차/기타차 > 홍차/아이스티 > 홍차`, 10관측 / 5고유제목
- pending 103: `커피/차 > 전통차/액상차/꿀 > 액상차/농축액 > 농축액`, 10/5
- pending 104: `커피/차 > 전통차/액상차/꿀 > 유자차`, 10/5
- pending 105: `견과 > 곡물가공/건강분말 > 곡물가공`, 9/5
- 재개 시 실제 제목/판매페이지 키/raw record ID를 먼저 확인하고 기존 proposal 및 431개 explicit review decision 충돌을 다시 검사한다.
- 분류가 이미 resolved이고 행사/수량/단위 등 다른 pending 사유만 남은 관측은 classification-only 해소로 세지 않는다.
- 새 taxonomy leaf가 필요하면 기존 leaf에 억지로 넣지 말고 신규 후보 또는 taxonomy-policy hold로 보존한다.
