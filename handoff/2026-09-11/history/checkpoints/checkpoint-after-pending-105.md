# WalletSaver 분류 체크포인트 — pending 105 완료 후

## 현재 기준

- 기준 브랜치: `cleanup/remove-legacy-ai-admin-coupling`
- 기준 데이터/분류 pass: `pass41`
- 기준 pending 관측 수: 3,916
- 기존 explicit review decision 수: 431
- 현재 작업은 GitHub read/write 기반 `proposal_only` 검토이며 DB/운영 반영이 아니다.
- pass41 실제 기준선(5,280 적재 / 3,916 pending)은 변경하지 않았다.

## 최신 유효 진행 회계

- pending 101 완료: 1,249 / 3,916
- pending 102 proposal: 1,249 -> 1,259
- pending 103 proposal: 1,259 -> 1,269
- pending 104 proposal: 1,269 -> 1,279
- pending 105 proposal: 1,279 -> 1,288

## 이번 구간에서 완료한 proposal_only

### pending 102

- 파일: `handoff/2026-09-11/proposals/homeplus-black-tea-102.json`
- 10관측 / 5상품
- 트와이닝 얼그레이, 트와이닝 잉글리쉬 블랙퍼스트, 아마드티 잉글리쉬블랙퍼스트, 아크바 실론티, 쌍계명차 제로 아이스티 유자 -> 모두 기존 `food.drinks.tea.black`
- current taxonomy가 홍차와 아이스티를 동일 leaf로 통합하므로 아이스티 유자도 해당 leaf를 재사용했다.
- 브랜드, 향미, 제로 여부, 티백 수량은 taxonomy 분기로 만들지 않았다.

### pending 103

- 파일: `handoff/2026-09-11/proposals/homeplus-fruit-concentrates-103.json`
- 10관측 / 5상품
- 유기농 레몬즙 14T/480ML, 깔라만시 100 480G, 비타민 레몬 티앤에이드 680G, 100%깔라만시 1L -> 공통 신규 후보 `food.drinks.concentrates.fruit`
- 현재 taxonomy에 음용 과일 농축액 exact leaf가 없다.
- pending 079의 조리용 레몬쥬스 신규 후보 `food.seasonings.acids.lemon_juice`와는 retail context와 product form이 달라 분리했다.
- 1+1 및 가격/수량 조건은 수정하지 않았다.

### pending 104

- 파일: `handoff/2026-09-11/proposals/homeplus-fruit-tea-preserves-104.json`
- 10관측 / 5상품
- 한라봉청, 자몽청, 레몬청, 생강레몬청, 한라봉차 -> 공통 신규 후보 `food.drinks.tea.fruit_preserve`
- raw shelf candidate `food.drinks.tea.citron`은 유자차 전용 leaf이므로 다른 과일청을 유자차로 강제하지 않았다.
- 과일 종류와 생강 혼합은 flavor/blend 속성으로 유지했다.

### pending 105

- 파일: `handoff/2026-09-11/proposals/homeplus-nurungji-105.json`
- 9관측 / 5상품
- 찹쌀누룽지, 김치누룽지, 가마솥 누룽지, 구운김 찹쌀누룽지, 백미 누룽지 -> 공통 신규 후보 `food.grains.processed.nurungji`
- current broad name rules가 `누룽지`를 차 또는 스낵 후보로 잡을 수 있지만, 이 묶음은 330G~2.5KG 대용량 가공 쌀 식품이라 그 후보를 승인하지 않았다.
- 김치/구운김, 백미/찹쌀, 제조방식과 중량은 속성으로 유지했다.

## 누적 진행률

- 이전 체크포인트 누적: 1,249 / 3,916
- 이번 구간 신규 classification 검토: 39
- 현재 누적 검토: 1,288 / 3,916 (약 32.9%)
- 남은 미검토: 2,628 / 3,916 (약 67.1%)

이 수치는 `proposal_only` classification 검토 진행량 회계다. 이미 classification이 resolved이고 수량/행사/단위 등 다른 사유만 남은 행은 새 classification 검토로 중복 계산하지 않는다.

## 충돌 검사

- pending 102~105의 20개 source_record_key를 기존 431개 explicit review decision과 대조했으며 일치 항목은 0건이다.
- current taxonomy에서 `food.drinks.tea.black` 존재를 재확인했다.
- current taxonomy의 `food.drinks.tea.citron`은 유자차-specific leaf이며 다른 과일청에 그대로 확장하지 않았다.
- `food.drinks.concentrates.fruit`, `food.drinks.tea.fruit_preserve`, `food.grains.processed.nurungji`에 대한 기존 candidate precedent는 repository 검색에서 찾지 못했다.
- 기존 explicit review decision이나 raw pending observation은 수정하지 않았다.

## 보존한 원칙

- 실제 product form을 broad retail shelf나 broad name rule보다 우선한다.
- 기존 leaf가 정확히 맞는 경우에만 재사용한다.
- 맛, 원료 변형, 중량, 팩 수량, 행사조건은 불필요한 taxonomy 분기로 만들지 않는다.
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

- 다음 대상: `handoff/2026-09-11/pending/106/001.json`
- pending 106: `냉장/냉동/밀키트 > 만두 > 진빵/만두피/화권/완탕/스프링롤 > 화권/완탕/스프링롤`, 9관측 / 5고유제목
- pending 107: `냉장/냉동/밀키트 > 피자/핫도그/치킨 > 냉동감자/치즈스틱 > 냉동감자`, 9/5
- pending 108: `라면/즉석식품/통조림 > 라면/수입면류 > 짜장라면/우동라면 > 짜장라면`, 9/5
- pending 109: `세탁/청소 > 세탁세제/섬유유연제 > 섬유유연제 > 고농축 섬유유연제`, 9/6
- 재개 시 실제 제목/판매페이지 키/raw record ID를 먼저 확인하고 기존 proposal 및 431개 explicit review decision 충돌을 다시 검사한다.
- 분류가 이미 resolved이고 행사/수량/단위 등 다른 pending 사유만 남은 관측은 classification-only 해소로 세지 않는다.
- 새 taxonomy leaf가 필요하면 기존 leaf에 억지로 넣지 말고 신규 후보 또는 taxonomy-policy hold로 보존한다.
