# 재개점 — pass48-final

## 현재 기준 (아래 이전 기록보다 우선)

- 기준 `.debug-artifacts/initial-catalog-20260914-pass48-final/checks-passed.json`. 6,010적재 / 3,186미해결. 과일청5종(한라봉청/자몽청/레몬청/생강레몬청/한라봉차), 관측10개 추가. 상품군/규격/판매페이지/매칭규칙 각5개, 리프/키워드 각1개 추가.
- 관련805검사·DB·멱등import·매칭119상품군/375hit·25miss/경로당1,200변형 통과. 기존 포함행/431결정/원본 및 복원DB 해시 보존. certificate는 기준 승격 전 state를 기록한다. 공개승인 없음.
- 홈플러스의 정확한 유자차 경로 두 형태에서 과일청이 확실하고 기존 유자차 이름검사가 거부하는 경우에만 해당 경로 후보 제거. 다른 유효한 후보는 유지한다. 실제 유자차/혼합세트/녹차/다른 하위 경로는 대체하지 않는 검사 추가. pass48 시도는 테스트 단계에서 실패해 DB출력/certificate 없음; 최종만 사용.
- 다음: 기존103 레몬즙 14T/480ML과 티앤에이드의 상품형태 및 수량 문제 검토. 이후 현재 unresolved에서 더 큰 공통 상품형태 묶음 선택. 104 과일청은 완료했으므로 아래 pass47의 다음 작업 안내는 과거 기록이다.

### pass47 이전 기록

- `.debug-artifacts/initial-catalog-20260914-pass47/checks-passed.json` 확인 완료. 6,000적재 / 3,196미해결. 새 상품군·규격·판매페이지·매칭규칙 각5개, 관측10개 추가. 삼계 조리재료3종 / 명확한 깔라만시 원액2종. 새 리프2개, 키워드2개. 기존 포함행과431결정 및 원본/복원DB 해시 보존.
- 관련787검사, DB 무결성·멱등import, 매칭119상품군/375hit·25miss/경로당1,200변형 통과. 공개승인 없음. certificate는 승격 전 catalog-state 해시를 기록하며, 검증 종료 후 기준 경로/count만 승격했다.
- 다음은 기존104 과일청5종의 잘못된 유자차 후보 충돌 해소. 현재 product-form fallback은 기존 후보가 있으면 적용되지 않는다. 유자차 이름 검증을 없애지 말고 좁은 원문/문맥 검증으로 처리한다. 103 레몬즙/티앤에이드 형태도 구분 필요. 누룽지 혼합 삼계재료와 단독 황기는 이번 규칙에서 보류했다.
- 이번 원문 영향 목록은 홈플러스 123591771 / 068979074 / 135314374 / 128545842 / 070028604. 전체 외주자료 복제 없이 로컬 bundle과 certificate의 추가10 ID를 사용한다. pass46-final 및 smoke는 이전 검증 기록이다.

## 모델 전환/컨텍스트 압축 후 먼저 읽기

- `AGENTS.md` → `docs/catalog-state.json` → `docs/CATALOG_RUNBOOK.md`. 다음 범위는 과일청차/과일농축액/삼계재료(주로 기존101·103·104). 새 전체순회나 외주문서 정리를 시작하지 않는다.
- `py tools/catalog_harness.py preflight` 후 `py tools/catalog_harness.py run --run-id initial-catalog-<날짜>-<새이름>`. 기존 prepare 명령을 직접 호출하지 않는다. 원본 경로/기존출력/해시변경/결정누락/이전행 유실은 실패 처리한다. 지시문/하네스는 OS sandbox가 아니다.
- 하네스 실증: `.debug-artifacts/initial-catalog-20260914-harness-smoke/checks-passed.json`. 관련779검사·DB·매칭119상품군/375hit·25miss/1,200변형 통과. 5,990/3,206 동일 재현, 추가ID0, 원본 불변. 이는 안전장치 검증이며 새 분류 실적이 아니다. 기준DB는 catalog-state의 pass46-final 유지.
- 모델은 사용자가 Sol low로 전환할 예정이며 이 작업에서 설정을 바꾸지 않았다. 낮은 추론에서도 동일 품질이 나온다고 가정하지 말고, 애매한 분류는 보류하고 검사 실패를 우회하지 않는다.

## 이전 분류 작업 실적

- 최신 안내는 [고정 입구](../handoff/README.md) → handoff/2026-09-14-pass46. GitHub 채팅 외주 반복 대신 로컬 공통 규칙 구현으로 전환했다.
- 새 사본 `.debug-artifacts/initial-catalog-20260914-pass46-final`: 5,990적재/3,206미해결. 이번18리프 정의, 78판매상품/135관측 새 적재. 분류해결89판매페이지/150관측. 초안 pass46은 사용금지.
- 원본 운영DB/복원 source-pending.sqlite SHA256 전후 동일, 기존 포함행/수동431결정 보존. 관련766테스트·DB·멱등import·매칭119상품군/375hit·25miss/1,200변형 통과. 공개/운영승인 없음.
- Luna는 읽기 전용 JSON 집계만 수행(322관측/95후보). 파일/DB/git/네트워크 접근 범위를 지시로 제한했고 주 에이전트가 원본 해시와 diff 확인. 절감률은 미측정. 다음에는 집계를 재사용하고 과일청/농축액/삼계재료 등 미해결 공통 형태를 처리한다.
- 이번에는 외주용 전체 자료를 복제하지 않았다. pass45 remaining에서 pass46 delta.json의135개ID를 제외하거나 로컬 최종 bundle의 unresolved를 사용한다. 새 taxonomy는 코드 기준. 기존 DB 사본은 보존했다.
- 원격0091915까지 후발 전체 제안파일을 보존했으나 의미/DB 검증은 하지 않았다. 이를 완료로 신뢰하거나 전량 승인하지 않는다.
- 관련 파일: initial_product_forms.py(입출력 없는18규칙), initial_taxonomy.py(기존 후보 없을 때만 적용), test_initial_product_forms.py, tools/verify_product_form_batch.py. 원본대신 복원된 수집전용DB로 새 출력폴더에만 빌드한다.
