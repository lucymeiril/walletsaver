# WalletSaver 분류 체크포인트 — pending 093 완료 후

## 현재 기준

- 기준 브랜치: `cleanup/remove-legacy-ai-admin-coupling`
- 기준 데이터/분류 pass: `pass41`
- 기준 pending 관측 수: 3,916
- 기존 explicit review decision 수: 431
- 현재 작업은 GitHub read/write 기반 `proposal_only` 검토이며 DB/운영 반영이 아니다.
- pass41 실제 기준선(5,280 적재 / 3,916 pending)은 변경하지 않았다.

## 최신 유효 진행 회계

- pending 089 완료: 1,129 / 3,916
- pending 090 proposal: 1,129 -> 1,139
- pending 091 proposal: 1,139 -> 1,149
- pending 092 proposal: 1,149 -> 1,159
- pending 093 proposal: 1,159 -> 1,169

## 이번 구간에서 완료한 proposal_only

### pending 090

- 파일: `handoff/2026-09-11/proposals/homeplus-kimchi-dumplings-090.json`
- 10관측 / 5상품
- 비비고 김치 왕교자 -> 기존 `food.meals.dumplings.gyoza`
- 고향만두 김치, 개성김치감자만두, 생만두 갓김치, 수제 김치 만두 -> 기존 `food.meals.dumplings.assorted`
- precise shelf가 김치교자만두여도 제목이 실제 교자 form을 명시하는 왕교자만 gyoza로 두고, 감자만두/수제만두의 기존 reviewed precedent와 일반 만두 form을 보존했다.
- 1+1과 2팩 수량은 수정하지 않았다.

### pending 091

- 파일: `handoff/2026-09-11/proposals/homeplus-global-meal-kits-091.json`
- 10관측 / 5상품
- 부대찌개, 밀푀유나베, 불고기 쉬림프 월남쌈, 마라탕, 감바스 모두 제목에 `[밀키트]`가 명시됨 -> 기존 `food.meals.prepared.meal_kit`
- 완성요리명보다 판매 product form인 meal kit를 우선했다.

### pending 092

- 파일: `handoff/2026-09-11/proposals/homeplus-tofu-kits-092.json`
- 10관측 / 5상품
- 얇은/넓은 두부면 -> 기존 `food.meals.noodles.tofu_noodle`
- 국산 연천콩 콩물 -> 신규 후보 `food.plant.soy.soy_liquid`
- 해물/야채 두부봉 -> 공통 신규 후보 `food.plant.soy.tofu_bar`
- 콩물을 두유로, 두부봉을 일반 두부로 강제하지 않았다. 맛/폭은 속성으로 유지한다.

### pending 093

- 파일: `handoff/2026-09-11/proposals/homeplus-surimi-093.json`
- 10관측 / 5상품
- 맛살 5상품 전부 -> 기존 `food.seafood.processed.surimi`
- 김밥용 표기와 2팩 수량은 사용처/수량 속성이며 product-form leaf를 분기하지 않는다.

## 누적 진행률

- 이전 체크포인트 누적: 1,129 / 3,916
- 이번 구간 신규 classification 검토: 40
- 현재 누적 검토: 1,169 / 3,916 (약 29.9%)
- 남은 미검토: 2,747 / 3,916 (약 70.1%)

이 수치는 `proposal_only` classification 검토 진행량 회계다. 이미 classification이 resolved이고 수량/행사/단위 등 다른 사유만 남은 행은 새 classification 검토로 중복 계산하지 않는다.

## 충돌 검사

- pending 090~093의 20개 source_record_key를 기존 431개 explicit review decision과 대조했으며 일치 항목은 0건이다.
- repository 검색에서 대상 source key는 pending/catalog-unresolved 근거만 확인됐고 기존 proposal 충돌은 발견하지 못했다.
- pending 092의 콩물/두부봉 신규 후보와 충돌하는 기존 candidate precedent도 찾지 못했다.

## 보존한 원칙

- 실제 제품형태를 broad retail shelf보다 우선한다.
- 기존 leaf가 정확히 맞을 때만 재사용한다.
- 만두 속재료, meal-kit 요리명, 두부면 폭, 맛살 사용처를 불필요한 taxonomy 분기로 만들지 않는다.
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

- 다음 대상: `handoff/2026-09-11/pending/094/001.json`
- pending 094: 홈플러스 `라면/즉석식품/통조림 > 참치/스팸/축수산통조림 > 스팸/햄/닭가슴살캔 > 돈육통조림`, 10관측 / 5고유제목
- pending 095: `수산물/건어물 > 간편/냉동수산물 > 수산간편식 > 소스류`, 10/5
- pending 096: `수산물/건어물 > 건오징어/건어물/다시팩 > 쥐포/어포/육포 > 육포`, 10/5
- pending 097: `욕실/생활용품 > 욕실용품 > 타월/욕실가운 > 세면타올`, 10/5
- 재개 시 실제 제목/판매페이지 키/raw record ID를 먼저 확인하고 기존 proposal 및 431개 explicit review decision 충돌을 다시 검사한다.
- 분류가 이미 resolved이고 행사/수량/단위 등 다른 pending 사유만 남은 관측은 classification-only 해소로 세지 않는다.
- 새 taxonomy leaf가 필요하면 기존 leaf에 억지로 넣지 말고 신규 후보 또는 taxonomy-policy hold로 보존한다.
