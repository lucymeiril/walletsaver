# WalletSaver 분류 체크포인트 — pending 069 완료 후

## 현재 기준

- 기준 브랜치: `cleanup/remove-legacy-ai-admin-coupling`
- 기준 데이터/분류 pass: `pass41`
- 기준 pending 관측 수: 3,916
- 기존 explicit review decision 수: 431
- 현재 작업은 GitHub read/write 기반 `proposal_only` 검토이며 DB/운영 반영이 아니다.
- pass41의 실제 DB 기준선(5,280 적재 / 3,916 pending)은 변경하지 않았다.

## 최신 유효 진행 회계

- pending 061 완료: 788 / 3,916
- pending 062 proposal: 788 -> 803
- pending 063 proposal: 803 -> 818
- pending 064 proposal: 818 -> 832
- pending 065 proposal: 832 -> 846
- pending 066 proposal: 846 -> 860
- pending 067 proposal: 860 -> 874
- pending 068 proposal: 874 -> 888
- pending 069: 13 pending 행을 확인했으나 이미 `food.produce.fruit.tomato`로 classified인 `ingestion:78:41`은 `count_range_unresolved`만 남아 있어 classification-only 진행량에서 제외. 신규 classification 검토 12건으로 888 -> 900.

## 이번 세션에서 이어서 완료한 proposal_only

### pending 066

- 파일: `handoff/2026-09-11/proposals/homeplus-cleaning-chemicals-066.json`
- 14관측 / 9상품
- 과탄산소다 2상품 / 3관측 -> 기존 `household.cleaning.laundry.oxygen_bleach`
- 세탁조 클리너 2상품 / 3관측 -> 기존 `household.cleaning.laundry.machine_cleaner`
- 세면대 배수관 클리너 1상품 / 2관측 -> 기존 `household.cleaning.bath.drain`
- 단독 베이킹소다 세정제 2상품 / 3관측 -> 신규 후보 `household.cleaning.general.baking_soda`
- 단독 구연산 세정제 2상품 / 3관측 -> 신규 후보 `household.cleaning.general.citric_acid`
- 원본 `욕실세정제` shelf를 그대로 믿지 않고 실제 제품 용도를 우선했다.

### pending 067

- 파일: `handoff/2026-09-11/proposals/homeplus-shower-balls-067.json`
- 14관측 / 7상품
- 전부 샤워볼이며 동일 판매페이지의 두 시점 관측을 상품별로 함께 묶었다.
- pass41에 샤워볼 leaf가 없어 전부 신규 후보 `household.bath.accessories.shower_ball`로 보류.
- 이 후보는 앞선 `proposals/emart-household-044.json`에서 이미 제안된 샤워볼 후보를 재사용한 것으로 새 병렬 taxonomy를 만들지 않았다.
- 색상 및 롱 타입 차이는 taxonomy 분기 사유로 사용하지 않았다.

### pending 068

- 파일: `handoff/2026-09-11/proposals/lottemart-non-alcoholic-drinks-068.json`
- 14관측 / 14상품
- 테라·하이트·클라우드·버드와이저·크라우스탈러·하이네켄·기네스·카스 계열 13상품 -> 기존 `food.drinks.non_alcoholic.beer`
- `티젠 젠하이볼향 0.0 레몬 (350ML)` 1상품 -> 맥주형이 아니므로 신규 후보 `food.drinks.non_alcoholic.cocktail`
- 모든 `promotion_unresolved`는 분류와 별개로 그대로 보존했다.

### pending 069

- 파일: `handoff/2026-09-11/proposals/emart-fruit-broad-069.json`
- pending 행 13건 확인 / 신규 classification 검토 12건 / 기존 classified 1건 제외
- 복숭아 4상품 -> 기존 `food.produce.fruit.peach`
- 골드키위 1상품 -> 기존 `food.produce.fruit.kiwi`
- 애플수박 1상품 -> 기존 `food.produce.fruit.watermelon`
- 머스크멜론·허니듀멜론 2상품 -> 기존 `food.produce.fruit.melon`
- 칠레산 레몬 1상품 -> 이전 pending 260과 동일하게 독립 레몬 leaf 부재/감귤류 통합 정책 미확정으로 보류. 라임으로 잘못 합치지 않음.
- 유기농 군밤 1상품 -> 생과일이 아니며 현재 견과/건과일 leaf에 강제하지 않고 roasted-chestnut/맛밤 taxonomy gap으로 보류.
- `[할인 특가]시즌 제철 과일 딜`, `친환경 신선 행사 모음전` 2행 -> `dealItemView` 기반 단일 상품이 아닌 컬렉션/행사 표면으로 판단해 상품 taxonomy assignment를 만들지 않음.
- `맑은청 찰토마토 7~10입/팩` (`ingestion:78:41`) -> 이미 `food.produce.fruit.tomato`로 classified이고 `count_range_unresolved`만 남아 있어 신규 classification 검토량에서 제외.

## 누적 진행률

- 세션 시작 전 최신 유효 누적: 846 / 3,916
- 이번 세션 신규 classification 검토: 54
- 현재 누적 검토: 900 / 3,916 (약 23.0%)
- 남은 미검토: 3,016 / 3,916 (약 77.0%)

이 수치는 `proposal_only` classification 검토 진행량 회계다. pending 파일을 읽은 행 수와 동일하지 않을 수 있으며, 이미 classification이 resolved이고 수량/행사/단위 등 다른 사유만 남은 행은 새 classification 검토로 중복 계산하지 않는다.

## 보존한 원칙

- 실제 상품명을 원본 진열 경로보다 우선한다.
- 기존 leaf가 제품형태와 명확히 맞을 때만 기존 taxonomy에 제안한다.
- 기존에 제안된 신규 leaf 후보가 같은 제품형태에 맞으면 새 병렬 후보를 만들지 않고 재사용한다.
- 레몬/라임, 군밤/견과·건과일처럼 제품형태 또는 taxonomy 정책이 불명확하면 가까운 leaf에 억지로 넣지 않는다.
- 딜/모음전처럼 단일 상품이 아닌 판매 표면에는 상품 taxonomy assignment를 만들지 않는다.
- 수량, 행사조건, 원본 관측, 상품 병합은 classification-only 검토에서 수정하지 않는다.
- promotion 관련 unresolved 사유는 분류 제안만으로 해소된 것으로 세지 않는다.
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

- 다음 대상: `handoff/2026-09-11/pending/070/001.json`
- PENDING_INDEX 순서를 그대로 이어 검토한다.
- 재개 시 먼저 실제 제목/판매페이지 키/raw record ID를 확인한다.
- 기존 proposal 중복과 431개 explicit review decision 충돌을 다시 검사한다.
- 분류가 이미 resolved이고 행사/수량/단위 등 다른 pending 사유만 남은 관측은 classification-only 해소로 세지 않는다.
- 새 taxonomy leaf가 필요하면 기존 leaf에 억지로 넣지 말고 신규 후보 또는 taxonomy-policy hold로 보존한다.
