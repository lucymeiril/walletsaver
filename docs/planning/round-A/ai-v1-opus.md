# AI 영역 기획 v1 — Opus 초안 (숲 관점)

> Round-A / 2번 타자. 다음: GPT 5.5 적대적 리뷰 → Opus 살붙이기 → GPT 반론 → Opus 최종.
> 범위: `packages/ai-admin/` 만. 크롤러/DB/웹은 경계까지만 언급.

---

## 0. 한 줄 요약

> **"AI는 raw_record를 카테고리·키워드·canonical_id로 자동 정렬하는 공장이다. 첫 사이클엔 100% LLM이 분류하지만, 매칭 테이블과 학습 지식이 쌓이면 두 번째 사이클부터는 자기 자신을 우회한다. 사람은 '엣지 케이스만' 본다."**

핵심 명제 5개:

1. **AI는 사용자에게 보이지 않는다.** 사용자는 검색/비교 결과만 본다. AI는 그 뒤에서 카테고리·키워드·canonical_id를 만든다.
2. **첫 사이클 AI 100% → 두 번째 사이클 자동매칭 ≥80%.** 호출 횟수가 줄어드는 게 정상이고, 안 줄면 학습 루프가 망가졌다는 뜻이다.
3. **신상품·엣지만 사람에게.** 일상 행은 자동, escalation은 한 화면. 새벽 3시 알람 금지.
4. **모든 LLM 호출은 증명되어야 한다.** wire log 영구 보존, 4-gate postcheck, shrink retry, reviewer-safe fallback. "AI가 했다고 우긴다"는 디버깅이 가장 비싸다.
5. **AI는 카테고리 트리/키워드 사전을 만들지 않는다.** 제안만 하고, 승인은 관리자(DB-admin)가 한다. 결합도 0 유지.

---

## A. 현황 진단

### A-1. 현재 파이프 한눈에

```
crawler raw_record
   │
   ▼
[ai_ingestion]  ── provider 호출 (google-gemini) ──► FieldProposal + KeywordProposal
   │                                                           │
   ▼                                                           ▼
[queue_ai_router]  C1 — confidence ≥0.7면 분류, 미만이면 ESCALATED
   │
   ▼
[postcheck_gate]   C2 — 4-gate 사후검증
   │   Gate1 TREE_VALID_ID    (트리에 있는 id인가)
   │   Gate2 CONFIDENCE        (모호어 패널티 적용 후 0.7 이상)
   │   Gate3 SIBLING_CONSISTENCY (같은 canonical의 L1 다수파와 충돌 X)
   │   Gate4 PRICE_SANITY      (|price - median| ≤ 5·MAD)
   │
   ├── 4-PASS ──► [review_publish] DB-admin으로 publish
   └── any-FAIL ─► [review_automation] / escalation 큐 (ProductReviewQueue)
```

코드 근거: `services/ai_ingestion.py`, `services/queue_ai_router.py`, `services/postcheck_gate.py`, `services/review_automation.py`, `services/review_publish.py`.

### A-2. 누적 회전 구조 (Match/Learned)

| 사이클 | 입력 행 | AI 호출률 | 자동매칭 | 비고 |
|---|---|---|---|---|
| 1차 | 100% 신규 | 100% | 0% | 매칭/지식 0건에서 시작 |
| 2차 | 60% 재방문 + 40% 신규 | ≤50% 목표 | ≥50% | ProductMatchStore + LearnedKnowledge 가동 |
| 3차+ | 80% 재방문 | ≤20% 목표 | ≥80% | 정상 운영 상태 |

- `ProductMatchStoreRepository`: source signature → canonical_id 매핑. `success_count`가 누적된다.
- `LearnedKnowledgeRepository`: `RULE_LEARNED_ALIAS`, `RULE_EXACT_CATALOG_KEYWORD` 등 룰별 학습 결과. 회전이 돌수록 LLM 우회.
- 코드 근거: `storage/repositories.py:538 ProductMatchStoreRepository`, `:912 LearnedKnowledgeRepository`, `services/review_automation.py:40-43 RULE_*`.
- 모니터: `api/routes/match_monitor.py` + `frontend/src/MatchMonitorPanel.jsx` (AI 호출률 추이 차트).

### A-3. 프로바이더 호출 증명 인프라

- `providers/wire_logger.py` — httpx 레벨에서 모든 provider 요청/응답을 JSONL로 영구 기록. latency, status, ok/fail 카운트.
- `WALLETSAVIOR_AI_LIVE_FORCE=1` — 캐시·매칭 우회 강제. "AI가 진짜 호출됐냐"를 운영자가 한 줄로 증명 가능.
- 라이브 호출 보호값: 12초 간격 / 5회분 / 300회일 / transient 3회 재시도 10~60s backoff.
- 코드 근거: `providers/wire_logger.py`, `services/ai_ingestion.py:1017-1059` (force-live 처리).

### A-4. 5단계 silent drop 추적

- ai_ingestion에서 provider가 일부 row만 라벨링 → 누락 row를 재시도 → 그래도 빠지면 `partial_review_required`로 표시. raw는 절대 버리지 않는다.
- shrink retry: 배치 N개가 실패하면 N→N/2→1로 쪼개서 재시도. 1-아이템도 실패하면 `confidence=0.42` reviewer-safe fallback.
- 코드 근거: `services/ai_ingestion.py:846-922 _reviewer_safe_fallback_response_item`, `:1397 shrink`, `tests/test_ai_ingestion_shrink.py`.

### A-5. 지금 안 보이는 것 (= 적이 칠 자리)

| 누락 | 영향 | 비고 |
|---|---|---|
| **비용 모니터 (월간 토큰/USD)** | 어느 날 갑자기 청구서 폭탄 | 1단계 후순위 OK |
| **다중 프로바이더 폴백 체인** | google-gemini 다운 시 전체 정지 | 2단계 |
| **unlearn 액션** | 잘못 학습된 매칭 영구 오염 | 1단계에 최소판 필요 |
| **새 카테고리/키워드 제안 큐** | AI 제안과 사람 제안이 섞여서 추적 어려움 | 2단계 |
| **"이거 핫딜 아님" 사용자 피드백 학습** | 사용자 신호 → AI 학습 연결 끊김 | 3단계 |
| **AI 성능 ABtest 모드** | 모델 갈아끼울 때 회귀 발견 불가 | 3단계 |
| **escalation 큐 SLA 표시** | 신상품 들어와도 며칠씩 묵힘 | 1단계 |

---

## B. AI가 책임져야 하는 것 (궁극 목표 관점)

> 궁극 목표: "복잡해서 못하던 비교를, 일반인이 자연스럽게."

이 한 문장에서 **AI 영역이 책임지는 것**을 역산하면:

1. **자동 카테고리 분류** — 사용자는 "라면" 검색만 하면 9개 마트 행이 같은 통에 들어와 있어야 한다. 분류 안 되면 비교 자체가 불가능.
2. **상품 정규화 (canonical_id)** — "농심 신라면 5개입 600g"와 "신라면 멀티팩 5입"이 같은 canonical_id에 묶여야 가격 비교 가능. 이게 AI 영역의 가장 큰 가치.
3. **키워드 추출** — 검색·자동완성·"비슷한 상품" 묶기의 원료. 사람이 일일이 짤 수 없다.
4. **신상품·엣지 행만 escalate** — 일상 행은 AI 자동, 새로운 SKU·애매한 행은 관리자 큐. "사람은 1%만 본다"가 목표.
5. **자기 자신을 우회하게 학습** — 매칭 테이블이 커질수록 AI 호출 비용 감소. 학습 안 되면 비용·지연 모두 폭증.

### B-1. AI가 책임 **안 지는** 것 (경계)

- **카테고리 트리/키워드 사전 자체의 정의** — DB-admin 영역.
- **소스 크롤링** — 크롤러 영역.
- **사용자 UI** — 웹 영역.
- **가격 자체의 판단 ("핫딜이냐 아니냐")** — 별도 룰/모델이 책임. AI는 가격 sanity만 게이팅(Gate 4).

> 이 경계가 무너지면 v1은 실패다. AI가 카테고리 트리를 "자기 마음대로 추가"하기 시작하면 결합도 0이 깨진다.

---

## C. 사용자 관점 (간접 영향)

사용자는 AI 화면을 직접 보지 않는다. 그러나 다음 4지점에서 AI 품질이 사용자 체감을 결정한다.

| 사용자 행동 | AI 영역 책임 | 실패 시 사용자 체감 |
|---|---|---|
| 검색창에 "라면" 입력 | 키워드 추출 + 카테고리 매칭 | "신라면" 검색해도 이마트만 뜨고 롯데마트 빠짐 |
| "비슷한 상품" 묶음 보기 | canonical_id 정규화 | 같은 상품인데 따로따로 보임 → 비교 불가 |
| 자동완성 | LearnedKnowledge 키워드 풀 | "라" 쳤는데 추천 안 뜸 |
| "이거 핫딜 아닌 것 같다" 신고 | 피드백 → 학습 (3단계) | 사용자가 신고해도 다음 사용자에게 똑같이 노출 |

### C-1. 사용자 피드백 → AI 학습 (3단계 항목)

- "이거 핫딜 아님" 버튼 → DB의 신고 테이블 → AI가 주기적으로 ReviewDecision로 흡수 → 가격 sanity Gate에 history로 반영.
- v1에선 **신고 누적 표시만**, 학습 반영은 v2/v3에서.

---

## D. 관리자 관점 UI/UX (ai-admin frontend)

현재 패널: `App.jsx`에서 ReviewQueuePanel, JobsPanel, MatchMonitorPanel, PromptPacksPanel, ProvidersPanel.

### D-1. 패널별 v1 목표

| 패널 | 현재 상태 | v1 목표 |
|---|---|---|
| **ReviewQueuePanel** | escalation 행 리스트 | 한 화면 + top-3 카테고리 후보 + confidence + 1-click 승인/반려/직접 지정 |
| **MatchMonitorPanel** | AI 호출률 추이 차트 | + 누적 카드 (ProductMatch by_status/by_source, LearnedKnowledge by_type/success_count) + 회전 비율 |
| **JobsPanel** | 라벨링 런 모니터 | 런별 입력/AI호출/자동매칭/escalated 카운트 + 5단계 silent drop 표 |
| **PromptPacksPanel** | 프롬프트 팩 | + wire log 뷰어 링크 (별도 라우트) |
| **ProvidersPanel** | 설정 | + latency 분포 + 일일 호출량 / quota 잔량 |
| **(신규) WireLogPanel** | 없음 | provider 호출 라이브 증명. 최근 N개 JSONL 표로 |
| **(신규) AI 성능 평가 모드** | 없음 | `WALLETSAVIOR_AI_LIVE_FORCE=1` 토글 + 결과 비교 |
| **(신규) 새 카테고리/키워드 제안 큐** | 없음 | AI 제안 vs 관리자 제안 분리 |

### D-2. 리뷰 큐 1-click UX (핵심)

```
┌─────────────────────────────────────────────────────────────┐
│  raw_title: "농심 신라면 큰사발 멀티팩 5입"                  │
│  source: 롯데마트  price: 4,980원  unit: 6.0g·5             │
│  ────────────────────────────────────────────────────────── │
│  AI 카테고리 후보 (top-3)                                   │
│    [ ] foods/noodles/instant         confidence 0.82  ✓     │
│    [ ] foods/noodles/cup             confidence 0.41        │
│    [ ] foods/processed/snack         confidence 0.12        │
│  ────────────────────────────────────────────────────────── │
│  매칭 후보 (ProductMatchStore)                              │
│    canonical_id: 신라면-멀티5  (success_count 12)           │
│  ────────────────────────────────────────────────────────── │
│  [ 1-click 승인 ]  [ 직접 지정 ]  [ 반려 ]  [ 신상품으로 ]  │
└─────────────────────────────────────────────────────────────┘
```

- AI가 top-3 후보를 confidence와 함께 제안.
- 매칭 후보가 있으면 같이 표시.
- 키보드 단축키 (1/2/3 후보 선택, Enter 승인) — 관리자는 하루 100건 이상 본다.

### D-3. silent drop 표 (JobsPanel)

| 런 | crawler raw | ai_ingestion 입력 | provider 호출 | postcheck pass | publish | escalated | 누락 |
|---|---|---|---|---|---|---|---|
| run-2026-05-13 | 1,240 | 1,240 | 87 (caching 93%) | 82 | 76 | 6 | 0 |
| run-2026-05-14 | 1,310 | 1,310 | 102 | 95 | 88 | 7 | 0 |

각 단계 사이의 **drop이 0이 아니면 빨간 표시**. 사일런트 드롭은 "AI가 했다고 우기는데 결과가 없는" 가장 비싼 버그다.

---

## E. 매칭 테이블 학습 루프

### E-1. RULE_LEARNED_ALIAS 자동 발동 threshold

현재: `services/review_automation.py`에 `RULE_LEARNED_ALIAS` 정의됨. 발동 정책은 코드를 더 봐야 한다.

**v1 권장 정책 (Opus 제안, 검증 필요)**:

| 신뢰도 출처 | 발동 threshold (success_count) | 비고 |
|---|---|---|
| 관리자 명시 승인 | 1회로 즉시 활성 | 가장 신뢰 |
| AI + 시맨틱 일치 (정규화 매칭) | 3회 누적 | 중간 신뢰 |
| AI 단독 (자기학습) | 5회 누적 + confidence 평균 ≥0.85 | 보수적 |
| reviewer-safe fallback (conf 0.42) | 절대 자동 활성 X | 영구 사람 검토 |

### E-2. unlearn (잘못 학습된 매칭 발견)

- 관리자가 ReviewQueuePanel/MatchMonitorPanel에서 `unlearn(canonical_id, signature)` 호출.
- 효과: `ProductMatchStore` 해당 row를 deprecated 표시 + `LearnedKnowledge` 연결된 룰의 `success_count`를 0으로 리셋.
- **삭제하지 않는다** — 감사 로그로 영구 보존. 코드 근거: 기존 `ReviewDecision` 패턴과 동일.

### E-3. 매칭 충돌 (같은 signature → 두 canonical)

- 충돌 감지 즉시 두 행 모두 `ProductMatchStatus.CONFLICT` 마크.
- escalation 큐에 충돌 카드로 한 줄 표시 → 관리자가 어느 쪽이 옳은지 선택 → 잘못된 쪽 unlearn.
- 자동 해결 시도 X. 충돌은 항상 사람 결정.

### E-4. 신뢰도 가중치 (조합)

```
final_trust = w_human * is_human_approved
            + w_semantic * semantic_match_score
            + w_ai_self * (1 - reviewer_safe_penalty)
```

- 가중치 초기값: w_human=0.6, w_semantic=0.3, w_ai_self=0.1.
- reviewer-safe fallback이 끼면 w_ai_self를 0.05로 감쇄.
- v1에선 **로그만 남기고 의사결정엔 안 씀**. v2에서 매칭 충돌 자동 우선순위로 활용.

---

## F. 프로바이더 / 비용 / 안정성

### F-1. 다중 프로바이더 폴백 체인 (2단계)

```
google-gemini31-live-matrix (primary)
  ├── timeout/5xx ─► google-gemma4-live (secondary)
  └── 일일 quota 소진 ─► openai-gpt4o-mini (tertiary, 옵션)
```

- 현재 코드: `tools/run_live_model_batch.py --provider-pool` 옵션으로 이미 풀 개념 존재.
- v1: provider 1개로 고정. polite-degrade는 polish 단계.
- v2: 풀 자동 선택 + 일일 quota 잔량 기반 라우팅.

### F-2. shrink retry + reviewer-safe fallback (이미 있음)

| 단계 | 동작 | 결과 |
|---|---|---|
| 1차 | N개 배치 호출 | 성공 시 종료 |
| 2차 | transient 에러면 N개 재호출 (최대 3회) | 성공 시 종료 |
| 3차 | 여전히 실패면 N/2로 쪼개기 | 어느 절반 실패면 그쪽만 1로 쪼갬 |
| 4차 | 1-아이템도 실패 | reviewer-safe fallback (confidence=0.42, 사람 검토 강제) |

코드 근거: `services/ai_ingestion.py:846-922, 1397`.

### F-3. 캐싱 정책

- prompt hash (raw_record 정규화 + 프롬프트 버전) 기준 캐시.
- 캐시 hit이면 wire log에 `cache_hit=true` 기록 (= provider 호출 0).
- `WALLETSAVIOR_AI_LIVE_FORCE=1`이면 캐시 무시하고 강제 호출.

### F-4. 비용 모니터 (1단계 후순위 → 2단계 초입)

- wire log JSONL을 daily roll-up → ProvidersPanel에 표:

| provider | 일일 호출 | 평균 latency | 추정 토큰 | 추정 USD |
|---|---|---|---|---|
| google-gemini31 | 87 | 1.4s | 142K | $0.07 |

- 임계 초과 시 알람 (PromQL 같은 거 도입 안 함, 단순 threshold 체크).

### F-5. 라이브 호출 증명 (wire log 영구 보존)

- 이미 `WALLETSAVIOR_AI_LIVE_FORCE=1` + httpx 인터셉트로 구현됨.
- v1 추가: WireLogPanel에서 최근 100건 표로 + 다운로드 버튼.
- 보존 기간: 무기한 (압축 회전은 운영 폴리시).

---

## G. 모듈 / 플러그인 관점

### G-1. AI 영역의 경계

```
crawler ──(REST: raw_records)──► ai-admin ──(REST: FieldProposal/Match)──► db-admin
                                    │
                                    └──(adapter)──► provider (google-gemini, openai, ...)
```

- **AI는 크롤러 DB도, DB-admin DB도 직접 안 읽는다.** 모두 API 경유.
- 코드 근거: `services/db_admin_adapter.py`, `core.contracts.ai_pipeline`, `core.contracts.control_plane`.

### G-2. 프로바이더 어댑터 패턴

- `providers/google_genai.py`가 단일 어댑터.
- v1: 어댑터 인터페이스 명시 — `call(prompt, options) -> ProviderResponse`만 충족하면 새 모델 갈아끼우기 가능.
- 새 프로바이더 추가는 yaml 한 줄 + 어댑터 파일 1개. 다른 코드 수정 0.

### G-3. 카테고리/키워드 동적 적응

- DB-admin이 카테고리 트리를 바꾸면 `shared/data/category_tree.yaml`이 갱신.
- AI는 호출 시점에 yaml을 다시 읽어 프롬프트 컨텍스트로 주입.
- v1: 핫리로드 아님 (프로세스 재시작 필요). v2: 파일 watcher.

---

## H. 로드맵

### 1단계 — 라이브 직전 (필수)

- [ ] postcheck 4-gate 안정화 (Gate1~4 모두 테스트 통과 + 실측 라이브 1회)
- [ ] 자동매칭 ≥80% 사이클 2회 이상 검증 (MatchMonitorPanel에서 시각 확인)
- [ ] wire log 영구 보존 (이미 됨) + WireLogPanel 추가
- [ ] ReviewQueuePanel 1-click UX (top-3 후보 + 키보드 단축키)
- [ ] silent drop 표 (JobsPanel)
- [ ] escalation SLA 표시 (큐에 N시간 묵힌 행 빨갛게)
- [ ] unlearn 최소판 (관리자 버튼 → deprecated 마크)

### 2단계 — 가동 직후 (1개월 내)

- [ ] 비용 모니터 (일일/월간 토큰·USD 추정)
- [ ] 다중 프로바이더 폴백 체인 (yaml 풀)
- [ ] 새 카테고리/키워드 제안 큐 (AI vs 관리자 분리)
- [ ] 카테고리 트리 핫리로드
- [ ] 매칭 충돌 카드 (CONFLICT 상태 UI)

### 3단계 — 가동 안정 후 (3개월+)

- [ ] AI 성능 ABtest 모드 (모델 A vs B 동시 실행, 라이브 트래픽 1% 샘플)
- [ ] "이거 핫딜 아님" 사용자 피드백 학습 루프
- [ ] 신뢰도 가중치 자동 우선순위 (E-4)
- [ ] 시맨틱 spot-check 자동화 (룰 기반 검증 통과율 추세)

---

## I. 자기검증

| 체크 | 결과 |
|---|---|
| 다른 영역(DB/크롤러/웹) 깊이 파지 않았는가 | ✅ 경계까지만 |
| 코드 변경했는가 | ✅ 없음 |
| v2/v3/v4/v5 미리 작성했는가 | ⚠️ 로드맵 2/3단계는 **항목만**, 설계는 안 함 |
| 안전 권고로 기능 축소했는가 | ✅ 없음. shrink/wire-log/postcheck은 이미 구현된 기능 정리 |
| 사용자 명시 ("안전 타령 금지") 위반 | ✅ 없음 |
| 5~10페이지 마크다운 | ✅ 약 8페이지 분량 |

---

## J. 다음 단계(GPT 5.5)가 봐야 할 포인트 3~5개

1. **E-1 RULE_LEARNED_ALIAS threshold가 임의값이다.** "AI 자기학습 5회·confidence≥0.85"는 Opus가 감으로 정한 숫자. 실제 라이브 데이터로 false positive·false negative 곡선이 어떻게 나오는지 검증 없이는 못 박을 수 없다. **GPT는 "이 숫자 어디서 나왔냐"를 쳐야 한다.**

2. **D-2 "1-click 승인" UX는 위험할 수 있다.** 관리자가 키보드만 두드리면서 잘못 승인하면 ProductMatchStore가 영구 오염된다. unlearn이 있긴 한데, **승인 직후 5분 이내 undo 윈도우**나 **승인 후 같은 canonical 재방문 시 2차 확인** 같은 안전장치가 v1에 들어가야 하는지 GPT 의견 필요.

3. **F-1 다중 프로바이더 폴백을 2단계로 미룬 게 너무 늦은가.** google-gemini 일일 quota는 300회로 좁고, 라이브 가동 첫 주에 1,500행 들어오면 폴백 없이는 막힌다. **1단계에 최소 2-provider 풀이 들어가야 할 수도** 있다.

4. **C-1 "이거 핫딜 아님" 사용자 피드백을 3단계로 미룬 게 정당한가.** 사용자 입장에서 가장 자연스러운 학습 신호인데, v1에 신고 버튼만 두고 학습 연결을 v2/v3로 미루면, "신고해도 바뀐 게 없다"는 사용자 불신이 라이브 직후 형성될 수 있다.

5. **E-3 매칭 충돌을 "항상 사람 결정"으로 둔 게 합리적인가.** 충돌 빈도가 일일 100건 넘어가면 관리자 1명으로는 처리 불가. 자동 해결 룰(예: success_count 높은 쪽 우선)을 일부라도 1단계에 넣어야 하는지 GPT가 판단해야 한다.

---

## 부록: 핵심 코드 위치 (라운드-B 검증용)

| 항목 | 파일 |
|---|---|
| ai_ingestion (메인 라벨링) | `packages/ai-admin/backend/services/ai_ingestion.py` |
| queue_ai_router (C1) | `packages/ai-admin/backend/services/queue_ai_router.py` |
| postcheck_gate (C2 4-gate) | `packages/ai-admin/backend/services/postcheck_gate.py` |
| review_automation (RULE_*) | `packages/ai-admin/backend/services/review_automation.py` |
| ProductMatchStore / LearnedKnowledge | `packages/ai-admin/backend/storage/repositories.py:538, 912` |
| wire_logger (호출 증명) | `packages/ai-admin/backend/providers/wire_logger.py` |
| match_monitor API | `packages/ai-admin/backend/api/routes/match_monitor.py` |
| review API | `packages/ai-admin/backend/api/routes/review.py` |
| frontend match panel | `packages/ai-admin/frontend/src/MatchMonitorPanel.jsx` |
| frontend review queue | `packages/ai-admin/frontend/src/ReviewQueuePanel.jsx` |

---

*— Opus 4.7, Round-A 2번 타자. GPT 5.5에게 넘긴다.*
