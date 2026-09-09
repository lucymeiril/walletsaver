# 재개 체크포인트 — 2026-09-08

## 2026-09-10 재개 업데이트 — 최신 pass30 (공통 규격 수정)

- 이 절이 아래 과거 시작점보다 우선한다. 사용자 피드백: 매번 소량 분류 후 전체 검사/마무리하는 속도로는 완료가 너무 느림. 다음에는 여러 카테고리 묶음을 함께 검토하고 전체 검증은 묶음 끝에 실행할 것. 완료 시점/남은 호출 수를 근거 없이 약속하지 않는다.
- 최신 `.debug-artifacts/initial-catalog-20260910-pass30`, 결정 입력 기존 `reviewed-initial-decisions-20260908-remaining-exact.json` 431개 그대로. 원본 운영 DB 변경 없음.
- 공통 파서: `1,050g`을 50g으로 자르는 오류 수정. 한 중량 뒤 연속 곱셈 `350g×5×2pk`, `5g×30ct×2` 전체 곱셈 처리. seed는 모든 곱셈 기호가 단일 해석에 포함된 경우만 허용, 구조화 수량/총량/명시 bundle_count 충돌은 계속 보류. 새 연속 묶음 중 500개 초과는 도매 규격 검토 대상으로 보류(품질 경계이며 산술 오류라는 뜻 아님). 기존 단일 1000개 종이컵에는 이 경계를 적용하지 않는다.
- 원본 9,196관측 대조: 93관측의 규격/진단 변경, 58개 단위 문제 해소, 분류까지 있는 34개 신규 적재. 대량 연속묶음 6개 검토 유지. 천 단위 숫자로 잘못 수집된 기존 구조화 필드는 덮어쓰지 않으므로 아직 보류다.
- 코스트코 수집기 자체의 마지막 숫자 추출기를 공통 파서로 교체하고 bundle_count/display_unit을 수집 결과 변환까지 보존. 라이브 수집은 하지 않음.
- 누적 상품군 2,663 / variant 2,693 / listing 2,813 / offer 4,176 / 규칙 2,740. 카테고리 323 / 키워드 248 / 경로 매핑 237. 보류 5,020 / 미분류 4,835. active 3,437 / promotion pending 739. active가 반드시 단위가격 비교 가능하다는 뜻은 아님.
- 관리자 802 passed(기존 경고 460), shared 161 passed, Costco crawler 14 passed. 이전 연속 곱셈 무조건 보류 테스트 13개는 파서 기능 부족 계약이므로 전체 곱셈 일치/충돌별 계약으로 교체. 부분 해석/소수 개수/혼합 상품/잘못 수집된 중량/도매 규모 거부 대체 테스트 추가.
- 멱등 적재, stage/snapshot/runtime 검증 성공. 이전 포함 행/431결정 보존, 실제 API 잡채 350g×10=3500g, 순대 500g×6=3000g, 볶음밥 300g×14=4200g 및 단위가격 확인. API 검사 전후 DB 파일 해시 동일. snapshot은 보류 739개 제거/3,437개 유지, 운영 게시 없음.
- bundle SHA-256 `86b945449175706fc1e71b30bb608f677aac9fbb98d0a8b5244c749ca2661201`. 원본 SHA 기존 `c4431eea85f0c1c2f54c202030daed8f8904d8c7b832491a126b8541590845e0` 유지. 독립 감사 `.debug-artifacts/audit_units_pass30.py`, `.debug-artifacts/verify_units_pass30.py`.
- 다음: 분류 대기 4,835관측을 마트별 원본 경로로 묶어 처리량 큰 여러 카테고리 전량 검토. 기존 쉼표 수량 오류는 원본 제목·URL·표시 단위가격을 확인해 명시 검토 결정으로 정정 가능(무조건 제목 우선 자동 덮어쓰기 금지). 혼합세트/범위 중량은 계속 별도 검토. 초기 DB 전체 완성·운영 적용은 아직 남아 있다.

## 2026-09-10 재개 업데이트 — 최신 pass29

- 아래 모든 pass28/pass27 시작점보다 이 절을 우선한다. 최신 출력 `.debug-artifacts/initial-catalog-20260910-pass29`, 누적 결정 입력 `reviewed-initial-decisions-20260908-remaining-exact.json` 431건 유지.
- 코스트코 `고기` 미분류 74개 제목 전량 검토. 22개 정확한 제목에 음식 형태별 리프 부여, 15관측 추가 적재, 7개 규격 문제 보류. 그릴/숯/사료/혼합세트는 고기로 넣지 않았다. 새 리프: 조리잡채·양념육·훈제오리·순대(순대는 규격 보류라 출력에는 아직 없음).
- 누적 상품군 2,629 / variant 2,659 / listing 2,779 / offer 4,142 / 매칭 규칙 2,706. 카테고리 320 / 키워드 245 / 경로 매핑 237. 보류 5,054관측, 리프 미지정 4,835. active 3,403 / 프로모션 pending 739. active와 단위가격 비교 가능 여부는 다르다.
- 관리자 전체 796 passed, 기존 경고 460. 전체 원본 비교에서 위 22건 외 분류 변경 없음. 기존 포함 행과 431개 결정 보존. 두 번 적재 멱등성, 독립 stage/snapshot/runtime 검증 통과. snapshot은 보류 739개 제거/3,403개 유지, 운영 공개 아님.
- 원본 해시 기존 `c4431eea85f0c1c2f54c202030daed8f8904d8c7b832491a126b8541590845e0` 유지. bundle SHA-256 `9e152e6c4a6c9dea7042a31b056ad22e8c8c901c8cac817837422ed06a077a6f`. 운영 DB 변경·승인·공개 교체 없음.
- 독립 감사 스크립트 `.debug-artifacts/audit_meat_pass29.py`. 다음은 규격 보류 원인 조사 권장: `2,500g`, `1,060g`, `1,050g`, `1,150g`가 multiple_package_quantities로 보류되는 것이 천 단위 쉼표 파싱 문제인지 원본 필드 충돌인지 확인. `350g x 5 x 2pk`, `500gx3x2`, `300g x 7 x 2봉(4200g)`도 연속 묶음 처리 검토. 테스트를 완화하지 말고 전체 9,196관측 영향과 실제 총량을 대조한다. 이후 이마트 간편식 등 다음 카테고리 묶음으로 진행.

## 2026-09-10 재개 업데이트 — 최신 pass28

- 아래 pass27 이력보다 이 절을 우선한다. 최신 폴더는 `.debug-artifacts/initial-catalog-20260910-pass28`이며 누적 수동 결정 입력은 기존 `reviewed-initial-decisions-20260908-remaining-exact.json` 431건 그대로다.
- 코스트코 과일 미분류 69개 판매 페이지를 읽고 23관측에 리프를 추가했다. 16관측이 새 검토 DB에 포함되고 7관측은 수량 충돌로 보류됐다. 원본 9,196관측 전체 비교에서 다른 분류 변경은 없었다.
- 상품군 2,614 / variant 2,644 / listing 2,764 / offer 4,127 / 매칭 규칙 2,691. 카테고리 317 / 키워드 242 / 경로 매핑 237. 보류 5,069관측, 리프 미지정 4,857관측. active offer 3,388, pending 739. active라고 모두 단위가격 비교 가능한 것은 아니다.
- 관리자 전체 782 passed(기존 경고 460), 멱등성·snapshot·runtime 검증 통과. 실제 API 4상품에서 중량 확인: 라임·자몽은 단위가격 계산, 용과·망고의 checkout_discount는 비교가격/단위가격 없음이 현재 계약이다.
- bundle SHA-256 `df3eb1e50e9b615b7c894d62ca2379e58b6a457b8f773fd42d8bb43f3efa6ef1`. 원본 변경/운영 승인/공개 교체 없음.
- 다음 작업: 과일의 나머지 혼합세트·가공음료 또는 코스트코 고기 진열 전량 검토. `6kg 미만` 수박, `4입(각 2입)` 멜론 등 부정확한 규격은 이번에 포함하지 않았으며 수량 처리 자체의 보강은 남아 있다. 그린키위 한 제목은 기존 충돌 검사가 막아 계속 보류한다.
- 독립 검사: `.debug-artifacts/audit_fruit_pass28.py`, `.debug-artifacts/verify_fruit_pass28.py`. 기존 출력 폴더를 덮어쓰지 않는다.

할당량 중단 후 재개한 작업 기록이다. 최신은 pass27이며 상세 근거는 `CLASSIFICATION_BATCH_20260908.md` 마지막 절을 우선한다. 다음 작업은 이 문서와 `git status`를 함께 확인한다. 아래 초기 카탈로그는 **별도 검증 DB의 초안이며 운영 승인본이 아니다**. pass4 등 과거 수치는 이력으로 보존한다.

## 보존 상태

- 최신 후속 변경: 이마트 카테고리 요청 간격을 고정 360초에서 매 요청 시도마다 360~420초 무작위로 변경했다. 마지막 요청 시각 저장은 유지하며 재시작 후에도 최소 360초를 지킨다. 이미 경과한 시간은 차감한다. 관련 검사 44 passed / 1 skipped, 실제 사이트 수집은 하지 않았다.
- 사용자에게 설명한 완료 경계: 원본 백업과 별도 검토용 DB 구축은 했지만, 운영 관리자 DB의 초기 매칭·카테고리·키워드·상품 테이블을 모두 완성하여 적용한 것은 아니다. 최신 pass27도 검토용 초안이다. 남은 상품 분류를 완료한 뒤 기존 승인 절차로 운영 적용해야 한다.

- 브랜치: `cleanup/remove-legacy-ai-admin-coupling`.
- `b6ef0cc`: 이마트 360초 영속 대기 제한, 검토 목록의 50개 배치 잘림 수정.
- `a247fee`: 원본 행 accounting/offer 근거 보존, 키워드 UnifiedCategory FK, 테스트 DB 격리.
- `19b0aed`: 초기 카탈로그 seed/계층 분류/검토 workspace/CLI와 회귀 테스트.
- `eb1c5be`: 매칭 ID의 3개 형식 동기화 및 인증 테스트 계약 격리.
- `75f4bd0`: 원본 listing/이름/규격 재검증, export miss 보존, 복합포장·수량구간 검수.
- `62e8e2e`: 스냅샷의 검토 대기 offer/주간 링크 제외 및 로컬·원격 검증기 거부.
- 사용자가 push를 승인했고 완료한 체크포인트는 원격에 반영한다. 과거 고정 커밋 수나 해시에 의존하지 말고 재개 시 `git status`와 로컬/원격 HEAD를 다시 확인한다.
- 실제 원본: `.walletsavior/admin.sqlite`. 이 작업에서 운영 DB 마이그레이션·분류 적재·수집 승인·공개 snapshot 승인은 하지 않았다.
- 기존 백업: `.walletsavior/backups/pre-initial-catalog-20260903-044952/admin.sqlite` (17,711,104 bytes).
- 원본은 108개 pending ingestion, 9,196개 관측이다. Emart 1,802 / Homeplus 5,227 / Lotte 829 / Costco 1,338. 고유 listing은 6,543개다.
- 선택 원본 행의 SHA-256: `c4431eea85f0c1c2f54c202030daed8f8904d8c7b832491a126b8541590845e0`. 이는 SQLite 파일 자체 해시가 아니라 `read_pending_source`의 명시적 컬럼/정렬/직렬화 해시다.
- Homeplus 두 수집의 겹친 2,492개 listing은 삭제하지 않았다. 가격 변경 51개, 이름 변경 4개를 포함한다. 반복 관측은 시점별 offer로 보존해야 한다.
- `packages/db-admin/backend/walletguardian.db`는 예전 개발용 사본이다. 초기 DB 원본으로 사용하지 않는다. 예전 인증 테스트가 이 설정 DB를 사용하던 문제를 임시 DB fixture로 고쳤다.

## 완료한 코드와 검증

- 이마트: 요청 전 시각 기록, 재시작/동시 인스턴스/별도 이벤트 루프에서 360초 제한 유지. 403/429/취소/네트워크 실패도 동일 제한. 단일 프로세스의 스레드 간 잠금이며 분산 프로세스 잠금은 아니다. 라이브 수집은 하지 않았다.
- 크롤러 프런트: 18 tests passed, production build 성공(기존 chunk size 경고). 최신 백엔드 전체 결과는 아래 검증 기록을 따른다.
- 데이터 검토: API 500개 단위로 모든 배치를 가져온다. 501개 fixture에서 마지막 51페이지 접근 확인.
- 키워드 통합 카테고리 FK와 `capstone_keyword_ssot_v1` 마이그레이션 추가. 실제 운영 DB의 **별도 복사본**에서 upgrade → downgrade → upgrade, 전체 테이블 건수·원본 해시 보존, integrity/FK 검증 통과.
- 인증 테스트는 실제 사용자를 임시 DB에 생성한 `/me` 200과 없는 사용자 404를 별개 검증한다. 이전 조건부/vacuous assertion을 제거했다.
- importer: malformed rows, 중복 source key/variant/match key, 잘못된 variant 부모, 단위 미해석, 원본 accounting 누락 검증 보강. 별도 bundle 재수집도 offer의 이전 raw evidence를 합쳐 보존한다. timezone-aware 시각은 UTC 변환 후 저장한다.
- `initial_catalog_seed.py`: 순수 결정적 bundle 생성, 원본 행 전량 accounting, 보수적 규격/브랜드/그룹/키 충돌 검증. 명시적으로 검토한 그룹만 cross-mart 병합한다.
- `initial_taxonomy.py`: 새 4단계 리프 분류기. 원본 경로도 오염될 수 있어 이름과 충돌하면 보류. 유제품 관련 원본 268 listing 전량 검토 및 형태/속성/비식품 오분류 방지 보강. 상세 범위는 `INITIAL_TAXONOMY_AUDIT.md` 참조. 155 tests passed.
- `initial_catalog_workspace.py` + `tools/prepare_initial_catalog.py`: 원본 DB read-only → 전량 HTML/JSON 보고서 → 새로운 별도 DB 적재 2회 → 중복/무결성 검사. 운영 적용/승인 옵션은 없다.
- 명시 검토 문서는 `reviewed_draft`/검토자/원본 snapshot hash/각 listing의 모든 raw ID+hash를 요구한다. 상품군·리프·규격 결정은 반영할 수 있지만 가격·프로모션·공개 승인 상태는 주입할 수 없다.
- 실제 브라우저에서 대기 108개, 마지막 11페이지 `101–108` 표시를 확인했다. 실제 프런트 → 실제 crawler API → 실제 DB API 경로이며 운영 DB 복사본을 사용했다. 서버 lifespan/startup은 꺼서 스케줄·수집·seed를 실행하지 않았다. 이것은 Windows 전체 시스템 실행 인수 테스트를 대신하지 않는다. 테스트 서버 8001/8002/5174는 종료했고 승인·삭제 버튼은 누르지 않았다.
- 매칭 동기화 YAML/JSONL/CSV에 `public_product_id`/`public_variant_id` 보존. 구버전 파일의 누락 열은 기존 ID 유지, 명시 null만 초기화한다. 실제 FK 대상과 3개 형식 왕복 검증.
- 매칭 import API의 401은 환경 의존 fixture 문제였다. moderator 인증 계약을 유지하고 임시 DB+명시 인증으로 갱신했다. 무인증/잘못된 키 401, viewer/service 403, 인증 실패 시 DB 미접근도 검증했다.

## 생성된 로컬 증거 (모두 Git 제외)

- 과거 `.debug-artifacts/initial-catalog-20260903-pass4/`: `source-ingestions.json`, `catalog-bundle.json`, `classification-decisions.json`, `reviewed-decisions.json`, `product-group-candidates.json`, `review.html`, `staging.sqlite`, `summary.json`, `public-snapshot-rehearsal.sqlite`.
- pass4: 상품군 2,236 / variant 2,236 / listing 2,248 / offer 3,552 / 매칭 규칙 2,185. 카테고리 233(부모 포함), 키워드 166, 원본 경로 매핑 222. 9,196관측 중 3,552개 stage, 5,644개 보류이며 전량 accounting/evidence가 일치한다. stage는 공개 승인이라는 뜻이 아니다.
- stage의 2,854개 관측은 가격 비교 가능 형태이고, 698개는 조건 확인 전 pending_review다. 620개 상품군은 비교 가능한 active offer가 없어 비활성이다. pending offer에 단위가격이 없고 내부 카테고리 귀속/잘못된 variant 부모/레거시 상품·카테고리 적재가 0임을 별도 read-only SQL로 확인했다.
- 원본 mart별 stage 관측: Costco 119 / Emart 165 / Homeplus 2,708 / Lotte 560. 미분류·규격 불확실 관측도 삭제하지 않고 보류 목록에 포함했다. 매칭 키 충돌 29그룹은 자동 규칙 생성에서 제외했다.
- 동일 bundle 두 번 적재 후 모든 테이블 건수 불변, FK 0, integrity ok. `.debug-artifacts/verify_initial_stage.py initial-catalog-20260903-pass4`가 독립 SQL/evidence 검사다. `--snapshot`은 기존 파일을 덮어쓰지 않고 검증용 파일만 만든다.
- `public-snapshot-rehearsal.sqlite`는 운영 게시본이 아니다. root 독립 검증: 보류 698→0, 비교 가능한 2,854 offer 유지, 비활성 상품군 620 유지, FK 0, stage DB 파일 해시 불변.
- pass1/pass2/pass3는 이전 증거로 보존했고 더 이상 최신 분류 결과가 아니다. 기존 출력 폴더는 덮어쓰지 않는다.
- `.debug-artifacts/initial-taxonomy-review.json`: 리프별 전체 상품명/원본 경로, 보류 목록. 첫 제안 2,279 listing의 이름을 리프별로 검토했다. 이후 오염 방지 규칙 적용 결과 taxonomy-only 2,139 listing / 159 leaves. 모든 미분류 상품을 수동 분류한 것은 아니다.
- `.debug-artifacts/lotte-promotion-audit.json`: 829개 관측의 57개 문구 분석. 78개 일반표시가 후보, 나머지 751개 조건 확인 전 추가 혜택가 계산 금지. 숫자 파싱 성공과 혜택가 확정을 혼동하지 않는다.
- `.debug-artifacts/reviewed-product-group-proposals.json`: 가공식품 13군 / 26 listing / 39 원본 관측 제안. 그중 12군/24 listing을 독립 검토해 `.debug-artifacts/reviewed-initial-decisions-20260903.json`에 기록하고 pass3/pass4에 반영했다. 제목·규격을 확인한 명시적 병합이며 운영 승인과 다르다. 고기엔참소스는 적합 리프/출처 검토가 더 필요해 보류했다.
- 12군 검토 문서 SHA-256: `be289d0c6beca0e6411dd62e8e431d1de4a5ab3db764f9ac17bb2d8caa2ed939`. 전체 119개 cross-mart 자동 후보가 모두 병합된 것은 아니며 명시 검토 12군만 병합했다.
- 후속 과일/채소/두부 조사: `.debug-artifacts/produce-taxonomy-review.json`은 267 listing/273관측 전량을 보존한다. root가 그중 토마토14/사과7/두부8/순두부2/냉동과일16의 실제 원본과 전체 경로를 재대조했다. 원본 상품군 병합이나 규격 추정 없이 리프만 개별 결정했다.
- 누적 71 listing 검토 문서: `.debug-artifacts/reviewed-initial-decisions-20260903-produce.json`, SHA-256 `36f42528b04ae4ed7c7c771b9cfd8302781a0e382a81567850d439f1eb36d8f1`. 기존 24 listing/12군 결정을 포함한다. 단위 경계 수정 후 이 문서로 pass4를 생성했다. 리프 분류가 정해져도 규격 검증을 통과하지 못하면 offer는 생성하지 않는다.
- `.debug-artifacts/keyword-migration-rehearsal-20260903.json` 및 `.sqlite`: 운영 DB 복사본 마이그레이션/롤백 검증 증거.

## 다음 시작점

2026-09-09 최신은 **pass27/코스트코 치즈 진열 전량 감사와 붙은 묶음 표기 수정/누적 431개 수동 결정 유지**다. 상품군 2,598 / variant 2,628 / listing 2,748 / offer 4,111, 보류 5,085관측이다. 최신 결과는 `docs/CLASSIFICATION_BATCH_20260908.md` 마지막 절을 우선한다. 위 pass4 건수는 이전 기록이다. 조사·제안 파일을 승인본으로 취급하지 않는다.

1. 최신 전체 테스트 결과와 `git status`를 확인한다. 아래 완료한 단위/스냅샷 수정을 다시 시작하지 않는다.
2. 현재 pass27이 최신이다. 분류 코드/검토 문서 변경 후에는 새 출력 폴더에 workspace를 재생성한다. 누적 431개 결정을 유지하려면 아래 `--review-decisions`를 반드시 사용한다.
3. 5,085개 보류 중 4,880개가 리프 assignment 미지정이다. 같은 방식으로 다음 원본 카테고리의 이름과 오염 예외를 한 번에 검토한다. 코스트코 치즈 진열의 애견용·도구·선물세트·형태 불명 치즈는 억지로 흡수하지 않았다.
4. `가지 3입(봉)`과 `팽이버섯 3입(봉)`은 홈플러스가 1봉, 다른 마트가 3입으로 읽혀 단위가 충돌하므로 보류했다. 4~7입 복숭아도 확정 수량처럼 비교하지 않는다. 후속 단위 파서 묶음에서 고친 뒤 다시 검토한다.
5. 이마트/코스트코의 대부분은 넓은 원본 카테고리와 부족한 제목 근거로 미분류다. 누락을 감추기 위해 `기타`/부모 노드에 밀어넣지 말고 실제 상품 검토로 보완한다.
6. 코스트코 1,338개에는 상품별 시각이 없다. ingestion UTC 수신시각을 쓰되 `timestamp_source=ingestion_received_at`, `observed_time_precision=batch`로 표시한다. 실제 개별 수집시각처럼 표현하지 않는다.
7. 1+1/2+1/10+1처럼 구매·증정 수량이 명시된 655개는 실지출과 실수령량으로 단위가격을 계산한다. 숫자 조건이 없거나 미해석인 프로모션은 가격 원문을 보존하되 공개 비교에서 제외한다.
8. 검토 완료 이후에만 운영 DB 백업 → 마이그레이션/초기 적재 → 두 단계 승인 → snapshot 진행. 현재 542개 레거시 category/4,813개 결과의 최종 재사용 또는 폐기는 아직 실행하지 않았다.

재생성 명령 (저장소 루트, 출력 폴더는 새 이름):

```powershell
& 'C:\Users\user\AppData\Local\Programs\Python\Python313\python.exe' tools/prepare_initial_catalog.py --out .debug-artifacts/initial-catalog-NEXT --run-id initial-catalog-NEXT --review-decisions .debug-artifacts/reviewed-initial-decisions-20260908-remaining-exact.json
```

이 환경의 `py` launcher가 실패했으므로 검증된 Python313 경로를 사용했다. JSON/HTML/SQLite 및 크롤링 산출물은 Git에 넣지 않는다.

## 최신 검증 기록

- DB 관리자 전체: **774 passed**, 460 existing warnings, 44.30s (2026-09-09).
- 크롤러 전체: **283 passed**, 1 live deselected, 32.86s (2026-09-05).
- 공개 API 전체: **74 passed**, 25 existing warnings, 11.34s (2026-09-09). 실행에 비운영 `JWT_SECRET_KEY`를 지정했다.
- 공통 계산 전체: **159 passed**, 0 warnings, 0.57s (2026-09-09).
- 집중 테스트는 전체 테스트와 중복이므로 합산하지 않는다. 프런트는 변경하지 않았고, 공통 가격 계산 패키지는 증정행사 계산을 추가해 전체 검사했다.

## 이번 재개에서 마무리한 경계 수정

- 실제 4사 각 원본의 builder → import → runtime/export hit 및 이름 변경·규격 변경·신규 source listing miss 확인. `T` 티백 개수를 ton으로 취급하던 runtime 단위 처리, `ea`/`개입` 동치 14건, 복합포장/수량구간 검수 보강을 완료했다. 초기 단위 검사를 통과한 실제 8,304관측에서 builder/runtime 판정 차이는 0건이다.
- `7~10입`을 10입으로 확정하지 않는다. 총중량 `1.5kg(5~6입)`은 중량 기준을 유지한다. 김부각 `(5개입)×5`, 종이타월 `160매×12롤`, 용기+분말 혼합패키지의 단일 수량 추정도 금지한다.
- 공개 API는 이미 pending 가격을 제외한다. 양반 김밥김 비교에서 이마트 3984원만 표시되고 롯데 pending 2990원은 제외, pending-only 상품은 detail/compare/history/trust 모두 404를 실제 router에서 확인했다.
- 기존 snapshot serializer가 pending offer와 주간 링크를 복사하던 문제를 수정했다. pending_review offer와 그 링크만 제외하며 로컬/원격 validator도 섞인 파일을 거부한다. inactive 상품이나 다른 과거 상태는 그대로 보존한다. 운영 snapshot은 생성/교체하지 않았다.
- 남은 호환 경계: shared `build_match_key(...,14,"T")` 직접 compound 입력은 여전히 ton으로 해석한다. 이번 실제 T 원본 20행에는 `pack_qty/pack_unit`이 없고 `||14t` 등 저장 키를 사용해 이 변환이 일어나지 않았다. shared 매칭 키 호환 정책은 이번에 변경하지 않았으며 후속 compound 입력 계약 정리가 필요하다.
