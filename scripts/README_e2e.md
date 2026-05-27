# WalletSavior Round R E2E 스크립트

이 스크립트는 sandbox가 아니라 **사용자 PC**에서 headed Chromium으로 실행합니다.

## 1. 최초 1회 설치

```powershell
py -3 -m pip install playwright pyyaml
py -3 -m playwright install chromium
```

Playwright 의존성은 `packages\crawler-admin\requirements.txt`, `packages\website\backend\requirements.txt`에 이미 있습니다.

## 2. G3 실행

```powershell
py -3 scripts\g3_e2e_user_scenario.py
```

DB를 비우려면 반드시 명시 플래그를 붙입니다. 기본값은 절대 wipe하지 않습니다.

```powershell
py -3 scripts\g3_e2e_user_scenario.py --confirm-wipe
```

## 3. G4 실행

```powershell
py -3 scripts\g4_e2e_ai_cycle.py
```

`--use-llm`은 자리만 마련되어 있습니다. API 키가 없으면 rule-based mock 분류기로 자동 fallback합니다.

## 4. 결과 위치

- G3 캡쳐: `devlog\round-R\captures\G3-e2e-<timestamp>\`
- G3 리포트: `devlog\round-R\g3-e2e-report.md`
- G4 캡쳐: `devlog\round-R\captures\G4-e2e-<timestamp>\`
- G4 리포트: `devlog\round-R\g4-e2e-report.md`

## 5. 자동 기동 서버

스크립트가 비어 있는 포트에 dev server를 자동 기동하고 종료 시 cleanup합니다. 이미 떠 있는 포트는 재사용합니다.

- DB Admin backend `:8001`
- Crawler Admin backend `:8002`
- Web API backend `:8010` (web-frontend proxy용)
- Web frontend Vite `:5173`
- DB Admin frontend Vite `:5174`
- Crawler Admin frontend Vite `:5175`

## 6. 주의

- 라이브 4사 크롤은 사용자 PC 네트워크/브라우저 신뢰도에 따라 차단될 수 있습니다.
- 차단 시 G1 seeder의 fixture fallback으로 최소 시나리오를 계속 진행합니다.
- production DB로 보이는 `DATABASE_URL`에서는 wipe가 guard에 막힙니다.
