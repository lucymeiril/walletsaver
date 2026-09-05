# 분류·매칭 재개 — 2026-09-05

## 보존 및 검증 기준

- 직전 중단 작업은 `5b10c16`에 소스/테스트/문서로 커밋했다. 실제 데이터는 Git 제외이며 원본 `.walletsavior/admin.sqlite`는 읽기 전용이다.
- pass5의 21개 수동 병합군 runtime/export까지 검증 완료. 자세한 이전 결과는 `CLASSIFICATION_BATCH_20260903.md` 마지막 절.
- 원본 선택 행 해시는 `c4431eea85f0c1c2f54c202030daed8f8904d8c7b832491a126b8541590845e0`으로 유지된다.

## batch3 결정 저장 완료

- 좁은 제목 범위를 통해 38 listing/55관측을 전량 읽었다. 실제 원본의 전체 제목·브랜드·규격·경로·URL·관측 충돌을 대조했다.
- 9군/22 listing/31관측을 추가 채택: 햇반 단호박죽·전복내장죽, 양반 밤단팥죽·백합죽·진전복죽, 동원 살코기참치·자연산 진꽁치·저스트 노슈가 스위트콘, 비비고 한우사골곰탕.
- 세 상품군은 복수 variant: 밤단팥죽 420g/285g, 살코기참치 90g×4/135g×4/250g×1, 한우사골곰탕 500g×1/500g×18. 규격은 원본대로 유지하고 포장형태·영양 동일성을 추정하지 않는다.
- 살코기/고추참치/포도씨유 혼합팩은 가족 병합 제외. 할리스 로우슈거는 일반형과, 한우 사골곰탕은 일반/저나트륨형과 구분한다.
- `노슈가`는 제품명 식별자이며 당함량 검증을 뜻하지 않는다. 롯데 조건 미해석 프로모션은 검수 상태를 유지한다.
- 누적 결정: `.debug-artifacts/reviewed-initial-decisions-20260905-batch3.json`, 144 listing/30군.
- SHA-256: `40c7e87bac0ab6b4fbb7fa5c968bcfaeabe5db96422041cb171c1dc267fb9815`.
- 전체 채택 근거 `.debug-artifacts/matching-review-20260905-batch3-evidence.json`, 선택/작성 스크립트 `.debug-artifacts/review_matching_batch3.py`, 조사 스크립트 `.debug-artifacts/inspect_matching_batch3.py`.
- 검증 대상 출력은 `.debug-artifacts/initial-catalog-20260905-pass6/`. 아래 완료 기록이 없으면 최신 검증 기준은 여전히 pass5다.

## pass6 검증 완료

- 전체 9,196관측 accounting/FK/integrity/2회 import 멱등성 통과. 원본 선택 행 해시 유지.
- 상품군 2,233, variant 2,237, listing 2,268, offer 3,577, matching rule 2,212. 카테고리 242/키워드 174/원본 경로 매핑 222. 미분류·규격 보류 5,619(리프 미지정 5,516).
- 수동 병합 정확히 30군이며 DB의 실제 listing 구성과 누적 결정이 일치한다. 복수 variant 3군/7규격도 SQL로 확인했다.
- runtime/enrichment/export: 30군/92관측 중 원본 hit 88, 미활성군 등의 miss 4. 이름변경/신규 source ID/규격변경 276건이 각 경로에서 모두 miss. stage 파일 해시 불변.
- snapshot 검증본은 pending 699개 제외, active 2,878개/비활성군 600개 보존, FK 0. 운영 게시는 하지 않았다.
- 주의: 보고서의 `active_offer_observations`는 **pending이 아닌 상태** 건수다. 모두 공개 API에서 계산 가능한 가격이라는 의미는 아니다. 실제 밤단팥죽은 `buy_x_get_y`, 한우사골곰탕은 `checkout_discount`여서 현재 API의 비교 목록은 비어 있다. 이 둘의 조건부 총지출/최대혜택가 구현은 남은 작업이다.

## 실데이터 API에서 발견한 오류 수정

- 동원 살코기참치 250g 가격 4,390원에 `90g×4`가 표시되던 오류를 수정했다. 대표 규격은 best_offer의 variant에서 가져오며, source display가 없으면 검증된 용량·묶음으로 표시한다.
- 같은 listing의 이전 관측까지 현재 비교로 내보내던 동작을 수정했다. 대표가/price-compare는 최신 관측만 사용하고 가격이력은 보존한다. 최신 가격이 계산 불가능하면 과거 가격을 복원하지 않는다.
- 실제 참치 비교는 최신 2건: 250g 4,390원(100g당1,756원), 90g×4 9,490원(총360g,100g당2,636원). 이전 2건은 이력에 남는다.
- 근거/실행 파일: pass6의 `batch3-variant-api-check.json`, `.debug-artifacts/verify_batch3_variants.py`. 실제 FastAPI router → snapshot read-only 경로를 검사했다.
- 다중곱 `400g×3×2`에 대한 seed 검수 경계를 runtime/export에도 반영했다. 기존 잘못된 ×3 매칭 규칙이 있어도 miss가 된다. 단일 ×3 묶음은 계속 허용한다.
- 회귀 테스트 완료: 공개 API **71 passed**, crawler **283 passed / 1 live deselected**. 기존 deprecation 경고만 남는다. 앞선 DB 관리자 574 passed는 이번에 변경되지 않은 코드의 직전 결과다.
- pass6 bundle SHA-256: `51957070bc6df8c8d51f302dde98cfa261cdd6f7836a57f0ab560edf306e07a7`.
- active 2,878관측의 실제 의미: final_price 1,968 / was_now_price 266 / buy_x_get_y 629 / checkout_discount 15. 현재 API 비교 가능 형태는 앞의 2,234관측이며, listing별 최신 선택 이후 노출 수는 더 적다. 조건부 가격을 지원했다고 과장하지 않는다.
