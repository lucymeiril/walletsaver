# DB-admin 영역 v4 반론 (GPT-5.5, Round-A)

> 입력: `db-v1-opus.md`, `db-v2-gpt.md`, `db-v3-opus.md`  
> 작성자: GPT-5.5 (v4)  
> 원칙: v3가 배척한 “금지·축소·과한 숫자 박기”는 되풀이하지 않는다. 대신 v3가 새로 얹은 모델의 빈틈, 운영 엣지, 웹/크롤러/AI 충돌 지점을 판다.

---

## A. 본문 요약

v3는 v2의 진짜 지적은 꽤 많이 받아들였다. `stable_id + redirect`, atomic snapshot publish, escalation claim/version, robust score, freshness_decay, category_remap, 조건부 가격 컬럼, 매칭 토큰 API P0 격상은 v2의 핵심을 흡수한 것이다.

동시에 v3는 v2의 일부 표현과 권고를 “운영자 권한을 깎고 기능을 줄이는 방식”으로 보고 강하게 배척했다. 이 배척은 상당 부분 정당하다. 특히 DnD depth 금지, score 숨김, snapshot 고정 MB 기준, 수동 6단계 rollback 같은 제안은 사용자 목표와 맞지 않았다.

내 입장: v3 방향은 v1보다 훨씬 단단하다. 다만 v3는 반대로 **P0가 너무 비대해졌고**, “가시화·감점·rollback이면 된다”는 문장 뒤에 실제 운영 계약이 비어 있는 곳이 있다. 이번 v4는 기능을 닫자는 말이 아니라, v5가 바로 결단할 빈칸을 드러내는 문서다.

---

## B. v3가 v2를 배척한 항목 재검토

### 1. “DnD는 depth 제한해야 한다” 배척

- **v3 배척은 대체로 정당하다.** depth가 깊다는 이유만으로 DnD를 막으면 운영자가 더 느리고 답답한 모달 흐름에 갇힌다.
- 하지만 v3의 “전체 depth DnD + preview + undo”도 빈칸이 있다.
  - 드래그 실수는 preview로 잡히지만, **검색으로 찾은 parent가 비슷한 이름일 때** 잘못 놓는 문제는 남는다. 예: `정육 > 한우 > 등심`과 `정육 > 수입소고기 > 등심`.
  - “변경 대기” 박스에 여러 이동이 쌓이면, 첫 이동이 두 번째 이동의 경로를 바꿔 preview가 낡을 수 있다.
  - 마우스/트랙패드가 불편한 운영자는 DnD보다 breadcrumb 검색 + “여기로 이동”이 더 빠를 수 있다.
- 재제기: DnD를 막지 말고, **DnD와 검색 기반 이동을 동등한 1급 입력 방식**으로 둬야 한다. 또한 적용 직전 preview는 “처음 드롭 시점”이 아니라 “최종 적용 직전의 최신 tree_version” 기준으로 다시 계산되어야 한다.

### 2. “롤백은 절차가 길어야 한다” 배척

- **v3 배척은 정당하다.** 운영자에게 pause→backup→restore→check→swap→resume을 매번 손으로 누르게 만들면 rollback 기능은 장식이 된다.
- 그러나 “한 클릭”이라는 말이 너무 강하면 다른 문제가 생긴다.
  - 선택한 백업이 현재 운영 DB보다 오래되어 `match_candidate_log`, `community_price_signal`, 최신 alias가 대량으로 사라질 수 있다.
  - 6단계 중 4단계 integrity check에서 실패했을 때, 이미 생성된 pre-restore 백업과 임시 DB 파일의 정리 규칙이 필요하다.
  - restore 도중 web-api가 옛 snapshot을 계속 보는지, 새 snapshot을 강제로 재빌드하는지 결정이 없다.
- 재제기: 버튼은 하나여도, 내부 작업은 **idempotent job**으로 남아야 한다. `restore_job_id`, 단계별 상태, 재시도 가능 단계, 실패 후 남은 파일 처리 규칙이 있어야 “한 클릭”이 실제 운영 기능이 된다.

### 3. “hotdeal_score 노출 금지, chips만” 배척

- **v3 배척은 정당하다.** 사용자는 “62점·살 만함” 같은 한 줄 답을 원한다. 점수를 숨기면 DB가 계산한 값을 UX가 제대로 쓰지 못한다.
- 다만 점수는 숫자라서 사용자가 과신한다.
  - 표본 n=6에서 78점과 n=300에서 78점은 같은 의미가 아니다.
  - `coupon/membership/card` 조건부 가격은 score가 높아도 체감 접근성이 낮다.
  - 카테고리별 label 임계가 다르면 “70점=핫딜”의 의미가 상품군마다 달라진다.
- 재제기: 점수를 숨기지 말고, **점수 성숙도**를 같이 줘야 한다. 예: `score=78`, `score_confidence=0.62`, `label=핫딜`, `label_basis=신선식품 프로파일 v1`. 숫자는 보이되 숫자의 바닥도 같이 보인다.

### 4. “snapshot 크기 100/300/500MB 규격” 배척

- **v3 배척은 정당하다.** 고정 MB 기준은 데이터 모양이 바뀌면 바로 틀린다.
- 하지만 v3의 “모니터만”은 약하다.
  - web-api가 snapshot을 열고 검색/상세/게시글 grade_summary를 응답하는 실제 지연이 기준에 없다.
  - 빌드 시간, 파일 크기, row count를 기록해도 “언제 쪼갤지” 결정을 못 하면 대시보드 숫자 구경으로 끝난다.
- 재제기: 고정 숫자 대신 **환경별 성능 예산**을 둬야 한다. 예: “상품 상세 p95 200ms 초과 3일 연속”, “snapshot build가 배포 주기보다 길어짐”, “web-api 메모리 상한의 70% 초과”처럼 실제 서비스 동작 기준으로 분리 결정을 만든다.

### 5. “escalation 큐 한 화면 25개 강제” 배척

- **v3 배척은 정당하다.** 운영자마다 처리 속도와 화면 크기가 다르니 25/50/100 고정은 취향이다.
- 하지만 완전 자유 설정도 빈틈이 있다.
  - 페이지 크기 500으로 저장한 운영자가 느린 화면을 만들고 “시스템이 느리다”고 느낄 수 있다.
  - raw name 그룹화가 틀리면 서로 다른 상품이 한 그룹으로 묶여 bulk 확정 사고가 난다.
- 재제기: 행 수를 강제하지 말고, **처리량 지표**를 보여줘야 한다. “오늘 확정 142건 / 재오픈 9건 / bulk 확정 취소 3건”처럼 큐 운영 품질을 봐야 한다. 그룹 bulk 확정은 항상 group evidence를 같이 보여줘야 한다.

### 6. “id immutable 강제” 배척

- **v3 배척은 절반 이상 정당하다.** fingerprint는 정책 변화에 따라 바뀌어야 한다. `immutable`을 fingerprint에 걸면 brand_alias, name_core 개선, 단위 파서 개선이 막힌다.
- 하지만 redirect가 만능은 아니다.
  - redirect chain이 길어지거나 cycle이 생기면 `resolve(id)`가 흔들린다.
  - split은 old stable_id 하나가 new stable_id 여러 개로 갈라지는 상황이다. 단순 `from_id → to_id` 한 줄로는 표현이 부족하다.
  - web-api의 `SnapshotRepo.product_by_id()`와 `grade_by_id()`는 현재 id를 그대로 조회한다. 모든 소비자가 redirect resolver를 반드시 거친다는 계약이 코드에 아직 없다.
- 재제기: fingerprint를 묶지 말고, **redirect resolver의 결정성**을 묶어야 한다. terminal id, chain max depth, split 시 fallback, legacy id 조회 경로를 snapshot/web-api까지 계약해야 한다.

### 7. “매칭 토큰 API 추가하면 결합 문제” 배척

- **v3 배척은 정당하다.** 이미 `Post.canonical_id`가 있고, 게시글 상세가 snapshot의 `price_grade`를 읽는다. 토큰 API가 없으면 결합이 사라지는 게 아니라 수동 입력으로 방치된다.
- 새 약점은 반대쪽이다.
  - 게시글 작성 화면이 match API 응답을 기다리면 db-admin 장애가 글 작성 UX에 영향을 준다.
  - 봇/스팸 작성이 match API를 계속 때리면 `match_candidate_log`와 검색 계산이 같이 늘어난다.
  - `request_id`만 있고 idempotency가 없으면 새로고침/재시도로 같은 후보 로그가 중복 적재된다.
- 재제기: 토큰 API는 P0가 맞다. 대신 web-api는 **응답 지연 시 “매칭 없이 게시 후 나중에 매칭”** 경로를 가져야 하고, db-admin은 request idempotency와 호출량 대시보드를 가져야 한다.

### 8. “category set_version 활성화는 unmapped 0 강제” 배척

- **v3 배척은 방향상 맞다.** 운영자가 “미분류로 떨어져도 지금 바꿔야 한다”고 판단할 수 있다.
- 하지만 강제 활성화의 후폭풍이 작지 않다.
  - 미분류 상품이 늘면 category feed, 검색 facet, 가격대 집계가 한동안 빈다.
  - 게시판 카테고리 필터는 stable_id 경유라 영향이 적다고 했지만, 카테고리별 hotdeal feed는 바로 흔들린다.
- 재제기: 강제 활성은 남기되, **활성 후 미분류 처리 큐**가 자동 생성되어야 한다. “47개 미매핑”을 경고하는 데서 끝나면 다음 날 운영자는 어디서부터 수습할지 모른다.

### 9. “도매 소스 끊기면 anchor 비활성” 배척

- **v3 배척은 정당하다.** 소스가 늦었다고 기능을 꺼버리면 일반 사용자는 갑자기 기준선을 잃는다.
- 다만 freshness_decay 산식은 너무 단순하다.
  - 계란/채소처럼 가격 변동이 큰 품목과 가공식품의 7일 의미가 다르다.
  - 여러 소스가 동시에 같은 기관 계열 데이터를 재가공한 것이라면 “다중 소스”처럼 보여도 실제론 같은 anchor다.
- 재제기: 기능은 살리되, freshness는 **카테고리별 half-life**와 source lineage를 가져야 한다. “3개 소스 평균”이 아니라 “서로 독립인 3개 소스인지”가 중요하다.

### 10. “브랜드 alias 자동 학습 금지” 배척

- **v3 배척은 정당하다.** 학습 자체를 막으면 매칭 품질이 좋아질 길이 없다. `suggested` 상태로 받고 운영자가 승인하는 흐름이 맞다.
- 약점은 queue 폭증과 AI 경계다.
  - 마트명/PB/판매자명이 섞인 alias suggestion이 매일 수백 개 쌓이면 운영자는 승인 화면을 안 보게 된다.
  - AI가 alias 후보를 만들고 DB가 승인 상태를 갖는다면, 어떤 feature/evidence가 DB에 남고 어떤 것은 AI 영역에 남는지 경계가 필요하다.
- 재제기: 자동 학습은 계속하되, alias suggestion은 **중복 묶음·영향 수·증거 출처**로 정렬되어야 한다. DB는 승인 기록과 evidence를 보관하고, AI는 후보 생성 모델을 소유하는 식으로 갈라야 한다.

---

## C. v3가 새로 도입한 것의 약점

### 1. stable_id + redirect

구현 난도는 v3가 적은 것보다 크다. 기존 `Post.canonical_id` 값이 SHA1인지, 테스트 fixture식 임의 문자열인지, 수동 입력인지 섞일 수 있다. `canonical_id_redirect`가 old fingerprint와 old stable_id를 같이 받으면 네임스페이스 충돌도 생긴다.

운영 부담: merge/split/redirect history를 보는 UI가 필요하다. “왜 이 게시글이 갑자기 다른 상품으로 보이나”를 설명하려면 redirect reason과 적용 시점이 사용자/운영자 양쪽에 남아야 한다.

웹 충돌: web-api의 snapshot 조회는 현재 canonical_id 직접 조회다. redirect resolver가 snapshot에 없으면 예전 게시글은 조용히 grade_summary가 사라진다.

AI 충돌: AI 추천은 stable_id를 반환해야 하는데, 학습 데이터는 과거 SHA1/fingerprint일 가능성이 높다. 모델 입력/출력 id 변환 레이어가 필요하다.

### 2. robust hotdeal_score 산식

v3 산식은 v1보다 낫지만 여전히 손으로 박은 가정이다. `0.5/0.3/0.2`, `coupon=0.7`, `bundle=0.6`, anchor 없으면 `0.5`는 설명 가능하지만 증명된 값은 아니다.

UX 영향: “anchor 없으면 중립값”은 사용자가 보기엔 점수가 평평해지는 원인이다. 같은 65점이라도 도매가 anchor가 있는 65점과 없는 65점은 다르다.

운영 부담: category별 pricing_profile을 운영자가 조정할 수 있게 하면, 점수 변동의 책임도 운영자에게 온다. “어제 80점이 오늘 62점”이면 price가 바뀐 건지 profile이 바뀐 건지 reason chip에 버전 diff가 있어야 한다.

### 3. freshness_decay

단순하고 좋지만 모든 품목에 7일 정상/37일 0은 맞지 않는다. 배추·상추·계란 같은 급변 품목과 휴지·세제 같은 생필품은 decay 속도가 달라야 한다.

크롤러 충돌: source failure가 “진짜 소스 중단”인지 “크롤러 파서 깨짐”인지 구분해야 한다. 둘 다 freshness가 떨어지지만, 운영자가 볼 해결 액션은 다르다.

### 4. category_remap

모델 자체는 맞다. 문제는 split/merge의 영향 범위다. category_remap이 category_id만 바꾸는 것처럼 보이지만 실제로는 keyword, autocomplete, price aggregation, board feed facet, dashboard 통계까지 재계산이 필요하다.

운영 부담: AI가 1차 매핑을 채운다고 했는데, AI 추천이 틀렸을 때 bulk approve가 더 큰 사고를 만든다. remap 화면은 “한 줄씩 승인”과 “근거가 같은 묶음 승인”을 구분해야 한다.

### 5. match_candidate_log

학습 신호로는 좋다. 하지만 게시글 title/body_excerpt/deal_url가 들어가면 사용자 활동 로그이기도 하다. 검색 의도, 구매 관심, 커뮤니티 작성 패턴이 모두 남는다.

운영 부담: 로그가 빨리 쌓인다. 후보 5개 JSON을 매 요청마다 저장하면 인덱스 설계 없이 나중에 “학습에 쓰고 싶다” 단계에서 조회가 느려진다. hot storage와 archive를 나눠야 한다.

### 6. atomic snapshot publish

`.next → checksum → os.replace`는 맞다. 추가 빈칸은 web-api의 핸들 교체다. 현재 SnapshotRepo는 id별 조회를 한다. 새 snapshot이 publish되어도 기존 커넥션이 언제 닫히는지, Windows에서 파일 핸들이 열린 상태의 replace 동작을 어떻게 다룰지 계약이 필요하다.

### 7. DnD + preview + undo

좋은 UX지만 undo가 쉬운 만큼 AuditLog가 더 중요해진다. AuditLog에 before/after JSON만 남기면 대량 이동 후 “다른 운영자가 중간에 같은 노드를 또 옮긴 경우” reverse가 단순하지 않다.

### 8. one-click rollback

DB 파일 rollback과 public snapshot rollback은 같은 일이 아니다. 운영 DB를 되돌렸는데 web-api가 새 snapshot을 계속 보면 화면은 복구되지 않는다. 반대로 snapshot만 되돌리면 admin DB와 공개 DB가 어긋난다.

### 9. community_price_signal

score 직접 조작을 피하고 dispute flag로 두는 건 맞다. 다만 댓글이 수정/삭제/숨김 처리될 때 count가 어떻게 감소하는지가 없다. 게시글의 canonical_id가 바뀌면 기존 verdict를 어느 stable_id에 귀속할지도 결정해야 한다.

### 10. pricing_profile

프로파일 테이블은 하드코딩보다 낫다. 하지만 운영자가 조정 가능한 값이 늘수록 “왜 이 점수가 나왔는가”를 설명하기 어려워진다. profile 변경은 snapshot_version/scoring_profile_version뿐 아니라 change note가 필요하다.

---

## D. v3 자수 5포인트(Z-3) 보강

### 1. stable_id 마이그레이션 한 방

v3가 자수한 대로 가장 큰 구멍이다. 추가로, web-api `Post.canonical_id`가 반드시 기존 SHA1이라고 볼 수 없다. 테스트에는 `prod_tofu_001` 같은 값도 있다. 운영 데이터에도 수동 문자열이 섞였을 가능성을 열어야 한다.

필요한 dry-run 출력:
- 현재 canonical_products에 존재하는 id와 일치하는 post 수
- snapshot에 grade가 있는 post 수
- 어느 쪽에도 안 맞는 orphan canonical_id 수
- 같은 legacy id가 둘 이상의 stable_id 후보로 갈리는 수
- redirect 생성 후 `grade_summary`가 복구되는 post 수

### 2. pricing_profile 가중치 시드의 자의성

v3의 robust 산식은 v1의 60/20/10/10보다 보기 좋지만, 결국 초기값은 사람이 박는다. A/B가 P2면 초반 운영자는 profile을 감으로 만진다.

보강 질문: v5는 “처음 3개월은 점수값을 고정하고 label 임계만 조정”할지, “프로파일 가중치까지 자주 조정”할지 정해야 한다. 둘은 운영 로그 해석이 완전히 다르다.

### 3. community_price_signal pull 배치 주기 미정

polling 주기만 문제가 아니다. 댓글 verdict는 게시글 숨김, 댓글 삭제, 유저 탈퇴, canonical_id 재매칭과 같이 움직인다. 단순 count pull이면 과거 신호가 잘못 남는다.

보강 모델:
- web-api가 `post_id + canonical_id + verdict_version` 요약을 제공
- db-admin은 마지막으로 본 `verdict_version` 이후만 pull
- post canonical_id 변경 시 old stable_id count에서 빼고 new stable_id count에 더하는 delta 이벤트 필요

### 4. canonical split P2 비용

merge만 P1이고 split이 P2면 데이터는 한 방향으로 뭉친다. 한 번 잘못 합쳐진 우유/저지방우유, 계란 특란/대란은 price_grade와 게시글 판단을 같이 오염시킨다.

v5가 split 풀세트를 P0로 올릴 필요는 없다. 하지만 최소한 P1에는 “split 요청 큐 + 새 관측치부터 분리 + 과거 관측치 격리”가 있어야 한다. 과거 전체 이관은 나중이어도, 새 데이터 오염은 멈춰야 한다.

### 5. match_candidate_log 적재량

로그 폭증 외에 개인정보성도 있다. body_excerpt와 deal_url는 구매 관심과 외부 쇼핑 URL을 담는다. 나중에 결제/구매 추적이 붙으면 이 로그는 더 민감한 행동 데이터가 된다.

필요한 운영 계약:
- request_id idempotency
- query_payload 필드별 저장/마스킹 기준
- 90일 hot, 이후 후보 JSON 압축 또는 집계 전환
- 봇/스팸 요청 별도 표식
- 학습에 사용된 로그 snapshot 버전 기록

---

## E. v1/v2/v3 모두 놓친 시나리오

### 1. 결제/구매 추적이 붙을 때

아직 없지만 향후 “이 핫딜 보고 샀다”를 추적하면 DB 모델이 바뀐다. 구매 이벤트는 게시글, stable_id, snapshot_version, 표시 점수, 실제 구매가, 쿠폰/멤버십 적용 여부를 같이 저장해야 한다. 그래야 “DB 점수가 실제 절약으로 이어졌는가”를 검증한다.

주의점은 상품 DB에 결제 원장을 넣지 않는 것이다. web-api/결제 영역이 구매 이벤트를 소유하고, db-admin은 집계된 conversion signal만 받아 scoring 검증에 써야 한다.

### 2. GDPR/개인정보 운영 요구

`search_query_log`, `match_candidate_log`, `session_hash`, 댓글 verdict, AuditLog는 모두 사용자 행동 흔적이다. 이름/이메일이 없어도 조합하면 사용자의 관심 상품과 활동 패턴이 보인다.

필요한 것:
- 사용자별 export/delete 요청이 들어왔을 때 지울 수 있는 키 설계
- raw query/body_excerpt TTL
- 집계 캐시와 원본 로그 분리
- admin audit은 삭제 대상과 보존 대상 구분
- session_hash 재식별 방지를 위한 rotation

### 3. DB 자체 백업/복구

v3는 rollback UX를 다뤘지만, 디스크 손상/서버 다운/파일 일부 손상은 별도다. SQLite라면 파일 단위 백업 검증이 핵심이다.

필요한 것:
- 백업 생성 후 `PRAGMA integrity_check` 결과 저장
- 운영 DB와 public snapshot의 버전 쌍 저장
- 다른 머신/디스크 위치에 복사된 백업
- 월 1회 restore drill 결과 기록
- WAL 파일 포함 여부 명시

### 4. 다국어/다지역 확장

현재 카테고리와 상품명은 한국어 중심이다. 해외 직구/오픈마켓까지 보면 locale, currency, tax, shipping, unit system이 들어온다.

모델 빈칸:
- `display_name_i18n`
- category locale label
- source currency + fx_rate_at_observed
- shipping 포함/제외 가격
- 국가별 세금 포함 여부

### 5. API rate limit / 봇 트래픽

match candidates, autocomplete, product summary는 봇이 때리기 쉽다. 문제는 차단 그 자체가 아니라, 봇 요청이 로그와 학습 데이터를 오염시키는 것이다.

필요한 운영 데이터:
- caller_id/web-api route별 요청량
- request_id idempotency
- bot_like flag
- 후보 로그에서 bot_like 제외 집계
- hot endpoint cache hit rate

### 6. 도매가 외 추가 anchor 소스

해외 직구, 오픈마켓, 쿠팡, 창고형, 가격비교 사이트를 anchor로 섞을 수 있다. 이때 도매가와 같은 weight로 두면 안 된다.

source class가 필요하다:
- wholesale
- retail_marketplace
- overseas_direct
- warehouse_bulk
- manual_admin

각 source class는 배송비, 관세, 최소구매수량, 신뢰도, 갱신주기가 다르다.

### 7. 시간대 / 타임존

KST는 DST가 없지만 외부 소스와 서버는 UTC일 수 있다. `observed_date`만 있으면 자정 근처 세일이 전날/다음날로 밀린다.

필요한 컬럼:
- `observed_at_utc`
- `source_timezone`
- `local_sale_date`
- `bucket_timezone`

특히 daily_agg는 “한국 사용자가 본 날짜” 기준인지 “source가 공시한 날짜” 기준인지 정해야 한다.

### 8. 대규모 트래픽 시 read replica

public snapshot은 read scaling에 좋다. 하지만 match_candidate_log, search_query_log, community pull, admin dashboard는 쓰기/집계를 만든다. 전부 SQLite 하나에 몰면 admin DB가 병목이 된다.

v5는 “공개 조회는 snapshot”, “학습 로그는 별도 append DB/테이블”, “운영 mutation은 admin DB”처럼 읽기/쓰기 경계를 더 쪼갤지 결정해야 한다.

### 9. 게시판 DB와 상품 DB 결합도가 정말 0인가

코드상 0이 아니다.

- `Post.canonical_id`가 web-api DB에 있다 (`board_models.py`).
- 게시글 작성 폼이 canonical_id를 받는다 (`routes/boards.py`).
- 상세 응답은 `grade_summary`를 snapshot에서 조회한다.
- `SnapshotRepo.product_by_id()` / `grade_by_id()`는 canonical_id 직접 조회다.

즉 결합은 FK가 없을 뿐, **문자열 의미 계약**으로 이미 존재한다. v5는 “약결합”이라는 표현을 유지하되, 실제 계약을 `stable_id`, redirect resolver, snapshot_version으로 명시해야 한다.

### 10. 매칭 학습과 AI 영역의 경계

DB는 ground truth와 운영 확정 이력을 가져야 한다. AI는 후보 생성과 ranking을 맡아야 한다. 이 선이 흐려지면 AI가 만든 alias가 DB에서 어느 날 승인된 사실처럼 쓰일 수 있다.

경계 제안:
- DB 소유: approved alias, rejected alias, conflict resolution, match_candidate_log, selected/rejected outcome
- AI 소유: candidate generator, feature extraction, model version, confidence calculation
- 공유: evidence schema, model_version, training_snapshot_id

---

## F. v5(Opus 최종)가 결단해야 할 질문 5개

1. **stable_id 마이그레이션 성공 기준은 무엇인가?**  
   orphan `Post.canonical_id` 몇 개까지 허용할지, dry-run에서 어떤 카운트가 0이어야 진행할지 정해야 한다.

2. **v3의 P0 15개 중 “테이블 자리만 P0”와 “운영 UI까지 P0”를 어떻게 나눌 것인가?**  
   전부 풀세트 P0면 라이브가 늘어진다. scaffold와 완성 기능을 분리해야 한다.

3. **hotdeal_score 초기값을 누가, 어떤 근거로 고정할 것인가?**  
   category pricing_profile v1의 가중치, label 임계, confidence 표시 규칙을 한 번에 정해야 한다.

4. **web-api와 db-admin의 약결합 계약은 어디까지인가?**  
   match API 장애 시 게시글 작성 경로, snapshot_version 헤더, redirect resolver, community signal sync 방식을 정해야 한다.

5. **행동 로그·백업·트래픽 운영 책임자는 누구인가?**  
   search/match/community 로그 TTL, restore drill, bot_like 제외 집계, read scaling 전환 기준을 DB 영역이 어디까지 소유할지 정해야 한다.

---

_v4 끝. v3의 “금지하지 말고 가시화·감점·rollback으로 푼다”는 방향은 유지한다. 대신 v5는 그 방향을 실제 운영 계약, 로그 수명, id migration 검증, 웹/AI 경계로 내려박아야 한다._

