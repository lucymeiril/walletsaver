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

## Google/Gemini secret setup

Provider 설정에는 실제 키가 아니라 alias만 저장한다. 예를 들어
`secret_alias`는 `GOOGLE_API_KEY`로 두고, 실제 값은 git에 커밋하지 않는
`.env` 파일에만 둔다.

1. `packages\ai-admin\backend\.env.example`을
   `packages\ai-admin\backend\.env`로 복사한다.
2. `.env`의 `GOOGLE_API_KEY` 값을 로컬 키로 바꾼다.

백엔드는 다음 순서로 alias를 해석한다.

1. `packages\ai-admin\backend\.env`
2. repository root `.env`
3. 현재 process environment

`.env`와 `.env.local`은 `.gitignore`에 포함되어 있으므로 실제 키를
커밋하지 않는다. API 응답과 provider 설정 DB에는 alias 이름만 저장된다.

## 주의

- `shared.core.contracts.ai_pipeline`만 import 하며, 다른 패키지의 내부
  모듈을 직접 참조하지 않는다.
- 비밀(secret)은 코드/DB/provider API 응답에 포함하지 않는다.
- Google GenAI는 `secret_alias`에 `GOOGLE_API_KEY` 같은 alias 이름만
  저장한다. 실제 키는 로컬 `.env`에만 둔다.
