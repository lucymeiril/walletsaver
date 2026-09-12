# WalletSaver 분류 체크포인트 — pending 109 완료 후

## 현재 기준

- 기준 브랜치: `cleanup/remove-legacy-ai-admin-coupling`
- 기준 데이터/분류 pass: `pass41`
- 기준 pending 관측 수: 3,916
- 기존 explicit review decision 수: 431
- 현재 작업은 GitHub read/write 기반 `proposal_only` 검토이며 DB/운영 반영이 아니다.
- pass41 실제 기준선(5,280 적재 / 3,916 pending)은 변경하지 않았다.

## 최신 유효 진행 회계

- pending 105 완료: 1,288 / 3,916
- pending 106 proposal: 1,288 -> 1,297
- pending 107 proposal: 1,297 -> 1,306
- pending 108 proposal: 1,306 -> 1,315
- pending 109 proposal: 1,315 -> 1,318

pending 109는 9관측이지만 그중 피죤 섬유유연제 6관측은 이미 `household.cleaning.laundry.softener`로 classification이 resolved되어 있고 `mixed_package_unresolved`만 남아 있다. 따라서 해당 6관측은 새 classification-only 진척에 중복 계산하지 않았고, 실제로 classification이 미해결이던 아우라 탈취제 3관측만 신규 검토로 계산했다.

## 이번 구간에서 완료한 proposal_only

### pending 106

- 파일: `handoff/2026-09-11/proposals/homeplus-dimsum-106.json`
- 9관측 / 5상품 / 신규 classification 9
- 씨제이 고메 새우 하가우, 씨제이 고메 샤오롱바오, 동원 사천우육 완탕, 동원 광동 새우완탕, 동원 딤섬 샤오롱바오 -> 기존 `food.meals.dumplings.dimsum`
- 하가우/완탕은 current taxonomy title rule과 일치하고 샤오롱바오도 동일 dim-sum dumpling product form으로 처리했다.
- 새우/우육 충전물, 사천/광동 스타일, 팩 수량, 1+1은 taxonomy 분기로 만들지 않았다.

### pending 107

- 파일: `handoff/2026-09-11/proposals/homeplus-frozen-potatoes-107.json`
- 9관측 / 5상품 / 신규 classification 9
- 감자튀김, 크링클컷 냉동감자, 케이준 양념감자, 스파이스웨지 -> 신규 후보 `food.meals.prepared.frozen_potato`
- current taxonomy에는 fresh potato, potato snack, raw/prepped frozen vegetable leaf는 있으나 ready-to-cook frozen fries/wedges exact leaf는 없다.
- 냉동 프라이/웨지를 신선감자, 감자칩, 일반 냉동채소에 강제하지 않았다.
- 컷 모양과 양념은 속성으로 유지했다.

### pending 108

- 파일: `handoff/2026-09-11/proposals/homeplus-black-bean-ramen-108.json`
- 9관측 / 5상품 / 신규 classification 9
- 이춘삼 짜장 건면, 올리브 짜파게티, 짜슐랭, 사천짜파게티, 짜짜로니 -> 기존 `food.meals.noodles.black_bean`
- 건면 여부, 사천 스타일, 멀티팩 수량은 product-form 분기로 만들지 않았다.
- 짜슐랭 관측의 `promotion_unresolved`는 classification-only 범위 밖으로 그대로 보존했다.

### pending 109

- 파일: `handoff/2026-09-11/proposals/homeplus-softener-deodorizer-109.json`
- 9관측 / 6상품 / 신규 classification 3
- 아우라 편백탈취제 숲속향/은은한향/상쾌한향 -> 기존 `household.cleaning.general.deodorizer`
- retail shelf는 고농축 섬유유연제지만 제목의 명시적 `탈취제` product type이 우선한다.
- 피죤 섬유유연제 핑크로즈/옐로우 미모사/블루비앙카는 총 6관측이 이미 `household.cleaning.laundry.softener`로 classified 상태다.
- 해당 피죤 6관측의 남은 사유는 `mixed_package_unresolved`이며 classification-only 신규 진척에는 0건으로 계산했다.

## 누적 진행률

- 이전 체크포인트 누적: 1,288 / 3,916
- 이번 구간 신규 classification 검토: 30
- 현재 누적 검토: 1,318 / 3,916 (약 33.7%)
- 남은 미검토: 2,598 / 3,916 (약 66.3%)

이 수치는 `proposal_only` classification 검토 진행량 회계다. 이미 classification이 resolved이고 수량/행사/단위/mixed package 등 다른 사유만 남은 행은 새 classification 검토로 중복 계산하지 않는다.

## 충돌 검사

- pending 106~109의 21개 source_record_key를 기존 431개 explicit review decision과 대조했으며 일치 항목은 0건이다.
- current taxonomy에서 `food.meals.dumplings.dimsum`, `food.meals.noodles.black_bean`, `household.cleaning.laundry.softener`, `household.cleaning.general.deodorizer` 존재를 재확인했다.
- current taxonomy에는 ready-to-cook frozen fries/wedges exact leaf가 없고 repository search에서도 `food.meals.prepared.frozen_potato` 후보 선례를 찾지 못했다.
- 기존 explicit review decision이나 raw pending observation은 수정하지 않았다.

## 보존한 원칙

- 실제 product form을 broad retail shelf보다 우선한다.
- 기존 leaf가 정확히 맞는 경우에만 재사용한다.
- 맛, 충전물, 컷 모양, 양념, 팩 수량, 행사조건은 불필요한 taxonomy 분기로 만들지 않는다.
- classification이 이미 resolved이고 다른 pending 사유만 남은 행은 classification-only 진척으로 세지 않는다.
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

- 다음 대상: `handoff/2026-09-11/pending/110/001.json`
- pending 110: lottemart `아이스크림ㆍ빙과류 > 튜브아이스크림`, 9관측 / 9고유제목
- pending 111: emart `헤어/바디/뷰티`, 8관측 / 8고유제목
- pending 112: homeplus `과자/시리얼 > 초콜릿/캔디/젤리/껌 > 껌`, 8관측 / 4고유제목
- pending 113: homeplus `냉장/냉동/밀키트 > 떡볶이/면류 > 떡국떡/떡볶이떡 > 떡국떡`, 8관측 / 4고유제목
- 재개 시 실제 제목/판매페이지 키/raw record ID를 먼저 확인하고 기존 proposal 및 431개 explicit review decision 충돌을 다시 검사한다.
- 분류가 이미 resolved이고 행사/수량/단위 등 다른 pending 사유만 남은 관측은 classification-only 해소로 세지 않는다.
- 새 taxonomy leaf가 필요하면 기존 leaf에 억지로 넣지 말고 신규 후보 또는 taxonomy-policy hold로 보존한다.
