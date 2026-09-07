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
