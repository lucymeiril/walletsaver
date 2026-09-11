# WalletSaver 분류 체크포인트 — pending 085 완료 후

## 현재 기준

- 기준 브랜치: `cleanup/remove-legacy-ai-admin-coupling`
- 기준 데이터/분류 pass: `pass41`
- 기준 pending 관측 수: 3,916
- 기존 explicit review decision 수: 431
- 현재 작업은 GitHub read/write 기반 `proposal_only` 검토이며 DB/운영 반영이 아니다.
- pass41 실제 기준선(5,280 적재 / 3,916 pending)은 변경하지 않았다.

## 최신 유효 진행 회계

- pending 081 완료: 1,046 / 3,916
- pending 082 proposal: 1,046 -> 1,057
- pending 083 proposal: 1,057 -> 1,068
- pending 084 proposal: 1,068 -> 1,079
- pending 085 proposal: 1,079 -> 1,089

## 이번 구간에서 완료한 proposal_only

### pending 082

- 파일: `handoff/2026-09-11/proposals/homeplus-health-supplements-082.json`
- 11관측 / 6상품
- 상쾌환 및 상쾌환 스틱 5상품 -> 신규 후보 `food.health.supplements.hangover`
- 알부민 프리미엄 골드 1상품 -> 신규 후보 `food.health.supplements.albumin`
- pass41에는 건강보조식품/숙취해소 제품 leaf가 없으므로 일반 음료·식품 leaf에 강제하지 않았다.
- retail shelf만으로 효능이나 의학적 성격을 추론하지 않았다.

### pending 083

- 파일: `handoff/2026-09-11/proposals/homeplus-frozen-rice-083.json`
- 11관측 / 6상품
- 햇반 주먹밥 4상품 -> 기존 `food.meals.rice.rice_ball`
- 올곧 김밥 2상품 -> 기존 `food.meals.prepared.kimbap`
- 원본 broad 냉동밥 shelf의 `food.meals.rice.fried` 후보보다 제목이 명시하는 실제 제품형태를 우선했다.

### pending 084

- 파일: `handoff/2026-09-11/proposals/homeplus-rice-noodles-tortillas-084.json`
- 11관측 / 6상품
- 백제 쌀국수 3상품 -> 기존 `food.meals.noodles.rice_noodle`
- 밀/통밀 또띠아 3상품 -> 신규 후보 `food.bakery.bread.tortilla`
- 쌀국수/월남쌈 mixed shelf라는 이유로 또띠아를 면류로 분류하지 않았다.

### pending 085

- 파일: `handoff/2026-09-11/proposals/homeplus-grain-snacks-085.json`
- 10관측 / 5상품
- 해태 오사쯔 -> 기존 `food.snacks.savory.vegetable`
- 켈로그 단백질바K -> 신규 후보 `food.snacks.bars.protein`
- 오리온 땅콩강정 2상품 -> 신규 후보 `food.snacks.traditional.gangjeong`
- 그린피스 와사비스낵 -> 신규 후보 `food.snacks.savory.legume`
- 1+1, 10+1 등 원본 행사조건과 별도 promotion unresolved 상태는 classification-only 검토에서 수정하지 않았다.

## 누적 진행률

- 이전 체크포인트 누적: 1,046 / 3,916
- 이번 구간 신규 classification 검토: 43
- 현재 누적 검토: 1,089 / 3,916 (약 27.8%)
- 남은 미검토: 2,827 / 3,916 (약 72.2%)

이 수치는 `proposal_only` classification 검토 진행량 회계다. 이미 classification이 resolved이고 수량/행사/단위 등 다른 사유만 남은 행은 새 classification 검토로 중복 계산하지 않는다.

## 충돌 검사

- pending 082~085의 source_record_key를 기존 431개 explicit review decision과 대조했으며 일치 항목은 0건이다.
- repository 검색에서 이번 대상들은 pending/raw/catalog-unresolved 근거만 확인됐고 기존 proposal 충돌은 발견하지 못했다.

## 보존한 원칙

- 실제 제품형태를 broad retail shelf보다 우선한다.
- 기존 leaf가 정확히 맞을 때만 재사용한다.
- 건강식품을 일반 식품/음료로, 김밥을 볶음밥으로, 또띠아를 쌀국수로 강제하지 않는다.
- 맛/속재료/번들 수량은 taxonomy product-form leaf를 불필요하게 분기하지 않는다.
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

- 다음 대상: `handoff/2026-09-11/pending/086/001.json`
- PENDING_INDEX상 pending 086은 홈플러스 `과자/시리얼 > 시리얼/간식류소시지 > 일반/곡물 시리얼 > 옥수수`, 10관측 / 5고유제목이다.
- 이후 pending 087은 `과자/시리얼 > 초콜릿/캔디/젤리/껌 > 젤리/푸딩`, 10관측 / 5고유제목이다.
- pending 088은 `냉장/냉동/밀키트 > 돈까스/떡갈비/너겟 > 돈까스/생선까스/탕수육/김말이/기타 > 탕수육/김말이`, 10관측 / 5고유제목이다.
- pending 089는 `냉장/냉동/밀키트 > 떡볶이/면류 > 국수/칼국수/우동 > 기타면`, 10관측 / 5고유제목이다.
- 재개 시 실제 제목/판매페이지 키를 먼저 확인하고 기존 proposal 및 431개 explicit review decision 충돌을 다시 검사한다.
- 분류가 이미 resolved이고 행사/수량/단위 등 다른 pending 사유만 남은 관측은 classification-only 해소로 세지 않는다.
- 새 taxonomy leaf가 필요하면 기존 leaf에 억지로 넣지 말고 신규 후보 또는 taxonomy-policy hold로 보존한다.
