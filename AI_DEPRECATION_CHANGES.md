# 2026-05-25: AI Live Pipeline Deprecation Implementation

## 배경
사용자가 AI live pipeline(504 timeout 무한 회귀)을 보류하기로 결정. 코드는 보존, feature flag로 비활성화, 프론트에 "보류" 배지 표시. 향후 복귀 가능.

## 변경 파일 목록 (총 7개)

### Backend Changes (4개)

#### 1. packages/ai-admin/backend/services/ai_ingestion.py
- **Line 13-17**: WALLETSAVIOR_LIVE_AI_ENABLED feature flag 추가 (module-level constant)
- **Line 1960-1981**: ingest_and_label_records 함수 시작부에 flag check 추가
  - flag=false이면 503 status + "deprecated" stage 반환
  - 2026-05-25 주석 포함: "보류: 외부 분류 워크플로우로 전환. 삭제 금지"

#### 2. packages/ai-admin/backend/api/routes/ingest.py
- **Line 17**: WALLETSAVIOR_LIVE_AI_ENABLED import 추가
- **Line 135-148**: /api/ingest/process-missing endpoint에 flag check 추가
  - flag=false이면 HTTP 503 + deprecated status 반환

#### 3. packages/ai-admin/backend/tests/test_live_ai_flag.py (NEW FILE)
- 3개 테스트 작성
  - test_process_missing_503_when_flag_disabled: /api/ingest/process-missing이 503 반환
  - test_raw_records_label_503_when_flag_disabled: /api/ingest/raw-records/label이 503 반환
  - test_process_missing_works_when_flag_enabled: flag=true 시 정상 경로 진입

#### 4. packages/ai-admin/backend/tests/conftest.py (NEW FILE)
- pytest_configure: 테스트 시작 시 환경변수 WALLETSAVIOR_LIVE_AI_ENABLED=true 설정
- enable_ai_pipeline_for_tests: session-scoped fixture - 모듈의 flag 업데이트
- reset_ai_flag_for_each_test: function-scoped autouse fixture - 각 테스트마다 flag 재설정

### Frontend Changes (3개)

#### 5. packages/ai-admin/frontend/src/LivePipelinePanel.jsx
- **Line 189-205**: AI 처리 step에서 "보류" 배지 추가 + 버튼 disabled
  - 배지: "🚧 보류 — 외부 분류 워크플로우 사용"
  - nextStep.idx === 1 (AI step)일 때만 표시

#### 6. packages/ai-admin/frontend/src/AdvancedPage.jsx
- **Line 287-340**: nextAction 로직에서 AI step이 disabled 상태로 설정
  - disabled: true (flag deprecation에 따른)
- **Line 378-405**: "보류" 배지 추가
  - nextAction이 AI processing일 때만 표시

#### 7. packages/ai-admin/frontend/src/styles.css
- **Line 78**: .badge.deprecated 스타일 추가
  - background: #3a2a14, color: var(--warn) (주황색 톤)

## 테스트 결과 ✓ PASSED

### Backend Tests
- test_process_missing.py: 9/9 PASSED
  - test_process_missing_zero_when_none
  - test_process_missing_handles_three_records
  - test_process_missing_requires_provider_id
  - test_process_missing_rejects_limit_above_cap
  - test_process_missing_dry_run_skips_ingest
  - test_process_missing_unknown_provider_returns_400
  - test_raw_clear_all_dry_run_is_default
  - test_raw_clear_all_executes_when_dry_run_false
  - test_process_missing_continues_after_sub_batch_504

- test_live_ai_flag.py: 3/3 PASSED (NEW)
  - test_process_missing_503_when_flag_disabled
  - test_raw_records_label_503_when_flag_disabled
  - test_process_missing_works_when_flag_enabled

### Frontend Tests
- npm run build: SUCCESS
  - dist/index.html (0.41 kB, gzip: 0.29 kB)
  - dist/assets/index-Bs0hnBuw.css (22.05 kB, gzip: 4.85 kB)
  - dist/assets/index-BJSx5OWt.js (362.91 kB, gzip: 104.70 kB)

- npm test: ALL PASSED
  - callProcessMissing tests (4/4)
  - runProcessMissingLoop tests (3/3)
  - formatProcessMissingLabel tests (1/1)
  - 기타 테스트들

## 기술 상세

### Feature Flag 구현
- **환경변수**: WALLETSAVIOR_LIVE_AI_ENABLED (기본값: "false")
- **평가 로직**: `os.environ.get("WALLETSAVIOR_LIVE_AI_ENABLED", "false").lower() in ("1", "true", "yes")`
- **정의 방식**: 모듈 상수 (import 시점에 평가)
- **영향 범위**: 
  - ingest_and_label_records() 함수 진입 시
  - /api/ingest/process-missing POST 진입 시
  - /api/ingest/raw-records/label POST 진입 시

### API 응답 (flag=false일 때)

#### POST /api/ingest/process-missing
```
HTTP 503 Service Unavailable
{
  "detail": {
    "status": "deprecated",
    "detail": "live AI pipeline disabled; export to external classifier"
  }
}
```

#### POST /api/ingest/raw-records/label
```
HTTP 503 Service Unavailable
{
  "error": "ai_ingestion_error",
  "stage": "deprecated",
  "message": "live AI pipeline is currently disabled; use external classification workflow",
  "status_code": 503
}
```

### Frontend 표시
- **배지 텍스트**: "🚧 보류 — 외부 분류 워크플로우 사용"
- **버튼 상태**: disabled (클릭 불가)
- **색상**: 주황색 톤 (background: #3a2a14, color: #f0a23a)
- **위치**: 
  - LivePipelinePanel: "다음 행동" 섹션 (AI step)
  - AdvancedPage: "다음 행동" 섹션 (AI step)

### 향후 복귀 방법
1. 환경변수 설정: `export WALLETSAVIOR_LIVE_AI_ENABLED=true` (또는 .env)
2. 또는 `packages/ai-admin/backend/services/ai_ingestion.py` 라인 15 수정:
   ```python
   WALLETSAVIOR_LIVE_AI_ENABLED = True  # os.environ.get(...) 대신 직접 설정
   ```
3. flag만 켜면 전체 코드가 정상 작동 (코드 삭제 불필요)

## 주석 위치
모든 변경에 "2026-05-25 보류" 주석 추가:
- ai_ingestion.py 라인 14: 모듈 docstring 다음
- ingest.py 라인 135: process-missing endpoint 위
- LivePipelinePanel.jsx 라인 189: 배지 추가 부분
- LivePipelinePanel.jsx 라인 199: deprecated 배지 부분
- AdvancedPage.jsx 라인 287: nextAction 로직
- AdvancedPage.jsx 라인 380: 배지 추가 부분
- styles.css 라인 78: deprecated 스타일

## 발견 이슈
**없음.** 모든 기존 회귀 테스트(test_process_missing.py)가 통과함. conftest.py의 fixture로 기존 테스트들을 flag=true 상태에서 실행하여 호환성 유지.

## 종합 평가
✅ 요구사항 완전히 구현
✅ 기존 회귀 테스트 통과 (9/9)
✅ 새 테스트 추가 및 통과 (3/3)
✅ Frontend 빌드 및 테스트 통과
✅ 향후 복귀 가능성 보장
✅ 한국어 주석 및 "삭제 금지" 명시
