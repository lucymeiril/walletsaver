# WalletSaver 분류 체크포인트 — pending 097 완료 후

## 현재 기준

- 기준 브랜치: `cleanup/remove-legacy-ai-admin-coupling`
- 기준 데이터/분류 pass: `pass41`
- 기준 pending 관측 수: 3,916
- 기존 explicit review decision 수: 431
- 현재 작업은 GitHub read/write 기반 `proposal_only` 검토이며 DB/운영 반영이 아니다.
- pass41 실제 기준선(5,280 적재 / 3,916 pending)은 변경하지 않았다.

## 최신 유효 진행 회계

- pending 093 완료: 1,169 / 3,916
- pending 094 proposal: 1,169 -> 1,179
- pending 095 proposal: 1,179 -> 1,189
- pending 096 proposal: 1,189 -> 1,199
- pending 097 proposal: 1,199 -> 1,209

## 이번 구간에서 완료한 proposal_only

### pending 094

- 파일: `handoff/2026-09-11/proposals/homeplus-canned-ham-094.json`
- 10관측 / 5상품
- 목우촌 뚝심, CJ 스팸 클래식, 스팸 25% 라이트, 동원 리챔, 스팸 클래식 싱글 -> 모두 기존 `food.preserved.canned.ham`
- 브랜드, 라이트/싱글 변형과 80g/200g 3팩 구성은 속성으로 두고 통조림 햄 product form을 유지했다.
- 1+1 및 가격/수량 필드는 수정하지 않았다.

### pending 095

- 파일: `handoff/2026-09-11/proposals/homeplus-seafood-condiments-095.json`
- 10관측 / 5상품
- 생와사비 -> 기존 `food.seasonings.spices.wasabi_paste`
- 홀스래디쉬 소스 2상품 -> 신규 후보 `food.seasonings.sauces.horseradish`
- 초데리소스 -> 신규 후보 `food.seasonings.sauces.sushi_vinegar`
- 속초식 물회소스 -> 신규 후보 `food.seasonings.sauces.mulhoe`
- broad 수산간편식 소스 shelf만으로 mustard/dressing/초고추장 등 기존 leaf에 억지로 넣지 않았다.

### pending 096

- 파일: `handoff/2026-09-11/proposals/homeplus-jerky-096.json`
- 10관측 / 5상품
- 우육포 2상품과 코주부 육포 MILD/HOT&SPICY/BBQ 3상품 -> 공통 신규 후보 `food.meat.processed.jerky`
- 현재 taxonomy에 육포 exact leaf가 없어서 기존 가공육/수산 건어물 leaf로 강제하지 않았다.
- 골든올리브, 오리지날, MILD, HOT&SPICY, BBQ는 flavor/style 속성으로 유지한다.

### pending 097

- 파일: `handoff/2026-09-11/proposals/homeplus-bath-towels-097.json`
- 10관측 / 5상품
- simplus 데일리/호텔 세면타월 5상품 -> 공통 신규 후보 `household.bath.textiles.towel`
- 현재 taxonomy의 `household.hygiene.paper.kitchen` 키친타월은 제지 상품이라 직물 세면타월과 분리했다.
- 색상, 150g/200g, 데일리/호텔 라인은 속성으로 유지한다.

## 누적 진행률

- 이전 체크포인트 누적: 1,169 / 3,916
- 이번 구간 신규 classification 검토: 40
- 현재 누적 검토: 1,209 / 3,916 (약 30.9%)
- 남은 미검토: 2,707 / 3,916 (약 69.1%)

이 수치는 `proposal_only` classification 검토 진행량 회계다. 이미 classification이 resolved이고 수량/행사/단위 등 다른 사유만 남은 행은 새 classification 검토로 중복 계산하지 않는다.

## 충돌 검사

- pending 094~097의 20개 source_record_key를 기존 431개 explicit review decision과 대조했으며 일치 항목은 0건이다.
- current taxonomy에서 `food.preserved.canned.ham`과 `food.seasonings.spices.wasabi_paste` 존재를 재확인했다.
- `food.meat.processed.jerky`, `household.bath.textiles.towel`, `food.seasonings.sauces.horseradish`에 대한 기존 proposal/candidate 선례는 repository 검색에서 찾지 못했다.
- source key와 상품 제목은 pending/raw/catalog-unresolved 근거와 일치하며 기존 explicit 결정은 덮어쓰지 않았다.

## 보존한 원칙

- 실제 product form을 broad retail shelf보다 우선한다.
- 기존 leaf가 정확히 맞는 경우에만 재사용한다.
- 맛, 색상, 중량, 팩 수량, 제품 라인명은 불필요한 taxonomy 분기로 만들지 않는다.
- 수량, 행사조건, 가격, 원본 관측, 상품 병합은 classification-only 검토에서 수정하지 않는다.
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

- 다음 대상: `handoff/2026-09-11/pending/098/001.json`
- pending 098: 홈플러스 `우유/유제품 > 우유 > 딸기/초코/바나나/기타 우유`, 10관측 / 5고유제목
- pending 099: `주방용품 > 주방/일회용품 > 고무장갑/랩/팩 > 고무장갑`, 10/5
- pending 100: `채소 > 건채소/기타 > 건채소 > 건나물`, 10/5
- pending 101: `채소 > 건채소/기타 > 건채소 > 건약재`, 10/5
- 재개 시 실제 제목/판매페이지 키/raw record ID를 먼저 확인하고 기존 proposal 및 431개 explicit review decision 충돌을 다시 검사한다.
- 분류가 이미 resolved이고 행사/수량/단위 등 다른 pending 사유만 남은 관측은 classification-only 해소로 세지 않는다.
- 새 taxonomy leaf가 필요하면 기존 leaf에 억지로 넣지 말고 신규 후보 또는 taxonomy-policy hold로 보존한다.
