# 이어받기 진행 기록

## 2026-09-11 인수인계 기준

- 분류 데이터는 pass41, 분류 코드18e8fc9 기준. 포장 중 추가 분류 없음.
- 9,196관측 중5,280검토 적재/3,916보류. 운영 승인/공개 없음.
- README → PENDING_INDEX → 해당 pending 조각 순으로 읽기.
- 다음 작업자는 아래에 새 절을 추가: 처리 묶음/원본ID, 판단, 수정파일, 제안과 실제 적재의 구별, 실행한 검사, 다음 재개점.
- 원본/현재 DB는 동결 기준선이다. 새로운 분류 커밋만으로 이 폴더의 DB 수치가 바뀌지 않는다.
- 포장 검증: manifest 전체 파일 해시/압축 복원, 원본108실행 및 catalog 모든 조각 무손실 대조, 보류3,916개 ID 전량 대조 통과. 추출 원본DB로 새 DB를 재구축하여 동일5,280적재/3,916보류 및 검증·멱등 import를 확인했다. 복원한 stage 정합성 검사도 통과. 전체 앱 회귀검사는 이번 자료 포장과 무관하여 미실행.

## 2026-09-11 쌀·잡곡·견과 제안 배치 — pending 034 / 028

- 확인 범위: `pending/034/001.json`, `pending/034/002.json`의 이마트 29관측과 `pending/028/001.json`, `pending/028/002.json`의 롯데마트 33관측을 원본 제목·raw record ID·가능한 세부 원본 경로와 함께 검토했다.
- 원본과 기존 결정 보존: `review-decisions-input.json`, `reviewed-decisions-applied.json`, pass41 catalog/DB 원본은 수정하지 않았다. 기존 `initial_taxonomy.py`에 이미 존재하는 리프만 제안에 사용했고 이번 배치에서 새 리프나 전역 자동 분류 규칙을 추가하지 않았다.
- 제안 저장: `proposals/grains-nuts-028-034.json`에 `status=proposal_only`, `baseline_pass=pass41`, `executed_tests=[]`로 30개 raw record ID의 분류 제안을 기록했다. 이 파일은 현재 import가 자동으로 읽는 입력이 아니며 DB 반영 전이다. 상품군 병합은 요청하지 않았다(`identity_merge=not_requested`).
- 이마트 034: 백미·혼합곡·아몬드·호두·캐슈넛·땅콩·혼합견과 등 제목과 진열 근거가 명확한 19건만 기존 리프에 제안했다. 피칸/치아씨드/호박씨처럼 현재 리프가 없는 품목, 강냉이/미숫가루 같은 가공품, 돼지감자 현미·슈퍼믹스·와사비맛 땅콩처럼 혼합/시즈닝 해석이 필요한 10건은 계속 보류한다.
- 롯데마트 028: 원본 상위 경로 `쌀ㆍ잡곡ㆍ견과류`만 신뢰하지 않고 payload의 세부 `category_path`와 제목을 함께 봤다. 일반 견과/혼합견과와 명시적 건과일 등 11건만 기존 리프에 제안했다. 고구마/바나나/단호박 칩과 누룽지부각, 피칸/호박씨/듀럼밀, HBAF 등 시즈닝·향미·프레첼 혼합 견과 22건은 계속 보류한다.
- 수량/규격: 이번 작업은 분류 제안만 작성했으며 정규화 수량을 변경하지 않았다. `quantity_review`는 모두 `unchanged; classification-only proposal`로 기록했다.
- 실제 반영/검사: GitHub 텍스트 읽기·쓰기만 사용했다. staging SQLite 재구축, DB import, `verify_initial_stage.py`, pytest, 멱등 import 검사는 실행하지 않았다. 따라서 5,280 적재/3,916 보류 수치도 변경됐다고 보지 않는다.
- 다음 재개점: 실행 가능한 환경에서 제안 30건을 기존 431개 명시 결정과 다시 충돌 검사한 뒤 승인할 항목만 explicit review decision으로 승격하고 새 pass DB를 생성한다. 이후 관련 taxonomy/data-integrity/멱등 검사를 실제 실행해 결과를 이 파일에 추가한다. 보류 32건은 피칸·씨앗류·듀럼밀의 신규 리프 필요성 및 시즈닝 견과를 원물 견과 리프로 볼지 정책을 먼저 정한 뒤 재검토한다.

## 2026-09-11 소형 곡물·견과 후속 제안 — pending 139 / 282 / 344 / 400 / 405 / 443 / 444 / 445 / 446

- 확인 범위: 위 9개 pending 묶음의 조각 전부, 총 17관측을 검토했다. 홈플러스 반복 수집은 동일 `source_record_key`/판매페이지를 새 상품으로 쪼개지 않고 같은 결정의 `raw_record_ids`에 함께 묶었다.
- 제안 저장: `proposals/grains-nuts-small-139-282-344-400-405-443-446.json`에 12관측을 기존 pass41 리프로 제안하고 5관측을 `held_decisions`로 명시 보류했다. 파일 상태는 `proposal_only`, `baseline_pass=pass41`, `executed_tests=[]`이다.
- 제안 12관측: 피스타치오 3개 판매페이지의 반복관측 6건 → `food.grains.nuts.pistachio`; 베스트견과 3MIX 반복 2건과 하루견과 1건 → `food.grains.nuts.mixed`; 미담쌀 백미20kg 1건과 가을햅쌀4kg 1건 → `food.grains.rice.white`; 병아리콩1.5kg 1건 → 기존 `food.grains.rice.chickpea`.
- 보류 5관측: 국산 서리태 반복 2건은 pass41에 서리태/검정콩 리프가 없어 보류, 렌틸콩 1건도 독립 리프 부재로 보류했다. 국내산 고구마 말랭이는 롯데 건과일 경로와 제목 품목형태가 충돌하여 보류했고, 명인부각 오리지널은 과일칩 경로와 제목 제품유형이 달라 원재료/부각 리프 근거가 부족해 보류했다.
- 안전장치: 서리태·렌틸콩을 병아리콩 리프로 대체하지 않았고, 고구마 말랭이를 건과일 리프로 강제하지 않았다. 가염/무염 피스타치오는 염도 속성 차이만으로 별도 리프를 만들지 않았다. 롯데 행사 문구가 unresolved인 백미/병아리콩은 분류 제안만 하고 행사조건 해소로 간주하지 않았다.
- 추가 점검: `pending/284` 감귤 2관측과 `pending/289` 배 2관측을 확인했다. 두 묶음은 분류 자체는 각각 `food.produce.fruit.citrus`, `food.produce.fruit.pear`로 이미 resolved 상태이며, 감귤은 `source_title_changed`, 배는 `count_range_unresolved` 때문에 pending이다. 따라서 classification-only 제안으로 해결된 것처럼 기록하지 않고 별도 비분류 사유 pending으로 남긴다.
- 실제 반영/검사: 이번 절 역시 GitHub 텍스트 읽기·쓰기만 사용했다. staging DB import/재구축, pytest, `verify_initial_stage.py`, 멱등 검사는 실행하지 않았다. pass41 적재/보류 수치에는 변화가 없다.
- 다음 재개점: 소형 과일/농산물 pending 중 `category_not_resolved_to_leaf`가 실제 원인인 묶음을 우선 골라 기존 리프로 제안한다. 이미 분류가 resolved이고 제목변경·수량범위·행사조건만 남은 묶음은 분류 완료와 pending 해소를 혼동하지 말고 별도로 표시한다.
