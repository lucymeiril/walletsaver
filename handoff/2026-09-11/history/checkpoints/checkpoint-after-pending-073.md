# WalletSaver 분류 체크포인트 — pending 073 완료 후

## 현재 기준

- 기준 브랜치: `cleanup/remove-legacy-ai-admin-coupling`
- 기준 데이터/분류 pass: `pass41`
- 기준 pending 관측 수: 3,916
- 기존 explicit review decision 수: 431
- 현재 작업은 GitHub read/write 기반 `proposal_only` 검토이며 DB/운영 반영이 아니다.
- pass41의 실제 DB 기준선(5,280 적재 / 3,916 pending)은 변경하지 않았다.

## 최신 유효 진행 회계

- pending 069 완료: 900 / 3,916
- pending 070 proposal: 900 -> 913
- pending 071 proposal: 913 -> 926
- pending 072 proposal: 926 -> 938
- pending 073 proposal: 938 -> 950

## 이번 세션에서 이어서 완료한 proposal_only

### pending 070

- 파일: `handoff/2026-09-11/proposals/emart-deli-broad-070.json`
- 13관측 / 13상품
- `김자반 야채` -> 기존 `food.seafood.seaweed.laver`
- 메추리알 장조림 2상품 -> 기존 `food.preserved.sides.braised`; 메추리알 원재료 leaf가 아니라 완성 반찬 형태를 우선했다.
- `백명란젓` -> 기존 `food.seafood.processed.pollock_roe`
- 단무지 -> 신규 후보 `food.preserved.sides.danmuji`
- 새우젓/오징어젓갈/낙지젓갈 -> pass41 initial taxonomy에 젓갈 축이 없어 각각 발효수산 신규 후보로 보류했다.
- 칠리함박&매쉬포테이토, 콘치즈, 강정새우, 팔보채 -> 가까운 기존 leaf에 강제하지 않고 prepared-food 신규 후보로 보류했다.
- `생연어초밥&훈제말이` -> 혼합 델리 상품이므로 단일 sushi leaf로 축소하지 않았다.

### pending 071

- 파일: `handoff/2026-09-11/proposals/homeplus-chocolate-cereal-071.json`
- 13관측 / 7상품
- 오레오오즈, 크리치오, 오곡 코코볼, 첵스초코 계열 전부 초코 어린이용 아침 시리얼이다.
- pass41 시리얼 leaf는 `food.snacks.cereal.flakes`와 `food.snacks.cereal.granola`뿐이라, 해당 압출형/볼형 시리얼을 어느 쪽에도 강제하지 않았다.
- 7상품 모두 공통 신규 후보 `food.snacks.cereal.chocolate`로 보류했다.
- 컵/박스 포장, 쿠키앤크림 맛, 어린이용 표시는 taxonomy 분기보다 variant/attribute로 유지했다.

### pending 072

- 파일: `handoff/2026-09-11/proposals/homeplus-convenience-noodles-072.json`
- 12관측 / 6상품
- 생칼국수, 바지락칼국수 -> 기존 `food.meals.noodles.kalguksu`
- 비비고 들기름막국수, 칠갑 들기름막국수 -> 기존 `food.meals.noodles.makguksu`
- 베트남 쌀국수 -> 기존 `food.meals.noodles.rice_noodle`
- 사천 마라탕면 -> pass41에 대응 leaf가 없어 신규 후보 `food.meals.noodles.malatang_noodle`
- 들기름/바지락은 맛·토핑 속성으로 보고 기본 면 형태를 우선했다.

### pending 073

- 파일: `handoff/2026-09-11/proposals/homeplus-kimbap-ingredients-073.json`
- 12관측 / 6상품
- 완성 김밥이 아니라 김밥용 재료 또는 재료 세트이므로 기존 `food.meals.prepared.kimbap`을 사용하지 않았다.
- pass41에 이미 `food.preserved.ingredients` 조리재료 상위축과 `inari` leaf가 있어, 김밥 세트 3상품 및 단무지+우엉 혼합상품은 신규 후보 `food.preserved.ingredients.kimbap`으로 보류했다.
- 김밥 단무지는 pending 070과 동일한 신규 후보 `food.preserved.sides.danmuji`를 재사용했다.
- 김밥용 우엉은 장아찌/조림 형태를 제목만으로 단정하지 않고 신규 후보 `food.preserved.ingredients.burdock`으로 보류했다.

## 충돌/중복 점검

- 각 pending 묶음의 실제 `source_record_key`를 기준으로 `review-decisions-input.json`의 기존 431개 explicit review decision과 대조했다.
- pending 070~073의 대상 키에서 기존 explicit review decision 일치는 확인되지 않았다.
- 저장소 검색에서도 해당 source key들은 pending/raw/catalog-unresolved 근거 외 기존 proposal 충돌이 확인되지 않았다.
- 따라서 기존 명시 결정을 덮어쓰는 수정은 하지 않았다.

## 누적 진행률

- 세션 시작 전 최신 유효 누적: 900 / 3,916
- 이번 세션 신규 classification 검토: 50
- 현재 누적 검토: 950 / 3,916 (약 24.3%)
- 남은 미검토: 2,966 / 3,916 (약 75.7%)

이 수치는 `proposal_only` classification 검토 진행량 회계다. 이미 classification이 resolved이고 수량/행사/단위 등 다른 사유만 남은 행은 새 classification 검토로 중복 계산하지 않는다.

## 보존한 원칙

- 실제 제품형태를 broad shelf보다 우선한다.
- 기존 leaf가 제품형태와 명확히 맞을 때만 사용한다.
- 기존 신규-leaf 후보가 같은 제품형태에 맞으면 병렬 후보를 만들지 않고 재사용한다.
- 완성식품과 조리재료를 혼동하지 않는다. 특히 김밥재료를 완성 김밥으로 보내지 않는다.
- flavor, 포장 형태, 어린이용 표시, 토핑은 제품형태를 바꾸지 않는 한 taxonomy 분기 사유로 쓰지 않는다.
- 혼합상품은 한 구성요소의 leaf로 임의 축소하지 않는다.
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

- 다음 대상: `handoff/2026-09-11/pending/074/001.json`
- PENDING_INDEX상 pending 074는 홈플러스 `라면/즉석식품/통조림 > 당면/건면/스파게티 > 즉석면요리 > 즉석면`, 12관측 / 6고유제목이다.
- 이후 pending 075는 어린이음료 12/6, pending 076은 기타과일 음료 12/6이다.
- 재개 시 실제 제목/판매페이지 키/raw record ID를 먼저 확인하고 기존 proposal 및 431개 explicit review decision 충돌을 다시 검사한다.
- 분류가 이미 resolved이고 행사/수량/단위 등 다른 pending 사유만 남은 관측은 classification-only 해소로 세지 않는다.
- 새 taxonomy leaf가 필요하면 기존 leaf에 억지로 넣지 말고 신규 후보 또는 taxonomy-policy hold로 보존한다.
