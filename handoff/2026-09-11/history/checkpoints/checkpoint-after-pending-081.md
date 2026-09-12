# WalletSaver 분류 체크포인트 — pending 081 완료 후

## 현재 기준

- 기준 브랜치: `cleanup/remove-legacy-ai-admin-coupling`
- 기준 데이터/분류 pass: `pass41`
- 기준 pending 관측 수: 3,916
- 기존 explicit review decision 수: 431
- 현재 작업은 GitHub read/write 기반 `proposal_only` 검토이며 DB/운영 반영이 아니다.
- pass41의 실제 DB 기준선(5,280 적재 / 3,916 pending)은 변경하지 않았다.

## 최신 유효 진행 회계

- pending 077 완료: 998 / 3,916
- pending 078 proposal: 998 -> 1,010
- pending 079 proposal: 1,010 -> 1,022
- pending 080 proposal: 1,022 -> 1,034
- pending 081 proposal: 1,034 -> 1,046

## 이번 구간에서 완료한 proposal_only

### pending 078

- 파일: `handoff/2026-09-11/proposals/homeplus-soy-protein-drinks-078.json`
- 12관측 / 6상품
- 베지밀 검은콩 2상품 -> 기존 `food.plant.soy.soymilk`
- 아몬드브리즈 무당 -> 기존 `food.plant.drinks.almond`
- 하이뮨 프로틴 액티브 3상품 -> 신규 후보 `food.drinks.other.protein`
- broad `일반두유` shelf보다 실제 제품형태를 우선했다.

### pending 079

- 파일: `handoff/2026-09-11/proposals/homeplus-cooking-sauces-079.json`
- 12관측 / 6상품
- 삼양 불닭소스, J-LEK 스리라차 -> 기존 `food.seasonings.sauces.chili`
- 피오디 레몬쥬스 -> 신규 후보 `food.seasonings.acids.lemon_juice`
- 샘표 오징어 낙지 볶음 양념 -> 신규 후보 `food.seasonings.sauces.stir_fry`
- 샘표 떡꼬치 양념 -> 신규 후보 `food.seasonings.sauces.tteok_skewer`
- 모니니 아세토발사믹글레이즈 -> 신규 후보 `food.seasonings.sauces.balsamic_glaze`
- 소스 진열이라는 이유만으로 서로 다른 사용형태를 하나의 catch-all leaf에 넣지 않았다.

### pending 080

- 파일: `handoff/2026-09-11/proposals/homeplus-cups-lids-080.json`
- 12관측 / 6상품
- 다회용 투명컵 3상품 -> 신규 후보 `household.kitchen.drinkware.plastic_cup`
- 테이크아웃 컵뚜껑 3상품 -> 신규 후보 `household.kitchen.drinkware.cup_lid`
- pass41 household taxonomy에는 cleaning/hygiene 중심 leaf만 있고 주방용 drinkware/cup leaf가 없어 신규 후보로 보존했다.
- 컵뚜껑을 컵 본체로 합치지 않았다.

### pending 081

- 파일: `handoff/2026-09-11/proposals/homeplus-frozen-vegetables-081.json`
- 12관측 / 6상품
- 냉동대파, 냉동양파, 찌개용/카레짜장용/볶음밥용 채소믹스 전부 -> 기존 `food.produce.processed_vegetables.frozen`
- `찌개용`, `카레짜장용`, `볶음밥용`은 사용 목적이며 완성식 제품형태가 아니다.
- fresh vegetable leaf보다 냉동 가공형태를 우선했다.

## 누적 진행률

- 이전 체크포인트 누적: 998 / 3,916
- 이번 구간 신규 classification 검토: 48
- 현재 누적 검토: 1,046 / 3,916 (약 26.7%)
- 남은 미검토: 2,870 / 3,916 (약 73.3%)

이 수치는 `proposal_only` classification 검토 진행량 회계다. 이미 classification이 resolved이고 수량/행사/단위 등 다른 사유만 남은 행은 새 classification 검토로 중복 계산하지 않는다.

## 보존한 원칙

- actual product form을 broad retail shelf보다 우선한다.
- 기존 leaf가 정확히 맞을 때만 재사용한다.
- 영양음료를 두유/우유로, 레몬즙을 음용주스로, 컵뚜껑을 컵 본체로 강제하지 않는다.
- 냉동 채소믹스를 완성 찌개·카레·볶음밥으로 분류하지 않는다.
- 수량, 행사조건, 원본 관측, 상품 병합은 classification-only 검토에서 수정하지 않는다.
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

- 다음 대상: `handoff/2026-09-11/pending/082/001.json`
- PENDING_INDEX상 pending 082는 홈플러스 `건강식품 > 소화제/자양강장/숙취해소 > 상쾌환`, 11관측 / 6고유제목이다.
- 이후 pending 083은 `냉장/냉동/밀키트 > 냉동밥/죽/스프 > 냉동밥/덮밥류 > 냉동밥/덥밥류`, 11관측 / 6고유제목이다.
- pending 084는 `라면/즉석식품/통조림 > 당면/건면/스파게티 > 쌀국수/월남쌈`, 11관측 / 6고유제목이다.
- 재개 시 실제 제목/판매페이지 키/raw record ID를 먼저 확인하고 기존 proposal 및 431개 explicit review decision 충돌을 다시 검사한다.
- 분류가 이미 resolved이고 행사/수량/단위 등 다른 pending 사유만 남은 관측은 classification-only 해소로 세지 않는다.
- 새 taxonomy leaf가 필요하면 기존 leaf에 억지로 넣지 말고 신규 후보 또는 taxonomy-policy hold로 보존한다.
