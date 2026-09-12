# WalletSaver 분류 체크포인트 — pending 089 완료 후

## 현재 기준

- 기준 브랜치: `cleanup/remove-legacy-ai-admin-coupling`
- 기준 데이터/분류 pass: `pass41`
- 기준 pending 관측 수: 3,916
- 기존 explicit review decision 수: 431
- 현재 작업은 GitHub read/write 기반 `proposal_only` 검토이며 DB/운영 반영이 아니다.
- pass41 실제 기준선(5,280 적재 / 3,916 pending)은 변경하지 않았다.

## 최신 유효 진행 회계

- pending 085 완료: 1,089 / 3,916
- pending 086 proposal: 1,089 -> 1,099
- pending 087 proposal: 1,099 -> 1,109
- pending 088 proposal: 1,109 -> 1,119
- pending 089 proposal: 1,119 -> 1,129

## 이번 구간에서 완료한 proposal_only

### pending 086

- 파일: `handoff/2026-09-11/proposals/homeplus-corn-cereal-086.json`
- 10관측 / 5상품
- 콘푸로스트, 콘푸라이트, 콘플레이크 전부 -> 기존 `food.snacks.cereal.flakes`
- 컵 포장, 저당 여부는 제품형태가 아니라 포장/속성으로 유지했다.

### pending 087

- 파일: `handoff/2026-09-11/proposals/homeplus-jelly-ice-pop-087.json`
- 10관측 / 5상품
- 자임 콜라겐 젤리 2상품 -> 기존 `food.snacks.sweets.jelly`
- 돌핀 폴라레티 3상품 -> 신규 후보 `food.frozen.desserts.ice_pop`
- 기존 Homeplus 테스트가 `돌핀 폴라레티 후르트 400ML`을 jelly로 분류하지 않도록 명시하므로 broad 젤리/푸딩 shelf보다 실제 아이스팝 제품형태를 우선했다.

### pending 088

- 파일: `handoff/2026-09-11/proposals/homeplus-fried-meals-088.json`
- 10관측 / 5상품
- 고메 유린기 -> 기존 `food.meals.prepared.chicken`
- 김말이 3상품 -> 신규 후보 `food.meals.prepared.gimmari`
- 고메 탕수육 -> 신규 후보 `food.meals.prepared.tangsuyuk`
- mixed 탕수육/김말이 shelf를 catch-all로 사용하지 않았다.

### pending 089

- 파일: `handoff/2026-09-11/proposals/homeplus-other-noodles-089.json`
- 10관측 / 5상품
- 베이컨 까르보나라 파스타 -> 기존 `food.meals.noodles.pasta`
- 풀무원 또띠아 2상품 -> pending 084에서 사용한 동일 신규 후보 `food.bakery.bread.tortilla`
- 부산밀면 2상품 -> 신규 후보 `food.meals.noodles.milmyeon`
- 기타면 shelf라는 이유로 또띠아를 면류에 넣거나 밀면을 냉면/소면으로 강제하지 않았다.

## 누적 진행률

- 이전 체크포인트 누적: 1,089 / 3,916
- 이번 구간 신규 classification 검토: 40
- 현재 누적 검토: 1,129 / 3,916 (약 28.8%)
- 남은 미검토: 2,787 / 3,916 (약 71.2%)

이 수치는 `proposal_only` classification 검토 진행량 회계다. 이미 classification이 resolved이고 수량/행사/단위 등 다른 사유만 남은 행은 새 classification 검토로 중복 계산하지 않는다.

## 충돌 검사

- pending 086~089의 source_record_key를 기존 431개 explicit review decision과 대조했으며 일치 항목은 0건이다.
- 폴라레티는 기존 taxonomy 테스트의 unresolved 의도를 보존했다.
- pending 089의 tortilla는 pending 084와 같은 신규 후보 id를 재사용했다.

## 보존한 원칙

- 실제 제품형태를 broad retail shelf보다 우선한다.
- 기존 leaf가 정확히 맞을 때만 재사용한다.
- 아이스팝을 젤리로, 김말이를 만두/일반튀김으로, 또띠아를 면류로 강제하지 않는다.
- 맛/저당/컵포장/속재료는 taxonomy product-form leaf를 불필요하게 분기하지 않는다.
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

- 다음 대상: `handoff/2026-09-11/pending/090/001.json`
- PENDING_INDEX상 pending 090은 홈플러스 `냉장/냉동/밀키트 > 만두 > 교자만두/군만두 > 김치교자만두`, 10관측 / 5고유제목이다.
- 이후 pending 091은 `냉장/냉동/밀키트 > 밀키트 > 글로벌밀키트`, 10/5다.
- pending 092는 `두부/김치/반찬 > 두부/나물 > 두부키트류`, 10/5다.
- pending 093은 `두부/김치/반찬 > 어묵/맛살/단무지 > 맛살 > 반찬용맛살`, 10/5다.
- 재개 시 실제 제목/판매페이지 키/raw record ID를 먼저 확인하고 기존 proposal 및 431개 explicit review decision 충돌을 다시 검사한다.
- 분류가 이미 resolved이고 행사/수량/단위 등 다른 pending 사유만 남은 관측은 classification-only 해소로 세지 않는다.
- 새 taxonomy leaf가 필요하면 기존 leaf에 억지로 넣지 말고 신규 후보 또는 taxonomy-policy hold로 보존한다.
