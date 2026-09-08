# 분류 재개 — 2026-09-08

## 곡물 개별 검토 저장 완료

- 시작점은 pass7 / 누적 199개 listing 결정 / 30개 수동 병합군이다. 원본은 `.walletsavior/admin.sqlite`이며 선택 행 해시 `c4431eea85f0c1c2f54c202030daed8f8904d8c7b832491a126b8541590845e0` 불변을 확인했다. 원본에는 쓰지 않았다.
- 곡물 제목 검색은 가공식품까지 139개를 찾으므로 그대로 분류하지 않았다. 곡물 판매 문맥의 26 listing 전체 관측과 별도 이맛쌀 20kg 1건을 읽고, 그중 21 listing/27관측을 개별 채택했다.
- 백미 7, 현미 4, 귀리 2, 찹쌀 1, 흑미 2, 병아리콩 2, 기장 1, 보리 2 listing이다. 홈플러스 7개 중 6개는 두 번 수집되었으며 27관측에 모두 보존한다.
- 찹쌀·흑미·보리·기장·병아리콩을 `식품 → 곡물·견과 → 쌀·잡곡 → 각 곡물`의 독립 리프로 추가했다. 키워드도 함께 생성한다. 새 자동 분류 규칙은 없으며 정확한 원본 ID와 모든 관측의 hash를 지정한 결정만 채택했다.
- 귀리쌀/기장쌀/보리쌀은 백미가 아니다. 찰현미는 현미다. 가루·떡·과자·차·보리새우는 이번 곡물 결정에서 제외한다. 서로 다른 판매 페이지의 상품군 병합이나 원본의 의심 브랜드(단일/귀리 등) 교정은 하지 않았다.
- 제외: 이마트 쿠폰 다운로드 문구 4개(`1000693432739`, `1000646184325`, `1000633806247`, `1000821271764`)는 가격 조건 추가 확인 필요. `1000827413348` 숙성 잡곡은 혼합 구성, `1000827413366` 돼지감자 현미는 가공/혼합 구분이 불명확해 보류. 할인혜택·건강효과를 추정하지 않는다.
- 누적 결정 `.debug-artifacts/reviewed-initial-decisions-20260908-grains.json`: 220 listing/기존 30군. SHA-256 `f585dec1517c535121dde80a84e1627e180896161a99683a36d400fcd97c44c4`.
- 전체 채택 근거 `.debug-artifacts/grain-review-20260908-evidence.json`, 작성 `.debug-artifacts/review_grains_20260908.py`, 좁은 범위 조사 `.debug-artifacts/inspect_grains_20260908.py`. 산출물은 Git 제외다.
- 분류 집중 검사 184 passed. 새 출력 `.debug-artifacts/initial-catalog-20260908-pass8/`를 검증할 예정이며 아래 완료 기록이 없으면 pass7이 마지막 검증본이다.

## pass8 검증 완료

- 상품군 2,304 / variant 2,308 / listing 2,339 / offer 3,654 / matching rule 2,283. 카테고리 252(부모 포함), 키워드 184, 원본 경로 매핑 228.
- 새 21 listing/27관측의 실제 DB 리프·독립 상품군·원본 payload/hash 전량 대조. 이전 199개 결정과 포함 관측 손실 0. 분류 코드 변경 전후 전체 9,196관측의 자동 판단이 완전히 같음을 독립 비교했다.
- 전량 accounting 9,196 = 포함 3,654 + 보류 5,542(리프 미지정 5,434). FK/integrity 및 두 번 import 멱등성 통과.
- 기존 30군 runtime/export: 92관측 88 hit/4 miss, 이름/규격/신규 ID 변경 276건은 각 경로에서 전부 miss. 검증용 snapshot pending 699개 제외, active 상태 2,955개/비활성 상품군 600개 유지. 운영 게시 없음.
- DB 관리자 전체 585 passed / 기존 경고 460개, 45.19초. 집중 검사 184개와 중복이므로 합산하지 않는다.
- bundle SHA-256 `5f2342e7e89db53e664ce0b3ae84e043cc86dbbe26ee50e57e543203b59873db`. 독립 근거는 pass8의 `grain-independent-check.json`, `reviewed-runtime-check.json`, `public-snapshot-rehearsal.sqlite`.

## 컵라면 9군 결정 저장 완료

- 홈플러스/롯데 18 listing/26관측 전량 검토. 삼양 불닭 큰컵 일반·까르보·치즈, 오뚜기 열라면 큰컵·진라면 큰컵 매운맛/순한맛·참깨라면 큰컵·컵누들 마라탕/매콤한맛을 각각 9군으로 묶었다.
- 제조사·제품선·맛·컵 형태·정확한 중량을 대조했다. 105g/110g뿐 아니라 컵누들 44.7g/37.8g 소수 중량도 보존한다. 봉지면/다른 맛/작은 컵과의 병합은 없다. 삼양/삼양식품 통일은 이 명시 검토 결정에만 적용한다.
- 롯데 9개 관측은 여전히 unknown promotion/pending이며, 같은 제품임을 확인했다고 가격을 공개 승인하지 않는다. 모든 원본 관측과 과거 가격은 유지한다.
- 누적 결정 `.debug-artifacts/reviewed-initial-decisions-20260908-cup-noodles.json`: 238 listing/39군. SHA-256 `d304856fb82c362c8d8a5f1cf4f4e358d42c9186074fdd6ce51bdc8e6dd2844f`.
- 전체 채택 근거 `.debug-artifacts/cup-noodle-review-20260908-evidence.json`, 작성 `.debug-artifacts/review_cup_noodles_20260908.py`, 조사 `.debug-artifacts/inspect_cup_noodles_20260908.py` (0/3/6 세 페이지 전부 읽음).
- 다음 검증 대상 `.debug-artifacts/initial-catalog-20260908-pass9/`. 아래 완료 기록 전에는 pass8이 마지막 검증본이다.

## pass9 검증 완료 — 최신

- bundle SHA-256 `da7c9abcef5a8868791c6cb456a218825da225b68a0f43b3c93b41012eedbe41`.
- 상품군 2,295 / variant 2,299 / listing 2,339 / offer 3,654 / matching rule 2,287. 상품군 9개 감소는 두 마트 상품 18개를 9군으로 병합한 결과이며 원본 소실이 아니다. 카테고리 252 / 키워드 184 / 원본 경로 매핑 228 유지.
- 이전 220개 결정과 전체 원본 포함/보류 집합 유지. 새 9군의 실제 DB 구성원 정확히 두 마트씩, 규격 1개씩 확인했다. 26개 원본 관측의 가격·행사유형·승인상태·전체 raw evidence가 pass8과 일치한다.
- 실제 공개 API router를 별도 검증용 DB에 연결해 9군의 최신 비교 각 1건(홈플러스), 총중량·100g당 가격을 확인했다. 롯데 pending 9건은 제외된다. 운영 서버나 브라우저를 실행한 검증은 아니다.
- runtime/export: 누적 39군/118관측 중 114 hit/4 miss. 이름변경·신규 ID·규격변경 354건은 각 경로에서 전부 miss. stage 파일 불변.
- snapshot 검증본 pending 699개 제외, active 상태 2,955개/비활성군 591개 유지. FK/integrity/accounting/2회 import 멱등성 통과. 운영 DB 적재·승인·공개 교체는 하지 않았다.
- 증거: pass9 `cup-noodle-independent-api-check.json`, `reviewed-runtime-check.json`, `public-snapshot-rehearsal.sqlite`. 독립 검사 스크립트의 시각 컬럼 오기(`observed_at`)를 실제 모델의 `crawled_at`으로 고친 뒤 재실행해 통과했다. 제품 코드를 검사에 맞춰 바꾸지 않았다.
- 다음 작업은 이 누적 문서로 이어간다. 기존 출력 폴더를 덮어쓰거나 대기 원본을 삭제하지 않는다. 다음 미검토 후보는 소스/조미료 또는 다른 가공식품 상품군이며, 불명확한 행사 문구 해석도 여전히 남아 있다.

```powershell
& 'C:\Users\user\AppData\Local\Programs\Python\Python313\python.exe' tools/prepare_initial_catalog.py --out .debug-artifacts/initial-catalog-NEXT --run-id initial-catalog-NEXT --review-decisions .debug-artifacts/reviewed-initial-decisions-20260908-cup-noodles.json
```

## 즉석카레·짜장 6군 결정 저장

- 홈플러스/롯데 12 listing/18관측을 읽고 오뚜기 3분 쇠고기짜장·일반짜장·쇠고기카레·카레 매운맛/순한맛/약간매운맛을 각각 6군으로 연결했다. 모두 200g 단품이며 서로 다른 맛/원료형을 합치지 않는다.
- 원본의 `즉석국(레토르트)`나 `짜장가루·짜장소스` 분류를 그대로 따르지 않고 실제 3분 제품선/상품명에 맞춰 우리 즉석카레·즉석짜장 리프를 지정했다. 이 원본 분류 전체에 적용하는 자동 규칙은 만들지 않는다. 롯데 6개 미해석 할인은 계속 검수 대기다.
- 전체 관측에서 제목·브랜드·규격·경로·URL·행사유형의 중복을 접어 읽었으며, 다른 값이 있는 관측은 별도로 표시했다. 가격 이력/원본 payload는 근거 파일에 전부 저장했다.
- 누적 문서 `.debug-artifacts/reviewed-initial-decisions-20260908-instant-curry.json`: 250 listing/45군, SHA-256 `82dc2dd2f0c72652c750281560cf6f6d8baf440fffc1f96ee68f55fb15f5770b`.
- 근거 `.debug-artifacts/instant-curry-review-20260908-evidence.json`, 조사/작성 `.debug-artifacts/review_instant_curry_20260908.py`.
- 검증 대상 `.debug-artifacts/initial-catalog-20260908-pass10/`. 아래 완료 기록이 없으면 마지막 검증본은 pass9다. 운영 DB 변경은 없다.

## pass10 검증 완료 — 최신 재개 지점

- 누적 250 listing 결정/45군. 상품군 2,297 / variant 2,301 / listing 2,347 / offer 3,668 / matching rule 2,289. 카테고리 252 / 키워드 184 / 원본 경로 매핑 228 유지.
- 이번 검토 18관측 중 기존 포함 4개 유지, 미분류 14개 신규 포함. 이전 238개 결정과 포함 관측 손실 0. 실제 DB의 리프·200g 단품 규격·전체 raw payload/hash·각 관측 상태를 독립 대조했다.
- 전체 9,196관측 = 포함 3,668 + 보류 5,528(리프 미지정 5,420). 원본 선택 행 해시 불변, FK/integrity 및 2회 import 멱등성 통과.
- 45군 runtime/export 136관측 중 132 hit/4 miss, 이름/규격/신규 ID 변경 408건은 각 경로에서 모두 miss. 새 6군의 원본 18관측 모두 hit이며 롯데 6가격은 계속 pending이다. 상품 연결 성공과 가격 공개 승인은 별개다.
- 검증용 snapshot pending 701개 제외, active 상태 2,967개/비활성군 587개 유지, stage 불변. 운영 DB/공개 데이터 변경 없음.
- bundle SHA-256 `1be89777dc66659b823f7732c6eaf8651d78e6013f4214c868d3b6810e939575`. 근거: pass10 `instant-curry-independent-check.json`, `reviewed-runtime-check.json`, `public-snapshot-rehearsal.sqlite`.
- 이번에는 제품 코드 변경 없이 데이터 결정만 추가했다. 전체 회귀를 중복 실행하지 않았으며 최신 DB 관리자 전체 검사 585 passed는 위 pass8 기록이다.
- 다음 입력은 `.debug-artifacts/reviewed-initial-decisions-20260908-instant-curry.json`. 출력 폴더는 새 이름을 사용한다. 차오차이 소스/완성 요리 후보는 ID 목록만 확인했으며 원본 개별 검토·병합은 아직 하지 않았다.

## 차오차이 검토 저장 — pass11 준비

- 원본 20 listing/28관측을 모두 읽었다. 이전 기록 정정: 차오차이 전체가 미검토였던 것은 아니며 직화간짜장소스/특제짜장소스의 이마트·홈플러스 4개는 초기 검토 때 이미 연결되어 있었다. 중복 결정 차단 검증이 이를 잡았고, 기존 250개 결정을 변경 없이 보존해 새 16개/20관측만 추가했다.
- 신규 병합 4군: 홍콩식 마파두부소스, 마라훠궈소스, 고추잡채소스, 130직화 간짜장 완성요리. 기존 직화간짜장소스 군에는 롯데 1개를 추가 연결했다. 기존 특제짜장소스 2개는 재확인만 했다.
- 완성 간짜장 180g과 소스 165g을 별도 군/리프로 유지. 마파두부 완성요리 180g과 소스 150g도 구분한다. 홍콩식/한국풍은 다른 제품이며, 마라샹궈/마랴샹궈 표기 차이는 오기로 추정하여 병합하지 않았다. 개별 7 listing은 리프만 결정했다.
- 새 4개 리프/키워드: 즉석마파두부, 마파두부소스, 고추잡채소스, 어향소스. 자동 분류 규칙은 추가하지 않았다. 집중 검사 190 passed.
- 누적 문서 `.debug-artifacts/reviewed-initial-decisions-20260908-chaochai.json`: 266 listing/49군. SHA-256 `be788b5c192114117775602463f223f15cfd39cc715552e2df7d9aeb3a3dc37a`.
- 근거 `.debug-artifacts/chaochai-review-20260908-evidence.json`, 조사/작성 `inspect_chaochai_20260908.py`/`review_chaochai_20260908.py` (같은 `.debug-artifacts` 폴더).
- 검증 대상 `.debug-artifacts/initial-catalog-20260908-pass11/`. 아래 완료 기록이 없으면 마지막 검증본은 pass10이다. 원본/운영 DB에는 쓰지 않았다.

## pass11 검증 완료 — 최신

- 상품군 2,304 / variant 2,308 / listing 2,359 / offer 3,684 / matching rule 2,298. 카테고리 256 / 키워드 188 / 원본 경로 매핑 230.
- 이전 250개 결정 그대로, 새 16 listing/20관측 중 기존 포함 4관측 유지·16관측 추가. 전체 원본 9,196 = 포함 3,684 + 보류 5,512(리프 미지정 5,404). 원본 선택 행 해시 불변.
- 실제 DB의 리프·수량·상품군 경계·전체 payload/hash·할인 상태 독립 대조. 완성요리/소스·홍콩식/한국풍·마라샹궈/마랴샹궈가 각각 다른 상품군임을 SQL로 확인했다. 분류 코드 전후 9,196개 자동 판단 동일.
- DB 관리자 전체 591 passed / 기존 경고 460개, 45.94초. 집중 190개는 중복이므로 합산하지 않는다. FK/integrity/두 번 import 멱등성 통과.
- 49군 runtime/export 148관측 중 144 hit/4 miss, 이름·규격·신규 ID 변경 444건은 각 경로에서 전부 miss. 신규 4군과 기존 간짜장소스 군 확장도 확인했다.
- snapshot 검증본 pending 708개 제외, active 상태 2,976개/비활성군 589개 유지. active 상태는 API에서 조건부 혜택가를 계산했다는 뜻이 아니다. 홈플러스 buy_x_get_y의 현재 API 비교 미지원은 여전히 남은 작업이다. 운영 적용/공개 없음.
- bundle SHA-256 `eebc309127af5496d7e2828b8211319296c371412b958bafb020e62cc03cb674`. pass11 `chaochai-independent-check.json`, `reviewed-runtime-check.json`, `public-snapshot-rehearsal.sqlite`에 증거 보존.
- 다음 입력은 `.debug-artifacts/reviewed-initial-decisions-20260908-chaochai.json`. 기존 pass11 폴더는 덮어쓰지 않는다. 차오차이 20개 조사를 다시 시작하지 않는다. 다음 후보는 남은 양념·식용유 상품군 또는 비식품 분류다.

## 조미료·식용유 6군과 규격 variant 검토 저장

- 기존 누적 266개 결정을 그대로 보존하고 15개 판매 페이지/24관측을 직접 검토했다. 먼저 같은 용량의 교차마트 12개를 pass12 중간본으로 묶은 뒤, 원본 전체에서 같은 제품명의 다른 용량 3개를 찾아 pass13에 함께 연결했다.
- 새 상품군 6개: 고기엔 참소스, 동원 참치액 진, 오뚜기 허니머스타드, 청정원 맛선생 멸치디포리 국물내기 한알, 해표 바삭요리유, 해표 카놀라유.
- 규격 variant를 갖는 3군: 고기엔 참소스 300g/800g, 동원 참치액 진 500g/900g, 해표 카놀라유 500ml/900ml. 참치액 순·프리미엄, 백설 참치액, 해표 바삭요리유·포도씨유는 이름이 비슷해도 병합하지 않았다.
- 기존 리프 `액젓·어류조미액`, `머스타드`, `육수`, `카놀라유`를 재사용했다. 정확한 리프가 없던 두 제품에는 `식품 → 양념·소스 → 조미소스 → 고기용소스`, `식품 → 양념·소스 → 식용유 → 요리유`를 추가했다. 두 리프는 검토 전용이라 자동 이름/원본경로 규칙은 비워 두었다.
- 고기엔 참소스의 이마트 브랜드 공란과 해표/사조해표 차이는 이 15개 판매 페이지의 명시적 상품군 결정 안에서만 통일했다. 전역 브랜드 alias로 확대하지 않았다. 요리유의 원료 종류와 육수 한 알의 개수도 원본에 없으므로 추정하지 않았다.
- 홈플러스의 1+1 `buy_x_get_y` 조건 공란과 롯데의 미해석 할인은 원문 그대로 보존했다. 상품 연결 성공을 할인 계산 또는 공개 가격 승인으로 바꾸지 않았다.
- 누적 문서 `.debug-artifacts/reviewed-initial-decisions-20260908-seasoning-variants.json`: 281개 결정/55개 수동 병합군, SHA-256 `499389ed9368209047347264e39d3943a7e5a976d384fe6eb60b089b52291666`.
- 근거는 `seasoning-review-20260908-evidence.json`, `seasoning-variant-review-20260908-evidence.json`, 조사/작성 스크립트는 같은 `.debug-artifacts` 폴더에 보존했다. 모두 Git 제외이며 운영 DB에는 쓰지 않았다.

## pass13 검증 완료 — 최신

- bundle SHA-256 `dc547ad4a731b6ac65a0a1b7a4fc8e0b73ce725d382cb980a2652731b6ffdf48`.
- 상품군 2,303 / variant 2,310 / listing 2,367 / offer 3,698 / matching rule 2,306. 카테고리 258 / 키워드 190 / 원본 경로 매핑 231.
- 전체 9,196관측 = 포함 3,698 + 보류 5,498(리프 미지정 5,390). 새로 검토한 24관측 중 기존 자동 포함 10개는 유지했고, 보류 14개를 새로 포함했다. 이전 266개 결정과 기존 포함 관측의 손실은 0이며 선택 원본 해시도 불변이다.
- 실제 DB에서 6군/15개 판매 페이지/24관측의 제목·규격·리프·상품군·전체 raw payload/hash·행사 상태를 독립 대조했다. 3개 다중 규격군의 variant 경계와 카놀라유/바삭요리유 및 동원/백설 참치액의 상품군 분리를 확인했다.
- 새 검토 전용 리프를 넣기 전후 실제 9,196관측의 자동 분류 결과는 모두 동일하다. FK/integrity, 동일 bundle 2회 import 멱등성, 원본 DB 미변경도 통과했다.
- 실제 runtime/export는 누적 55군/172관측 중 168 hit/4 miss. 이름·규격·신규 ID 변경은 각 경로 516건 모두 miss였다.
- 실제 공개 API router를 검증용 snapshot에 연결했다. 참소스의 300g 2,590원 결과는 총량 300g/100g당 863원과 같은 variant로 반환됐고 800g 정보가 섞이지 않았다. 1+1은 조건 계산 전 비교가가 없으며 롯데 pending offer도 공개 응답에서 제외됐다.
- 검증용 snapshot은 pending 709개를 제거하고 active 상태 2,989개 및 비활성 상품군 585개를 유지했다. stage 파일은 불변이고 운영 게시/승인은 하지 않았다.
- DB 관리자 전체 **594 passed**, 기존 경고 460개. 집중 분류 검사 193개는 전체와 중복이므로 합산하지 않는다.
- 독립 증거: pass13의 `seasoning-variant-independent-check.json`, `seasoning-public-api-check.json`, `reviewed-runtime-check.json`, `public-snapshot-rehearsal.sqlite`.
- 다음 입력은 `.debug-artifacts/reviewed-initial-decisions-20260908-seasoning-variants.json`. pass12/pass13 폴더를 덮어쓰지 않으며 다음에는 아직 미검토인 가공식품 또는 비식품 범위를 새 체크포인트로 고른다.

## 과자 20군과 규격 variant 검토 저장

- 기존 누적 281개 결정을 그대로 보존하고 과자 58개 판매 페이지를 전량 살폈다. 그중 기본 제품과 맛이 다른 `콘칩 초당옥수수`, `맛동산 밤라떼맛` 2개는 합치지 않았고, 나머지 56개 판매 페이지/89관측을 20개 상품군으로 연결했다.
- 새 상품군은 꼬깔콘 2종, 도리토스, 빠다코코낫, 치토스 2종, 고소미, 눈을감자, 썬, 오징어땅콩, 초코송이, 치즈뿌린 치킨팝, 못말리는 신짱, 죠리퐁, 카라멜콘메이플, 콘칩, THE빠새, 구운양파, 맛동산, 허니버터칩이다. 서로 다른 맛은 이름이 비슷해도 별도 상품으로 남겼다.
- 20군 안에서 용량·묶음이 다른 규격을 36개 variant로 분리했다. 특히 눈을감자 `56g×12=672g`, 오징어땅콩 `98g×3=294g`, 허니버터칩 `40g×4=160g`의 총량과 단위가격을 실제 공개 API 응답까지 대조했다.
- 기존 리프를 우선 재사용했다. 정확한 리프가 없던 죠리퐁에는 `식품 → 과자·간식 → 스낵 → 곡물스낵`을 추가했으며, 이 리프는 검토 전용이라 자동 이름/원본경로 규칙을 비워 두었다. 빠다코코낫은 비스킷, 고소미는 크래커로 검토 결정하고 마트별 원본 카테고리 차이는 근거에 보존했다.
- 상품 연결과 행사 가격 계산을 분리했다. 조건이 불명확한 1+1과 할인 문구는 `pending_review`로 유지해 단위가격·최저가 비교에 넣지 않았다.
- 누적 문서 `.debug-artifacts/reviewed-initial-decisions-20260908-snacks.json`: 337개 결정/75개 수동 병합군, SHA-256 `bf791fa82c1ce42a537161040fc3cb915bb67228d78d0800d74e4fa9e343cef2`.
- 근거는 `snack-review-20260908-evidence.json`, 독립 검증은 pass14의 `snack-independent-api-check.json`에 보존했다. 모두 Git 제외이며 운영 DB에는 쓰지 않았다.

## pass14 검증 완료 — 최신

- bundle SHA-256 `bbb766ea728009afe16692389734c115a6ee5f5c0bfa2e3221e8e60edb997122`.
- 상품군 2,286 / variant 2,309 / listing 2,386 / offer 3,719 / matching rule 2,317. 카테고리 259 / 키워드 191 / 원본 경로 매핑 230.
- 전체 9,196관측 = 포함 3,719 + 보류 5,477(리프 미지정 5,369). 이번 89관측 중 기존 자동 포함 68개는 유지했고 보류 21개를 새로 포함했다. 이전 281개 결정의 손실은 0이며 선택 원본 해시도 불변이다.
- 실제 DB에서 20군/56개 판매 페이지/89관측의 제목·브랜드·규격·리프·상품군·전체 raw payload/hash·행사 상태를 독립 대조했다. 제외한 다른 맛 2개가 별도 상품으로 남는 것도 확인했다.
- 새 검토 전용 리프를 넣기 전후 실제 9,196관측의 자동 분류 결과는 모두 동일하다. FK/integrity, 동일 bundle 2회 import 멱등성, 원본 DB 미변경도 통과했다.
- 실제 runtime/export는 누적 75군/261관측 중 257 hit/4 miss. 이름·규격·신규 ID 변경은 각 경로 783건 모두 miss였다.
- 실제 공개 API router를 검증용 snapshot에 연결해 20군 전부를 조회했다. variant별 총량·단위가격이 맞고 다른 규격이 섞이지 않았으며, 조건 불명확 offer는 공개 비교에서 제외됐다.
- 검증용 snapshot은 pending 711개를 제거하고 active 상태 3,008개 및 비활성 상품군 577개를 유지했다. stage 파일은 불변이고 운영 게시/승인은 하지 않았다.
- DB 관리자 전체 **596 passed**, 기존 경고 460개. 집중 분류 검사 195개는 전체와 중복이므로 합산하지 않는다.
- 다음 입력은 `.debug-artifacts/reviewed-initial-decisions-20260908-snacks.json`. pass14 폴더를 덮어쓰지 않으며 과자 20군 조사는 다시 하지 않는다. 다음에는 아직 미검토인 가공식품 또는 비식품 범위를 새 체크포인트로 고른다.

## 햇반컵반 4군 검토 및 pass15 검증 완료 — 최신

- 미역국밥 167g, 스팸김치덮밥 251g, 스팸마요덮밥 219g, 치킨마요덮밥 233g을 각각 별도 상품군으로 두고 홈플러스·롯데의 같은 맛/같은 중량만 연결했다. 총 8개 판매 페이지/12관측이며 다른 컵반 맛으로 규칙을 넓히지 않았다.
- 기존 자동 포함 4관측을 유지하고 홈플러스의 보류 8관측을 새로 stage했다. 12관측 모두 행사 조건을 해석할 수 없어 `pending_review`이고, 검증용 공개 snapshot 및 상품 상세·가격 비교 API에서는 전부 숨겨지는 것을 확인했다.
- 누적 문서 `.debug-artifacts/reviewed-initial-decisions-20260908-cupban.json`: 345개 결정/79개 수동 병합군, SHA-256 `ef846b06cfcbd2203a01a5ddd7ae935e99b36ccfaccfb10c2a6a589ed1bdbd4d`.
- bundle SHA-256 `66ba017345aac407355632569f2740cb8989230646aa3e68561788065805eb21`. 상품군 2,286 / variant 2,309 / listing 2,390 / offer 3,727 / matching rule 2,321.
- 전체 9,196관측 = 포함 3,727 + 보류 5,469(리프 미지정 5,361). pending 719개를 제외한 active offer는 3,008개이고 비활성 상품군 577개를 유지했다.
- 전체 accounting/evidence, FK/integrity, 동일 bundle 2회 import, snapshot 필터, 원본·stage·snapshot 파일 불변을 확인했다. 독립 근거는 pass15의 `cupban-independent-api-check.json`이다. 운영 게시/승인은 하지 않았다.
- DB 관리자 전체 결과는 **596 passed**로 유지된다. 다음 입력은 `.debug-artifacts/reviewed-initial-decisions-20260908-cupban.json`이며 pass15 폴더와 컵반 4군 조사를 다시 시작하지 않는다.
