# AI 영역 기획 v3 — Opus 살붙이기 (v2 적대적 검토 응답 + 본문 보강)

> 입력: `docs/planning/round-A/ai-v1-opus.md` (Opus 초안), `docs/planning/round-A/ai-v2-gpt.md` (GPT 적대적 검토)
> 원칙: v1·v2 절대 수정 금지. v3는 별도 파일. v2의 진짜 약점은 수용, 회피·떠넘김 어휘는 배척.
> 범위: `packages/ai-admin/` 만. 코드 변경 없음.

---

## 0. 한 줄 요약

> **"v1은 방향이 맞고 v2는 운영 디테일을 잘 짚었다. v3는 v2가 옳은 약점만 수용해 살을 붙이고, '숫자 고정 자체가 나쁘다' 같은 회피 어휘는 잘라낸다. 라이브 직전 P0를 좁히되, Google quota 단일 의존만은 P1로 끌어올린다."**

---

## 서문. v2 응답 정책

### 0-A. 수용 약점 (v2가 옳다)

| 항목 | v2 지적 | v3 수용 여부 |
|---|---|---|
| `ProductMatchStatus.CONFLICT` 코드에 없음 | 정확 | **수용**. v1 표현은 설계 제안이지 현 상태 아님. v3에선 `disabled_reason`/`is_active` 기반으로 표현 교체. |
| shrink 코드 위치 `:1397` 부정확 (실제 `:1150`) | 정확 | **수용**. 단순 라인 오류. |
| `WALLETSAVIOR_AI_LIVE_FORCE` 가 ProductMatch precheck 우회만 보장, "캐시·매칭 전체 우회"는 과장 | 정확 | **수용**. v3에서 표현 좁힘. |
| 일일 300회 한도가 process memory 카운터 — 재시작 시 0으로 초기화 | 정확 | **수용**. 영속 카운터(파일/DB roll-up) 필요. P1 항목. |
| wire log "영구 보존"이 코드 보장 아님 (append만) | 정확 | **수용**. rotation/archive 룰을 v3가 명시. |
| `learned_alias_min_confidence=0.92`, `min_success_count=2` 가 실제 값. v1 제안표는 감 | 정확 | **수용**. v1 표는 "라이브 측정 전 임시 가설"로 격하. |
| 1-click 승인 후 undo 윈도우 없음 | 정확 | **수용**. P0에 undo 5초 + 스택 7건 명시. |
| 매칭 충돌 100% 사람은 큐 폭주 시 병목 | 정확 | **수용**. 단, 자동화는 "후보 정렬·tie-break까지". 최종 merge/split는 사람. |
| 새 카테고리 제안 dedupe 부재 | 정확 | **수용**. P1로 끌어올림. |
| escalation 폭주 시 클러스터링 | 정확 | **수용**. gate별/source별 그룹화. |
| 사용자 신고 학습 3단계는 늦다 — 최소 anomaly 유입은 1단계 가능 | 정확 | **부분 수용**. "anomaly 유입 + 재검수 후보화"만 P0, 모델 학습은 P2 유지. |
| Google quota 단일 의존을 폴백 2단계로 미룬 건 운영 연속성 리스크 | 정확 | **수용**. P0는 아니되 **P1 초입**으로 끌어올림. |
| alias 오염 downstream 회수 (적용된 raw_record 일괄 처리) | 정확 | **수용**. unlearn은 "버튼 하나"가 아니라 영향 범위 표시 + 일괄 복원. |
| force-live run을 자동매칭 성능 평균에서 분리 | 정확 | **수용**. run log에 `force_live=true/false` 저장, MatchMonitor에서 시각 분리. |

### 0-B. 배척 (v2 회피·떠넘김)

| v2 어휘/주장 | 배척 사유 |
|---|---|
| "숫자 고정은 동적 대응을 막는다" → threshold를 아예 "관측표에 붙는 손잡이"로만 두자 | **반쪽 진실**. 초기 default 없이는 라이브 1일차에 트리거가 안 돌아간다. v3는 "default + 라이브 N일 후 데이터 기반 재조정" 두 단계로 못 박는다. v2 식대로 default 자체를 회피하면 라이브 못 연다. |
| "사람 큐로 미루는 것은 자동화 축소"라는 일반론 | **과한 일반화**. 의미 결정(canonical merge/split, 카테고리 트리 의미 변경, 정책 판단)은 사람이 한다. v3는 "반복 분류 노동 = 자동화 실패 / 의미 결정 = operator capture" 경계를 그대로 유지. v2도 D.2에서 같은 결론으로 가지만, C.13의 "사람 결정 = 기능 축소" 어휘는 잘라낸다. |
| 회피 어휘 ("...요한지 검토 필요", "...해야 할 수도 있다") | v2가 12개 약점을 던지면서 7개를 "v3가 정해라"로 떠넘김. v3는 그 7개에 **숫자/조건/시점**으로 답한다. 떠넘김 받지 않는다. |
| 자기학습 alias "봉인" 권고 류 | v2가 직접 봉인을 권고하진 않았다(공정 확인). 그러나 "오염 그래프가 무섭다"는 어조로 자기학습을 의심만 키운 부분은 배척. v3는 **봉인 대신** audit/decay/cross-check 메커니즘으로 운영. |
| "신중한 검토 필요" 식 마무리 | v2 결론 "v1의 적은 ... 사람 큐로 보내는 구조다"는 받아들이되, 그 결론을 자동화 일반에 적용해 "사람 결정 자체가 나쁘다"로 읽히게 하는 부분은 잘라낸다. |

### 0-C. v2가 v3에 던진 질문 5개 — 답변

> v2 § E의 다섯 질문에 직설로 답한다.

**Q1. AI 호출 예산을 run 시작 전에 어떻게 예측하고, shrink/missing retry로 얼마나 벗어났는지 어디에 남길 것인가?**

- **사전 예측 공식**: `est_calls = ceil(input_rows / batch_size) × (1 - cache_hit_rate_prev_run)`. cache hit rate는 직전 7일 평균(없으면 0).
- **실측 차이**: run 종료 시 `actual_calls - est_calls`, 그 중 shrink로 추가된 call 수, missing retry로 추가된 call 수를 **분해해서** `LabelingRun` row에 저장.
- **노출 위치**: JobsPanel run 카드에 "예상 87 / 실측 142 / shrink +38 / missing +17" 형태로 한 줄.
- **알람**: 실측이 예상의 2배 이상이면 빨강. 3배면 다음 run 자동 hold.

**Q2. `WALLETSAVIOR_AI_LIVE_FORCE=1` run을 MatchMonitor 성능 지표에서 어떻게 분리할 것인가?**

- `LabelingRun.force_live: bool` 컬럼 추가(스키마 한 줄). force-live run의 ai_call_rate, auto_match_rate는 **별 색·점선**으로 차트에 표시하되, 평균 집계에서는 제외.
- MatchMonitor 상단에 "force-live run 제외 / 포함" 토글.
- ai-admin 프론트 헤더에 현재 force-live ENV 상태 배지(빨강 LIVE FORCE ON / 회색 OFF).

**Q3. 1-click 승인 뒤 즉시 undo의 데이터 단위는?**

- 기준은 **`ReviewDecision.id`** 한 줄. ReviewDecision은 이미 (proposal_id, match_id, knowledge_id) 여러 개를 묶을 수 있으므로 이 단위가 "되돌릴 한 동작"이다.
- undo 윈도우: **5초** 토스트 + **최근 7건 스택**(상단 고정).
- 되돌림 시: 연결된 ProductMatch는 `is_active=false`, LearnedKnowledge는 `success_count -= 1` (음수 방지), 원래 proposal 상태로 롤백.
- 5초 지나면 토스트는 사라지지만 7건 스택과 일괄 unlearn 화면(D-2)에서는 1시간 내 되돌리기 가능.

**Q4. RULE_LEARNED_ALIAS threshold를 관측표로 조정하려면 최소 로그는?**

다음 6개 컬럼이 `LearnedKnowledgeApplication` (신규) 로그에 필요:

| 컬럼 | 용도 |
|---|---|
| `knowledge_id` | 어떤 룰이 적용됐는가 |
| `raw_record_id` / `match_id` | 적용 대상 |
| `confidence_at_apply` | 적용 시점 confidence |
| `success_count_at_apply` | 적용 시점 누적 |
| `outcome` (pending/approved/rejected/rollback) | 사후 결과 |
| `outcome_settled_at` | 결과 확정 시각 |

이 표만 있으면 (success_count, confidence) 격자별 false-positive 율을 데이터로 본다. 그때 비로소 0.92/2 라는 default를 옮긴다. **default 자체를 없애지 않는다**(v2 식 회피 배척).

**Q5. "사람 결정" 충돌과 자동 정렬 가능 충돌을 어떻게 나눌 것인가?**

- **자동 정렬·tie-break 가능**:
  - 한쪽이 human-approved, 다른 쪽이 AI 단독 → human 우선.
  - 동일 raw_title + 동일 package_signature + 한쪽만 success_count 있음 → 후보 1위로.
  - 한쪽이 reviewer-safe fallback (conf 0.42) → 자동 후순위.
  - 카테고리 동일·canonical_name 동일·id만 다름 → "merge 후보" 묶음 카드.
- **사람 결정 (operator capture)**:
  - canonical_name이 다르되 같은 상품군 (예: "신라면 5입" vs "신라면 멀티팩 5") → merge/split 의미 결정.
  - 카테고리 트리 자체가 흔들리는 경우.
  - 두 쪽 모두 human-approved 이력 → 사람 사이 충돌, 사람만 정리 가능.

기계가 후보를 **줄이고 정렬**해서 카드 한 장으로 만들어준 뒤 사람이 1초로 결정. v2가 옳게 짚은 "사람이 후보 정렬까지 하면 큐 폭주"는 그대로 수용.

---

## A. 사실관계 정정 (v1 오류)

v2가 잡은 v1 사실관계 오류를 v3가 공식 정정한다.

| v1 표현 | 정정 |
|---|---|
| `ai_ingestion.py:1397 shrink` | shrink 함수 본체는 `:1150` 부근. 1397은 fallback 설명. |
| `WALLETSAVIOR_AI_LIVE_FORCE=1` "캐시·매칭 우회 강제" | "**approved ProductMatch precheck 우회**". 캐시 전체 우회는 코드 보장 아님. |
| `ProductMatchStatus.CONFLICT` 자동 마크 | 현 enum은 `PROPOSED`/`APPROVED`/`REJECTED`. 충돌 표현은 `is_active=false` + `disabled_reason="conflict"` 조합으로 대체. |
| "300회/일 보호값" | 실제 코드 default 맞지만 **process memory 카운터**. 재시작 시 초기화. |
| wire log "영구 보존" | 코드는 append-only. 영구는 운영 폴리시이지 코드 보장 아님. |
| `RULE_LEARNED_ALIAS` 발동 정책 "AI 단독 5회 + 평균 conf≥0.85" | 실제 코드는 `min_confidence=0.92` + `min_success_count=2` + negative evidence 차단. v1 표는 임시 가설로 격하. |
| `tools/run_live_model_batch.py --provider-pool` 기반의 "풀 자동 라우팅" | CLI wrapper 기능. 본체 ingestion이 자동 라우팅한다고 읽히면 안 됨. |

그 외 v1 본문의 모듈 경로(`ai_ingestion.py`, `queue_ai_router.py`, `postcheck_gate.py`, `review_automation.py`, `match_monitor.py`, `MatchMonitorPanel.jsx`, `wire_logger.py`, repositories.py 538/912)는 v2 검증대로 **정확**.

---

## B. v1 자기검증 5포인트 + v2 약점 통합 재답변

### B-1. RULE_LEARNED_ALIAS threshold — 감 vs 데이터

- **현재 코드값**: `min_confidence=0.92`, `min_success_count=2`, negative evidence 차단, target keyword 정확 일치.
- **v3 입장**: 코드 default는 **그대로 둔다**. v1의 "AI 단독 5회/0.85"는 임시 가설로만 본다.
- **데이터 기반 조정 절차** (v2 Q4 답변과 같은 표):
  1. P0: `LearnedKnowledgeApplication` 로그(위 6컬럼) 도입.
  2. 라이브 14일 측정.
  3. (success_count, confidence) 격자별 rollback/reject 율을 admin이 본다.
  4. 격자 중 fp율 ≥ 5% 구간은 차단(자동 적용 X, 사람 검토로). 격자 중 fp율 ≤ 1% & 적용 ≥30건은 default 완화 후보.
- **v2 식 "default 자체를 동적 손잡이로"는 배척**. default 없이는 1일차에 룰이 안 돈다.

### B-2. 1-click 승인 위험 + undo 윈도우

- 위험은 v2 지적대로 **다음 사이클 자동 오분류로 증식**한다.
- v3 안전장치(P0 필수):
  - 승인 즉시 5초 토스트 + 7건 undo 스택.
  - undo 단위는 `ReviewDecision.id` (v2 Q3 답변).
  - 1시간 내라면 ReviewQueuePanel의 "최근 승인" 탭에서 되돌리기.
  - 1시간 뒤 오염이 발견되면 D-2의 **일괄 unlearn 화면**으로 match_id/signature/keyword 역추적.
- 키보드 단축키 (1/2/3 후보 선택 + Enter) 유지. **속도 깎지 않는다**. 속도 깎기는 v2 식 회피.

### B-3. 다중 프로바이더 폴백 — 진짜 P2가 맞나

- v1: P2(2단계). v2: P0 검토 권고.
- v3 결론: **P1 초입으로 끌어올림**. P0 아닌 이유는 라이브 1주는 trafic 적어서 quota 닫혀도 escalation으로 견딘다. P1 초입인 이유는 v2가 옳다 — Google quota 단일 의존은 운영 연속성 리스크. + force-live 실험 run이 quota를 빨리 태운다.
- 최소판 (P1 초입):
  - provider yaml 풀(primary/secondary) 정의.
  - retryable failure(5xx, quota exhausted) 시 secondary 1회 시도.
  - run log에 어느 provider 어느 row에 쓰였는지 기록 → 추후 모델 비교.
  - 자동 라우팅 본격판(quota 잔량 기반 routing)은 P2 유지.

### B-4. 사용자 신고 학습 보류 — 신뢰 영향

- v1: P2. v2: "신고 후 변화 없음"이 신뢰 깎는다.
- v3 분리:
  - **P0 (얇은 유입)**: 신고 → AI-admin anomaly 큐로 유입 + ReviewQueuePanel에 "신고 N건" 배지 + 신고 처리 상태(접수/검토중/조치완료)를 user-facing API로 노출.
  - **P2 (학습 반영)**: ReviewDecision 자동 흡수 → 가격 sanity Gate history 반영. 이건 그대로 P2.
- 사용자 입장에서는 "신고가 운영 큐로 들어갔다"는 흔적만 빨리 보이면 신뢰는 유지된다. 모델 학습까지 P0로 끌어올리지 않는다.

### B-5. 매칭 충돌 "항상 사람" — 처리 가능성

- v1: 100% 사람. v2: 100건/일이면 사람 못 따라감.
- v3 분리(v2 Q5 답변 재인용):
  - **자동 정렬·tie-break 4개 룰** (human 우선 / signature·success_count tie-break / fallback 후순위 / merge 후보 묶음) → 카드 한 장으로 압축.
  - **최종 merge/split 결정은 사람**. 카테고리 트리·canonical 의미 변경도 사람.
- 사람 큐를 100건에서 10건으로 줄인다. "사람 없애기"가 아니라 "사람이 의미만 결정".

---

## C. v1이 빠뜨린 시나리오 보강

### C-1. `WALLETSAVIOR_AI_LIVE_FORCE` 라이브 잔존 — 환경 분리

- 위험(v2): 켜진 채 운영되면 ProductMatch precheck 우회 → 학습 루프 지표 오염 → quota 빨리 소진.
- v3 조치(P0):
  - **금지가 아니라 가시화**. 운영 환경에 켜지는 것 자체는 막지 않음(증명용으로 필요).
  - `LabelingRun.force_live` 컬럼.
  - MatchMonitor 차트에서 force-live run을 다른 색·점선.
  - 자동매칭 성능 평균에서 force-live run 분리.
  - ai-admin 프론트 헤더에 현재 ENV 상태 배지(빨강 ON).
  - 백엔드 부팅 로그에 force-live 상태 명시.
- 환경 분리: dev/staging은 force-live 기본 ON, prod는 default OFF + 명시적 토글 필요. yaml로 환경별 default.

### C-2. shrink retry 무한루프 / 최대 retry depth

- 무한 분할은 아님(v1 주장 맞음). 그러나 호출 폭증·시간 폭증은 발생(v2 지적 옳음).
- v3 조치:
  - **shrink depth 상한**: `max_shrink_depth=log2(batch_size)+1` (기본 batch 32 → depth 6).
  - **shrink로 추가된 call 수를 LabelingRun에 분해 저장** (v2 Q1 답변).
  - **fallback 비율 임계**: 한 run의 reviewer-safe fallback 비율이 ≥20%면 prompt/schema 회귀로 간주 → 다음 run 자동 hold + 알람.
  - **missing_records 재귀 동일 row 반복**은 row_id 기준 3회로 캡. 그 이상은 영구 reviewer-safe.

### C-3. 자기학습 alias 오염 — 봉인 대신 audit/decay/cross-check

> **v2가 직접 봉인을 권고하진 않았지만, 오염 그래프 어조로 의심만 키운 부분은 받지 않는다.** 자기학습은 시스템의 핵심 가치. 봉인이 아니라 3중 검증으로 운영.

1. **Audit (정기 검토)**:
   - LearnedKnowledge 적용으로 생긴 ProductMatch의 사후 rollback/reject 율을 주간 집계.
   - knowledge_id별 fp율 ≥10%면 자동 비활성화(`is_active=false`) + 관리자 알람.
2. **Decay (시간 감쇄)**:
   - 마지막 적용 후 90일 미사용 룰은 success_count 절반으로 감쇄.
   - 다시 적용되면 회복.
3. **Cross-check (교차 검증)**:
   - 같은 pattern에 서로 다른 target_value를 갖는 룰이 둘 이상이면 자동 충돌 → 그 룰은 적용 보류.
   - human-approved 룰과 AI 단독 룰이 같은 raw_record에 다른 결과를 내면 human 우선 + AI 룰의 부정 evidence로 기록.

### C-4. escalation 큐 폭주 — 일일 N건 + 그룹화/우선순위

- v2 시나리오(새 마트/트리 개편/schema 오류/포맷 변경/force-live/MAD outlier)에 동의.
- v3 조치:
  - **일일 처리 캐파**: 관리자 1인 기준 200건/일. 그 이상은 자동 그룹화 강제.
  - **그룹화 키**: (실패한 gate, source, category 후보 top-1) → 같은 키는 한 카드.
  - **"한 결정으로 N건" 표시**: 카드 상단에 "이 결정을 적용하면 38건 처리".
  - **우선순위**: 가격 sanity 실패(돈 직결) > 신상품 > MAD outlier > 기타.

### C-5. 새 카테고리 제안 폭주 — 빈도/유사도 임계

- v1: 큐만 분리. v2: dedupe·재평가 부재 지적.
- v3 조치(P1):
  - 제안 발화 시 기존 카테고리·기존 pending 제안과 **이름 유사도(Jaro-Winkler ≥0.85)** + **상위 노드 일치** 체크.
  - 유사한 제안 있으면 **신규가 아니라 기존 제안에 vote 1** 추가.
  - 관리자가 카테고리 추가하면 기존 pending 제안 자동 재평가(이미 만들어졌는지 매칭).
  - 일일 신규 카테고리 제안 ≥10개면 카테고리 트리 자체 점검 알람.

### C-6. wire_log 누적 디스크 폭주 — rotation/archive

- v1: "압축 회전은 운영 폴리시" → v2: 문서상 빈칸 지적, 옳음.
- v3 조치:
  - **일간 파일 분리**: `wire-YYYY-MM-DD.jsonl`.
  - **30일 후 자동 gzip + archive 폴더 이동**.
  - **180일 후 원본 삭제** (집계 roll-up은 DB에 남음).
  - MatchMonitor의 "최근 N건"은 당일+직전 파일만 scan. 그 이상은 archive에서 사용자 요청 시 비동기 조회.
  - 디스크 사용량을 ProvidersPanel에 표시.

### C-7. 다중 프로바이더 폴백 — Google 단일 quota

(B-3과 같음. P1 초입.)

### C-8. AI 평가 모드 — A/B 다른 모델 동시 운영

- v1: P3. v3: P2 유지하되 설계 명시.
- 설계:
  - 라이브 트래픽 1% 샘플을 B 모델로도 호출 (shadow).
  - B 결과는 publish 안 함. `ABTestResult` 테이블에 저장.
  - 두 모델 결과 diff 율, postcheck 통과율, latency를 ProvidersPanel에서 비교.
  - 토글 위치: ProvidersPanel 상단 + 위험 배지 "AB 모드 ON (quota 2× 소진)".

### C-9. ai-admin 외 모듈과 인터페이스 안정성

- 경계(v1 G-1 유지): 크롤러 → REST → ai-admin → REST → db-admin. 직접 DB 접근 X.
- v3 보강:
  - 인터페이스 contract는 `core.contracts.ai_pipeline` 에 버전 명시 (semver).
  - breaking change 시 양쪽 어댑터에 deprecation 6주 윈도우.
  - 어댑터 layer(`services/db_admin_adapter.py`)에 schema 검증.

### C-10. 모델 변경 시 기존 매칭 신뢰도 재평가

- v1 누락. v2도 명시 안 함. **v3 신규**.
- 모델 갈아끼우면 과거 ProductMatch가 자동으로 "이전 모델 기준"이 된다.
- 조치:
  - ProductMatch / LearnedKnowledge에 `created_by_model_version` 컬럼.
  - 모델 변경 시 옛 row는 **자동 비활성화 X**, 대신 MatchMonitor에 "이전 모델 매칭 N건" 표시.
  - 관리자가 명시적으로 "재평가 run" 트리거 → 샘플 1%만 새 모델로 재호출 → diff 율 보고.

### C-11. 비용 예산 hard cap vs soft cap

- v3 정책:
  - **soft cap (월 $X)**: 80% 도달 시 알람. 호출은 계속.
  - **hard cap (월 $Y, Y > X)**: 도달 시 신규 run 자동 hold. 진행 중 run은 완료.
  - **per-run cap**: 예상 call의 3배 도달 시 run 중단.
  - 토큰 단가는 yaml로 관리. provider별.

---

## D. 매칭 학습 메커니즘 보강

### D-1. threshold 결정 데이터 기반 절차

(B-1 재인용 + 절차 표)

| 단계 | 기간 | 산출 |
|---|---|---|
| 1. default 유지 | 라이브 D+0~D+14 | 현 코드값(`min_conf=0.92`, `success_count=2`) 그대로 |
| 2. 측정 | D+0~D+14 | `LearnedKnowledgeApplication` 로그 6컬럼 수집 |
| 3. 분포 보고 | D+14 | (success_count, confidence) 격자별 fp율 보고서 자동 생성 |
| 4. 갱신 | D+14~D+21 | fp율 ≤1% & 적용≥30건 격자는 default 완화, fp율 ≥5% 격자는 차단 |
| 5. 재측정 | D+21~D+42 | 변경 후 같은 표 다시 |

### D-2. self-learned alias의 audit

(C-3 재인용)

- 주간 audit: knowledge_id별 fp율.
- 90일 decay.
- 교차 충돌 시 보류.
- audit 결과는 **별도 화면**에 (MatchMonitor → "LearnedKnowledge 건강 탭").
- 일괄 unlearn 화면: 한 knowledge_id 비활성화 시 그 룰이 만든 ProductMatch 영향 범위 표시 + 일괄 `is_active=false`.

### D-3. 충돌 자동 처리 vs 사람

(B-5 재인용)

- **자동**: human 우선 / signature·success_count tie-break / fallback 후순위 / merge 후보 묶음.
- **사람**: canonical merge/split 의미 결정, 카테고리 트리 변경, human끼리 충돌.

### D-4. 매칭 학습 vs DB canonical 학습 경계

- AI-admin: 매칭 패턴 학습(`LearnedKnowledge`, `ProductMatchStore`).
- DB-admin: canonical 정의 자체(어떤 canonical_id를 만들 것인가).
- 승격 룰(G-2 참조): AI-admin의 학습 결과가 일정 임계 넘으면 **DB-admin에 "canonical 후보 승격" 제안**으로 전송. DB-admin이 최종 채택. AI-admin은 직접 canonical_id 생성 안 함.

---

## E. 관리자 UI/UX 보강

### E-1. ReviewQueuePanel

- 1-click 승인 + **5초 undo 토스트** + **최근 승인 7건 스택**(상단 고정) + **top-3 후보 키보드 단축키(1/2/3 + Enter)** + **일괄 액션**("이 결정을 38건에 적용").
- 키보드 단축키: 1/2/3(후보 선택), Enter(승인), R(반려), N(신상품으로), U(직전 undo), J/K(다음/이전).
- "최근 승인" 탭: 1시간 내 ReviewDecision 되돌리기.

### E-2. MatchMonitor

- 누적 카드(ProductMatch by_status/by_source, LearnedKnowledge by_type/success_count) + 추이 차트(AI 호출률, 자동매칭률) + **제안 큐 카운터** + **wire_log 최근 N건 링크** + **force-live run 분리 토글** + **LearnedKnowledge 건강 탭**.

### E-3. JobsPanel

- 런별 입력/AI호출/자동매칭/escalated 카운트 + **5단계 silent drop 표** (각 단계 사이 drop ≠0이면 빨강) + **silent drop 행 별도 표 + 재시도 버튼** + 예상/실측 call 분해 표시.

### E-4. AI 평가모드 토글 위치 + 위험 가시화

- ProvidersPanel 상단.
- ON 시 빨강 배지 "AB 모드 ON (quota 2× 소진 / 라이브 트래픽 1% B 모델 호출)".
- 토글 옆에 "현재 비교 중 모델: A=gemini-2.5 / B=gemini-2.0".

---

## F. 프로바이더 / 비용 보강

### F-1. 폴백 전략

```
google-gemini (primary)
  ├── retryable 5xx / quota exhausted ─► google-gemma (secondary, 동일 quota 풀)
  ├── 동일 vendor 전체 다운 ─────────► alt API key (별도 결제 계정)
  ├── 그래도 실패 ──────────────────► 로컬 OSS LLM (gemma-2 / qwen) — 품질 낮음, escalation 증가 감수
  └── 전부 실패 ────────────────────► 룰만 (RULE_EXACT_CATALOG_KEYWORD 등) + 나머지 reviewer-safe
```

- P1 초입: primary + secondary 자동 시도.
- P2: alt key + 로컬 OSS.
- 룰-only fallback은 항상 last resort, escalation이 폭증함을 가시화.

### F-2. prompt-hash 캐시 + invalidate 룰

- 캐시 키: `sha256(prompt_template_version + raw_record_normalized + category_tree_version)`.
- invalidate 트리거: (a) 프롬프트 버전 변경, (b) category_tree.yaml 변경, (c) 명시적 운영 명령, (d) 캐시 entry 90일 경과.
- 캐시 hit 시 wire log에 `cache_hit=true` 라인 (현재 미확인, P0에 명시 추가).

### F-3. 일일 quota 모니터 + soft/hard cap

- quota 카운터를 **DB 영속**으로(현 process memory 카운터 교체) — P0.
- soft cap (300×0.8=240회): 알람.
- hard cap (300회): 신규 호출 차단, 진행 run은 secondary로 자동 전환.
- ProvidersPanel에 잔량 게이지 + 시간대별 호출 분포.

### F-4. 비용 대시보드

- wire log daily roll-up → ProvidersPanel:
  - provider별 일/월 호출 수, 평균 latency, 추정 토큰, 추정 USD.
  - 모델 단가는 yaml.
  - 누적 월 비용 + soft/hard cap 게이지.
  - 비용 폭증 알람(전일 대비 3×).

---

## G. 모듈 / 플러그인 보강

### G-1. ai-admin이 노출하는 contract

- **inbound** (크롤러로부터): `POST /raw_records` (RawRecord schema, semver=1.x).
- **outbound** (db-admin으로): `POST /proposals/field`, `POST /proposals/keyword`, `POST /proposals/canonical_candidate`, `POST /matches/published`.
- **observability**: `GET /match-monitor/cumulative`, `/runs`, `/wire-log/recent`, `/learned-knowledge/health`.
- **admin**: `POST /reviews/{id}/decide`, `POST /reviews/{id}/undo`, `POST /knowledge/{id}/unlearn`.
- 모든 schema는 `core.contracts.ai_pipeline` 에 정의 + semver. breaking change는 6주 deprecation.

### G-2. 자기학습 → DB canonical 승격 룰

- LearnedKnowledge의 `RULE_LEARNED_ALIAS`가 다음 조건 모두 만족 시 **canonical 후보 승격 제안**:
  - success_count ≥ 10
  - 적용 raw_record source ≥ 3개 (다른 마트에서도 같은 alias 등장)
  - human-approved 이력 ≥ 1 또는 audit fp율 ≤ 2%
  - 최근 30일 활성 (decay 안 됨)
- 승격은 **제안일 뿐**. DB-admin이 최종 채택. ai-admin이 canonical_id 신규 생성하지 않는다(v1 G-1 결합도 0 원칙 유지).

### G-3. 어댑터 패턴

- v1과 동일: `providers/<name>.py`에 `call(prompt, options) -> ProviderResponse` 한 메서드.
- 추가 요구: `quota_status() -> {used, limit, reset_at}`, `health() -> bool`.
- yaml에 한 줄 추가하면 풀에 합류. 폴백 체인은 yaml의 순서.

---

## H. 로드맵 P0/P1/P2 재정렬

> v1 로드맵 → v2 지적 → v3 재정렬. **Google quota 단일 의존만 P1 초입으로 끌어올림.** 나머지는 v1 골격 유지.

### P0 (라이브 직전 필수)

- [ ] postcheck 4-gate 안정화
- [ ] 자동매칭 ≥80% 사이클 2회 검증
- [ ] wire log 일간 파일 분리 + cache_hit=true 라인 추가
- [ ] **WireLogPanel** + force-live 환경 가시화 (헤더 배지 + LabelingRun.force_live 컬럼)
- [ ] ReviewQueuePanel 1-click + **5초 undo + 7건 스택 + 단축키**
- [ ] silent drop 표 + 재시도 버튼 (JobsPanel)
- [ ] escalation SLA 표시
- [ ] **unlearn 최소판** (knowledge_id 비활성화 + 영향 범위 표시)
- [ ] **LearnedKnowledgeApplication 로그 6컬럼** (threshold 데이터 수집)
- [ ] **quota 카운터 DB 영속화** (process memory 탈출)
- [ ] **사용자 신고 anomaly 유입** (얇은 P0)
- [ ] **per-run 예상/실측 call 분해** (JobsPanel)

### P1 (가동 직후 1개월 내)

- [ ] **다중 프로바이더 폴백 최소판** (primary+secondary 자동, **v1의 P2에서 끌어올림**)
- [ ] 비용 모니터 + soft/hard cap
- [ ] 새 카테고리/키워드 제안 큐 + dedupe(Jaro-Winkler) + 재평가
- [ ] 카테고리 트리 핫리로드
- [ ] 매칭 충돌 자동 정렬·tie-break 4룰 + 카드 묶음
- [ ] LearnedKnowledge 건강 탭(주간 audit + decay)
- [ ] threshold default 갱신 (D+14 데이터 기반)
- [ ] wire log archive 자동 회전

### P2 (가동 안정 후 3개월+)

- [ ] AI 평가 모드 (A/B shadow 1% 트래픽)
- [ ] 사용자 신고 → ReviewDecision 자동 흡수 + 가격 sanity history
- [ ] 신뢰도 가중치 자동 우선순위
- [ ] provider 자동 라우팅 본격판 (quota 잔량 기반)
- [ ] alt API key + 로컬 OSS LLM 폴백
- [ ] 모델 변경 시 재평가 run 자동화

---

## I. 안전 타령 배척 선언

> v3가 v2에 굽힌 지점은 **운영 데이터·환경 분리·wire log·threshold 측정 로그** 같은 **기능 추가**다. 다음은 안전 타령이 아니라 기능 차원이라 유지한다. 반대로 v2가 깔만한 회피 어휘는 잘라낸다.

1. **자기학습 봉인 — 배척**. v2가 직접 권고하진 않았지만 어조로 의심만 키운 부분 거부. C-3의 audit/decay/cross-check 3중으로 운영. 봉인하면 시스템 핵심 가치 죽음.
2. **매칭 학습 금지 — 배척**. ProductMatchStore + LearnedKnowledge가 시스템의 자산. 끄지 않는다. 대신 D-1의 데이터 기반 threshold 조정으로 품질 확보.
3. **"신중한 검토 필요" 떠넘기기 — 배척**. v2가 v3로 떠넘긴 12개 약점 중 7개 회피 어휘는 v3가 **숫자·시점·조건**으로 답했다(0-C, B 섹션).
4. **숫자 default 자체 회피 — 배척**. v2 식 "관측표에 붙는 손잡이로만"은 라이브 1일차에 룰이 안 돈다. v3는 default + 데이터 기반 갱신 두 단계 (D-1).
5. **"사람 결정 = 자동화 축소" 일반론 — 배척**. 의미 결정은 사람, 반복 분류는 기계라는 v1 경계 유지. v2 D.2와 결론 같음.

**기능 차원이라 유지하는 것** (안전 타령 X):

- 환경 분리(force-live dev ON / prod OFF default + 배지) — 가시화이지 금지 아님.
- wire log rotation/archive — 디스크 관리이지 보안 아님.
- threshold 데이터 기반 갱신 — 실험적 운영이지 회피 아님.
- undo 윈도우 — 속도 깎기 아님, 같은 화면에서 즉시 복구.
- audit/decay/cross-check — 자기학습 유지 위한 장치.

---

## J. 자기검증

| 체크 | 결과 |
|---|---|
| v1, v2 수정했는가 | ✅ 아니오 |
| 다른 영역 깊이 팠는가 | ✅ 경계까지만 |
| 코드 변경했는가 | ✅ 없음 |
| 안전 권고로 기능 축소했는가 | ✅ 없음. C-3 자기학습 audit는 봉인 아닌 운영. |
| v2에 굽힌 흔적 | 운영 디테일 14개 수용, 회피 어휘 5개 배척. 명세에 명시. |
| 동적 대응 차단 흔적 | 없음. threshold default + 데이터 기반 갱신, 자기학습 유지, 매칭 학습 유지. |
| v4/v5 미리 작성 | 로드맵 P2 항목명만, 설계는 v4 이후. |
| 비개발자 가독 | ✅ 표·예시 위주 |

---

## K. v4가 깔만한 약점 3~5포인트

> v3 스스로 보는 빈틈. v4(GPT)가 칠 자리를 미리 본다.

1. **D-1 threshold 갱신 절차의 "라이브 14일"이 임의값**. 14일이 통계적으로 충분한 표본인가? raw_record 일일 유입량이 1,500 행이라 가정한 건데 실측 분포가 적으면 14일이 부족하다. v4는 "표본 수 기반"(예: knowledge_id당 최소 30 적용)으로 조건 바꾸자고 칠 것.

2. **G-2 canonical 승격 룰의 수치 (success_count≥10, source≥3, fp율≤2%)도 감**. D-1과 같은 비판이 그대로 돌아온다. v3는 D-1엔 measurement 절차를 명시했지만 G-2엔 default만 박았다. v4가 "이건 왜 measurement 안 거는가" 칠 자리.

3. **C-10 "모델 변경 시 재평가 run 자동화"가 P2로 미뤄짐**. 라이브 1개월 안에 모델 갱신이 한 번이라도 일어나면 P0에 들어왔어야 한다. v3가 라이브 직후 빈도를 과소평가했을 수 있음.

4. **F-1 폴백 체인의 "로컬 OSS LLM" 품질 가정 미검증**. 가격 sanity나 카테고리 분류에서 OSS가 어느 정도 받쳐주는지 데이터 없이 last resort로 박았다. v4가 "그럼 그게 진짜 fallback이 되긴 하나" 칠 자리.

5. **사용자 신고 P0 유입 → P2 학습 사이의 공백 4-8주**. 그동안 신고가 운영 큐로 들어가긴 하지만 같은 문제가 반복 노출되는 건 동일. v3는 "신뢰 흔적은 P0"라고 답했지만 v4는 "흔적만으로 신뢰가 회복되는가" 칠 수 있음.

---

*— Opus 4.7, Round-A v3. 다음: GPT 5.5가 v4로 친다. Opus는 v5에서 최종.*
