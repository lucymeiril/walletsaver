# 재개 체크포인트 — 2026-09-03

할당량 중단 후 2026-09-03 재개한 작업 기록이다. 다음 작업은 이 문서와 `git status`를 함께 확인한다. 아래 초기 카탈로그는 **별도 검증 DB의 초안이며 운영 승인본이 아니다**.

## 보존 상태

- 브랜치: `cleanup/remove-legacy-ai-admin-coupling`.
- `b6ef0cc`: 이마트 360초 영속 대기 제한, 검토 목록의 50개 배치 잘림 수정.
- `a247fee`: 원본 행 accounting/offer 근거 보존, 키워드 UnifiedCategory FK, 테스트 DB 격리.
- `19b0aed`: 초기 카탈로그 seed/계층 분류/검토 workspace/CLI와 회귀 테스트.
- `eb1c5be`: 매칭 ID의 3개 형식 동기화 및 인증 테스트 계약 격리.
- 위 커밋은 로컬 보존 상태다. 공개 원격 `lucymeiril/walletsaver`에 대한 push는 권한 검사에서 보류됐고 사용자에게 확인을 요청했다. 답변 전 재시도하거나 다른 도구로 우회하지 않는다.
- 실제 원본: `.walletsavior/admin.sqlite`. 이 작업에서 운영 DB 마이그레이션·분류 적재·수집 승인·공개 snapshot 승인은 하지 않았다.
- 기존 백업: `.walletsavior/backups/pre-initial-catalog-20260903-044952/admin.sqlite` (17,711,104 bytes).
- 원본은 108개 pending ingestion, 9,196개 관측이다. Emart 1,802 / Homeplus 5,227 / Lotte 829 / Costco 1,338. 고유 listing은 6,543개다.
- 선택 원본 행의 SHA-256: `c4431eea85f0c1c2f54c202030daed8f8904d8c7b832491a126b8541590845e0`. 이는 SQLite 파일 자체 해시가 아니라 `read_pending_source`의 명시적 컬럼/정렬/직렬화 해시다.
- Homeplus 두 수집의 겹친 2,492개 listing은 삭제하지 않았다. 가격 변경 51개, 이름 변경 4개를 포함한다. 반복 관측은 시점별 offer로 보존해야 한다.
- `packages/db-admin/backend/walletguardian.db`는 예전 개발용 사본이다. 초기 DB 원본으로 사용하지 않는다. 예전 인증 테스트가 이 설정 DB를 사용하던 문제를 임시 DB fixture로 고쳤다.

## 완료한 코드와 검증

- 이마트: 요청 전 시각 기록, 재시작/동시 인스턴스/별도 이벤트 루프에서 360초 제한 유지. 403/429/취소/네트워크 실패도 동일 제한. 단일 프로세스의 스레드 간 잠금이며 분산 프로세스 잠금은 아니다. 라이브 수집은 하지 않았다.
- 매칭 수정 전 크롤러 백엔드 기준: 231 passed, 1 live deselected. 크롤러 프런트: 18 tests passed, production build 성공(기존 chunk size 경고). 최신 백엔드 결과는 아래 최종 점검란을 따른다.
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

- 최신 `.debug-artifacts/initial-catalog-20260903-pass3/`: `source-ingestions.json`, `catalog-bundle.json`, `classification-decisions.json`, `reviewed-decisions.json`, `product-group-candidates.json`, `review.html`, `staging.sqlite`, `summary.json`.
- pass3: 상품군 2,213 / variant 2,213 / listing 2,225 / offer 3,533 / 매칭 규칙 2,164. 카테고리 233(부모 포함), 키워드 166, 원본 경로 매핑 227. 9,196관측 중 3,533개 stage, 5,663개 보류이며 전량 accounting/evidence가 일치한다. stage는 공개 승인이라는 뜻이 아니다.
- stage의 2,828개 관측은 가격 비교 가능 형태이고, 705개는 조건 확인 전 pending_review다. 627개 상품군은 비교 가능한 active offer가 없어 비활성이다. pending offer에 단위가격이 없고 내부 카테고리 귀속/잘못된 variant 부모/레거시 상품·카테고리 적재가 0임을 별도 read-only SQL로 확인했다.
- 동일 bundle 두 번 적재 후 모든 테이블 건수 불변, FK 0, integrity ok. `.debug-artifacts/verify_initial_stage.py`는 pass3 독립 SQL/evidence 검사 스크립트다.
- pass1/pass2는 이전 증거로 보존했고 더 이상 최신 분류 결과가 아니다. 기존 출력 폴더는 덮어쓰지 않는다.
- `.debug-artifacts/initial-taxonomy-review.json`: 리프별 전체 상품명/원본 경로, 보류 목록. 첫 제안 2,279 listing의 이름을 리프별로 검토했다. 이후 오염 방지 규칙 적용 결과 taxonomy-only 2,139 listing / 159 leaves. 모든 미분류 상품을 수동 분류한 것은 아니다.
- `.debug-artifacts/lotte-promotion-audit.json`: 829개 관측의 57개 문구 분석. 78개 일반표시가 후보, 나머지 751개 조건 확인 전 추가 혜택가 계산 금지. 숫자 파싱 성공과 혜택가 확정을 혼동하지 않는다.
- `.debug-artifacts/reviewed-product-group-proposals.json`: 가공식품 13군 / 26 listing / 39 원본 관측 제안. 그중 12군/24 listing을 독립 검토해 `.debug-artifacts/reviewed-initial-decisions-20260903.json`에 기록하고 pass3에만 반영했다. 제목·규격을 확인한 명시적 병합이며 운영 승인과 다르다. 고기엔참소스는 적합 리프/출처 검토가 더 필요해 보류했다.
- 12군 검토 문서 SHA-256: `be289d0c6beca0e6411dd62e8e431d1de4a5ab3db764f9ac17bb2d8caa2ed939`. 전체 119개 cross-mart 자동 후보가 모두 병합된 것은 아니며 명시 검토 12군만 병합했다.
- 후속 과일/채소/두부 조사: `.debug-artifacts/produce-taxonomy-review.json`은 267 listing/273관측 전량을 보존한다. root가 그중 토마토14/사과7/두부8/순두부2/냉동과일16의 실제 원본과 전체 경로를 재대조했다. 원본 상품군 병합이나 규격 추정 없이 리프만 개별 결정했다.
- 누적 71 listing 검토 문서: `.debug-artifacts/reviewed-initial-decisions-20260903-produce.json`, SHA-256 `36f42528b04ae4ed7c7c771b9cfd8302781a0e382a81567850d439f1eb36d8f1`. 기존 24 listing/12군 결정을 포함한다. **pass3에는 아직 후속 47개가 들어 있지 않다.** 단위 경계 수정 후 이 문서로 pass4를 생성한다.
- `.debug-artifacts/keyword-migration-rehearsal-20260903.json` 및 `.sqlite`: 운영 DB 복사본 마이그레이션/롤백 검증 증거.

## 다음 시작점

1. 최신 전체 테스트 결과와 `git status`를 확인한다. 크롤러 runtime/export의 원본 이름·규격·source listing 검증 수정은 전체 테스트/실제 4사 행 검증을 마무리해야 한다.
2. 현재 pass3가 최신이다. 분류 코드/검토 문서 변경 후에는 새 출력 폴더에 workspace를 재생성한다. 12군 명시 검토를 유지하려면 아래 `--review-decisions`를 반드시 사용한다.
3. 과일/채소/두부 등 다음 좁은 원본 범위를 전량 검토하고 분류를 보강한다. 5,663개 미해결 관측 대부분은 아직 카테고리 검토 전이다. 119개 후보의 상품군 병합도 후속 검토 대상이다.
4. 이마트/코스트코의 대부분은 넓은 원본 카테고리와 부족한 제목 근거로 미분류다. 누락을 감추기 위해 `기타`/부모 노드에 밀어넣지 말고 실제 상품 검토로 보완한다.
5. 코스트코 1,338개에는 상품별 시각이 없다. ingestion UTC 수신시각을 쓰되 `timestamp_source=ingestion_received_at`, `observed_time_precision=batch`로 표시한다. 실제 개별 수집시각처럼 표현하지 않는다.
6. 불명확한 프로모션은 가격 원문을 보존하되 공개 가격 비교/단위가격/주간 최저가 계산과 분리한다. 규격 미해석·명칭 변경·브랜드 충돌은 여전히 검수 대기다.
7. 검토 완료 이후에만 운영 DB 백업 → 마이그레이션/초기 적재 → 두 단계 승인 → snapshot 진행. 현재 542개 레거시 category/4,813개 결과의 최종 재사용 또는 폐기는 아직 실행하지 않았다.

재생성 명령 (저장소 루트, 출력 폴더는 새 이름):

```powershell
& 'C:\Users\user\AppData\Local\Programs\Python\Python313\python.exe' tools/prepare_initial_catalog.py --out .debug-artifacts/initial-catalog-NEXT --run-id initial-catalog-NEXT --review-decisions .debug-artifacts/reviewed-initial-decisions-20260903.json
```

이 환경의 `py` launcher가 실패했으므로 검증된 Python313 경로를 사용했다. JSON/HTML/SQLite 및 크롤링 산출물은 Git에 넣지 않는다.

## 최신 검증 기록

- DB 관리자 전체: **516 passed**, 460 existing datetime deprecation warnings, 38.22s.
- 분류/seed/workspace/sync 집중 검증: **252 passed**. 위 전체 테스트와 중복이므로 합산하지 않는다.
- 최초 runtime/export 수정 후 크롤러 전체: **259 passed**, 1 live deselected, 30.96s. 아래 추가 수정 전 결과다.

## 현재 진행 중인 작은 수정 (완료로 오인하지 말 것)

- 실제 4사 각 원본의 builder → import → runtime/export hit 및 신규 source listing miss 확인. `T` 티백 개수를 ton으로 취급하는 runtime 단위 처리, `ea`/`개입` 동치, 복합포장/수량구간 검수 보강이 후속 수정 중이다.
- `7~10입`을 10입으로 확정하지 않는다. 총중량 `1.5kg(5~6입)`은 중량 기준을 유지한다. 김부각 `(5개입)×5`, 종이타월 `160매×12롤`, 용기+분말 혼합패키지의 단일 수량 추정도 금지한다.
- 공개 API는 이미 pending 가격을 제외한다. 양반 김밥김 비교에서 이마트 3984원만 표시되고 롯데 pending 2990원은 제외, pending-only 상품은 detail/compare/history/trust 모두 404를 실제 router에서 확인했다.
- 다만 기존 snapshot serializer는 pending offer 705개와 관련 주간 링크까지 파일로 복사하고 양쪽 validator가 통과시켰다. pending_review offer와 그 링크만 제외하고 로컬/원격 validator 거부를 추가하는 중이다. inactive 상품이나 과거 상태를 일괄 삭제하지 않는다. 운영 snapshot은 생성/교체하지 않았다.
