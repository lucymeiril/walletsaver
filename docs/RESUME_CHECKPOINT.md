# 재개점 — pass46-final

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
