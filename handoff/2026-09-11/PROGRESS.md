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

## 2026-09-11 소형 신선과일 후속 제안 — pending 142 / 143 / 144 / 198 / 199 / 200 / 260 / 284 / 289 / 290 / 291 / 406 / 407

- 제안 저장: `proposals/fruit-small-142-143-198-199-200-260-284-289-290-291-406-407.json`. 이번 파일도 `status=proposal_only`, `baseline_pass=pass41`, `executed_tests=[]`이며 DB 입력 파일이 아니다.
- 분류 제안 26관측: 홈플러스 키위 3판매페이지의 반복관측 6건 → `food.produce.fruit.kiwi`; 국산포도 3판매페이지 6건과 수입포도 2판매페이지 4건 → `food.produce.fruit.grape`; 멜론 2판매페이지 4건 → `food.produce.fruit.melon`; 자몽 반복 2건 → `food.produce.fruit.grapefruit`; 아보카도 반복 2건 → `food.produce.fruit.avocado`; 황금향 1건 → `food.produce.fruit.citrus`; 골드망고 1건 → `food.produce.fruit.mango`.
- 규격/단위 분리: 키위 7-10입/7-12입, 아보카도 3-4입, 황금향 4-7입의 `count_range_unresolved`는 분류 제안 후에도 그대로 남긴다. 허니듀 멜론과 골드망고의 `unit_unresolved`도 분류와 별개로 남긴다. 제목에 개수 범위가 있는 거봉 역시 이번 작업에서 정규화 규격을 다시 쓰지 않았다.
- 분류 보류 5관측: 레몬 관련 3관측은 원본 경로가 레몬/라임이지만 pass41에는 라임 리프만 확인되어 레몬을 라임으로 오분류하지 않도록 보류했다. `고산지 허니글로우(베트남)` 반복 2관측은 바나나 진열이지만 제목에 바나나가 없고 기존 분류기도 `source_leaf_needs_name_corroboration`으로 판단하므로 경로만으로 확정하지 않았다.
- 비분류 pending 별도 기록: 감귤 2관측은 이미 `food.produce.fruit.citrus`로 분류됐으나 `source_title_changed`; 배 2관측과 복숭아 6관측은 각각 기존 배/복숭아 리프에 분류됐으나 `count_range_unresolved`; 델몬트 바나나 반복 2관측은 이미 바나나로 분류됐으나 `unit_unresolved`가 남아 있다. 이들은 분류 제안 숫자에 포함하지 않았다.
- 반복 수집 보존: 동일 홈플러스 `source_record_key`/판매페이지가 8월31일과 9월2일에 반복 수집된 경우 하나의 결정에 두 `raw_record_ids`를 묶어 기록했다. 서로 다른 판매페이지 상품군 병합은 요청하지 않았다.
- 실제 반영/검사: GitHub 텍스트 읽기·쓰기만 사용했다. staging DB import/재구축, pytest, `verify_initial_stage.py`, 멱등 import 검사는 실행하지 않았다. pass41의 5,280 적재/3,916 보류 수치는 변경되지 않았다.
- 다음 재개점: 소형 신선채소 묶음에서 기존 리프가 있는 대파·배추·무·양파·마늘·부추·버섯·샐러드채소 등을 먼저 검토한다. 세부 품종 리프가 없거나 처리형태(건조/데침/냉동)가 다른 상품은 기존 신선채소 리프에 억지로 합치지 않는다.

## 2026-09-11 소형 유제품·조미료 후속 제안 — pending 344 / 345 / 346 / 349 / 350 / 351 / 352 / 353 / 354 / 404 / 449 / 450

- 확인 범위: 위 12개 pending 묶음의 인덱스상 관측 전부를 읽었다. `pending/344` 서리태 반복 2관측은 앞선 `grains-nuts-small-139-282-344-400-405-443-446.json`에서도 이미 보류한 항목으로, 이번 파일에서는 재확인일 뿐 새 결정으로 세지 않는다.
- 제안 저장: `proposals/small-food-344-354-404-449-450.json`. 상태는 `proposal_only`, `baseline_pass=pass41`, `executed_tests=[]`이며 현재 import 입력이 아니다. 기존 pass41 DB·431개 review decision·applied decision은 수정하지 않았다.
- 기존 리프 제안 9관측: 비요뜨 쿠키앤크림 반복 2건 → `food.dairy.yogurt.topping`; 빙그레 바나나맛우유 미니 반복 2건 → `food.dairy.milk.banana`; 신영 페페로치노홀 반복 2건 → `food.seasonings.spices.whole_chili`; 폰타나 모데나 발사믹 식초 반복 2건 → `food.seasonings.baking.vinegar`; 벨큐브 고메스타일 1건 → 기존 벨큐브 125g 제품군 근거로 `food.dairy.cheese.portion` 후보. 서로 다른 판매페이지 상품군 병합은 요청하지 않았다.
- 기존 결정 보존: pass39 문서에서 성분 불명으로 미확정한 `CJ 백설 자일로스 갈색설탕 1KG` 반복 2건과 `simplus 뉴슈가 100G` 반복 2건은 새 근거가 없어 계속 보류했다. 특히 마트의 갈색설탕/흰설탕 경로만으로 강제 분류하지 않았다.
- 새 정책/리프 필요 보류: 서리태 반복 2건은 콩/서리태 리프 부재, 농심 혼다시 반복 2건은 어류계 다시 stock 리프 부재, 파스퇴르 단백질플러스 검은콩·검은깨맛/곡물맛 각 1건은 현재 맛별 우유 리프에 대응 항목 부재로 보류했다. `요즘 마시는 그릭요거트` 1건은 drink와 greek 축 충돌이라 정책 결정을 기다린다.
- 비분류 pending 별도 기록: 청정원 까르보나라 파스타소스 동일 판매페이지 2관측은 이미 `food.seasonings.sauces.pasta`로 분류되어 있고 pending 원인은 `source_title_changed`다. 분류 제안으로 pending이 해소됐다고 보지 않는다.
- 근거 교차확인: `initial_taxonomy.py`에 비요뜨 해당 정확 제목의 topping 규칙이 있으며, `initial_audited_seasonings.py`에는 신영 페페로치노홀 정확 제목이 `whole_chili`로 감사돼 있다. 발사믹 식초는 상품명 자체의 제품형태를 마트의 드레싱 혼합 진열보다 우선했다.
- 실제 반영/검사: GitHub 텍스트 읽기·쓰기만 사용했다. staging DB import/재구축, pytest, `verify_initial_stage.py`, 멱등 import 검사는 실행하지 않았다. pass41 5,280 적재/3,916 보류 수치는 변경하지 않았다.
- 다음 재개점: 이미 PROGRESS에 예고된 소형 신선채소 묶음을 계속 검토하되, 기존 리프가 없는 세부 채소/처리형태는 새 리프 후보로 별도 보류한다. 제안 파일을 합칠 때는 `raw_record_id` 기준으로 344 같은 재확인 중복을 제거한다.

## 2026-09-11 소형 신선·가공채소 후속 제안 — pending 244 / 245 / 246 / 247 / 248 / 371 / 372 / 374 / 375 / 380 / 382

- 확인 범위: 위 11개 pending 묶음의 조각 전부, 총 34관측을 읽었다. 반복 수집은 배열 인덱스가 바뀐 경우가 있어 각 관측의 실제 `raw_record_id`와 `source_record_key`를 대조해 같은 판매페이지 관측만 한 결정에 묶었다.
- 제안 저장: `proposals/vegetables-small-244-382.json`. 상태는 `proposal_only`, `baseline_pass=pass41`, `executed_tests=[]`이며 staging DB/import 입력이 아니다.
- 분류 제안 26관측: 건표고/건목이 반복 4건 → `food.produce.processed_vegetables.dried_mushroom`; 일반 무 반복 2건 → `food.produce.vegetables.radish`; 양송이 2판매페이지 반복 4건·맛타리 반복 2건·모둠버섯 2판매페이지 2건 → `food.produce.vegetables.mushroom`; 대파 2판매페이지 반복 4건 → `food.produce.vegetables.scallion`; 부추 반복 2건 → `food.produce.vegetables.chives`; 통배추 반복 2건 → `food.produce.vegetables.napa_cabbage`; 깐마늘 반복 2건 → `food.produce.vegetables.garlic`.
- 분류 보류 6관측: `고추채 절임` 반복 2건과 `명이 절임` 반복 2건은 마트의 데친나물/삶은나물 경로보다 제목의 절임 형태를 우선해 `blanched`에 넣지 않았다. `열무` 반복 2건은 일반 무와 다른 품목인데 pass41에 독립 열무 리프가 없어 보류했다.
- 비분류 pending 2관측: `양파 중(망)`은 이미 `food.produce.vegetables.onion`으로 confidence 0.97 분류됐지만 동일 판매페이지의 첫 관측은 1800g, 후속 관측은 1개로 정규화되어 `source_specification_changed`가 남아 있다. 분류 제안으로 pending을 해소했다고 보지 않는다.
- 안전장치: 배추/절임배추 혼합 경로의 `배추 (국산/통)`은 제목이 통배추라 신선 배추로 제안했고, 절임 제목 상품은 별도 보류했다. 깐대파·깐마늘은 박피/기본 손질만 있는 신선 원물로 보고 기존 신선 리프에 제안하되 규격이나 상품군 병합은 건드리지 않았다.
- 실제 반영/검사: GitHub 텍스트 읽기·쓰기만 사용했다. staging DB import/재구축, pytest, `verify_initial_stage.py`, 멱등 import 검사는 실행하지 않았다. pass41의 5,280 적재/3,916 보류 수치는 변경되지 않았다.
- 다음 재개점: 소형 채소 잔여 중 기존 리프가 있는 항목을 계속 확인하되, 생강·쪽파·브로콜리·샐러리·열무·절임채소처럼 현재 리프와 직접 일치하지 않는 품목은 신규 리프/정책 후보로 모아 한 번에 검토한다. 이미 분류가 resolved이고 규격/행사/제목변경만 pending인 항목은 제안 수에서 분리한다.

## 2026-09-11 채소 신규 리프 후보 수집 — pending 249 / 370 / 373 / 378 / 379 / 381 / 383 / 384 / 418

- 확인 범위: 위 9개 pending 묶음의 조각 전부, 총 19관측을 검토했다. 이 배치는 현재 리프에 억지로 넣는 대신 신규 taxonomy 후보를 한곳에 모으는 목적이다.
- 제안 저장: `proposals/vegetable-new-leaf-candidates-249-418.json`. `status=proposal_only`, `baseline_pass=pass41`, `executed_tests=[]`이며 `suggested_new_leaf`는 검토용 이름일 뿐 `initial_taxonomy.py`나 DB에 추가한 것이 아니다.
- 기존 리프 제안 1관측: `목이버섯 150G(팩)`은 건조 표기가 없는 신선 버섯으로 `food.produce.vegetables.mushroom`에 제안했다.
- 신규 리프 후보 18관측: 브로콜리 2판매페이지 반복 4건 → `food.produce.vegetables.broccoli`; 미나리 반복 2건 → `water_parsley`; 얼갈이 반복 2건 → `young_napa_cabbage`; 셀러리 반복 2건 → `celery`; 통 양상추 반복 2건 → `lettuce`; 생강 반복 2건 → `ginger`; 깐쪽파 반복 2건 → `spring_onion`; 생옥수수 반복 2건 → `corn` 후보로 기록했다.
- 정책 보류 이유: 얼갈이를 일반 통배추, 쪽파를 기존 표시명 대파인 `food.produce.vegetables.scallion`, 양상추를 쌈채소/샐러드채소로 자동 축소하지 않았다. 브로콜리 손질팩도 신선 브로콜리 품목으로 보고 냉동/가공채소 리프로 돌리지 않았다.
- 실제 반영/검사: taxonomy 코드, 기존 review decision, staging DB는 수정하지 않았다. GitHub 텍스트 읽기·쓰기 외 실행 도구가 없어 pytest/DB import/verify/멱등 검사는 실행하지 않았다. pass41 적재/보류 수치는 그대로다.
- 다음 재개점: 신규 리프 후보는 다른 마트의 동일 품목 관측이 있는지 먼저 모아 교차근거를 늘린 뒤 한 번에 taxonomy 설계를 검토한다. 그 전에는 `suggested_new_leaf`를 실존 리프처럼 사용하지 않는다. 이어서는 아직 손대지 않은 소형 채소/식품 묶음 중 기존 리프로 안전하게 제안 가능한 항목을 우선 처리한다.

## 2026-09-11 친환경 채소 제안 — pending 385 / 420 / 421 / 422

- 확인 범위: 위 4개 pending 묶음의 조각 전부, 총 5관측을 검토했다.
- 제안 저장: `proposals/organic-vegetables-385-422.json`. 상태는 `proposal_only`, `baseline_pass=pass41`, `executed_tests=[]`이며 DB/import 입력이 아니다.
- 분류 제안 5관측: 친환경 감자 → `food.produce.vegetables.potato`; 친환경 당근 → `food.produce.vegetables.carrot`; 친환경 오이맛고추 → `food.produce.vegetables.pepper`; 친환경 양파 → `food.produce.vegetables.onion`; 친환경 부추 → `food.produce.vegetables.chives`.
- 판단 원칙: 친환경/유기농은 판매·재배 속성이지 별도 상품 유형이 아니므로 제목에 명시된 실제 채소 품목의 기존 통합 리프를 사용한다. 마트의 `친환경근채류/과채류/김장채소/엽채류` 진열을 통합 taxonomy로 그대로 복사하지 않았다.
- 실제 반영/검사: GitHub 텍스트 읽기·쓰기만 사용했다. taxonomy 코드, 기존 review decision, staging DB는 수정하지 않았고 pytest/DB import/verify/멱등 검사는 실행하지 않았다.

## 2026-09-11 소형 음료 후속 제안 — pending 219 / 220 / 221 / 222 / 323 / 324 / 325 / 326 / 327

- 확인 범위: 위 9개 pending 묶음의 조각 전부, 총 26관측을 검토했다. 반복 수집은 동일 `source_record_key`만 같은 결정의 `raw_record_ids`에 묶었다.
- 제안 저장: `proposals/beverages-small-219-327.json`. 상태는 `proposal_only`, `baseline_pass=pass41`, `executed_tests=[]`이며 신규 리프 이름도 검토용 후보일 뿐 실제 taxonomy에는 추가하지 않았다.
- 기존 리프 제안 14관측: 델몬트 오렌지주스와 simplus NFC 착즙 오렌지주스 반복 4건, simplus NFC 착즙 사과주스 반복 2건 → `food.drinks.juice.fruit`; 게토레이 레몬/레몬제로 반복 4건 → `food.drinks.water_soda.sports`; 웰치소다 그레이프/웰치 제로 그레이프 반복 4건 → `food.drinks.water_soda.soda`.
- 신규 리프 후보 8관측: 진로 토닉워터 2판매페이지 반복 4건 → `food.drinks.water_soda.tonic` 후보; 비타500 100ml×10 반복 2건 → `food.drinks.water_soda.vitamin` 후보; 상쾌환 100ml×2 반복 2건 → `food.drinks.functional.hangover` 후보. 기존 sports/energy 리프로 억지 흡수하지 않았다.
- 원본 경로 충돌/제품형태 보류 4관측: 델몬트 알로에 로우슈거 반복 2건은 `천연야채음료` 경로지만 제목에 주스가 없어 vegetable juice 확정 보류; 델몬트 매실 로우슈거 반복 2건은 `pending/324`에서 감귤주스 경로에 잘못 걸렸고 다른 raw 진열에서는 매실/기타과일 계열로 나타나며 제목에도 주스가 없어 `fruit`와 `fruit_drink` 중 선택을 보류했다.
- 행사조건: 오렌지주스·알로에·매실 등에 있는 1+1은 분류와 별개로 기존 정규화 상태를 변경하지 않았다. 이번 proposal은 가격/행사 해소를 승인하지 않는다.
- 실제 반영/검사: GitHub 텍스트 읽기·쓰기만 사용했다. staging DB import/재구축, pytest, `verify_initial_stage.py`, 멱등 import는 실행하지 않았다. pass41의 5,280 적재/3,916 보류 수치는 변경되지 않았다.
- 다음 재개점: 음료 신규 후보(토닉·비타민·숙취)를 다른 마트 관측과 교차확인해 taxonomy 추가 여부를 한 번에 검토한다. 이어서는 아직 분류 원인이 남은 소형 식품 묶음을 처리하되 이미 classification resolved이고 행사/수량/제목변경만 남은 행은 별도로 구분한다.
