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

Provider별 LIVE 호출 보호값은 `/api/providers`와 frontend의 Provider 설정에서
조정한다. 기본값은 기존 안전 동작과 동일하게 최소 호출 간격 12초, 분당 5회,
일일 300회, provider transient 오류 재시도 3회(10~60초 backoff)다.

## Live model validation

Operator-facing live validation has three separate entry points:

- `tools\one_shot_db_build_orchestrator.py` defaults to a fixture/stub/dry-run
  readiness and orchestration artifact. With explicit crawler-batch and live
  labeling flags, it delegates bounded real labeling to
  `tools\run_live_model_batch.py`; it still does not crawl every source or
  mutate DB-admin by default.
- `tools\live_validation_harness_v2.py` is the current minimal real-model
  batch validation harness.
- `services.aistudio_live_smoke` is a one-call AIStudio smoke check. It only
  consumes provider quota when `WALLET_SAVIOR_LIVE_AI_SMOKE=1` is set.

Safe smoke commands from `packages\ai-admin\backend`:

```powershell
cd packages\ai-admin\backend

# Default: checks readiness and skips the live provider call; no quota consumed.
python -m services.aistudio_live_smoke

# Opt in to one AIStudio call; consumes quota only when the key alias resolves.
$env:WALLET_SAVIOR_LIVE_AI_SMOKE = "1"
python -m services.aistudio_live_smoke
Remove-Item Env:\WALLET_SAVIOR_LIVE_AI_SMOKE
```

Minimal batch validation from the repository root:

```powershell
python tools\run_live_model_batch.py
```

The wrapper first preflights the fixture/input split count without calling the
provider, checks that ai-admin backend `/health` responds on port 8003, then
forwards to `tools\live_validation_harness_v2.py` with fixture input,
`--max-items 2`, `--max-provider-calls 1`, provider id
`google-gemini31-live-matrix`, model `gemini-3.1-flash-lite-preview`,
`--ai-batch-size 20`, and `--ai-batch-prompt-chars 8000`. The AI batch size is
operator-configurable but bounded by both row count and prompt characters, so
large/ambiguous rows still split before unsafe prompt growth. This is a
higher-quota configured default, not proof that the live provider is available.
If that provider is not configured in your local `ai_control.db`, safely list
configured non-secret provider fields (for example, provider id and
`default_model`, never `secret_alias` values) and choose a higher-quota
configured Gemma 3, Gemma 4, or Gemini 3.1 Flash Lite model with
`--provider-id` and `--provider-model`. Do not use `gemini-2.5-flash-lite` for
repeated validation batches. A passing `/health` only proves a process
responded; restart ai-admin before using this wrapper to validate backend code
changes.

To keep both Gemini 3.1 Flash Lite and Gemma 4 configured without unsafe
switching, use an explicit finite pool and a matching provider-call budget:

```powershell
python tools\run_live_model_batch.py `
  --provider-pool "google-gemini31-live-matrix=gemini-3.1-flash-lite-preview,google-gemma4-live=gemma-4-26b-a4b-it" `
  --max-provider-calls 2
```

The wrapper tries at most the configured pool entries, sleeps at least 10
seconds between failed choices, and still blocks before any live call if the
total possible attempts would exceed `--max-provider-calls`. A timeout/deadline
from Gemma 4 is treated as retryable Google/server slowness, not as evidence
that Gemma 4 should be removed. By contrast, a `NOT_FOUND`/404 model error means
that exact model string is unavailable for the provider/key and should be
corrected before retrying that choice. If the daily quota is exhausted, add
another configured provider/API-key alias or wait for reset rather than
increasing the loop.

Keep secret values in `.env` or process environment only; never paste API
keys, tokens, or credentials into commands, issue comments, tickets, or logs.
DB-admin mutation is not part of the minimal batch command. It requires the
extra explicit `--allow-db-admin-submit` flag on the wrapper and should be used
only when the operator intends to write through DB-admin.

Operator-triggered crawler artifact path from the repository root:

```powershell
python tools\one_shot_db_build_orchestrator.py `
  --crawler-batch-json .walletsavior-crawler\latest-batch.json `
  --allow-live-ai-provider `
  --allow-live-ai-labeling `
  --provider-id google-gemini31-live-matrix `
  --provider-model gemini-3.1-flash-lite-preview `
  --live-batch-max-items 300 `
  --retain-all-crawler-input `
  --live-batch-max-provider-calls 1
```

This consumes the crawler artifact and runs the live model batch only after both
live AI flags are present. `--retain-all-crawler-input` forwards
`--retain-all-input` to the batch wrapper so all readable crawler artifact rows
(for example 300 input rows) remain in classification/anomaly artifacts rather
than being truncated to `--live-batch-max-items`. Remove that flag when you want
the default bounded dry-run-style selection. The one-shot artifact records the
delegated wrapper command, provider-call counts, and pending/complete DB-admin
phase; it does not claim the orchestrator performed a live all-source crawler
build. To intentionally submit/final-approve through DB-admin, add
`--allow-db-mutation`; without that flag the wrapper does not forward
`--allow-db-admin-submit`.

Live provider calls are rate-limited inside ai-admin before each real provider
request: at least 12 seconds between live calls, no more than 5 calls per
minute, and no more than 300 calls per provider per day. Transient provider
failures retry up to three times with at least a 10-second retry delay. If a
provider labels only part of a batch, ai-admin retries only the missing rows
before reporting any remaining rows as `partial_review_required`; raw records
remain retained either way. When the daily budget is exhausted, add another
configured provider/API-key alias or wait for quota reset rather than spinning.

Quality blockers are publication gates, not deletion rules. A row blocked for
hotdeal publication must still keep raw evidence, current price, source URL,
unit/image evidence when present, and audit diagnostics so WalletSavior can use
it as a price observation or review candidate instead of dropping most collected
data.

## 주의

- `shared.core.contracts.ai_pipeline`만 import 하며, 다른 패키지의 내부
  모듈을 직접 참조하지 않는다.
- 비밀(secret)은 코드/DB/provider API 응답에 포함하지 않는다.
- Google GenAI는 `secret_alias`에 `GOOGLE_API_KEY` 같은 alias 이름만
  저장한다. 실제 키는 로컬 `.env`에만 둔다.
