# Round R G3/G4 E2E Scripts Report

## 생성 파일

- `scripts\_e2e_common.py` — dev server spawn/readiness, atexit cleanup, screenshot capture, visible assertion, markdown report helper.
- `scripts\g3_e2e_user_scenario.py` — G3 4사 크롤 → 자동분류 → `/compare` drilldown/modal headed Playwright 시나리오.
- `scripts\g4_e2e_ai_cycle.py` — G4 외부 AI Export → rule-based mock 산출물 3종 → Import → DB trust 확인 → web 노출 시나리오.
- `scripts\README_e2e.md` — 사용자 PC 실행 순서, Playwright 설치, DB wipe 주의사항, 결과 위치.

## 사용자 실행 명령

```powershell
py -3 scripts\g3_e2e_user_scenario.py
py -3 scripts\g4_e2e_ai_cycle.py
```

선택 DB wipe는 절대 자동 실행하지 않으며 아래처럼 명시해야 합니다.

```powershell
py -3 scripts\g3_e2e_user_scenario.py --confirm-wipe
```

## 자동 기동/정리

스크립트는 비어 있는 포트만 자동 기동하고, 자신이 띄운 프로세스만 종료합니다.

- db-admin backend `:8001`
- crawler-admin backend `:8002`
- web-api backend `:8010` (`web-frontend` proxy 필요)
- web-frontend Vite `:5173`
- db-admin frontend Vite `:5174`
- crawler-admin frontend Vite `:5175`

## 결과 위치

- G3 screenshots: `devlog\round-R\captures\G3-e2e-<timestamp>\`
- G3 report: `devlog\round-R\g3-e2e-report.md`
- G4 screenshots: `devlog\round-R\captures\G4-e2e-<timestamp>\`
- G4 report: `devlog\round-R\g4-e2e-report.md`

## 알려진 한계

- 이 sandbox는 4사 라이브 HTTP와 headed browser 표시가 막혀 있으므로 라이브 E2E는 실행하지 않았습니다.
- 사용자 PC에서 4사 anti-bot 차단이 발생하면 `round_r_g1_seed.py --fixture-fallback` 경로로 최소 검증을 계속합니다.
- 현재 db-admin frontend에는 별도 “자동분류 실행” 페이지가 없어, G3 스크립트는 backend CLI/API 실행 결과를 db-admin 캡쳐용 HTML 리포트로 렌더링합니다.
- G4 `--use-llm`은 안내용 플래그입니다. 기본은 deterministic rule-based mock이며 실제 LLM 키/adapter 없으면 skip/fallback합니다.

## 컴파일 확인

```powershell
py -3 -c "import ast; ast.parse(open('scripts\\g3_e2e_user_scenario.py', encoding='utf-8').read())"
py -3 -c "import ast; ast.parse(open('scripts\\g4_e2e_ai_cycle.py', encoding='utf-8').read())"
```
