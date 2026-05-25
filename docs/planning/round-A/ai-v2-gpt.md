# AI 영역 기획 v2 — GPT 적대적 검토

> 입력: `docs/planning/round-A/ai-v1-opus.md`  
> 원칙: v1을 고치지 않고, v1의 약점·엣지·모순·떠넘김을 잡는다.

---

## A. 본문 요약 — 내가 이해한 v1

v1의 핵심은 이렇다.

1. AI-admin은 크롤러가 넘긴 `raw_record`를 받아서 카테고리, 키워드, canonical 매칭 후보를 만든다.
2. 첫 사이클은 LLM 호출 비중이 높지만, `ProductMatchStore`와 `LearnedKnowledge`가 쌓이면 같은 상품·같은 표현은 LLM을 건너뛰어야 한다.
3. 사용자는 AI를 직접 보지 않고, 검색/비교 결과 품질로만 체감한다.
4. 관리자는 ReviewQueuePanel에서 엣지 케이스만 보고, MatchMonitorPanel에서 AI 호출률 감소를 본다.
5. wire log, postcheck gate, shrink retry, reviewer-safe fallback은 “AI가 실제로 뭘 했는지” 추적하기 위한 증거 장치다.
6. AI는 카테고리 트리나 키워드 사전을 직접 확정하지 않고 제안만 한다. 확정은 관리자/DB-admin 쪽이다.
7. v1은 라이브 전 필수 항목으로 postcheck, 자동매칭 검증, wire log, 1-click 리뷰 UX, silent drop 표, escalation SLA, unlearn 최소판을 잡았다.

내 판단: 방향은 맞다. 하지만 v1은 “AI가 사람 일을 1%로 줄인다”고 말하면서도, 실제 실패 시나리오가 커지면 사람 큐로 밀어 넣는 부분이 많다. 특히 매칭 충돌, 새 카테고리 제안, alias 오염, 사용자 신고 학습, provider quota 문제에서 사람이 병목이 되는 장면을 덜 팠다.

---

## B. v1 사실관계 검증

### 1. 파일·모듈 구조

- `packages/ai-admin/backend/services/ai_ingestion.py` 존재: **정확함**.
- `queue_ai_router.py`, `postcheck_gate.py`, `review_automation.py`, `review_publish.py` 존재: **정확함**.
- `api/routes/match_monitor.py`와 `frontend/src/MatchMonitorPanel.jsx` 존재: **정확함**.
- `providers/wire_logger.py` 존재: **정확함**.
- `ProductMatchStoreRepository`가 `storage/repositories.py:538`, `LearnedKnowledgeRepository`가 `:912`에 있다는 인용: **정확함**.

### 2. C1 confidence 0.7

v1의 `queue_ai_router` 설명은 대체로 **정확함**.

- `CONFIDENCE_THRESHOLD = 0.7` 실제 존재.
- confidence 미만, 빈 응답, provider 오류, 트리에 없는 id는 `ESCALATED`로 간다.
- 다만 v1은 C1 → C2가 한 파이프처럼 읽히는데, 실제로는 `livepass_pipeline.py` 같은 경로에서 붙는다. 개념은 맞지만 코드 흐름은 한 파일 안의 단순 직선은 아니다.

### 3. C2 4-gate

v1의 Gate1~4 설명은 **정확함**.

- `TREE_VALID_ID`, `CONFIDENCE`, `SIBLING_CONSISTENCY`, `PRICE_SANITY`에 해당하는 로직이 있다.
- confidence 기준 0.7, 가격 MAD multiplier 5.0도 실제 값과 맞다.
- 모호어 패널티도 실제 존재한다.

### 4. ProductMatch / LearnedKnowledge 누적 구조

v1 설명은 **대체로 정확함**.

- `ProductMatchStoreRepository`는 source/signature 기반 매칭을 저장한다.
- `LearnedKnowledgeRepository`는 `success_count`를 갖고 있고, MatchMonitor API는 `success_count_distribution`도 제공한다.
- 다만 v1이 말한 “source signature → canonical_id 매핑”은 실제 코드에서 `target_id`, `canonical_product_id`, `canonical_product_name`, `category_id` 등으로 더 넓다. canonical 하나만 저장하는 단순 테이블은 아니다.

### 5. MatchMonitorPanel

v1 설명은 **정확함**.

- 백엔드는 `/api/match-monitor/cumulative`, `/api/match-monitor/runs`를 제공한다.
- 프론트는 ProductMatch 누적, LearnedKnowledge 누적, 최근 AI 호출률, 런 테이블을 보여준다.
- `ai_call_rate = ai_called / total_input * 100` 계산도 실제 repository에 있다.

### 6. wire log

v1 설명은 **반은 정확하고 반은 과장**이다.

- `WALLETSAVIOR_WIRE_LOG_PATH`가 있으면 JSONL 파일에 요청/응답 메타를 append한다: **정확함**.
- httpx event hook으로 google-genai 내부 client에 붙는다: **정확함**.
- latency, status, prompt hash, response size를 남긴다: **정확함**.
- “영구 보존”은 코드가 보장하지 않는다. 파일에 계속 append할 뿐이고, 보존 기간/압축/삭제 정책은 코드 밖이다.
- v1의 `cache_hit=true` wire log 기록은 확인되지 않았다. wire_logger 필드는 `timestamp`, `url`, `domain`, `status`, `latency_ms`, `req_prompt_hash`, `resp_size_bytes` 중심이다.

### 7. `WALLETSAVIOR_AI_LIVE_FORCE`

v1 설명은 **부분 정확함**.

- 실제로 `ai_ingestion.py`에서 `WALLETSAVIOR_AI_LIVE_FORCE=1`이면 approved ProductMatch precheck를 우회하고 provider로 보낸다.
- wire_logger도 force flag를 읽고, process exit 때 successful call 0건이면 경고한다.
- 하지만 이 플래그가 “캐시·매칭 우회 전체”를 보장한다고 쓰면 과장이다. 확인된 것은 ProductMatch precheck 우회와 wire logger의 zero-call 경고다.
- 그리고 이 값은 환경변수다. 개발용인지, 운영 토글인지, 누가 켜고 끄는지 v1이 못 박지 않았다.

### 8. 라이브 호출 보호값

v1의 “12초 간격 / 5회분 / 300회일”은 **정확함**.

- `_MIN_PROVIDER_REQUEST_INTERVAL_SECONDS = 12.0`
- `_MAX_PROVIDER_CALLS_PER_MINUTE = 5`
- `_MAX_PROVIDER_CALLS_PER_DAY = 300`

단, 이 call history는 process memory다. 재시작하면 카운터가 초기화된다. “일일 quota 모델”로 운영하려면 DB나 파일 roll-up과 맞물려야 한다.

### 9. shrink retry

v1의 동작 설명은 **핵심은 정확함**.

- 실패하면 N을 반으로 쪼갠다.
- N=1도 실패하면 fallback proposal을 만든다.
- fallback confidence 0.42도 맞다.

다만 v1의 코드 인용 `:1397 shrink`는 부정확하다. shrink 함수는 `ai_ingestion.py:1150`부터이고, 1397 근처는 fallback 설명이다.

또 하나: v1은 “transient 3회 재시도 후 shrink”처럼 읽히는데, 현재 `_call_provider_with_shrink_retries`는 retryable error에서 같은 배치 3회 반복이 아니라 바로 split 경로로 간다. 별도 `_call_provider_with_retries`는 있지만 v1의 표와 실제 shrink 경로가 완전히 같지는 않다.

### 10. RULE_LEARNED_ALIAS threshold

v1이 “발동 정책은 코드를 더 봐야 한다”고 한 것은 **정확한 태도**였고, 실제 코드는 이미 값을 갖고 있다.

- `learned_alias_min_confidence = 0.92`
- `learned_alias_min_success_count = 2`
- negative evidence 있으면 blocked
- target keyword가 정확히 맞아야 통과

v1의 제안값 “AI 단독 5회 + 평균 confidence 0.85”는 코드와 다르다. v1 스스로 검증 필요라고 했으므로 거짓말은 아니지만, 다음 라운드에서 이 표를 그대로 설계값처럼 쓰면 안 된다.

### 11. 매칭 충돌 상태

v1의 `ProductMatchStatus.CONFLICT`는 **현재 코드와 맞지 않다**.

실제 enum은:

- `PROPOSED`
- `APPROVED`
- `REJECTED`

`CONFLICT`가 없다. v1의 “두 행 모두 CONFLICT 마크”는 현 구조에 없는 상태를 전제로 한다.

### 12. unlearn / deprecated

v1의 unlearn 설명은 **아직 설계 제안에 가깝다**.

- ProductMatch에는 `is_active`, `disabled_reason`이 있다.
- LearnedKnowledge에도 `is_active`, `success_count`가 있다.
- 하지만 `unlearn(canonical_id, signature)` API나 `deprecated` status는 확인되지 않았다.
- v1의 “삭제하지 않는다 — 감사 로그로 영구 보존”은 방향은 그럴듯하지만, 현재 코드에 완성 기능처럼 쓰면 안 된다.

### 13. provider pool

v1의 “`tools/run_live_model_batch.py --provider-pool` 옵션 존재”는 **정확함**.

하지만 이건 CLI wrapper 쪽이다. ai-admin ingestion 본체가 provider pool을 자동 라우팅하는 구조라고 보면 안 된다.

### 14. 1-click 승인 UI

현재 ReviewQueuePanel은 승인/반려/보정/직접수정/묶음승인 UI가 있다. v1의 “top-3 후보 + keyboard shortcut + 1-click 카드”는 **목표안**이지 현재 구현 상태가 아니다.

이미 있는 것은:

- 단일 제안 승인 버튼
- 고신뢰 묶음 승인
- 키워드 승인/반려
- 발행 후 rollback 요청

없는 것은:

- v1이 그린 top-3 카테고리 후보 카드
- 승인 직후 undo window
- 매칭 오염을 바로 되돌리는 unlearn 버튼

---

## C. v1 핵심 약점

### 1. 일 300회 quota 가정이 운영 모델로 약하다

v1은 “300회/일”을 보호값처럼 다룬다. 실제 코드는 300회를 기본값으로 갖지만 process memory 카운터다. 프로세스를 재시작하면 초기화된다.

문제 시나리오:

- 오전에 280회 호출
- 배포/장애 대응으로 backend 재시작
- 카운터 0으로 돌아감
- 같은 날 다시 280회 호출 가능

또 v1의 사이클 예시는 1,240행 중 provider 호출 87건 같은 이상적인 캐시 효율을 깔고 있다. 라이브 첫 주에는 ProductMatch와 LearnedKnowledge가 비어 있고, 300회/일은 금방 닫힌다. 1,500행이 들어오면 batch size에 따라 호출 수는 줄어도 shrink retry와 missing retry가 붙으면서 예측이 깨진다.

완화책은 “막자”가 아니라 계량이다.

- run 시작 전에 예상 provider call count를 계산
- 실제 call count와 shrink 추가 호출 수를 런 로그에 남김
- provider별 day counter를 process memory 밖에 저장
- quota 소진 시 어느 mart/source/batch가 밀렸는지 MatchMonitor에 표시

### 2. shrink retry는 무한분할은 아니지만 호출 폭증은 가능하다

v1은 shrink가 log₂(N)라서 무한 루프가 없다고 말한다. 무한분할은 맞다. 하지만 비용/시간 폭증은 따로 봐야 한다.

예: 128개 batch가 전부 timeout이면 128개 단일 fallback까지 내려가며 다수의 provider call이 발생한다. 중간에 `_reserve_live_provider_call`이 12초 간격을 걸면 한 런이 몇 시간짜리가 될 수 있다.

핵심 질문은 “무한이냐 아니냐”가 아니다.

- 한 run당 shrink로 추가된 call 수가 몇 개인가?
- fallback 비율이 몇 %를 넘으면 provider가 아니라 prompt/schema 문제인가?
- missing_records 재귀가 특정 row에서 반복되는 패턴은 없는가?
- shrink log가 MatchMonitor/JogsPanel에서 보이는가?

v1은 “완료된다”에 초점을 뒀고, “얼마나 늦고 비싸게 완료되는가”를 덜 봤다.

### 3. `WALLETSAVIOR_AI_LIVE_FORCE`가 운영에 남으면 학습 루프를 부순다

이 플래그는 증명용으로는 강력하다. 문제는 이름이 환경변수이고, 코드상 운영/개발 경계가 없다.

켜진 채로 운영되면:

- ProductMatch precheck를 우회한다.
- AI 호출률이 낮아져야 하는 MatchMonitor 지표가 망가진다.
- “학습이 안 먹힌다”는 오판을 만든다.
- quota를 더 빨리 태운다.

v1은 이 플래그를 “운영자가 한 줄로 증명”하는 도구로만 봤다. v2 관점에서는 “켜졌을 때 모든 회전 지표를 오염시키는 실험 모드”이기도 하다.

필요한 것은 금지가 아니라 가시성이다.

- 모든 labeling run log에 `force_live=true/false` 저장
- MatchMonitor 차트에서 force-live run을 다른 색으로 표시
- force-live run은 자동매칭 성능 평균에서 분리
- backend 시작 로그가 아니라 UI 상단에 현재 force-live 상태 노출

### 4. 1-click 승인은 오염 속도를 올린다

v1은 관리자가 하루 100건 이상 본다고 보고 1-click/단축키를 제안했다. 속도는 필요하다. 그런데 ProductMatchStore와 LearnedKnowledge는 다음 사이클부터 LLM을 우회시키는 재료다. 즉 한 번의 빠른 오승인이 다음 런의 자동 오분류로 증식한다.

현재 ReviewQueuePanel에는 단일 승인, 묶음 승인, 키워드 승인, 발행 rollback은 있지만 “승인 직후 undo”나 “방금 승인한 학습 항목 되돌리기”는 없다.

필요한 UX는 승인 방해가 아니라 빠른 복구다.

- 승인 직후 화면 상단에 “방금 승인 7건” 스택
- 같은 화면에서 즉시 되돌리기
- 되돌리면 ProductMatch `is_active=false`, LearnedKnowledge success_count 조정, 관련 proposal 상태 복원
- 하루 뒤 발견한 오염은 match_id/signature/keyword로 역추적해서 일괄 unlearn

1-click을 넣을수록 undo는 같은 단계에 있어야 한다.

### 5. RULE_LEARNED_ALIAS threshold 근거가 약하다

v1이 스스로 찌른 지점이다. 실제 코드는 `success_count >= 2`, confidence `0.92`다. v1 제안표는 human 1회, AI+semantic 3회, AI 단독 5회 등으로 나눴지만 근거 데이터가 없다.

여기서 나쁜 결론은 “숫자를 더 엄격히 고정하자”다. 숫자 고정은 동적 대응을 막는다.

대신 필요한 것은 threshold를 평가하는 표본이다.

- success_count 1/2/3/5 구간에서 실제 오승인률
- confidence 0.85/0.9/0.92/0.95 구간에서 재사용 성공률
- source별 alias 품질 차이
- category별 alias 품질 차이
- negative_examples가 있는 alias의 재등장률

threshold는 정책값이 아니라 관측값에 붙는 손잡이여야 한다.

### 6. 자기 학습 alias 오염을 v1이 너무 얕게 봤다

가장 무서운 오염은 “AI가 틀린 제안을 하고, 사람이 못 보고 승인하고, 다음부터 learned alias가 그 틀린 제안을 자동화하는” 루프다.

코드는 LearnedKnowledge에 positive/negative examples와 success_count를 갖고 있다. 하지만 v1은 오염 전파 그래프를 그리지 않았다.

필요한 질문:

- 특정 learned alias가 몇 개 raw_record에 적용됐는가?
- 그 alias로 승인된 상품 중 나중에 rejected/rollback 된 비율은?
- alias가 만든 ProductMatch가 다시 LearnedKnowledge를 키우는 순환이 있는가?
- 같은 pattern이 서로 다른 target_value로 등장했을 때 어떤 쪽이 이겼는가?

v1은 unlearn을 버튼 하나처럼 봤다. 실제로는 “오염된 alias가 이미 적용된 downstream 결과 회수”까지 봐야 한다.

### 7. escalation 큐 폭주 시나리오가 부족하다

v1은 “신상품·엣지만 사람에게”라고 한다. 그런데 엣지가 하루 1%라는 보장이 없다.

폭주 예:

- 새 마트 추가
- 카테고리 트리 개편 직후
- provider schema 오류
- 특정 source의 title 포맷 변경
- force-live run
- price sanity가 행사/묶음 가격을 outlier로 대량 판단

이때 “사람이 본다”는 말은 해결책이 아니다. 사람 큐에 쌓인 항목도 자동으로 묶고, 원인별로 나누고, 대표 샘플만 먼저 봐야 한다.

자동화 가능한 것:

- 동일 실패 gate별 cluster
- 같은 source/title pattern 묶음
- 같은 category 후보 충돌 묶음
- source별 폭주 원인 top-N
- “한 결정으로 N건 처리 가능” 카드

### 8. 다중 provider fallback을 2단계로 미룬 건 비용보다 운영 연속성 문제다

v1은 provider pool을 2단계로 뒀다. 그런데 이미 CLI에는 `--provider-pool`이 있다. 즉 완전한 미지의 기능은 아니다.

문제 시나리오:

- primary provider 5xx
- quota exhausted
- 특정 모델만 JSON mode/schema에 약함
- shrink가 provider 오류를 row 문제처럼 분해하며 시간을 태움

fallback이 없으면 AI-admin이 멈추는 게 아니라, reviewer-safe fallback과 escalation을 대량 생산할 수 있다. 그러면 “AI 호출 실패”가 “관리자 일감 폭증”으로 바뀐다.

최소판은 자동 provider routing 전체가 아니어도 된다.

- provider failure class 기록
- retryable failure면 다음 provider 1회 시도
- provider별 성공률/latency를 run log에 저장
- provider 바뀐 row는 나중에 모델 비교가 가능하게 표시

### 9. “매칭 충돌은 항상 사람 결정”은 병목 선언이다

v1은 같은 signature → 두 canonical이면 항상 사람 결정이라고 했다. 게다가 `CONFLICT` status도 현재 코드에 없다.

충돌이 적으면 사람이 봐도 된다. 하지만 하루 100건이면 사람이 못 따라간다. “사람 결정”을 남겨두더라도 먼저 자동으로 정렬해야 한다.

자동화 가능한 충돌 정리:

- 완전 동일 raw_title + 동일 package_signature + 기존 human-approved match가 있으면 우선 후보 표시
- source_product_id_history가 한쪽에만 있으면 tie-break 근거로 표시
- 한쪽은 AI provenance, 한쪽은 HUMAN provenance면 HUMAN 후보를 위로
- 둘 다 human이면 최근 승인자/승인시각/적용건수 비교
- 같은 canonical_name인데 id만 다르면 merge 후보로 묶기

사람이 필요한 부분은 최종 merge/분리 결정이다. 후보 정렬까지 사람이 하면 큐가 터진다.

### 10. 새 카테고리 제안 폭주가 관리자 부담으로 전가된다

v1은 새 카테고리/키워드 제안 큐를 2단계로 둔다. 실제 `review_publish.py`에는 `new_category_proposals`, `new_keyword_proposals` anomaly bucket이 이미 있다. 즉 씨앗은 있다.

문제는 큐가 생기면 끝이 아니라는 점이다.

- AI가 비슷한 카테고리명을 조금씩 다르게 제안
- source별 표현 차이로 같은 의미 제안이 중복
- 카테고리와 키워드 제안이 서로 분리되어 같은 원인을 두 번 처리
- 관리자가 카테고리를 추가했는데 기존 pending 제안들이 자동으로 재평가되지 않음

필요한 것은 “제안 큐”보다 “제안 dedupe와 재평가”다.

### 11. wire_log 누적 디스크 폭주를 v1이 운영 폴리시로 밀었다

v1은 wire log 영구 보존을 말하고 “압축 회전은 운영 폴리시”라고 했다. 이건 문서상 빈칸이다.

현재 wire_logger는 파일을 append로 연다. prompt hash만 저장하므로 payload 전체보다는 작지만, 호출이 많고 장기 운영되면 디스크는 계속 늘어난다.

필요한 질문:

- 하루 평균 JSONL 크기는?
- run_id/provider_id별로 파일을 나눌 것인가?
- MatchMonitor가 최근 N건을 보려면 파일을 매번 scan할 것인가?
- roll-up 후 raw wire log는 압축만 할 것인가, 별도 archive로 옮길 것인가?

“영구”라는 단어는 멋있지만, 검색·압축·조회 단위가 없으면 디버깅 때도 느리다.

### 12. 사용자 신고 학습을 3단계로 미루면 신뢰 피드백이 끊긴다

v1은 “이거 핫딜 아님” 학습 루프를 3단계로 뒀다. 사용자 입장에서는 신고 후 다음에도 같은 문제가 보이면 서비스가 듣지 않는다고 느낀다.

바로 모델 학습까지 갈 필요는 없다. 최소한 다음은 1단계에 붙일 수 있다.

- 신고된 canonical/source/title을 AI-admin anomaly로 유입
- 같은 match_id가 다시 노출될 때 신고 count 표시
- ProductMatch/LearnedKnowledge 적용 결과 중 신고가 많이 붙은 항목을 재검수 큐로 올림
- 신고 후 처리 상태를 user-facing 영역에 간단히 노출

학습 반영을 늦추더라도 “신고가 운영 큐로 들어갔다”는 흔적은 빨리 만들어야 한다.

### 13. v1 자기검증의 약점

v1 자기검증은 “회피 권고로 기능 축소하지 않았다”고 했지만, 사람 결정으로 넘긴 부분이 사실상 기능 축소처럼 작동할 수 있다.

특히:

- 매칭 충돌 항상 사람
- 새 카테고리/키워드 제안 큐
- 신고 학습 3단계
- fallback은 reviewer-safe로 사람 큐
- operator-supplied automation config

이들은 겉으로는 운영 통제처럼 보이지만, 큐가 커지는 순간 “AI 자동화” 목표를 깎아먹는다. v1은 그 자기모순을 덜 봤다.

---

## D. operator_capture / 사람개입에 대한 내 입장

### 1. 사람에게 떠넘긴 것 중 자동화 가능한 것

사람이 최종 결정을 하더라도, 아래 작업은 기계가 먼저 해야 한다.

1. **충돌 후보 정렬**  
   success_count, provenance, source history, package_signature, title similarity로 후보 순서를 만들 수 있다.

2. **escalation clustering**  
   같은 gate failure, 같은 source, 같은 title pattern, 같은 category 후보는 묶어야 한다.

3. **새 카테고리/키워드 제안 dedupe**  
   “컵라면”, “라면컵”, “용기면” 같은 제안을 전부 별도 카드로 보여주면 관리자 시간이 녹는다.

4. **alias 오염 탐지**  
   특정 LearnedKnowledge가 만든 승인 결과에서 rollback/reject가 늘면 자동으로 “오염 의심”으로 올릴 수 있다.

5. **force-live run 분리**  
   사람이 해석하지 않아도 성능 지표에서 실험성 run을 자동 분리해야 한다.

6. **신고 기반 재검수 후보 생성**  
   사용자 신고는 바로 모델 학습이 아니어도, 어떤 match/alias를 다시 봐야 하는지 자동 후보화할 수 있다.

7. **wire log roll-up**  
   사람이 JSONL을 뒤지는 게 아니라 provider/status/latency/call_count 요약을 먼저 봐야 한다.

### 2. 사람이 진짜 필요한 부분

사람이 필요한 일도 있다. 단, “모든 애매함”이 아니라 아래처럼 최종 의미 결정이 들어가는 경우다.

1. **카테고리 트리 의미 변경**  
   새 카테고리를 만들지, 기존 카테고리에 alias를 붙일지, 상품군을 재정의할지는 사람이 봐야 한다.

2. **canonical merge/split 최종 결정**  
   같은 상품인지, 용량/구성 차이로 분리해야 하는지는 가격 비교 품질에 직접 영향을 준다.

3. **사용자 신고가 정책 판단을 요구하는 경우**  
   “핫딜 아님”이 가격 문제인지, 카테고리 문제인지, 노출 정책 문제인지는 사람이 정해야 할 때가 있다.

4. **대량 자동 처리 룰의 승격**  
   특정 cluster를 앞으로 자동 처리할지 결정하는 순간은 사람이 한 번 찍어야 한다. 대신 그 뒤 같은 패턴은 자동으로 가야 한다.

### 3. operator_capture에 대한 자기비판

`operator_capture`류 표현은 조심해야 한다. 운영자 선택을 기록한다는 말이, 실제로는 “AI가 결정을 못 했으니 사람에게 넘김”을 멋있게 포장하는 코드가 될 수 있다.

내 기준은 이렇다.

- 사람이 **의미를 결정**하면 operator capture다.
- 사람이 **반복 분류 노동**을 하면 자동화 실패다.
- 사람이 **모델 실패를 대신 수습**하면 provider/prompt/schema 문제다.
- 사람이 **큐 폭주를 손으로 정리**하면 모니터링 설계 실패다.

v3는 “사람 개입”이라는 단어를 쓸 때마다 그 앞에 자동 cluster, 후보 정렬, dedupe, 일괄 처리, undo가 있는지 확인해야 한다.

---

## E. v3가 다룰 질문 5개

1. **AI 호출 예산을 run 시작 전에 어떻게 예측하고, 실제 shrink/missing retry로 얼마나 벗어났는지 어디에 남길 것인가?**

2. **`WALLETSAVIOR_AI_LIVE_FORCE=1` run을 MatchMonitor 성능 지표에서 어떻게 분리할 것인가?**

3. **1-click 승인과 묶음승인 뒤에 즉시 undo/unlearn을 어떤 데이터 단위로 붙일 것인가: proposal_id, match_id, signature, knowledge_id 중 무엇을 기준으로 되돌릴 것인가?**

4. **RULE_LEARNED_ALIAS threshold를 고정 숫자가 아니라 source/category/confidence/success_count별 관측표로 조정하려면 어떤 최소 로그가 필요한가?**

5. **“사람 결정”으로 남길 매칭 충돌과, 자동 후보 정렬·cluster 처리할 매칭 충돌을 어떻게 나눌 것인가?**

---

## 결론

v1은 큰 방향은 맞다. 하지만 v1의 적은 “방어장치 부족”이 아니라 “자동화한다고 해놓고 실패하면 사람 큐로 보내는 구조”다. v3는 사람 개입을 줄이는 척하지 말고, 사람이 봐야 하는 카드를 더 똑똑하게 줄이는 쪽으로 살을 붙여야 한다.
