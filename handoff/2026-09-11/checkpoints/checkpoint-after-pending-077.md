# WalletSaver 분류 체크포인트 — pending 077 완료 후

## 현재 기준

- 기준 브랜치: `cleanup/remove-legacy-ai-admin-coupling`
- 기준 데이터/분류 pass: `pass41`
- 기준 pending 관측 수: 3,916
- 기존 explicit review decision 수: 431
- 현재 작업은 GitHub read/write 기반 `proposal_only` 검토이며 DB/운영 반영이 아니다.
- pass41의 실제 DB 기준선(5,280 적재 / 3,916 pending)은 변경하지 않았다.

## 최신 유효 진행 회계

- pending 073 완료: 950 / 3,916
- pending 074 proposal: 950 -> 962
- pending 075 proposal: 962 -> 974
- pending 076 proposal: 974 -> 986
- pending 077 proposal: 986 -> 998

## 이번 세션에서 이어서 완료한 proposal_only

### pending 074

- 파일: `handoff/2026-09-11/proposals/homeplus-instant-noodles-074.json`
- 12관측 / 6상품
- 비빔막국수 -> 기존 `food.meals.noodles.makguksu`
- 평양물냉면 -> 기존 `food.meals.noodles.naengmyeon`
- 직화볶음짬뽕 -> 기존 `food.meals.noodles.jjamppong`
- 직화볶음짜장 -> 기존 `food.meals.noodles.black_bean`
- 멸치칼국수 -> 기존 `food.meals.noodles.kalguksu`
- 가쓰오우동 -> 기존 `food.meals.noodles.udon`
- 육수·볶음 방식·맛은 제품형태보다 하위 속성으로 보고 기존 면 leaf를 사용했다.

### pending 075

- 파일: `handoff/2026-09-11/proposals/homeplus-kids-drinks-075.json`
- 12관측 / 6상품
- 뽀로로 딸기맛·사과, 카프리썬 오렌지·오렌지망고 4상품 -> 기존 `food.drinks.juice.fruit_drink`
- 제목에 100% 주스/착즙 근거가 없어 `food.drinks.juice.fruit`로 확대하지 않았다.
- `팔도 뽀로로 밀크` -> 일반 흰우유/가공유라고 단정하지 않고 신규 후보 `food.drinks.kids.milk_flavored`
- `마일로 초코` -> 초코우유라고 단정하지 않고 신규 후보 `food.drinks.malt.chocolate`
- 어린이용 표시는 제품형태 증거로만 활용하고 연령 자체를 과도한 taxonomy 분기로 쓰지 않았다.

### pending 076

- 파일: `handoff/2026-09-11/proposals/homeplus-other-fruit-drinks-076.json`
- 12관측 / 6상품
- 델몬트 망고 로우슈거, 모구모구 파인애플맛·리치·망고 -> 기존 `food.drinks.juice.fruit_drink`
- 델몬트 스테비아토마토 -> 기존 `food.drinks.juice.vegetable_drink`
- `모구모구 요거트맛` -> 실제 발효유나 과일음료라고 단정하지 않고 신규 후보 `food.drinks.other.yogurt_flavored`
- 원본 기타과일 진열을 그대로 복사하지 않고 실제 음료 형태를 우선했다.

### pending 077

- 파일: `handoff/2026-09-11/proposals/homeplus-drain-bleach-077.json`
- 12관측 / 6상품
- simplus 배수관 클리너 4L·1L, 유한펑크린 배수관 세정제 2L -> 기존 `household.cleaning.bath.drain`
- simplus 다용도 락스 4L·1L, 유한락스 레귤러 3L -> 신규 후보 `household.cleaning.general.chlorine_bleach`
- 염소계 락스를 기존 `household.cleaning.laundry.oxygen_bleach`로 잘못 합치지 않았다.
- 배수용품 shelf에 있다는 이유만으로 다용도 락스를 drain leaf에 넣지 않았다.

## 충돌/중복 점검

- 각 pending 묶음의 실제 `source_record_key`를 기준으로 `review-decisions-input.json`의 기존 431개 explicit review decision과 대조했다.
- pending 074~077 대상 키에서 기존 explicit review decision 일치는 확인되지 않았다.
- pending 077의 배수관세정제는 pending 066에서 확인한 기존 taxonomy 선례만 재사용했으며 상품 identity를 병합하지 않았다.
- 기존 명시 결정을 덮어쓰거나 raw observation을 수정하지 않았다.

## 누적 진행률

- 세션 시작 전 최신 유효 누적: 950 / 3,916
- 이번 세션 신규 classification 검토: 48
- 현재 누적 검토: 998 / 3,916 (약 25.5%)
- 남은 미검토: 2,918 / 3,916 (약 74.5%)

이 수치는 `proposal_only` classification 검토 진행량 회계다. 이미 classification이 resolved이고 수량/행사/단위 등 다른 사유만 남은 행은 새 classification 검토로 중복 계산하지 않는다.

## 보존한 원칙

- 실제 제품형태를 broad shelf보다 우선한다.
- 기존 leaf가 제품형태와 명확히 맞을 때만 사용한다.
- `주스`와 `과일음료`, 실제 발효유와 요거트맛 음료, 유제품 우유와 밀크향 어린이음료를 근거 없이 동일시하지 않는다.
- 산소계표백제와 염소계 락스를 분리하고, 진열 경로만으로 배수관세정제로 확대하지 않는다.
- 기존 신규-leaf 후보가 같은 제품형태에 맞으면 병렬 후보를 만들지 않고 재사용한다.
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

- 다음 대상: `handoff/2026-09-11/pending/078/001.json`
- PENDING_INDEX상 pending 078은 홈플러스 `우유/유제품 > 두유 > 일반두유`, 12관측 / 6고유제목이다.
- 이후 pending 079는 `장류/양념/제빵 > 소스 > 즉석요리소스/장국`, 12/6이다.
- pending 080은 `주방용품 > 주방/일회용품 > 종이컵 > 컵류`, 12/6이다.
- 재개 시 실제 제목/판매페이지 키/raw record ID를 먼저 확인하고 기존 proposal 및 431개 explicit review decision 충돌을 다시 검사한다.
- 분류가 이미 resolved이고 행사/수량/단위 등 다른 pending 사유만 남은 관측은 classification-only 해소로 세지 않는다.
- 새 taxonomy leaf가 필요하면 기존 leaf에 억지로 넣지 말고 신규 후보 또는 taxonomy-policy hold로 보존한다.
