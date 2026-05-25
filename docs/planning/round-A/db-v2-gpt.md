# DB-admin 영역 v2 적대적 검토 (GPT-5.5, Round-A)

> 대상: `docs/planning/round-A/db-v1-opus.md`  
> 원칙: v1을 덮어쓰지 않고, 코드와 운영 리스크 기준으로 반박/보강한다.  
> 결론: v1은 방향은 맞지만, “이미 있다”와 “기획이다”를 몇 군데 섞었고, 라이브 직전 P0 우선순위가 아직 덜 날카롭다.

---

## 본문 요약

v1의 큰 그림은 유효하다. 현재 db-admin에는 canonical 상품, 마트 SKU alias, 가격 관측, 가격 분위수, 검토 큐, 카테고리/키워드 UI, 백업 코드가 실제로 있다. web-api에는 별도 게시판 DB 모델도 있다.

하지만 v1은 다음을 과소평가했다.

1. `canonical_id`를 SHA1로 계산하는 순간, 정규화 규칙 변경이 곧 외부 매칭 파괴로 이어진다.
2. 게시판 결합은 “없음”이 아니라 `Post.canonical_id`가 이미 있어 반쯤 들어와 있다. 다만 자동 매칭/신뢰도/토큰 계약이 없다.
3. 공개 스냅샷 빌더는 `.tmp → atomic rename`이 아니라 기존 파일 삭제 후 재생성이다. 운영 중 깨질 수 있다.
4. 카테고리 트리 편집은 DnD가 아니라 버튼/선택 기반 이동이다. 3-depth 이상에서 화면 피로가 커진다.
5. 핫딜 점수 0–100은 분포가 한쪽으로 치우치면 바로 망한다. 특히 P10/P50 간격이 좁거나 표본이 적으면 점수가 거짓 확신을 준다.

---

## A. v1 사실관계 검증

### A-1. v1이 맞게 본 것

| v1 주장 | 검증 결과 |
|---|---|
| `CanonicalProduct`가 있다 | 맞다. `packages/db-admin/backend/storage/canonical_models.py`에 SQLAlchemy 모델이 있고, `packages/shared/core/canonical_models.py`에도 Pydantic DTO가 있다. |
| `CanonicalProduct.id = SHA1(brand|name_core|pack_qty|pack_unit)` | 맞다. shared 모델의 `make_id()`가 실제로 SHA1을 만든다. DB 모델 주석도 같은 계약을 적고 있다. |
| `MartSkuAlias`와 `UNIQUE(mart, mart_item_id)`가 있다 | 맞다. `canonical_mart_sku_aliases`에 unique constraint가 있다. |
| `PriceObservation`과 `canonical_id, mart, observed_at` 인덱스가 있다 | 맞다. 다만 인덱스 방향은 주석과 달리 SQLAlchemy 코드상 DESC 지정은 없다. |
| `ProductReviewQueue`가 있다 | 맞다. raw_payload, source_mart, reason, suggested_canonical_id, resolved_at, resolver_user_id가 있다. |
| `oneshot_public_db.build_snapshot`이 있다 | 맞다. canonical/product/price_grade/category/alias를 공개 SQLite로 뽑는다. |
| `Keyword`/`ProductKeyword`는 있으나 검색 로그 기반 학습 테이블은 없다 | 맞다. `Keyword.search_count` 증가는 있지만 `search_query_log` 같은 raw query 로그는 없다. |
| `AuditLog`가 있다 | 맞다. legacy `storage/models.py`에 있다. |
| `CategoryCorrection`이 따로 있다 | 맞다. legacy 카테고리 보정 이력으로 존재한다. |
| KAMIS 금지 주석이 있다 | 맞다. `oneshot_public_db.py`와 `price_grading.py`에 명확히 있다. |

### A-2. v1이 부정확하거나 과장한 것

| v1 주장 | 실제 코드 기준 반박 |
|---|---|
| 게시판 DB가 `packages/web-api/backend/var/board.sqlite` 등에 있다 | `var` 디렉터리는 없다. 기본 경로는 `packages/web-api/backend/storage/board.sqlite`다. 단, 파일은 런타임 생성이고 환경변수 `WALLETSAVIOR_BOARD_DB`로 바뀐다. |
| 게시판-상품 결합 모델이 없다 | 완전한 결합 모델은 없지만 `web-api`의 `Post`에 이미 `canonical_id`, `deal_price`, `mart_name`, `deal_url`이 있다. `grade_summary`도 public snapshot에서 p10/p50을 읽는다. 즉 “없다”가 아니라 “수동 canonical_id 입력 수준만 있고 자동 매칭/신뢰도/토큰이 없다”가 정확하다. |
| 공개 스냅샷이 `.tmp → atomic rename`으로 매일 새로 생성 | 현재 코드는 기존 snapshot 파일을 `unlink()`하고 새로 만든다. atomic rename은 기획이지 구현이 아니다. |
| 스냅샷이 read-only | 스키마상 공개용일 뿐, 파일 권한이나 SQLite `mode=ro` 강제는 빌더 코드에 없다. 소비자가 read-only로 열어야 한다. |
| 카테고리 트리 adjacency list 4depth | canonical 모델 주석은 1~4를 말하지만 DB 제약으로 4depth를 강제하지 않는다. legacy `Category`는 `depth` 숫자만 있고 4depth 제약이 없다. |
| 카테고리 DnD 미구현 | 맞다. 현재 `ClassificationPage`는 트리 표시, 추가/수정/삭제, 이동 모달 흐름이다. 드래그앤드롭은 없다. |
| 백업 서비스는 있다 | 맞다. 하지만 restore API/UI는 보이지 않는다. backup 생성/list 위주다. “롤백 UX”는 거의 기획이다. |
| 권한 모델은 거의 안 다룸 | v1의 자수는 절반만 맞다. 코드에는 `viewer/service/moderator/admin/ai_publisher` 계층과 scoped role이 있다. 다만 DB-admin, web-api, ai-admin 사이의 권한 계약은 문서화가 약하다. |

---

## B. v1이 빠뜨린 부분 / 약점

### B-1. v1 자기검증 5포인트에 대한 적대적 답

#### 1) 도매가 anchor 소스

약점 맞다. 테이블 모양만 있고 실제 수급처, 갱신 주기, 단위 환산, 지역 단위가 없다.

단, 여기서 “크롤러 막기”로 가면 안 된다. 해야 할 일은 금지가 아니라 **소스 다중화**다.

- 1차: 수동 입력/CSV 업로드로 P0를 살린다.
- 2차: 공판가/도매시장/마트 납품가 성격의 공개 가능한 소스를 여러 개 둔다.
- 3차: 소스별 신뢰도와 freshness를 저장한다.

`wholesale_baseline`에는 단순 `source`만 두지 말고 `source_status`, `last_success_at`, `freshness_days`, `confidence_score`가 필요하다. 소스가 끊기면 기능을 끄는 게 아니라 “도매 anchor 오래됨”으로 감점해야 한다.

#### 2) canonical_id 안정성

v1 최대 약점이다. SHA1 자체가 문제가 아니라 **SHA1 입력이 정책이라는 점**이 문제다.

`brand_alias`를 나중에 넣으면 기존 `서울우유|우유|1|L`과 `(주)서울우유|우유|1|L`의 id가 달라진다. 게시판, alias, price_grade, snapshot, 댓글 검증이 전부 흔들린다.

필요한 모델:

- `canonical_product_identity`
  - `stable_id`: 외부 공개용 불변 ID
  - `current_fingerprint`: 현재 정규화 해시
  - `fingerprint_version`
  - `merged_into_id`
  - `split_from_id`
- `canonical_id_redirect`
  - old_id → new_id
  - reason: merge/split/brand_alias_rule/category_rebuild

외부에는 해시를 그대로 계약하지 말고 stable_id를 계약해야 한다.

#### 3) escalation resolve 트랜잭션 + 동시성

v1 지적이 맞다. 현재 `ProductReviewQueue`에는 `resolved_at`만 있고 row version, claim, lock owner가 없다. 두 운영자가 같은 큐를 열고 동시에 확정하면 마지막 commit이 이길 수 있다.

필요한 최소 모델:

- `claimed_by`, `claimed_at`, `claim_expires_at`
- `version` 또는 `updated_at` 기반 optimistic check
- resolve API는 `WHERE id=? AND resolved_at IS NULL AND version=?` 형태로 1행 갱신 성공 여부를 봐야 한다.
- 실패하면 “이미 다른 관리자가 처리함”으로 새 상태를 보여준다.

금지가 아니라 충돌을 사용자에게 빨리 보여주는 구조가 필요하다.

#### 4) 공개 스냅샷 크기·갱신 SLA

v1은 문제를 봤지만 충분히 못 박지 않았다. 현재 스냅샷에는 raw observations 전체가 들어가지는 않는다. 그래서 크기 폭발은 당장은 덜하다. 하지만 trend API, daily agg, hotdeal score, 지역/단위/시즌 정보가 들어가면 다시 커진다.

P0 SLA를 숫자로 박아야 한다.

- snapshot build 60초 이내
- 파일 크기 100MB 이내에서 시작, 300MB 경고, 500MB 분리
- atomic publish 필수: `public_snapshot_next.sqlite` 생성 → checksum → rename
- 이전 N개 snapshot 보관
- web-api는 현재 열고 있는 snapshot 핸들을 바로 갈아끼우지 않고 다음 요청부터 새 파일을 쓰게 한다.

#### 5) 매칭 토큰 API P0 여부

P0로 올려야 한다. 이유는 간단하다. 게시판 `Post.canonical_id`가 이미 있고, `grade_summary`도 이미 붙는다. 그런데 사용자가 글 쓸 때 canonical_id를 어떻게 안정적으로 얻는지가 없다. 이 상태로 라이브하면 게시판-상품 결합은 “폼에 id 직접 넣는 기능” 수준이 된다.

최소 P0:

- title/body/deal_url/mart_name/deal_price 입력 → 후보 canonical 5개 반환
- 후보별 `match_reason`, `confidence`, `unit_basis`, `last_seen_at`
- 작성자가 선택/무시 가능
- 무시된 케이스도 로그로 남겨 모델 개선

### B-2. v1이 명시 안 한 엣지 케이스

#### 마트 폐점 / 상품 단종

`MartSkuAlias.first_seen_at/last_seen_at`은 있지만 active 상태가 없다. 단종을 가격 하락/품절/크롤 실패와 구분해야 한다.

필요 컬럼:

- alias `availability_status`: active/out_of_stock/discontinued/unknown
- `last_success_seen_at`
- `last_missing_seen_at`
- 단종은 canonical 삭제가 아니라 alias 상태 변경이다.

#### 같은 상품 두 마트 동시 핫딜

현재 score가 canonical 단위로만 강하면 “어느 마트에서 싼지”가 흐려진다. 핫딜은 canonical 전체 점수와 mart별 현재 최저가 점수를 분리해야 한다.

- `canonical_hotdeal_score`: 상품 전체의 시장 상태
- `mart_offer_score`: 특정 마트의 현재 오퍼 상태
- 게시판 배지는 후자를 먼저 보여줘야 한다.

#### 도매가 소스 중단

소스가 죽어도 기능을 끄면 안 된다. freshness를 점수에 반영하면 된다.

- 7일 이내: 정상
- 8~30일: anchor 감점
- 31일 이상: “도매가 오래됨” 표시, 시장 분위수 중심으로 fallback

#### 카테고리 트리 재편 시 기존 데이터 migration

v1의 `category_set_version`은 방향은 좋지만, “전환 한 번”으로 끝난다는 말은 과장이다. 기존 상품의 category_id, 키워드, 검색 로그, 게시판 필터가 같이 움직인다.

필요한 것은 버전 전환이 아니라 **mapping table**이다.

- old_category_id → new_category_id
- confidence/manual 여부
- unmapped bucket
- snapshot에는 active version만 내보내되, 관리자 화면에는 미매핑 수를 보여준다.

#### 게시판-상품 매칭 깨질 때

web-api `Post.canonical_id`는 FK가 아니다. 그래서 깨져도 DB가 모른다. public snapshot에서 grade가 없으면 `grade_summary=None`으로 조용히 사라진다.

필요한 표시:

- “이 게시글의 상품 매칭이 오래되었거나 사라짐”
- 재매칭 후보
- old canonical redirect 지원

#### 가격 표기 변동: 중량/할인 조건부

현재 `unit_price_normalized`와 `unit_price_basis`는 있다. 좋은 출발이다. 하지만 조건부 할인이 빠져 있다.

예:

- 2개 구매 시 1개당 1,500원
- 쿠폰 적용 시 2,000원
- 멤버십가
- 카드 청구할인
- 100g당 표시가 있지만 실제 포장 중량 랜덤

필요 모델:

- `effective_price_type`: base/sale/coupon/membership/card/bundle
- `min_purchase_qty`
- `requires_membership`
- `coupon_required`
- `display_price_text`
- `normalized_price_confidence`

### B-3. SQLite 용량/성능 임계 도달 시 plan

SQLite로 시작하는 건 맞다. 하지만 “언제 분리할지”가 없으면 늦게 터진다.

운영 기준을 숫자로 둔다.

- `canonical_price_observations` 500만 행: daily agg 필수, raw 조회 제한
- 2천만 행: observations 월별 archive DB 분리
- 5천만 행 또는 DB 20GB: PostgreSQL/ClickHouse류 분석 저장소 검토
- public snapshot은 raw observations 금지, 집계/현재가/검색 인덱스만 포함

DB-admin UI에는 행수, DB 파일 크기, vacuum 필요 여부, 최근 쿼리 지연을 보여줘야 한다.

### B-4. 백업/롤백 운영 안전성

백업은 SQLite backup API를 써서 그럭저럭 안전하다. 문제는 restore다.

현재 restore 함수는 target DB로 바로 backup을 덮는다. ingestion이 동시에 쓰는 중이면 결과가 꼬일 수 있다. UI 버튼 하나로 운영 DB를 되돌리는 구조는 위험하다.

필요한 운영 절차:

1. ingestion pause flag 켜기
2. 현재 DB pre-restore 백업
3. restore를 새 파일에 수행
4. integrity check
5. DB 핸들 교체
6. ingestion resume

이건 기능 축소가 아니라, 롤백 버튼을 실제로 쓸 수 있게 만드는 최소 안전장치다.

### B-5. 관리자 두 명이 카테고리 트리 동시 편집

현재 legacy category move는 parent/depth를 바로 바꾸고 commit한다. optimistic lock이 없다. 두 명이 동시에 트리를 옮기면 한 명의 화면은 낡은 트리 기준이다.

필요한 UX:

- 편집 세션 시작 시 tree_version 표시
- 저장 시 `tree_version`이 다르면 diff 보여주고 재적용
- 대규모 이동은 dry-run preview에서 영향 상품 수/하위 노드 수 표시
- 삭제는 admin만, 이동은 moderator 가능이라는 현재 권한은 괜찮지만 대량 이동은 admin 승인 옵션이 필요하다.

### B-6. 권한 모델: db-admin / web-api / ai-admin 분리

코드에는 db-admin role이 꽤 있다. 문제는 서비스 경계다.

- crawler/service: ingestion write만 가능
- ai-admin/ai_publisher: suggestion write, snapshot read 정도만 가능
- web-api: public snapshot read, token lookup call만 가능
- db-admin moderator: 큐 resolve/category move 가능
- db-admin admin: backup/restore/reset/delete 가능

v1은 “운영 DB 직접 접근 금지”를 말했지만, 각 API의 실제 권한 scope 표가 없다. 이건 P0 문서로 있어야 한다.

---

## C. v1 UI/UX 제안 검토

### C-1. 카테고리 DnD는 정말 직관적인가

소규모 트리에서는 직관적이다. 3-depth를 넘고 노드가 수백 개가 되면 DnD는 오히려 사고를 부른다.

추천:

- 1~2depth: DnD 허용
- 3depth 이상: “이동” 버튼 + 검색 가능한 parent 선택 + preview
- 대량 이동: 영향 상품 수, 하위 노드 수, 바뀌는 path 목록을 먼저 보여준다.

현재 UI는 DnD가 아니라 트리 행 버튼과 이동 모달 흐름이므로, v1의 P0 DnD는 “있으면 좋은 개선”이지 핵심 P0는 아니다. P0는 **실수 없는 이동 preview와 되돌리기**다.

### C-2. escalation 큐 한 화면 노출 개수

한 화면에 100개를 뿌리면 운영자가 읽지 않는다. 큐는 “많이 보기”보다 “빨리 확정하기”가 중요하다.

추천:

- 기본 25개
- compact 모드 50개
- bulk suggestion은 100개 단위
- 각 row에는 raw name, mart, reason, 후보 1순위, confidence, 생성시각만 표시
- 상세 패널에서 raw_payload 전체 확인

### C-3. 백업/롤백 오작동 위험

백업 버튼은 쉬워도 된다. 롤백 버튼은 쉬우면 안 된다.

추천:

- 백업: admin 1클릭 가능
- restore/rollback: 영향 요약 → “현재 DB도 백업됨” 확인 → restore target 선택 → integrity check 결과 → 적용
- 운영 중 ingestion pause/resume 상태를 화면에 보여준다.

삭제하거나 금지하자는 말이 아니다. 오히려 롤백 기능을 진짜 운영자가 쓸 수 있게 만들자는 말이다.

---

## D. v1 데이터 모델 검토

### D-1. 핫딜 점수 0–100 산식

v1 산식은 `P50 - current`를 `P50 - P10`으로 나눈다. 이건 분포가 안정적이라는 가정이 깔려 있다.

망하는 케이스:

- P10과 P50이 거의 같음: 분모가 작아서 점수 폭발
- 표본 5개: 충분성 기준은 통과하지만 분포 대표성이 낮음
- 행사 기간 표본이 대부분: P10/P50이 같이 내려가 핫딜을 못 잡음
- 지역/마트가 섞임: 부산 가격과 서울 가격을 한 분위수로 비교

보완:

- 분모 하한값 설정
- sample_size별 confidence 곱
- mart별 score와 전체 score 분리
- 조건부 가격은 별도 confidence 감점
- 점수 대신 `score + reason chips`를 같이 제공

### D-2. 3-layer anchor 가중치

v1은 도매가/시장분위수/이벤트 anchor를 제시하지만 가중치 결정 방식이 없다.

처음부터 ML로 갈 필요는 없다. 카테고리 프로파일을 둔다.

- 신선식품: 도매가 비중 높음, 지역/시즌 보정 높음
- 가공식품: 마트 분위수 비중 높음
- 생필품: 정기 세일 사이클 비중 높음
- 수입/창고형 상품: 도매가 anchor 약함

가중치는 DB에 저장하고 운영자가 조정 가능해야 한다. 하드코딩하면 나중에 움직임이 막힌다.

### D-3. canonical_id 충돌/병합/분리

SHA1 해시 충돌 자체보다 의미 충돌이 더 현실적이다.

예:

- 같은 “계란 30개”인데 특란/대란이 name_core에서 빠짐
- 같은 우유 1L인데 저지방/멸균 차이가 빠짐
- 브랜드 alias가 과하게 합쳐짐

행동 정책:

- 충돌 발견 시 바로 덮어쓰지 않는다.
- `canonical_conflict_queue`에 올린다.
- 운영자는 merge/split/keep separate 중 선택한다.
- merge 시 old_id redirect를 남긴다.
- split 시 기존 price_observations를 어느 쪽으로 보낼지 rule 또는 수동 선택이 필요하다.

### D-4. brand_alias 학습 루프 오염

brand_alias를 자동 학습하면 편하지만 오염되기 쉽다.

오염 예:

- “노브랜드”를 브랜드 없음으로 처리
- “CJ”와 “씨제이제일제당”은 합쳐도 되지만, “제일제당” 단독은 문맥 필요
- PB상품/마트명/판매자명이 브랜드처럼 들어옴

대응:

- 자동 alias는 `suggested` 상태로만 저장
- 적용 전 영향 canonical 수와 merge 후보를 보여준다.
- alias별 rollback 가능해야 한다.
- alias 적용은 새 fingerprint_version에서만 반영한다.

---

## E. v1이 회피한 부분

### E-1. 단계적 로드맵에서 중요한 게 P2로 밀린 것

P2로 밀면 안 되는 것:

- 지역 가격차: 최소한 `region_hint` nullable은 P0/P1에 들어가야 한다. 신선식품은 지역차가 크다.
- 세일 사이클: 완전 학습은 P2여도, `event_labels`와 요일/기간 집계 필드는 P1에 있어야 한다.
- 사용자 신고 반영: 게시판 댓글 verdict가 이미 있으므로 “이거 핫딜 아님” count를 score confidence에 반영하는 최소 루프는 P1이다.
- 매칭 토큰 API: P0다. 게시판 canonical_id가 이미 있으므로 늦추면 실제 라이브에서 결합이 빈 껍데기가 된다.

### E-2. 라이브 직전 P0 재판정

v1 P0 중 조정이 필요하다.

진짜 P0:

1. snapshot atomic publish
2. canonical stable_id/redirect 최소 계약
3. 게시판 매칭 후보 API
4. escalation claim/resolve 동시성
5. price_daily_agg 최소판
6. backup + restore 절차의 ingestion pause
7. 단위 가격 정규화 confidence

P0에서 내려도 되는 것:

- 카테고리 DnD 자체: preview/undo가 더 중요하다.
- 도매가 자동 수급 완성: 수동 입력 + freshness 모델로 먼저 간다.
- hotdeal_score 0–100 완성판: 처음엔 label/confidence/reason 중심으로 간다.

---

## F. 추가 제안

### F-1. 가격 표시 단위 정규화 모델

사용자는 “한 봉지 2,000원”이 싼지 모른다. DB는 반드시 비교 단위를 같이 줘야 한다.

추가 모델:

- `display_price_text`: 원문 가격 표시
- `package_quantity`, `package_unit`
- `normalized_unit_price`
- `normalized_unit_basis`: per_100g/per_1kg/per_each/per_1l
- `normalization_confidence`
- `condition_text`: “2개 이상”, “쿠폰가”, “멤버십가”

화면은 “봉지당 2,000원”과 “100g당 667원”을 같이 보여줘야 한다.

### F-2. 환경/지역 가격 차이

전국 단일 가격처럼 보이면 신뢰가 깨진다.

- `region_hint`: NULL 허용으로 시작
- `store_scope`: online/national/region/store
- region 없는 데이터는 전국 평균으로 쓰되, region 있는 데이터와 섞을 때 confidence를 낮춘다.

서울/부산 가격차를 처음부터 완벽히 맞출 필요는 없다. 하지만 컬럼 자리는 지금 뚫어야 나중에 덜 깨진다.

### F-3. 정기 세일 사이클 학습

마트는 요일/월초/명절/멤버십 데이에 패턴이 있다. 이걸 DB에 남겨야 “오늘 싼 건지, 매주 하는 가격인지”를 구분한다.

모델:

- `mart_sale_cycle`
  - mart
  - category_id/canonical_id nullable
  - weekday_pattern
  - monthly_pattern
  - holiday_pattern
  - confidence
  - updated_at

초기에는 통계 캐시로 충분하다.

### F-4. 사용자 신고/댓글을 가격 신뢰도에 반영

web-api 댓글에는 이미 `verdict`가 있다. `hot_deal`, `not_hot_deal`, `neutral` 카운트를 DB score와 연결해야 한다.

방법:

- web-api가 post verdict summary를 유지
- matched canonical_id가 있으면 `community_price_signal`로 집계
- “not_hot_deal”이 많으면 hotdeal_score를 깎기보다 `dispute_flag`와 confidence를 낮춘다.

점수를 바로 조작하면 여론몰이에 취약하다. 하지만 신뢰도 신호로는 강력하다.

### F-5. A/B 테스트 인프라

스냅샷 두 버전을 동시에 제공할 수 있어야 한다.

- `snapshot_version`
- `scoring_profile_version`
- `category_set_version`
- web-api는 사용자/세션 단위로 A/B bucket을 선택
- 두 버전의 클릭률, 댓글 verdict, 재방문을 비교

이건 과한 규격화가 아니다. 핫딜 점수 산식이 논쟁적이기 때문에, 나중에 감으로 바꾸지 않게 하는 최소 장치다.

---

## v1 핵심 약점 5개

1. **canonical_id 안정성 계약 부재**  
   SHA1 입력 규칙이 바뀌면 게시판/스냅샷/alias가 깨진다. stable_id와 redirect 없이는 운영 중 정책 변경이 위험하다.

2. **게시판 결합 현황 오판**  
   결합이 “없다”가 아니라 `Post.canonical_id`가 이미 있다. 그래서 매칭 토큰 API는 P1이 아니라 P0다.

3. **스냅샷 운영 방식 과대평가**  
   현재 코드는 atomic publish가 아니다. 기존 파일 삭제 후 재생성이라 운영 중 web-api가 빈틈을 맞을 수 있다.

4. **핫딜 점수 산식 근거 약함**  
   P10/P50 기반 0–100은 skewed distribution, 작은 표본, 조건부 할인에서 거짓 확신을 준다.

5. **동시성/롤백이 기획 수준**  
   큐 resolve, 카테고리 이동, restore 모두 in-flight 작업과 충돌할 수 있다. claim/version/pause 절차가 필요하다.

---

## v3 작성자에게 던지는 질문

1. `canonical_id`를 외부 공개 ID로 계속 쓸 것인가, 아니면 `stable_id + fingerprint_version + redirect`로 분리할 것인가?
2. 게시판 작성 시 canonical 후보 매칭 API를 P0로 올릴 것인가? 올린다면 후보 confidence와 사용자의 “매칭 안 함” 로그는 어디에 저장할 것인가?
3. 공개 snapshot publish를 언제 atomic 방식으로 바꿀 것인가? build 실패 시 web-api가 이전 snapshot을 계속 보게 하는 계약을 명시할 것인가?
4. hotdeal_score 0–100을 바로 노출할 것인가, 아니면 초기에는 label/confidence/reason chips로 시작하고 A/B 테스트로 점수 산식을 검증할 것인가?
5. 카테고리 트리 개편 시 old→new category mapping과 미매핑 상품 큐를 P0/P1 중 어디에 넣을 것인가?

---

_v2 끝. v3는 방향을 더 키우기보다, 위 약점에 대해 “운영 중 안 깨지는 계약”을 박아야 한다._
