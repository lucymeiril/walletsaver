# ai-admin (skeleton)

로컬 전용 AI 워커 관리 패널. 현재는 스켈레톤 단계이며 실제 provider SDK
의존성과 워커 구현은 추후 단계에서 추가된다.

## 구성

- `backend/` — FastAPI 앱 (port 8003 기본)
  - `/health` — 단순 상태 점검
  - `/api/capabilities` — `shared.core.contracts.ai_pipeline`의
    `AIWorkerRole`, `ProviderKind` 목록을 노출
- `frontend/` — Vite + React 관리 대시보드 (port 5176 기본)

## 실행

```powershell
# 백엔드
cd packages\ai-admin\backend
$env:PYTHONPATH = "..\..\shared"
python -m uvicorn api.app:create_app --factory --port 8003 --host 127.0.0.1

# 프론트엔드
cd packages\ai-admin\frontend
npm install
npm run dev
```

## 테스트

```powershell
cd packages\ai-admin\backend
python -m pytest
```

## 주의

- 실제 AI provider SDK(예: google-generativeai, openai)는 아직 추가하지 않는다.
- `shared.core.contracts.ai_pipeline`만 import 하며, 다른 패키지의 내부
  모듈을 직접 참조하지 않는다.
- 비밀(secret)은 코드에 포함하지 않는다. `.env`는 추후 단계에서 도입한다.
