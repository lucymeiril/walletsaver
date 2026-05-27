# Round S — s-orchestrator-ui 진단 보고서

## 1. start_all.bat / 셸 실행 현황

### 파일 위치

- `start_all.bat`는 루트/직속 폴더에 없음.
- 실제 존재 파일:
  - `start-all.bat` → `powershell -ExecutionPolicy Bypass -File "%~dp0start-all.ps1" %*`
  - `start.bat` → 웹사이트 단독 `start.ps1`

따라서 사용자가 `start_all.bat`를 실행했다면 Windows 셸에서는 파일명 불일치로 실패한다. 호환 별칭으로 `start_all.bat`를 추가하는 것이 좋다.

### start-all.ps1가 띄우는 서버

`start-all.ps1` 기준:

```text
PYTHONPATH = packages\shared; packages\crawler-admin\backend; packages\db-admin\backend; packages\ai-admin\backend; packages\website\backend
웹 backend/frontend        8000 / 5173
crawler-admin backend/FE  8001 / 5174
DB-admin backend/FE       8002 / 5175
AI-admin backend/FE       8003 / 5176
```

프론트 Vite 설정 확인:

- `packages\crawler-admin\frontend\vite.config.js`: 기본 5174, API 8001
- `packages\db-admin\frontend\vite.config.js`: 기본 5175, API 8002
- `packages\ai-admin\frontend\vite.config.js`: 기본 5176, API 8003
- `packages\web-frontend\vite.config.ts`: 기본 5173, API 8010
- `packages\website\frontend\vite.config.js`: 기본 5174, API 8001이나 `start-all.ps1`에서 5173으로 override

### 셸 실행 실패 후보 5종

1. 파일명 혼동: `start_all.bat` 없음, 실제는 `start-all.bat`.
2. 웹 패키지 혼선: 스크립트는 `packages\website`를 사용하지만 현행 E2E는 `web-api` 8010 + `web-frontend` 5173을 사용한다.
3. PYTHONPATH 누락: `packages\web-api\backend`가 포함되지 않고 `packages\website\backend`가 포함됨.
4. requirements 미설치: `start-all.ps1`는 pip에 일부 패키지만 직접 설치한다. `crawler-admin\requirements.txt`의 `playwright`, `selenium`, `undetected-chromedriver`, `cloudscraper`, `fake-useragent`, `apscheduler`, `Pillow`, `slowapi`, `psutil` 등이 빠질 수 있다.
5. PowerShell 정책/환경: `py`/`python`, `npm`, `npx.cmd`, `Get-NetTCPConnection` 권한/존재 문제. `.bat`는 `-ExecutionPolicy Bypass`를 주지만 `.ps1` 직접 실행은 막힐 수 있다.

## 2. 진행률 0/0/0/0 데이터 흐름

### 기존 흐름

```text
crawler-admin FE Crawlers.jsx
  └─ POST /api/crawlers/{id}/run
      └─ backend routes/crawlers.py: _crawl_results[id] = running + 0 카운터
          └─ asyncio.create_task(_run_and_store)
              └─ CrawlPipeline.run_crawler(id)
                  └─ crawler.crawl()
                  └─ validate/dedup/store
              └─ 완료 후 _crawl_results[id]를 최종 카운터로 교체
  └─ EventSource /api/crawlers/{id}/status/stream 또는 polling /status
      └─ CounterChips가 items_found/items_valid/items_saved를 표시
```

### 끊긴 지점

- `routes/crawlers.py`는 실행 직후 `items_found/items_valid/items_saved = 0`만 저장하고, 파이프라인 진행 중 중간 업데이트가 없었다.
- SSE는 `_crawl_results` 변경 시에만 push한다. 변경이 없으니 UI가 계속 0 카운터를 받는다.
- `PipelineResult.status`가 `partial_failure`일 수 있는데 SSE/FE는 `success|failed`만 종료 상태로 처리했다. 저장 0건이면 UI가 계속 실행 중으로 남을 수 있었다.
- 4사 크롤러 중 최소 이마트/롯데마트는 `pages_attempted`, `items_count`, `quality_details`는 만들지만 UI용 publish 콜백은 없었다.

## 3. 적용한 미니 패치

### 백엔드

- `packages\crawler-admin\backend\pipeline\pipeline.py`
  - `run_crawler(..., progress_callback=None)` 추가.
  - 단계별 publish: `started`, `crawl_attempt`, `crawl_finished`, `items_collected`, `validated`, `storing`, `stored`, `failed`.
  - 크롤러 인스턴스에 `progress_callback` 속성을 주입.
- `packages\crawler-admin\backend\api\routes\crawlers.py`
  - `_run_and_store()` 내부 `publish_progress()`가 `_crawl_results[id]`를 중간 갱신.
  - SSE 종료 상태에 `partial_failure` 추가.
  - 최종 응답에 `progress_stage`, `quality_score`, `quality_details` 포함.
- `packages\crawler-admin\backend\crawlers\marts\emart\crawler.py`
  - 페이지 파싱마다 `source_page_parsed` / `fallback_page_parsed` publish.
- `packages\crawler-admin\backend\crawlers\marts\lottemart\crawler.py`
  - 검색 페이지 및 스크롤 완료 지점에서 publish.
- `packages\crawler-admin\backend\api\routes\dashboard.py`
  - `partial_failure`를 dashboard의 partial 상태로 집계.

### 프론트엔드

- `packages\crawler-admin\frontend\src\pages\Crawlers\Crawlers.jsx`
  - 카운터 칩을 `총 수집 / 유효 / 저장 / 중복 / 오류`로 변경.
  - running 메시지에 `progress_stage` 표시.
  - `partial_failure`를 종료 상태로 처리.
- `packages\crawler-admin\frontend\src\api\client.js`
  - SSE terminal status에 `partial_failure` 추가.

### 사용자 PC E2E 보강

- `scripts\g3_e2e_user_scenario.py`
  - crawler-admin 실행 직후 캡쳐에 더해 8초 뒤 `01b-crawler-admin-progress-counters` 캡쳐 추가.

## 4. UI/UX 검수 노트

### crawler-admin 후보

- Dashboard `crawlerCards`는 `JobTracker` 기반인데 수동 실행 API `_crawl_results`와 직접 연결되지 않는다. 수동 실행 후 대시보드가 즉시 비어 보일 수 있다.
- Dashboard `STATUS_LABEL`에는 `partial_failure` 직접 라벨이 없다. 백엔드에서 partial로 매핑했지만 원본 상태를 직접 쓰는 화면은 추가 점검 필요.
- Crawlers 페이지는 최근 실행/총 실행/성공률 값이 registry metadata에 의존한다. 실제 run history와 불일치 가능.
- DataReview `items.length || item.itemCount || item.items_count`는 스키마별 필드명이 혼재되어 빈 값처럼 보일 수 있다.

### DB-admin Product 테이블

현재 보이는 컬럼:

- 표시됨: `mart`, `mart_native_code`, `unit_price_displayed`, `external_seller`, `mart_native_category_path`, `source/source_type`, `valid_from/valid_to`
- 후보 누락: `canon_hash`, `promo_label`, `source_url/detail_url` 직접 링크, `unit_price_basis_raw`, `discount_type`, `mart_native_product_id` 원문, `offer_raw_data` 요약
- 상세 모달은 `source/source_type`, 가격, 할인율 위주이며 `mart_native_code`, `canon_hash`, `promo_label`, 원본 카테고리/원본 URL이 표보다 덜 드러난다.

## 5. 사용자 PC 검증 체크리스트

1. `E:\pdf\capston01`에서 `dir start*` 캡쳐: `start-all.bat`, `start-all.ps1`, `start.bat` 확인.
2. `start_all.bat` 실행 시 실패 메시지 캡쳐(파일명 불일치 확인).
3. `start-all.bat -Admin` 실행 로그 캡쳐.
4. PowerShell에서 `py --version`, `python --version`, `npm --version`, `npx --version` 결과 캡쳐.
5. `http://localhost:5174/crawlers` 접속 캡쳐.
6. 크롤러 관리 페이지에서 마트 필터 클릭 후 4사 카드 캡쳐.
7. 이마트 실행 버튼 클릭 직후 `크롤링 실행 중...(started/crawl_attempt/...)` 표시 캡쳐.
8. 5~15초 뒤 카운터가 `총 수집/유효/저장`으로 변하는지 캡쳐.
9. 롯데마트 실행 버튼 클릭 후 `source_page_parsed` 또는 `scroll_finished` 표시 캡쳐.
10. DevTools Network에서 `/api/crawlers/{id}/status/stream` SSE 응답 JSON 캡쳐.
11. SSE가 불안정하면 `/api/crawlers/{id}/status` polling 응답 JSON 캡쳐.
12. 완료 후 `partial_failure`라도 UI가 무한 running에 남지 않는지 캡쳐.
13. `http://localhost:5174/dashboard`에서 crawlerCards/신선도 반영 여부 캡쳐.
14. `http://localhost:5175/products`에서 Product 테이블 컬럼 캡쳐.
15. Product 상세 모달에서 `mart_native_code`, 원본 URL, canon/promo 누락 여부 캡쳐.
16. `py -3 scripts\g3_e2e_user_scenario.py --no-spawn` 실행 후 `devlog\round-R\captures\...\01b-crawler-admin-progress-counters.*` 확인.
17. 서버 로그 `crawler-admin-backend.log`에서 progress 단계와 오류 메시지 캡쳐.

## 6. Cross-cut todo

- `start_all.bat` 호환 alias 추가 또는 README/스크립트명 통일.
- `start-all.ps1`을 `web-api`/`web-frontend` 기준으로 정리하고 `packages\web-api\backend`를 PYTHONPATH에 추가.
- 각 backend requirements를 서비스별로 설치하도록 스크립트 개선.
- Homeplus/Costco에도 이마트/롯데마트와 같은 `progress_callback` publish 적용.
- crawler-admin Dashboard를 `_crawl_results` 또는 run history와 동기화.
- DB-admin Product 상세 모달에 `canon_hash`, `promo_label`, 원본 URL, native code/path 표시 추가.
