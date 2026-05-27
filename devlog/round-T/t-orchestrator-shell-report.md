# Round T — t-orchestrator-shell Report

## start_all.bat 진단

- 발견된 배치 파일: `start-all.bat`, `start.bat`.
- 사용자가 요청한 underscore 이름 `start_all.bat`은 없어서 `./start_all.bat` 실행 시 실패할 수 있었다.
- `start-all.bat`은 PowerShell 위임만 수행했으며, Round T 기준 public web stack(`packages/web-api` + `packages/web-frontend`) 대신 legacy website stack을 기동했다.
- sandbox에서 backend 직접 기동 확인:
  - `crawler-admin` 8001 `/health` 200
  - `db-admin` 8002 `/health` 200
  - `ai-admin` 8003 `/health` 200
  - legacy website backend 8000 `/api/health` 200
  - public `web-api` 8010 `/api/v1/health` 200

## 신/구 diff 요약

- `start_all.bat` 신설: 더블클릭/CMD/PowerShell에서 `start-all.ps1` 실행.
- `start-all.bat` 수정: `cd /d "%~dp0"`, `-NoProfile`, 인자 전달 안정화.
- `start-all.ps1` 수정:
  - web stack을 `packages/web-api/backend` 8010 + `packages/web-frontend` 5173으로 전환.
  - `PYTHONIOENCODING`, `PYTHONUTF8`, `PYTHONPATH`에 repo/shared/admin/web-api 경로 설정.
  - DB/ingestion API 기본 URL 설정.
  - frontend Vite에 `--host 127.0.0.1 --strictPort` 적용해 포트 자동 밀림 방지.
  - 포트 정리 대상: 8010, 5173, 8001, 5174, 8002, 5175, 8003, 5176.

## 5 패키지 기동 매트릭스

| 영역 | 포트 | 명령 | PYTHONPATH/비고 |
|---|---:|---|---|
| shared | n/a | import path only | `packages\shared` |
| web-api | 8010 | `py -m uvicorn api.app:app --port 8010 --host 127.0.0.1` | `packages\web-api\backend` |
| web-frontend | 5173 | `npx vite --host 127.0.0.1 --port 5173 --strictPort` | proxies `/api` to 8010 |
| crawler-admin backend | 8001 | `py -m uvicorn api.app:create_app --factory --port 8001 --host 127.0.0.1` | crawler backend + shared |
| crawler-admin frontend | 5174 | `npx vite --host 127.0.0.1 --port 5174 --strictPort` | proxies to 8001 |
| db-admin backend | 8002 | `py -m uvicorn api.app:create_app --factory --port 8002 --host 127.0.0.1` | db backend + shared |
| db-admin frontend | 5175 | `npx vite --host 127.0.0.1 --port 5175 --strictPort` | proxies to 8002 |
| ai-admin backend | 8003 | `py -m uvicorn api.app:create_app --factory --port 8003 --host 127.0.0.1` | ai backend + shared |
| ai-admin frontend | 5176 | `npx vite --host 127.0.0.1 --port 5176 --strictPort` | proxies to 8003 |

## DB verify 스크립트 출력 샘플

Command: `py -3 scripts\round_t_db_verify.py`

- Report: `devlog/round-T/db-verify-report.md`
- DB: `packages\db-admin\backend\walletguardian.db`
- Product table: `products`
- Current rows: `0`
- `promo_label` column: missing in current SQLite file, so script reports schema/migration gap instead of failing.
- URL/promoNo/UUID/duplicate canon_hash checks completed with zero rows.

## crawler-admin 진행률 0/0/0/0 진단

Data flow:

1. Frontend `Crawlers.jsx` calls `api.runCrawler()` then `api.subscribeCrawlerStatus()`.
2. `client.js` opens EventSource: `/api/crawlers/{id}/status/stream`.
3. Backend `api/routes/crawlers.py` streams `_crawl_results[crawler_id]`.
4. `_run_and_store()` calls `CrawlPipeline.run_crawler(..., progress_callback=publish_progress)`.
5. `pipeline.py` emits stages: `started`, `crawl_attempt`, `crawl_finished`, `items_collected`, `validated`, `storing`, `stored`.

Patch locations:

- `packages\crawler-admin\backend\api\routes\crawlers.py`
  - Preserve progress fields from callback and final `quality_details`: `source_raw_count`, `pages_attempted`, `queries_attempted`, `items_count`, `deduplicated_count`, `invalid_count`.
  - Treat `partial_failure` as terminal for SSE, avoiding a stream that stays open after a partial persistence result.
- `packages\crawler-admin\frontend\src\pages\Crawlers\Crawlers.jsx`
  - Counter summary now falls back through `items_count`, `source_raw_count`, and nested `quality_details`.
  - Duplicate/filter/error counters read backend quality diagnostics.

## 검증

- `./start_all.bat -Web`: 5173 + 8010 started, web API health 200, frontend loaded and called API.
- `./start_all.bat -Admin`: 8001/5174, 8002/5175, 8003/5176 started with fixed ports and backend health 200.
- `py -3 scripts\round_t_db_verify.py`: report generated successfully.
- `py -3 -m py_compile scripts\round_t_db_verify.py packages\crawler-admin\backend\api\routes\crawlers.py`: pass.
- `cd packages\crawler-admin\frontend && npm test`: 7 files / 28 tests passed.
- `cd packages\crawler-admin\backend && py -3 -m pytest tests\test_crawler_api.py -q`: 11 passed.
