# ai-admin

로컬 전용 AI 워커 관리 패널. 크롤러 원본 데이터를 AI provider로 라벨링/분류하고
사람 검수 큐에 제안으로 저장한다.

## 구성

- `backend/` — FastAPI 앱 (port 8003 기본)
  - `/health` — 단순 상태 점검
  - `/api/capabilities` — `shared.core.contracts.ai_pipeline`의
     `AIWorkerRole`, `ProviderKind` 목록을 노출
  - `/api/providers` — provider 설정. secret 값은 저장하지 않고 alias만 저장
  - `/api/providers/{provider_id}/models` — SDK 모델 목록 조회
  - `/api/ingest/raw-records/label` — raw record 저장 후 provider 라벨링 제안 생성
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

- `shared.core.contracts.ai_pipeline`만 import 하며, 다른 패키지의 내부
  모듈을 직접 참조하지 않는다.
- 비밀(secret)은 코드/DB/provider API 응답에 포함하지 않는다.
- Google GenAI는 `secret_alias`에 환경변수 이름만 저장한다. 예:

```powershell
$env:GOOGLE_API_KEY = "<local secret>"
```

이 값을 설정한 같은 터미널에서 백엔드를 실행해야 SDK 호출이 가능하다.
