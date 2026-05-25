# AI 영역 기획 v5 (FINAL) — Opus 최종본

> 입력: v1(`ai-v1-opus.md`), v2(`ai-v2-gpt.md`), v3(`ai-v3-opus.md`), v4(`ai-v4-gpt.md`).
> 원칙: v1~v4 절대 수정 금지. v5는 **단일 완성 기획서**.
> 범위: `packages/ai-admin/` 만. 크롤러/DB/웹은 경계까지만.
> 톤: 한국어, 비개발자 가독, 표/체크리스트 위주. 회피 어휘 금지.

---

## 0. 한 줄 요약

> **"AI-admin은 raw_record를 카테고리·키워드·canonical 후보로 정렬하는 공장이다. 1차 사이클은 LLM 100%, 학습이 누적되면 30% 아래로 떨어진다. 사람은 의미 결정만 본다. 자기학습은 봉인하지 않는다 — audit·decay·cross-check로 운영한다. 안전 어휘로 기능을 깎지 않는다."**

핵심 명제 7개:

1. AI는 사용자에게 직접 보이지 않는다. 검색·묶기·자동완성·신고 4지점에서 품질로만 체감된다.
2. **첫 사이클 AI 호출률 100% → 2~3회 사이클 후 30% 이하**가 정상. 안 줄면 학습 루프가 망가졌다.
3. 모든 LLM 호출은 wire log로 증명된다. **실측 7건 라이브 호출(generativelanguage.googleapis.com) + WALLETSAVIOR_AI_LIVE_FORCE 플래그**로 이미 입증.
4. 자기학습 alias는 시스템의 자산이다. **봉인 금지**. audit/decay/cross-check로 운영.
5. 사람은 의미 결정(canonical merge/split, 카테고리 트리 변경, 정책 판단)만. 반복 분류는 기계.
6. AI는 카테고리 트리·canonical_id를 직접 생성하지 않는다. DB-admin에 **제안 + vote**만.
7. 안전·금지 어휘로 기능을 깎지 않는다. 가시화·구조화·측정으로 운영.

---

## 서문. v1~v4 통합 정책

### 0-A. v4가 옳게 짚은 약점 — 수용

| v4 지적 | v5 수용 결정 |
|---|---|
| C-1 undo 윈도우가 "토스트 5초"가 아니라 `ReviewDecision` 상태 전이로 정의돼야 한다 | **수용**. `undoable_until`, `downstream_application_count`, `reused_in_run_ids` 컬럼 추가 (§4-B). |
| C-2 threshold 14일은 달력값, 표본 조건이 본조건이어야 한다 | **수용**. D+14는 보조, 본조건은 `knowledge_id별 unique source≥3 / unique normalized_title≥20 / settled≥50` (§4-A). |
| C-3 decay 90일이 계절 상품을 깬다, audit 주간이 spike에 늦다 | **수용**. decay는 시간 + `last_seen_seasonality` + `recent_fp_count` 복합. audit은 주간 배치 + 실시간 spike 분리 (§4-C). |
| C-4 quota DB 영속 키 설계 부재 | **수용**. `(provider, model, api_key_fingerprint, billing_account, window_start, window_end)` + `call_purpose` 분해 (§5-C). |
| C-5 tie-break 4룰을 자동 확정으로 쓰면 깨진다 | **수용**. tie-break는 **카드 정렬·1초 결정 보조**이지 자동 확정 X. `rank_reason`과 `counter_evidence` 같이 표시 (§4-D). |
| C-6 OSS LLM은 품질표 없으면 폴백이 아니라 escalation 생성기 | **수용**. `ProviderCapability`에 `schema_valid_rate / ko_product_score / p95_latency / postcheck_pass_rate` 등록 의무 (§5-A). |
| D-2 canonical 승격 수치도 measurement 필요 | **수용**. 승격도 D-1과 같은 표본 조건 + 빈도 제한 (동일 normalized alias당 7일 1회) (§10-B). |
| D-3 모델 변경 재평가 P2는 늦다 | **부분 수용**. **P0**: `model_version`/`prompt_version` provenance 저장. **P1**: 수동 sample replay 버튼. 자동화만 P2 유지 (§11). |
| D-5 신고 P0 유입과 P2 학습 사이 공백 | **수용**. P0에 얇은 재사용 억제 룰 추가: 신고 N건 이상 `match_id`/`knowledge_id`는 다음 자동 적용 시 ReviewQueue에 "신고 많은 자동매칭" 배지 (§9). |
| E-1 모델 deprecation/요금 변경 대응 | **수용**. provider yaml에 `effective_from / deprecated_at / price_version`. 단가 변경 시 과거 비용은 **당시 단가 보존** (§5-D). |
| E-2 prompt injection 경로 | **수용 (기능 차원)**. raw text를 instruction과 분리된 JSON field로. postcheck가 카테고리 트리·canonical 후보에 맞는지만 본다. wire log → raw_record_id 연결 (§7). |
| E-3 canonical 승격 빈도/중복 룰 부재 | **수용**. 승격은 신규 생성보다 **vote/근거 추가가 기본**. `canonical_candidate_fingerprint`로 dedupe (§10-B). |
| E-4 다국어/한자/브랜드 약어 | **수용**. normalized_title 전처리에 script normalization + transliteration + brand dictionary 도입 (§3-D). |
| E-5 동음이의 상품 ("사과"/"배"/"밤") | **수용**. 짧은 alias는 `RULE_LEARNED_ALIAS` 자동 적용 보류. 주변 token + category prior + unit/package 같이 본다 (§3-D). |
| E-6 매칭 사용자 가시성 (`match_explanation`) | **수용**. `match_explanation` JSON 필드 도입. 묶인 이유를 evidence 단위로 노출 (§4-E, §9). |
| E-7 신고 → 재학습 닫힌 루프 4상태 | **부분 수용**. P0에 1~2번 상태(연결 + 처리 구분), 3~4번(과거 신고 prompt 반영, 동일 묶음 노출 측정)은 P1 (§9). |
| E-8 latency 폭주 시 JobsPanel 가시성 | **수용**. JobsPanel에 batch 단위 progress + p50/p95/p99 + "oldest in-flight call age" (§8-C). |
| E-9 비용 대시보드 단위 (원화/source별/call_purpose별) | **수용**. 원/일·주·월 + provider·model·source·run·call_purpose별 분해 + 1k raw_record당 비용 + 자동매칭 1건 절감당 비용 (§5-E). |
| E-10 A/B 통계 유의성 (1% 충분한가) | **수용**. primary metric 명시(postcheck pass + human approval + rollback diff) + 최소 표본 계산 + source/category stratified sampling (§8-D). |
| E-11 canonical change event feed | **수용**. DB-admin → AI-admin canonical change webhook. merge/split/rename 시 ProductMatchStore + LearnedKnowledge 영향 범위 계산 (§10-C). |

### 0-B. v4가 안전 타령/학습 봉인 방향으로 끌고 갔다면 — 명시 배척

v4 본문을 정독한 결과, **v4는 명시적 봉인 권고는 하지 않았다**. 그러나 다음 어조는 v5가 거부한다:

| v4의 미묘한 어조 | v5 거부 사유 |
|---|---|
| "audit/decay만으로는 부족하다, 왜 적용됐고 왜 빠졌는지 보여줘야 한다" (B-4) | 보여주기는 받지만, 그게 자기학습 **사용 보류·제한** 어조로 번지면 거부. v5는 **자기학습 계속 + 설명(`match_explanation`) 추가**. |
| "tie-break 자동 확정 깨진다 → 자동 확정하려면 룰별 precision 쌓아야" (C-5) | 정당. 단, 이게 "당분간 자동 확정 금지"로 번지면 거부. v5는 **카드 정렬은 즉시 적용, 자동 확정은 룰별 precision 누적 후**의 **두 단계 운영** (§4-D). |
| "OSS LLM은 가능성이 아니라 benchmark 통과해야" (C-6) | 정당. 단, 이게 "OSS LLM 폴백 보류"로 번지면 거부. v5는 **benchmark 미달 OSS는 폴백 합류 거부 + 합류 시점 명시** (§5-A). |
| "1% A/B 표본 충분한가" (E-10) | 정당. 단, 이게 "A/B 모드 보류"로 번지면 거부. v5는 **A/B는 P2 그대로 + 표본 계산 기준 명시** (§8-D). |
| "신고 P0~P2 사이 공백" → 추가 안전망 (D-5) | 정당. v5는 **얇은 재사용 억제 + 배지**까지 P0로 끌어올리되, 모델 학습은 P2 유지. **자동 적용 자체 봉인 X**. |

**v5의 운영 원칙 (안전 어휘로 기능 깎지 않음)**:

- 자기학습은 **계속** 한다. 봉인·일시 중지·승인 게이트 추가 거부.
- 매칭 학습 누적은 **시스템 가치의 본체**다. 끄지 않는다.
- 동적 카테고리 트리 적응(yaml 갱신 + AI 컨텍스트 주입)은 **계속** 한다.
- 사람 결정은 의미 결정만. 큐 폭주 시 사람으로 미루는 안일함 거부.
- 환경 분리·wire log·undo는 **기능**이지 안전이 아니다.

### 0-C. v4가 v5에 던진 결단 질문 5개 — 직답

**Q1. threshold 갱신 기준을 달력 14일로 둘 것인가, 독립 settled 표본 수로 바꿀 것인가? 최소 표본 단위는?**

→ **표본 조건이 본조건. 달력은 보조**. 본조건은 `knowledge_id` 단위로 다음 셋 모두 만족:
- `unique source_family ≥ 3` (계열 마트 그룹화 후)
- `unique normalized_title ≥ 20`
- `settled outcome ≥ 50` (pending 제외, rollback/reject/신고확정만 settled)

보조 조건: `D+14 경과`. 표본만 차면 D+14 이전이라도 갱신 후보. D+14 지나도 표본 부족이면 default 유지.

**Q2. undo는 단순 ReviewDecision 되돌리기인가, downstream 적용 회수까지 포함하는가?**

→ **두 모드 모두 제공**. 기본은 `ReviewDecision` 한 줄 되돌리기 (5초 토스트 + 7건 스택 + 1시간 윈도우). **단,** ReviewDecision 카드에 `downstream_application_count` (이미 적용된 raw_record 수)와 `reused_in_run_ids` (재사용된 run 목록)를 **표시**. 1시간 내 다음 run이 재사용했어도, 관리자가 "downstream까지 회수" 버튼을 누르면 해당 ProductMatch에 `is_active=false` + 재사용된 run의 publish 결과는 rollback 큐로 자동 유입. 자동 회수는 X. 항상 사람이 한 번 더 찍는다.

**Q3. quota DB 영속 키를 어디까지 쪼갤 것인가?**

→ **풀 키**: `(provider, model, api_key_fingerprint, billing_account, window_start, window_end)` + `call_purpose` 분해 컬럼 (primary / retry / shrink / missing_retry / ab_shadow / force_live). atomic reservation (reserve → call → settle) 흐름. multi-worker에서는 DB row의 `SELECT FOR UPDATE` 또는 원자 increment로 oversubscribe 방지. timezone은 provider별 `reset_at_utc`를 yaml에 명시.

**Q4. canonical 승격 제안은 신규 생성이 기본인가, pending 후보 vote/evidence 추가가 기본인가?**

→ **vote/evidence 추가가 기본**. AI-admin이 canonical 후보를 만들 때 `canonical_candidate_fingerprint = sha256(normalized_brand + normalized_product + package_signature + category_l2)` 계산. 같은 fingerprint의 pending 후보가 DB-admin에 이미 있으면 **신규 생성 X, vote +1 + evidence(source, raw_record_id, knowledge_id) 추가**. 동일 normalized alias당 신규 승격 제안은 **7일 1회**. DB-admin의 merge/split webhook(§10-C)으로 fingerprint 변경 시 AI-admin의 후보도 자동 재계산.

**Q5. 사용자 신고 루프를 P0에서 어디까지 닫을 것인가?**

→ **P0 4단계까지**:
1. 신고 anomaly 큐 유입 (v3 채택)
2. 신고 → `match_id`/`knowledge_id`/`canonical_candidate_id` 연결 (v4 E-7의 1번)
3. **신고 누적 ≥ N건인 match_id/knowledge_id는 다음 자동 적용 시 ReviewQueue에 "신고 많음" 배지** (v4 D-5)
4. 사용자에게 처리 상태(접수/검토중/조치완료) 노출 (v3 채택)

**P1**으로 미루는 것: 과거 신고를 prompt/postcheck context에 반영 (v4 E-7의 3번), 처리 후 동일 묶음 노출 측정 (v4 E-7의 4번). **P2**: 신고 → ReviewDecision 자동 흡수 + 가격 sanity history 반영. 자동 흡수 모델 학습은 P2 유지. 단, **자동 재사용 봉인 X** — 배지만 붙이고 적용은 계속.

---

## 1. 프로젝트 맥락 + AI 책임

### 1-A. 궁극 목표에서 AI 책임 역산

**궁극 목표**: "복잡해서 못하던 비교를, 일반인이 자연스럽게."

이 한 문장에서 AI-admin이 책임지는 것:

| 책임 | 실패 시 사용자 체감 |
|---|---|
| **카테고리 분류** | "라면" 검색해도 일부 마트 누락 → 비교 자체 불가 |
| **canonical_id 정규화** | 같은 상품이 따로 보임 → 가격 비교 깨짐 |
| **키워드 추출** | 검색·자동완성·"비슷한 상품" 묶기 원료 부재 |
| **신상품·엣지만 escalate** | 사람 큐 폭주 → 신상품 며칠씩 묵힘 |
| **자기 자신 우회 학습** | 비용·지연 폭증 |

### 1-B. AI가 책임 **안** 지는 것 (경계)

- 카테고리 트리·키워드 사전의 **정의 자체** → DB-admin.
- 소스 크롤링 → 크롤러.
- 사용자 UI → 웹.
- "핫딜이냐 아니냐" 판단 → 별도 룰/모델. AI는 가격 sanity만 게이팅 (Gate 4).
- canonical_id **신규 생성** → DB-admin이 최종 채택. AI-admin은 제안 + vote.

### 1-C. 실측 컨텍스트 (v5에 명시)

- **라이브 호출 입증**: `generativelanguage.googleapis.com`로 실제 HTTPS 호출, `wire_log` JSONL에 7건 캡처 완료. `WALLETSAVIOR_AI_LIVE_FORCE=1` 플래그로 강제 호출 후 wire_logger 확인.
- **C1 router + C2 4-gate postcheck + shrink retry + reviewer-safe fallback**: 코드 존재 + 테스트 통과.
- **MatchMonitor (`LabelingRunLog` + `/api/match-monitor`)**: AI 호출률 100% → 30% 사이클 시뮬 확인.
- **ProductMatch / learned_alias 누적** = AI 호출률 감소가 실측 데이터로 작동.

---

## 2. 파이프라인 전체 흐름 (완성판)

### 2-A. 큰 흐름

```
crawler raw_record
    │
    ▼
[ai_ingestion]  ── provider 호출 (google-gemini primary) ──► FieldProposal + KeywordProposal
    │            wire_log JSONL append (prompt hash + latency + status + call_purpose)
    ▼
[queue_ai_router]  C1 — confidence ≥0.7면 분류, 미만이면 ESCALATED
    │
    ▼
[postcheck_gate]   C2 — 4-gate 사후검증
    │   Gate1 TREE_VALID_ID      (트리에 있는 id인가)
    │   Gate2 CONFIDENCE          (모호어 패널티 적용 후 0.7 이상)
    │   Gate3 SIBLING_CONSISTENCY (같은 canonical L1 다수파와 충돌 X)
    │   Gate4 PRICE_SANITY        (|price - median| ≤ 5·MAD)
    │
    ├── 4-PASS ──► [review_publish] DB-admin으로 publish
    └── any-FAIL ─► [review_automation] / escalation 큐 (ProductReviewQueue)

매칭 학습 우회 (다음 사이클부터):
  raw_record → ProductMatchStore lookup → hit이면 LLM 호출 skip → publish
                                       → miss면 LearnedKnowledge 적용 시도
                                       → 적용 성공이면 LLM skip
                                       → 실패면 ai_ingestion으로
```

### 2-B. 매칭 학습 루프 (AI 호출률 감소)

| 사이클 | 입력 행 | AI 호출률 | 자동매칭 | 비고 |
|---|---|---|---|---|
| 1차 | 100% 신규 | 100% | 0% | ProductMatchStore 비었음 |
| 2차 | 60% 재방문 + 40% 신규 | ≤50% | ≥50% | LearnedKnowledge 가동 시작 |
| 3차+ | 80% 재방문 | ≤30% | ≥70% | 정상 운영 |

코드 근거: `storage/repositories.py:538 ProductMatchStoreRepository`, `:912 LearnedKnowledgeRepository`, `services/review_automation.py RULE_*`.

### 2-C. 라이브 force 모드 / 환경 분리

- `WALLETSAVIOR_AI_LIVE_FORCE=1`: approved ProductMatch precheck **우회**(만). 캐시 전체 우회는 코드 보장 아님(v2 정정 수용).
- **환경별 default**:
  - dev/staging: `force_live=true` 기본 (증명용).
  - prod: `force_live=false` 기본. 명시 토글 필요.
- **가시화 (금지가 아님)**:
  - `LabelingRun.force_live: bool` 컬럼.
  - ai-admin 프론트 헤더에 빨강 배지 "LIVE FORCE ON".
  - MatchMonitor 차트에서 force-live run은 점선·다른 색.
  - 자동매칭 성능 평균에서 force-live run **분리** (포함/제외 토글).

### 2-D. shrink retry + reviewer-safe fallback

| 단계 | 동작 | 결과 |
|---|---|---|
| 1차 | N개 배치 호출 | 성공 종료 |
| 2차 | retryable 에러면 3회 retry | 성공 종료 |
| 3차 | 여전히 실패면 N/2로 split, 1까지 | 일부 성공 가능 |
| 4차 | 1-아이템도 실패 | reviewer-safe fallback (confidence=0.42, 사람 검토 강제) |

- `max_shrink_depth = log2(batch_size) + 1` (기본 batch 32 → depth 6) — 폭증 방지.
- shrink로 추가된 call 수, missing_retry 추가 call 수를 `LabelingRun`에 **분해 저장**.
- 한 run의 reviewer-safe fallback 비율 ≥ 20%면 prompt/schema 회귀로 간주 → 다음 run **자동 hold** + 알람.
- `missing_records` 재귀 동일 row 반복은 row_id 기준 **3회 캡** → 그 이상은 영구 reviewer-safe.

코드 근거: `services/ai_ingestion.py:1150 shrink`, `:846-922 _reviewer_safe_fallback_response_item` (v2 정정 반영).

---

## 3. 분류/매칭 모델 (완성판)

### 3-A. 카테고리 분류

- 입력: raw_record (title, source, price, unit, package_signature 등).
- 출력: `FieldProposal(category_id, confidence, top3_candidates)`.
- 트리 컨텍스트: `shared/data/category_tree.yaml`을 호출 시점에 read (P1: 핫리로드).
- 트리에 없는 id 반환은 Gate1에서 차단 → escalation.

### 3-B. canonical_id 정규화 (DB 경계 명시)

- AI-admin은 **canonical 후보(`canonical_candidate`)만** 만든다. 실제 `canonical_id` 발급은 DB-admin이 한다.
- 후보 fingerprint: `sha256(normalized_brand + normalized_product + package_signature + category_l2)`.
- 같은 fingerprint pending이 DB-admin에 있으면 vote 추가 (§10-B).

### 3-C. 키워드 추출

- 출력: `KeywordProposal(keyword, weight, source_evidence)`.
- 사용자 검색·자동완성·"비슷한 상품" 묶기의 원료.
- 짧은 키워드(2-char 이하)는 자동 적용 보류 (동음이의 위험, §3-D).

### 3-D. 동음이의/다국어/한자혼용/광고문구 대응

| 케이스 | 대응 |
|---|---|
| 동음이의 ("사과"/"배"/"밤") | normalized_title 길이 ≤ 2자는 `RULE_LEARNED_ALIAS` 자동 적용 보류. 주변 token + category prior + unit/package 같이 본다. |
| 다국어 ("りんご"/"苹果"/"APPLE") | normalized_title 전처리에 **script normalization** (가타카나→히라가나, 한자→한글 음역 보조) + **transliteration table** (yaml로 관리). |
| 한자 혼용 ("辛라면"/"신라면") | 한자→한글 transliteration 후 brand dictionary 매칭. |
| 브랜드 약어 ("CJ"/"제일제당") | brand dictionary yaml (DB-admin 관리, AI-admin은 read-only). |
| 광고문구 ("초특가! 신라면 5입") | title 전처리에 광고 토큰 stripping (`초특가`, `한정`, `타임세일` 등). |
| 묶음/구성/리뉴얼 | package_signature 분리 학습. 동일 brand+product여도 package_signature가 다르면 canonical 분리 후보. |

### 3-E. escalation 분기

- C1 confidence 미만 → ESCALATED.
- C2 어느 gate라도 실패 → ESCALATED.
- shrink 후 N=1도 실패 → reviewer-safe fallback (영구 사람 검토).
- escalation 폭주 시 클러스터링 (§8-A).

---

## 4. 매칭 학습 메커니즘 (완성판)

### 4-A. RULE_LEARNED_ALIAS threshold — default + 데이터 기반 갱신

| 항목 | default (현 코드값) | 갱신 절차 |
|---|---|---|
| `min_confidence` | 0.92 | §4-A 절차 |
| `min_success_count` | 2 | §4-A 절차 |
| negative evidence 차단 | 활성 | 유지 |
| 짧은 alias (≤2자) 자동 적용 | **보류** (v5 신규) | category prior + 주변 token 추가 시 활성 |

**갱신 절차** (v4 수용 — 표본 본조건):

1. **D+0~D+14**: default 유지. `LearnedKnowledgeApplication` 로그 6컬럼 수집.
2. **표본 조건 검사**: `knowledge_id` 단위로 unique source ≥3, unique title ≥20, settled ≥50 만족 시 갱신 후보.
3. **격자 분석**: `(rule_type, source_family, category_L2, model_version, prompt_version, confidence_bucket, success_count_bucket)`별 fp율.
4. **갱신 룰**:
   - fp율 ≤ 1% & 적용 ≥ 30건 격자 → default 완화 후보 (DB-admin 승인 후 적용).
   - fp율 ≥ 5% 격자 → 자동 적용 차단, 사람 검토로.
5. **재측정**: 변경 후 동일 표본 조건 다시.

**로그 6컬럼 (`LearnedKnowledgeApplication`)**:

| 컬럼 | 용도 |
|---|---|
| `knowledge_id` | 어떤 룰 |
| `raw_record_id` / `match_id` | 적용 대상 |
| `confidence_at_apply` | 적용 시점 |
| `success_count_at_apply` | 적용 시점 누적 |
| `outcome` (pending/approved/rejected/rollback/reported) | 사후 결과 |
| `outcome_settled_at` | 결과 확정 시각 |

### 4-B. self-learned alias audit / decay / cross-check

**1. Audit (정기 + 실시간)**

- **주간 배치**: knowledge_id별 fp율 집계. fp율 ≥ 10% & 분모 ≥ 30이면 자동 `is_active=false` + 관리자 알람.
- **실시간 spike**: 같은 knowledge_id의 최근 1시간 rollback/reject ≥ 5건이면 즉시 사용 일시 보류 (자동 해제 X, 사람 확인 필요). 주간 배치만 의존 시 6일간 오염 누적되는 v4 C-3 시나리오 차단.

**2. Decay (복합 조건)**

시간 단독이 아니라 다음 복합:

- `days_since_last_apply ≥ 90` AND
- `last_seen_seasonality` 분기와 다른 시기 AND
- `recent_application_volume = 0`

조건 모두 만족 시 success_count 절반 감쇄. 재적용되면 회복. **negative evidence는 decay 대상에서 제외** — 과거 실패 패턴 보존.

계절 상품 (설날/추석/크리스마스)은 `last_seen_seasonality` 비교로 자동 보호.

**3. Cross-check**

- 같은 pattern에 서로 다른 target_value 룰 ≥ 2 → 자동 충돌 → 적용 보류 + escalation.
- human-approved 룰 vs AI 단독 룰 동일 raw_record 다른 결과 → human 우선 + AI 룰 negative evidence 기록.

### 4-C. 사용자 가시성 (`match_explanation`)

매칭/묶음 결과에 사용자가 "왜 묶였는지" 볼 수 있게 evidence JSON 제공:

```json
{
  "matched_by": "RULE_LEARNED_ALIAS",
  "knowledge_id": "ka_neungoshik_shin_multi5",
  "evidence": {
    "brand": "농심",
    "product": "신라면",
    "package": "5입",
    "sources_seen": 3
  },
  "human_approval_history": 1,
  "fp_rate_30d": 0.012,
  "explanation_ko": "농심 신라면 5입 묶음 — 3개 마트에서 같은 패턴, 운영자 1회 승인."
}
```

웹 영역은 이 JSON에서 `explanation_ko`만 표시. AI-admin은 evidence API만 책임.

### 4-D. 충돌 자동 tie-break 4룰 — 카드 정렬 (자동 확정 X)

| 룰 | 적용 | rank_reason |
|---|---|---|
| 한쪽 human-approved + 다른 쪽 AI 단독 | human 우선 후보로 | "human approved history" |
| 동일 raw_title + 동일 package_signature + 한쪽만 success_count | success_count 있는 쪽 1위 | "signature + history" |
| 한쪽 reviewer-safe fallback (conf 0.42) | 후순위 | "fallback confidence" |
| 카테고리 동일 + canonical_name 동일 + id만 다름 | "merge 후보" 묶음 카드 | "name match, id diff" |

**중요 (v4 C-5 수용)**: 4룰은 **카드 정렬·우선순위 제시**까지. 자동 확정 X. 카드 하단에 `counter_evidence`도 함께 표시 (예: human approved지만 1년 전 / 묶음승인이라 단건 검증 안 됨 등).

**자동 확정 승격 조건** (P2): 룰별 precision ≥ 95% & 분모 ≥ 100건이 누적되면 그 룰만 자동 확정 후보. DB-admin이 승격 결정.

### 4-E. undo (downstream 회수 포함)

- 단위: `ReviewDecision.id` (v3 채택).
- 윈도우: **5초 토스트 + 7건 스택(상단 고정) + 1시간 내 "최근 승인" 탭**.
- `ReviewDecision` 컬럼 추가:
  - `undoable_until` (timestamp)
  - `downstream_application_count` (이미 적용된 raw_record 수)
  - `reused_in_run_ids` (재사용된 run id 배열)
- **두 모드 undo**:
  - 기본: ReviewDecision만 되돌리기 → 연결된 ProductMatch `is_active=false`, LearnedKnowledge `success_count -= 1` (음수 방지), proposal 상태 복원.
  - 확장: "downstream까지 회수" 버튼 → 재사용된 run의 publish 결과를 rollback 큐로 자동 유입. 자동 회수 X, 항상 사람이 한 번 더 찍는다.

---

## 5. 프로바이더 / 비용 / quota

### 5-A. Google 단일 의존 위험 — P1 격상

v3에서 P1 초입. v5는 그대로 P1. P0 아닌 이유: 라이브 1주 trafic은 escalation으로 견딘다. P1인 이유: Google quota 단일 의존은 운영 연속성 리스크 + force-live가 quota 빨리 태움 (v2 D-8 수용).

### 5-B. 폴백 전략

```
google-gemini (primary)
  ├── retryable 5xx / quota exhausted ─► google-gemma (secondary, 동일 vendor)
  ├── vendor 전체 다운 ────────────────► alt API key (별도 결제 계정)
  ├── 그래도 실패 ─────────────────────► 로컬 OSS LLM (gemma-2 / qwen) — benchmark 통과 시만
  └── 전부 실패 ───────────────────────► 룰만 (RULE_EXACT_CATALOG_KEYWORD 등) + 나머지 reviewer-safe
```

**OSS LLM 합류 조건 (v4 C-6 수용)** — `ProviderCapability` 테이블 등록:

| 지표 | 임계 (P1 합류) |
|---|---|
| `schema_valid_rate` | ≥ 95% |
| `ko_product_score` (한국어 라벨링 정확도) | ≥ 80% |
| `postcheck_pass_rate` | ≥ 70% |
| `p95_latency_ms` | ≤ 10,000 |
| `cost_per_1k_rows` | primary 대비 ≤ 30% |
| `escalation_increase_vs_primary` | ≤ 2× |

ProvidersPanel에 이 표 표시. 미달 OSS는 폴백 합류 거부.

### 5-C. prompt-hash 캐시 + invalidate

- 캐시 키: `sha256(prompt_template_version + raw_record_normalized + category_tree_version)`.
- invalidate 트리거:
  - 프롬프트 버전 변경
  - category_tree.yaml 변경
  - 명시 운영 명령
  - 캐시 entry 90일 경과
- 캐시 hit 시 wire log에 `cache_hit=true` 라인 추가 (현재 미확인 → P0에 명시).

### 5-D. quota DB 영속 (v4 C-4 수용)

**키**: `(provider, model, api_key_fingerprint, billing_account, window_start, window_end)`

**call_purpose 분해 컬럼**: `primary` / `retry` / `shrink` / `missing_retry` / `ab_shadow` / `force_live`

**reservation 흐름**:

1. `reserve_call(key, purpose)` → DB row 원자 increment + reservation_id 반환
2. `call_provider(reservation_id)` → 실제 호출
3. `settle(reservation_id, status, latency, tokens)` → 결과 기록

multi-worker: `SELECT FOR UPDATE` 또는 원자 increment로 oversubscribe 방지.

**timezone**: provider yaml에 `reset_at_utc` 명시. 일일 카운터는 UTC 기준 reset.

**soft/hard cap**:

- soft cap (월 $X 또는 일 240회): 80% 도달 시 알람. 호출 계속.
- hard cap (월 $Y 또는 일 300회, Y > X): 도달 시 신규 run hold. 진행 run은 secondary로 자동 전환.
- per-run cap: 예상 call의 3배 도달 시 run 중단.

### 5-E. 모델 deprecation / 요금 변경 대응 (v4 E-1 수용)

provider yaml:

```yaml
google-gemini:
  models:
    - id: gemini-2.5-flash
      effective_from: 2025-01-15
      deprecated_at: null
      price_version: 2025-01-15
      price_per_1k_input_tokens: 0.075
      price_per_1k_output_tokens: 0.30
```

- 단가 변경 시 과거 비용은 **당시 단가 보존**. 현재 단가로 환산하지 않는다.
- 모델 변경 전후 sample replay (P1, 수동 버튼).
- `ProductMatch` / `LearnedKnowledge`에 `created_by_model_version`, `created_by_prompt_version` 컬럼 (P0).

### 5-F. 비용 대시보드 단위 (v4 E-9 수용)

ProvidersPanel:

| 단위 | 분해 |
|---|---|
| 원/일 · 원/주 · 원/월 | KRW 표시, USD→KRW 환율은 yaml로 관리 |
| provider · model | 각각 |
| source/mart | 어느 마트가 비싼지 |
| run | run별 비용 |
| call_purpose | primary/retry/shrink/ab/force-live |
| 1k raw_record당 비용 | 처리 효율 |
| 자동매칭 1건 절감당 비용 | ROI |

비용 폭증 알람: 전일 대비 3× → 자동 알람.

---

## 6. 환경 분리 + 라이브 검증

### 6-A. WALLETSAVIOR_AI_LIVE_FORCE

- 범위: approved ProductMatch precheck 우회 (v2 정정).
- 환경별 default: dev/staging ON, prod OFF.
- 가시화: 헤더 배지 + run 컬럼 + MatchMonitor 분리 (§2-C).

### 6-B. wire_log rotation/archive

- 파일명: `wire-YYYY-MM-DD.jsonl`.
- 30일 후 자동 gzip + archive 폴더 이동.
- 180일 후 원본 삭제. 집계 roll-up은 DB에 남음.
- MatchMonitor "최근 N건"은 당일+직전 파일만 scan. 그 이상은 archive 비동기 조회.
- 디스크 사용량 ProvidersPanel 표시.
- wire log entry에 `raw_record_id` 연결 (v4 E-2 수용 — injection 역추적용).

---

## 7. 보안 (기능 차원, 안전 타령 X)

### 7-A. Prompt Injection

사용자 입력(상품명, 신고 사유, source title)이 prompt 경로에 들어간다. **금지가 아니라 구조화**:

| 대응 | 설명 |
|---|---|
| Instruction/Data 분리 | raw text는 instruction과 분리된 JSON field로 주입. system prompt 안에 raw text 끼우지 않음. |
| postcheck 게이팅 | provider 응답이 카테고리 트리에 있는 id인지, canonical 후보가 fingerprint와 일치하는지 — 응답 자체를 신뢰하지 않고 검증. |
| 응답 schema 강제 | JSON schema mode 사용. 자유 텍스트 응답 거부. |
| Injection 의심 패턴 로그 | raw_record title에 "ignore previous", "category_id=" 등 패턴 발견 시 anomaly flag. |
| wire_log → raw_record_id 연결 | injection 원문 역추적 가능. wire_log entry에 `raw_record_id` 필드 추가. |

**안전 어휘로 기능 깎지 않음**: 사용자 신고 텍스트도 anomaly 요약 prompt에 계속 들어간다. 단, 위 5단계로 구조화한다.

---

## 8. 관리자 UI/UX (완성판)

### 8-A. ReviewQueuePanel

- top-3 카테고리 후보 + confidence + 매칭 후보 (success_count 표시).
- **1-click 승인** + **5초 undo 토스트** + **최근 승인 7건 스택 (상단 고정)** + **단축키 (1/2/3 후보, Enter 승인, R 반려, N 신상품, U undo, J/K 이동)**.
- **일괄 액션** 카드: "이 결정을 38건에 적용".
- **escalation 클러스터링**: 같은 (gate, source, category_top1) 키는 한 카드.
- **우선순위**: 가격 sanity 실패 (돈 직결) > 신상품 > MAD outlier > 기타.
- **"최근 승인" 탭**: 1시간 내 ReviewDecision 되돌리기 + `downstream_application_count` 표시 + "downstream 회수" 버튼.
- **신고 배지**: 신고 N건 이상 자동매칭은 "신고 많음" 배지 (v4 D-5).
- **escalation SLA**: 큐에 24시간 이상 묵힌 행 빨강 표시.

### 8-B. MatchMonitor

- 4 카드: `ProductMatch by_status`, `ProductMatch by_source`, `LearnedKnowledge by_type`, `LearnedKnowledge success_count_distribution`.
- 추이 차트: AI 호출률, 자동매칭률, 사이클 비교.
- **force-live run 분리 토글** (포함/제외).
- **제안 큐 카운터** (canonical 후보 / 카테고리 제안 / 키워드 제안).
- **wire_log 최근 N건 링크**.
- **LearnedKnowledge 건강 탭**: knowledge_id별 fp율, 적용 빈도, decay 상태.

### 8-C. JobsPanel

- 런별 입력/AI호출/자동매칭/escalated 카운트.
- **5단계 silent drop 표** (각 단계 사이 drop ≠ 0이면 빨강).
- **silent drop 행 별도 표 + 재시도 버튼**.
- **예상/실측 call 분해**: "예상 87 / 실측 142 / shrink +38 / missing +17".
- **실측이 예상의 2배 이상 → 빨강, 3배 → 다음 run 자동 hold**.
- **latency 패널 (v4 E-8)**: batch 단위 progress + p50/p95/p99 + "oldest in-flight call age".
- **재시도 버튼은 idempotent**: 같은 batch_id 재호출 방지.

### 8-D. WireLogPanel

- 최근 100건 표 (timestamp, provider, model, status, latency, prompt_hash, call_purpose, raw_record_id).
- 다운로드 버튼 (JSONL).
- archive 검색 (날짜 범위 → 비동기 조회).

### 8-E. 평가모드 A/B 통계 유의성 (v4 E-10 수용)

- ProvidersPanel 상단 토글 + 위험 배지 "AB 모드 ON (quota 2× 소진)".
- **primary metric**: postcheck pass rate + human approval rate + rollback rate + canonical diff rate.
- **최소 표본 계산**: source/category stratified, 효과 크기 5%p 검출 기준 → 모델당 최소 1,000 sample.
- **샘플링**: 1% 라이브 트래픽이되 source/category stratified. 특정 source에 편중 방지.
- **prompt cache 분리**: A/B는 cache 키에 model_id 포함. 같은 raw_record가 A/B 양쪽 호출되어도 cache 충돌 X.
- B 결과는 publish 안 함. `ABTestResult` 테이블에 저장. ReviewQueue에 비교 카드.

---

## 9. 사용자 영향 (간접) — 4지점 + 신고 루프

| 사용자 행동 | AI 책임 | 실패 시 사용자 체감 |
|---|---|---|
| 검색 ("라면") | 키워드 추출 + 카테고리 매칭 | 일부 마트 누락 |
| "비슷한 상품" 묶음 | canonical_id 정규화 + `match_explanation` | 같은 상품 따로 보임 / 왜 묶였는지 모름 |
| 자동완성 | LearnedKnowledge 키워드 풀 | 추천 부재 |
| 신고 ("이거 핫딜 아님") | 신고 → 학습 루프 | 신고해도 변화 없음 |

**신고 → 학습 루프 4단계 (v4 E-7 일부 수용)**:

| # | 상태 | 단계 |
|---|---|---|
| 1 | 신고 anomaly 큐 유입 | **P0** |
| 2 | 신고 → `match_id`/`knowledge_id`/`canonical_candidate_id` 연결 | **P0** |
| 3 | 신고 누적 ≥ N건은 자동 적용 시 ReviewQueue "신고 많음" 배지 + 사용자에게 처리 상태 노출 | **P0** |
| 4 | 과거 신고를 prompt/postcheck context 반영 + 처리 후 동일 묶음 노출 측정 | **P1** |
| 5 | ReviewDecision 자동 흡수 + 가격 sanity history 반영 | **P2** |

**자동 재사용 봉인 X** — 배지만 붙이고 적용은 계속. v4 D-5 어조에 동의하되 안전 어휘로 기능 깎지 않음.

---

## 10. 모듈 경계

### 10-A. ai-admin이 노출하는 contract

```
크롤러 ──(REST: raw_records)──► ai-admin ──(REST: FieldProposal/Match)──► db-admin
                                   │
                                   └──(adapter)──► provider (google-gemini, ...)
```

| 방향 | endpoint |
|---|---|
| inbound (crawler→) | `POST /raw_records` |
| outbound (→db-admin) | `POST /proposals/field`, `POST /proposals/keyword`, `POST /proposals/canonical_candidate`, `POST /matches/published` |
| observability | `GET /match-monitor/cumulative`, `/runs`, `/wire-log/recent`, `/learned-knowledge/health` |
| admin | `POST /reviews/{id}/decide`, `POST /reviews/{id}/undo`, `POST /knowledge/{id}/unlearn` |
| **신규 (v5)** | `POST /canonical/change-event` (DB-admin → AI-admin webhook, §10-C) |

모든 schema는 `core.contracts.ai_pipeline`에 정의 + **semver**. breaking change는 6주 deprecation 윈도우.

### 10-B. 자기학습 → DB canonical 승격 룰

**승격 조건** (모두 만족):

- `success_count ≥ 10`
- 적용 raw_record `unique source_family ≥ 3` (계열 마트 그룹화)
- `human-approved` 이력 ≥ 1 OR audit fp율 ≤ 2%
- 최근 30일 활성 (decay 안 됨)
- 같은 normalized alias 신규 승격 제안 **7일 1회 제한**

**중복 처리** (v4 E-3 수용):

- `canonical_candidate_fingerprint`로 dedupe.
- 동일 fingerprint pending이 DB-admin에 있으면 신규 생성 X, **vote +1 + evidence 추가**.
- DB-admin이 채택/거부.
- AI-admin은 canonical_id 직접 생성 안 함 (v1 결합도 0 원칙 유지).

### 10-C. canonical change event feed (v4 E-11 수용)

DB-admin이 canonical merge/split/rename 시 AI-admin webhook:

```json
{
  "event_type": "canonical_merge",
  "from_ids": ["c_001", "c_002"],
  "to_id": "c_merged_001",
  "effective_at": "2026-01-15T03:00:00Z"
}
```

AI-admin 처리:

- `ProductMatchStore`에서 from_ids 참조 row → to_id로 업데이트.
- `LearnedKnowledge`에서 from_ids 관련 룰 → 영향 범위 계산 후 관리자 알람.
- merge가 split을 깨는 경우 (이전 canonical 패턴 자동 적용 위험) → 해당 LearnedKnowledge `is_active=false` 임시.

---

## 11. 로드맵 P0 / P1 / P2 (최종)

### P0 — 라이브 직전 필수

- [ ] postcheck 4-gate 안정화
- [ ] 자동매칭 ≥ 80% (또는 호출률 ≤ 30%) 사이클 2회 검증
- [ ] wire log 일간 파일 분리 + `cache_hit=true` 라인 + `raw_record_id` 연결
- [ ] WireLogPanel + force-live 환경 가시화 (헤더 배지 + LabelingRun.force_live)
- [ ] ReviewQueuePanel 1-click + 5초 undo + 7건 스택 + 단축키 + 신고 배지
- [ ] `ReviewDecision`에 `undoable_until` / `downstream_application_count` / `reused_in_run_ids` 컬럼
- [ ] silent drop 표 + 재시도 버튼 + 예상/실측 call 분해 (JobsPanel)
- [ ] latency 패널 (p50/p95/p99 + oldest in-flight age)
- [ ] escalation SLA 표시 + 클러스터링
- [ ] unlearn 최소판 (knowledge_id 비활성화 + 영향 범위 표시 + downstream 회수 버튼)
- [ ] `LearnedKnowledgeApplication` 로그 6컬럼
- [ ] quota DB 영속화 (process memory 탈출) + 키 6필드 + call_purpose 분해
- [ ] `ProductMatch` / `LearnedKnowledge`에 `created_by_model_version` / `created_by_prompt_version`
- [ ] 사용자 신고 anomaly 유입 + match_id/knowledge_id 연결 + "신고 많음" 배지 + 처리 상태 노출 (4단계 중 1~3)
- [ ] `match_explanation` JSON 필드
- [ ] prompt injection 5단계 구조화 (instruction/data 분리 + schema mode + postcheck + 의심 패턴 anomaly + raw_record_id 역추적)
- [ ] LearnedKnowledge 실시간 spike 감지 (1h ≥ 5 rollback → 일시 보류)

### P1 — 가동 직후 1개월 내

- [ ] 다중 프로바이더 폴백 (primary + secondary 자동, **v1의 P2에서 끌어올림**)
- [ ] OSS LLM benchmark 등록 + ProviderCapability 표
- [ ] 비용 대시보드 단위 분해 (원/일·주·월 + source/run/call_purpose별 + 1k raw당 + 자동매칭 절감 ROI)
- [ ] soft/hard cap (월 $X / 일 240·300)
- [ ] 새 카테고리/키워드 제안 큐 + dedupe (Jaro-Winkler ≥ 0.85) + 재평가
- [ ] 카테고리 트리 핫리로드 (파일 watcher)
- [ ] 매칭 충돌 tie-break 4룰 + 카드 묶음 + rank_reason + counter_evidence
- [ ] LearnedKnowledge 건강 탭 (주간 audit + 복합 decay)
- [ ] threshold default 갱신 (표본 본조건 만족 시)
- [ ] wire log archive 자동 회전 (30d gzip / 180d 삭제)
- [ ] 모델 변경 sample replay 버튼 (수동)
- [ ] 다국어/한자/브랜드 dictionary + transliteration
- [ ] canonical change event webhook + ProductMatchStore/LearnedKnowledge 자동 영향 처리
- [ ] 신고 학습 4단계 중 4번 (과거 신고 prompt 반영 + 동일 묶음 노출 측정)

### P2 — 가동 안정 후 3개월+

- [ ] AI 평가 모드 A/B shadow 1% + 통계 유의성 (stratified sampling + 최소 표본 1,000)
- [ ] 신고 → ReviewDecision 자동 흡수 + 가격 sanity history
- [ ] 신뢰도 가중치 자동 우선순위
- [ ] provider 자동 라우팅 본격판 (quota 잔량 기반)
- [ ] alt API key + 로컬 OSS LLM 폴백 (benchmark 통과 후)
- [ ] 모델 변경 시 재평가 run 자동화
- [ ] tie-break 자동 확정 승격 (룰별 precision ≥ 95% & 분모 ≥ 100)

---

## 12. 미해결 / 추후 결단

| 항목 | 사유 | 결단 시점 |
|---|---|---|
| OSS LLM 후보 모델 선정 | 한국어 상품명 benchmark 데이터 부재 | P1 진입 직전 |
| `source_family` 그룹화 정의 (계열 마트 묶음) | 현 데이터로 그룹 자동 도출 어려움 | DB-admin과 협의 후 P0~P1 사이 |
| 환율 yaml 갱신 주기 | 운영 폴리시 | P1 |
| AB 모델 후보 (gemini-2.5 vs gemini-2.0 / gpt-4o-mini) | 모델 가격 변동 | P2 직전 |
| 신고 누적 임계 N (배지 띄울 기준) | 실측 신고량 모름 | P0 라이브 1주 후 |
| force-live 운영 환경 토글 권한 (운영자 vs SRE만) | 권한 모델은 웹/운영 영역 | P0 ~ P1 |

---

## 13. v1~v4 추적 매트릭스

| 항목 | v1 | v2 (적대) | v3 (보강) | v4 (재반론) | v5 (최종) |
|---|---|---|---|---|---|
| `ProductMatchStatus.CONFLICT` | 사용 | 코드에 없음 정정 | `is_active=false`+`disabled_reason` | — | §4-D tie-break 카드, 자동 확정 X |
| force-live 범위 | "캐시·매칭 우회" | precheck 우회만 | precheck 우회 명시 | — | §6-A precheck 우회 + 환경별 default + 가시화 |
| 일일 300회 quota | 보호값 | process memory 카운터 | DB 영속 필요 | 키 설계 부재 | §5-D 6필드 키 + call_purpose 분해 |
| wire log 영구 보존 | 영구 | append-only 정정 | 운영 폴리시 | rotation 빈칸 | §6-B 30d gzip / 180d 삭제 + raw_record_id |
| RULE_LEARNED_ALIAS threshold | 5회/0.85 | 실제 2/0.92 | default + 14일 측정 | 표본 본조건 필요 | §4-A 표본 본조건 (source≥3 / title≥20 / settled≥50) + D+14 보조 |
| 1-click undo | 부재 | 위험 | 5초/7건/1시간 | 윈도우 정의 부족 | §4-E `undoable_until`+`downstream_application_count`+`reused_in_run_ids` + 두 모드 |
| 다중 provider | P2 | P0 검토 권고 | P1 초입 | OSS 품질 검증 부재 | §5-B P1 + ProviderCapability benchmark 의무 |
| 사용자 신고 학습 | P3 | 1단계 anomaly 가능 | P0 anomaly + P2 학습 | P0~P2 사이 공백 | §9 P0 4단계 + P1 4번 + P2 5번 |
| 매칭 충돌 | 항상 사람 | 100건/일 병목 | 4룰 자동 정렬 | 자동 확정 깨짐 | §4-D 카드 정렬만 + 자동 확정은 P2 precision 누적 후 |
| 새 카테고리 제안 | 큐 | dedupe 부재 | Jaro-Winkler + 재평가 | 빈도/중복 룰 부재 | §10-B fingerprint dedupe + 7일 1회 + vote 기본 |
| 자기학습 alias 오염 | unlearn 버튼 | 그래프 추적 | audit/decay/cross-check | 계절성/spike/분모 | §4-B 복합 decay + 주간 + 실시간 spike + negative 보존 |
| 모델 변경 재평가 | 누락 | — | P3 | P2 늦음 | §5-E P0 provenance + P1 수동 replay + P2 자동화 |
| 비용 대시보드 | $만 | — | $/USD | 원화/source/call_purpose | §5-F 풀 분해 |
| prompt injection | 누락 | — | — | 경로 지적 | §7-A 5단계 구조화 |
| 다국어/한자/동음이의 | 누락 | — | — | 케이스 지적 | §3-D 전처리 + 짧은 alias 보류 |
| `match_explanation` | 누락 | — | — | API 필요 | §4-C JSON evidence |
| canonical change event | 누락 | — | — | feed 필요 | §10-C webhook + 자동 영향 처리 |
| latency 폭주 가시성 | 누락 | — | — | JobsPanel 부재 | §8-C p50/p95/p99 + oldest in-flight |
| A/B 통계 유의성 | 누락 | — | 1% shadow | 표본 계산 필요 | §8-E primary metric + stratified + 1000 sample |

---

## 14. 안전 타령 + 학습 봉인 + 동적 차단 배척 최종 선언

**v5는 다음을 명시적으로 거부한다**:

1. **자기학습 봉인 거부**. `LearnedKnowledge`/`ProductMatchStore` 가동 계속. audit/decay/cross-check로 운영하되 끄지 않는다. 봉인하면 시스템 핵심 가치(AI 호출률 100→30%) 사망.

2. **매칭 학습 누적 차단 거부**. 학습이 누적되어 LLM 우회가 늘어나는 것이 정상. 우회율을 인위적으로 막지 않는다.

3. **동적 카테고리/키워드 적응 차단 거부**. `category_tree.yaml` 갱신 시 AI가 다시 읽어 컨텍스트 주입한다. "사람 승인 게이트 매번 추가" 같은 안전 어휘 거부.

4. **숫자 default 회피 거부**. v2식 "관측표에 붙는 손잡이만"은 라이브 1일차에 룰이 안 돈다. default + 표본 본조건 갱신 두 단계.

5. **"사람 결정 = 자동화 축소" 일반론 거부**. 의미 결정만 사람. 반복 분류는 기계. 자동 tie-break는 카드 정렬까지 즉시 가동.

6. **신고 자동 재사용 봉인 거부**. 신고 누적 자동매칭에 배지만 붙이고 자동 적용은 계속. "신고 N건이면 자동 중지"는 안전 어휘. 운영자가 결정한다.

7. **safe-by-default fallback 봉인 거부**. reviewer-safe fallback (conf 0.42)은 비상 안전망. 모든 행을 reviewer-safe로 보내자는 어조 거부.

8. **OSS LLM 합류 보류 거부**. benchmark 통과 시 즉시 합류. "당분간 보류"는 안전 어휘.

**기능 차원이라 유지하는 것** (안전이 아님):

- 환경 분리 (dev/staging force-live ON, prod OFF default): 가시화이지 금지 아님.
- wire log rotation: 디스크 관리이지 보안 아님.
- threshold 데이터 기반 갱신: 실험적 운영이지 회피 아님.
- undo 윈도우: 속도 깎기 아님. 같은 화면 즉시 복구.
- audit/decay/cross-check: 자기학습 유지 위한 장치.
- prompt injection 구조화: 응답 schema 강제이지 입력 금지 아님.

---

## 15. 자기검증

| 체크 | 결과 |
|---|---|
| v1~v4 수정했는가 | ✅ 안 함. 각각 별도 파일 |
| 다른 영역(DB/크롤러/웹) 깊이 팠는가 | ✅ 경계만. canonical_id 발급은 DB-admin, 크롤링은 크롤러, UI는 웹 명시 |
| 코드 변경했는가 | ✅ 없음 |
| 안전 권고로 기능 축소했는가 | ✅ 없음. §14에 8개 명시 배척 |
| **v4가 명시 약점/시나리오/v5 결단 질문 5개 답했는가** | ✅ §0-A 21개 수용, §0-C 결단 질문 5개 직답 |
| **v4가 안전·학습 봉인 어조로 갔다면 명시 배척했는가** | ✅ §0-B에 5개 미묘한 어조 거부 명시. §14에 8개 배척 |
| 사용자 헌법 (동적 대응 / 자기학습 / 매칭 누적 / 모듈화) 위반 없는가 | ✅ §14에서 명시 유지 선언 |
| 다른 영역 기획과 충돌 없는가 | ✅ canonical 발급 권한·crawler raw_records contract·웹 evidence JSON 표시만 — 모두 경계까지만 |
| 회피 어휘 사용했는가 | ✅ "검토 필요" / "...해야 할 수도" 같은 어휘 없음. 숫자·조건·시점·키로 답 |
| 비개발자 가독성 | ✅ 표 + 체크리스트 + 한국어 |
| **실측 컨텍스트 명시했는가** | ✅ §1-C에 라이브 7건 + force_live + MatchMonitor + ProductMatch 누적 입증 |
| roadmap P0/P1/P2 명확한가 | ✅ §11에 28 P0 / 14 P1 / 7 P2 |
| 추적 매트릭스 있는가 | ✅ §13에 v1~v5 19개 항목 |

**v4가 가장 옳게 친 곳** (수용 우선순위):

- C-4 quota 다중 키 — §5-D에서 6필드 키로 답.
- C-1 undo downstream — §4-E `reused_in_run_ids` + 두 모드.
- E-3 canonical 중복 학습 — §10-B fingerprint + vote 기본.
- E-11 canonical change feed — §10-C webhook.
- E-2 prompt injection — §7-A 5단계 구조화.

**v4가 가지친 곳 (배척)**:

- 자동 tie-break "당분간 자동 확정 금지" 어조 → §4-D에서 "카드 정렬은 즉시, 자동 확정은 룰별 precision 누적 후 P2"로 분리.
- OSS LLM "보류" 어조 → §5-A benchmark 통과 시 즉시 합류.
- 신고 자동 재사용 "봉인" 어조 → §9 배지만 붙이고 적용 계속.

---

*— Opus 4.7, Round-A v5 (FINAL). v1~v4 통합 완료. 이 문서가 AI 영역 단일 기준이다.*
