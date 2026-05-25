# DB-admin 영역 v3 살붙이기 (Opus, Round-A)

> 입력: `db-v1-opus.md` (Opus v1 초안), `db-v2-gpt.md` (GPT 5.5 적대적 검토)
> 작성자: Opus 4.7 (v3)
> 원칙: v2의 진짜 약점은 박아 넣고, 안전 타령·과한 규격화·기능 축소 권고는 명시 배척.
> v1/v2 파일은 건드리지 않는다.

---

## 0. 서문 — v2 응답 정책

### 0-1. 수용하는 v2 약점 (사실로 인정)

| v2 지적 | 사실 여부 | v3 처리 |
|---|---|---|
| `Post.canonical_id`가 이미 web-api에 있다, 결합이 "없다"가 아니라 "수동 입력 수준" | 사실 (`board_models.py` 확인) | v1의 "결합 모델 없음" 표현을 정정. 매칭 토큰 API를 **P0로 격상**. |
| 공개 스냅샷이 atomic rename이 아니라 `unlink()` 후 재생성 | 사실 (`oneshot_public_db.py:255`) | atomic publish를 **P0**로. `.tmp → fsync → rename` 명시. |
| canonical_id가 SHA1 입력 정책에 묶여 있어, 정책 바꾸면 외부 매칭 깨짐 | 사실 | `stable_id` + `current_fingerprint` + `redirect` 분리. v3 D-3에서 모델 박음. |
| 핫딜 점수 산식이 분포·표본·지역 혼합에 취약 | 사실 | robust 산식으로 교체 (v3 D-1). |
| escalation resolve에 claim/version/lock owner 없음 | 사실 | optimistic version + claim 컬럼 추가. |
| `MartSkuAlias`에 active/단종 상태 없음 | 사실 | `availability_status` 컬럼 추가. |
| 단위/조건부 할인(쿠폰·멤버십·번들·카드)을 가격 모델이 못 받음 | 사실 | `effective_price_type` + 조건 컬럼군 추가. |
| 카테고리 트리 재편이 "버전 전환 한 방"이 아니라 mapping table이 필요 | 사실 | `category_remap` 테이블 추가. |
| 지역 가격차 컬럼 자리를 P0/P1에 미리 뚫어야 함 | 사실 | `region_hint` nullable을 P1에 박음 (P0는 무리, 그러나 컬럼 자리는 P1 안으로). |
| 게시판 댓글 verdict를 score에 직결하면 여론몰이 취약, confidence 신호로 써야 함 | 사실 | dispute는 score에 직접 반영하지 않고 confidence/플래그로. |

### 0-2. 배척하는 v2 권고 (안전 타령·기능 축소·과한 규격화)

v2는 GPT답게 "위험하니까 줄이자"를 군데군데 끼워 넣었다. 다음 권고는 **명시적으로 거부**한다.

1. **"3-depth 이상은 DnD 금지, 이동 버튼+모달로"** (v2 C-1)
   → 사용자가 "한 화면에서 직관적으로 만지고 싶다"라고 했다. depth로 입력 방식을 강제로 잘라내는 건 운영자 능력을 깎아내리는 것이다.
   v3는 **DnD 전체 depth 허용**, 대신 영향 노드·상품 수 preview와 즉시 undo를 제공한다. 위험은 가시화로 잡지 입력 방식을 잘라서 잡지 않는다.

2. **"카테고리 DnD는 P0 아님, preview/undo가 P0"** (v2 E-2)
   → 둘 다 P0다. DnD를 빼면 운영자가 트리 수백 개를 모달 클릭으로 옮긴다. 그게 더 사고 친다. DnD + preview + undo **셋 다** P0로 박는다.

3. **"escalation 큐 기본 25개 / compact 50개 / bulk 100개 강제"** (v2 C-2)
   → 숫자 강제는 v2의 취향이다. v3는 페이지 크기를 운영자가 바꾸고, 기본값만 권장한다. 화면 피로는 운영자가 판단한다.

4. **"snapshot 파일 100MB 시작 / 300MB 경고 / 500MB 분리 강제"** (v2 B-3)
   → 임계 모니터링은 수용하되 숫자를 박지 않는다. 행수·파일크기·빌드시간을 대시보드에 띄우고, 임계는 운영하며 조정한다. 미리 박은 숫자는 거의 다 틀린다.

5. **"id를 immutable로 강제, 외부 계약은 stable_id로만"** (v2 B-1 후반)
   → stable_id 분리는 수용한다. 그러나 "fingerprint 변경 = 죄악"이라는 톤은 거부한다. **fingerprint는 정책 진화에 맞춰 자유롭게 바뀌어야 하고**, 외부 깨짐은 redirect로 흡수한다. immutable 강제가 아니라 redirect 보장이 계약이다.

6. **"롤백 6단계 절차 강제 (pause→pre-backup→restore→integrity→handle swap→resume)"** (v2 B-4)
   → 절차 자체는 합리적이지만, 이걸 운영자가 매번 6번 클릭하라고 만들면 롤백 못 쓴다. v3는 **"롤백 한 클릭, 내부 6단계 자동 실행, 단계별 진행 상태 표시"**로 구현한다. 절차를 운영자에게 떠넘기지 않는다.

7. **"hotdeal_score 0–100을 처음부터 노출 금지, label/confidence/reason chips로만 시작, A/B로 검증 후 노출"** (v2 E-2)
   → 점수와 reason chips는 **공존**한다. 일반인은 한 줄 답을 원한다. "62점·핫딜 임박" + "근거: 도매가 대비 -18%, 표본 충분, 멤버십가 아님" 같이 같이 보여준다. 점수를 숨기고 chips로만 가는 건 비개발자 가독성을 깎는다.

### 0-3. v2가 v3에 던진 질문 5개 — 직답

1. **canonical_id를 외부 공개 ID로 계속 쓸 것인가, 아니면 stable_id + fingerprint_version + redirect로 분리할 것인가?**
   → **분리한다.** 외부(스냅샷, web-api, 게시판)는 `stable_id`만 본다. 내부 정규화 결과는 `current_fingerprint`로 들고 있고, fingerprint 변경 시 자동으로 `canonical_id_redirect`를 생성한다. fingerprint는 자유롭게 바꾼다.

2. **게시판 매칭 후보 API를 P0로 올릴 것인가? 매칭 안 함 로그는 어디에?**
   → **P0**. `match_candidate_log (post_draft_id, query_payload, candidates_json, selected_canonical_id NULL, rejected_reasons_json, ts)`에 후보 응답과 선택 결과를 같이 남긴다. "어떤 후보도 안 골랐다"가 가장 학습 가치 높은 신호다.

3. **공개 snapshot atomic publish를 언제 바꿀 것인가? 빌드 실패 시 web-api가 이전 snapshot을 계속 보게 하는 계약은?**
   → **P0**. `public_snapshot.sqlite.next` 빌드 → `sha256` 체크섬 파일 동시 생성 → `os.replace`로 rename. web-api는 시작 시 파일 핸들을 잡고, 빌더가 "publish 알림"(파일 mtime 변화 또는 명시 신호)을 보낼 때만 다음 요청부터 새 핸들로 갈아탄다. 실패 시 next 파일을 버리고 현재 파일은 그대로. 이전 N개(기본 7개) 보관.

4. **hotdeal_score 0–100 바로 노출 vs label/chips부터?**
   → **둘 다 동시 노출.** 점수는 "62점" 한 줄, chips는 근거. 산식은 robust 버전(D-1)으로 시작하고 A/B는 점수 산식 조정용 인프라(`scoring_profile_version`)로만 깔아둔다. A/B 결과 기다리느라 점수 숨기지 않는다.

5. **카테고리 트리 개편 시 old→new mapping과 미매핑 큐는 P0/P1 어디에?**
   → **mapping 모델 자체는 P0**, mapping을 굴리는 운영 화면은 P1. mapping 테이블 자리를 P0에 못 박지 않으면 첫 개편에서 데이터가 뒤섞인다. 화면은 가동 후 첫 개편이 닥치기 전까지만 만들면 된다.

---

## A. 사실관계 정정 (v1 오류만)

v2가 적은 사실관계 반박은 거의 다 맞다. v3에서 v1을 직접 고치진 않지만 다음을 정정으로 남긴다.

1. **게시판 결합 "없음"이 아니라 "수동 canonical_id 입력 수준"이다.** `web-api/backend/storage/board_models.py`에 `Post.canonical_id` / `deal_price` / `mart_name` / `deal_url`가 있고, `grade_summary`도 public snapshot에서 가져온다. v3는 "자동 매칭/신뢰도/토큰이 없다"로 표현한다.
2. **공개 스냅샷이 atomic rename이 아니다.** `oneshot_public_db.py:255`에서 기존 파일을 `unlink()` 후 새로 만든다. atomic publish는 v1 시점엔 기획이었다.
3. **공개 스냅샷의 read-only는 스키마상 의도일 뿐, 파일 권한·SQLite `mode=ro`는 빌더 코드에 없다.** 소비자(web-api)가 ro로 열어야 강제된다.
4. **카테고리 트리 4depth가 DB로 강제되지 않는다.** 주석/관행이지 체크 제약이 아니다.
5. **백업은 있고, restore는 함수 수준만 있고 UI는 없다.** v1이 "백업 서비스 있음, UI 노출 약함"이라 적은 건 절반만 맞다. restore까지 가야 진짜 운영.

---

## B. v1 자기검증 5포인트 + v2 약점 통합 재답변

### B-1. 도매가 anchor 소스

v1에서 "테이블 모양만 있고 소스 비어 있음"이라고 자수했다. v2가 "소스 다중화 + freshness 모델"을 붙였다. 수용.

**v3 결론**: 도매가는 **단일 소스 의존 금지, 끊기면 감점 모델로 굴린다.** KAMIS는 코드 주석에 박힌 대로 안 쓴다.

```
wholesale_baseline
─────────────────────────────────────
  id              PK
  source_code     TEXT      -- 'AT_GONGPAN', 'NH_DOMAE', 'CSV_MANUAL', ...
  commodity_key   TEXT
  observed_date   DATE
  unit_price_krw  INTEGER
  unit_basis      ENUM(kg/L/each/...)
  region_hint     TEXT NULL
  raw_payload     JSON
  ingested_at     TIMESTAMP

wholesale_source_status
─────────────────────────────────────
  source_code         PK
  display_name        TEXT
  last_success_at     TIMESTAMP
  last_failure_at     TIMESTAMP NULL
  consecutive_fails   INTEGER
  freshness_days      INTEGER       -- 마지막 성공 이후 경과일
  confidence_weight   REAL          -- 0.0~1.0, 운영자 조정 가능
  status              ENUM(active/stale/dead)
```

**산식 반영**:
- `effective_wholesale_anchor = Σ(source.price × source.confidence × freshness_decay) / Σ(가중치)`
- `freshness_decay = max(0, 1 - max(0, days-7) / 30)` (7일까지 1.0, 37일에 0, 그 이후 0)
- 모든 소스가 stale → anchor 컬럼 자체에 `is_stale=true` 플래그. UI는 "도매가 기준선 오래됨, 시장 분위수 기준으로 표시" 안내. **기능을 끄지는 않는다.**

수동 CSV 업로드는 P0. 자동 수급 파이프라인 추가는 P1+. (v2의 "수동부터" 권고 수용)

### B-2. canonical_id 안정성

v1 자수, v2 박살. 정직하게 수용.

**v3 결론**: `canonical_id`(SHA1)는 **내부 fingerprint로만** 쓰고, 외부 계약은 `stable_id`로 분리. 정책이 바뀌면 fingerprint는 새로 계산되고, redirect 테이블이 old→new를 흡수한다. **fingerprint를 immutable로 강제하지 않는다.**

```
canonical_product_identity
─────────────────────────────────────
  stable_id           TEXT PK    -- ulid 또는 nanoid, 외부 계약용 영구 불변
  current_fingerprint TEXT       -- 지금의 SHA1(brand_norm|name_core|pack_qty|pack_unit|fp_version)
  fingerprint_version INTEGER    -- 정규화 규칙 세대
  created_at, updated_at
  merged_into         TEXT NULL  -- 병합되어 다른 stable_id로 흡수된 경우
  split_from          TEXT NULL  -- split된 경우 부모
  status              ENUM(active/merged/split/dead)

canonical_id_redirect
─────────────────────────────────────
  from_id     TEXT PK       -- 옛 stable_id 또는 옛 fingerprint
  to_id       TEXT
  reason      ENUM(merge/split/brand_alias_rule/fingerprint_version_bump/manual)
  created_at, created_by_user_id
```

**계약**:
- 외부(web-api, 스냅샷 소비자, 게시글 `Post.canonical_id`)는 stable_id만 본다.
- 조회는 항상 redirect lookup 한 번 거친다. `resolve(id) = follow_redirect(id) until terminal`.
- merge/split은 운영자 액션으로만. AI 추천은 `canonical_conflict_queue`에 올린다.

기존 `Post.canonical_id`는 이미 SHA1을 박아두고 있을 가능성이 높다 → 마이그레이션 한 번: 각 SHA1에 대해 stable_id를 발급하고, 옛 SHA1을 redirect from_id로 등록. **외부 깨짐 없음.**

### B-3. escalation resolve 트랜잭션 + 동시성

v1이 "5테이블 묶음 트랜잭션" 자수, v2가 "claim/version 없으면 두 운영자 동시 처리 시 마지막이 이김" 박살. 수용.

```
ProductReviewQueue (보강)
─────────────────────────────────────
  ... (기존)
  version            INTEGER NOT NULL DEFAULT 0   -- 갱신마다 +1
  claimed_by         user_id NULL
  claimed_at         TIMESTAMP NULL
  claim_expires_at   TIMESTAMP NULL              -- 기본 +15분
```

**resolve API 의사코드**:
```
UPDATE product_review_queue
SET resolved_at=?, resolver_user_id=?, version=version+1
WHERE id=? AND resolved_at IS NULL AND version=?
-- 1행 갱신 실패 → "이미 다른 관리자(@X)가 처리함, 갱신된 결과 보기" UI 분기
```

다섯 테이블(`MartSkuAlias` / `CanonicalProduct.category` / `ProductReviewQueue` / `AuditLog` / 옵션 유사 큐 일괄 제안)은 **단일 transaction** 안에서 처리한다. 트랜잭션이 길어 보일 수 있으나 escalation 한 건 처리에 ms 단위면 충분하다. 비관 락도 필요 없음 (claim + optimistic version으로 충분).

claim 만료(15분) 자동 해제 cron 한 개 추가.

### B-4. 공개 스냅샷 크기·갱신 SLA

v2가 숫자(100/300/500MB)를 박으려 했다. 거부한다. 대신 **운영 가능한 모니터**를 박는다.

**v3 SLA**:
- **atomic publish 필수** (P0): `.next` 빌드 → checksum → `os.replace`. 빌드 실패 시 `.next` 폐기, 현재 파일 유지.
- 빌드 시간·파일 크기·rows-per-table을 매 빌드마다 `snapshot_build_log`에 기록.
- web-api는 핸들 교체를 안전하게 하기 위해 빌더가 발급한 `snapshot_version` 토큰을 보고 다음 요청부터 새 파일을 쓴다 (현재 in-flight 쿼리는 옛 핸들 유지).
- 이전 7개(기본) snapshot 보관, 그 너머는 cron이 자동 삭제. 운영자가 보관 수 조정 가능.

```
snapshot_build_log
─────────────────────────────────────
  id, snapshot_version, started_at, finished_at, duration_ms,
  file_size_bytes, sha256, row_counts_json, status(ok/failed),
  error_message
```

raw observations는 절대 snapshot에 넣지 않는다 (v2 권고 수용). 들어가는 건: canonical_product / price_grade / category / alias / `price_daily_agg` 90일치 / `hotdeal_score` / `wholesale_anchor` 컬럼.

### B-5. 매칭 토큰 API P0 여부

P0. v2 권고 수용.

```
POST /public/match/candidates
  body: { title, body_excerpt?, mart_hint?, deal_url?, deal_price?, unit_hint? }
  resp: {
    candidates: [
      { stable_id, display_name, brand, pack, confidence, match_reasons:[...],
        unit_basis, last_seen_at, current_price_band, score_preview }
    ],
    request_id
  }

POST /public/match/select   (또는 reject)
  body: { request_id, selected_stable_id | rejected: true, reason? }
```

`match_candidate_log`에 (request_id, query_payload, candidates_json, selected_stable_id NULL, rejected_reasons_json, ts, post_id NULL) 적재 → 미매칭/오매칭이 학습 신호. 이걸 안 남기면 토큰 API가 블랙박스로 굳는다.

---

## C. 빠뜨린 시나리오 보강

### C-1. 마트 폐점 / 상품 단종

```
MartSkuAlias (보강)
─────────────────────────────────────
  ... (기존)
  availability_status   ENUM(active/out_of_stock/discontinued/unknown)
  last_success_seen_at  TIMESTAMP NULL
  last_missing_seen_at  TIMESTAMP NULL
  consecutive_miss_count INTEGER DEFAULT 0
```

규칙: 7일 연속 크롤 miss → `out_of_stock`. 30일 → `discontinued` 후보로 escalation 큐. **canonical은 삭제하지 않는다.** alias 상태만 바뀐다 (다른 마트엔 살아있을 수 있음).

**마트 자체 폐점**: `mart` 테이블에 `status (active/closed)` + `closed_at`. closed면 해당 alias 전체를 archive 상태로 마킹. 가격 분위수 산정에서 제외. 과거 추이 그래프엔 회색으로 표시.

### C-2. 두 마트 동시 핫딜 dedup

v2의 "canonical 점수 vs mart offer 점수 분리"는 정확하다.

```
canonical_hotdeal_signal
─────────────────────────────────────
  stable_id, snapshot_date, market_score, best_mart, best_offer_price,
  active_offer_count, dedup_key  -- 같은 가격대(±3%) 묶음 식별
```

게시판에서 같은 stable_id + 같은 dedup_key를 가진 게시글이 24h 안에 둘 이상 올라오면 web-api가 "관련 핫딜" 묶음으로 표시 (별도 게시글은 유지, 게시 차단 아님).

### C-3. 도매 소스 중단 fallback

B-1에 박은 freshness_decay가 답이다. 추가로 UI 표시:
- anchor 7일 이내: 정상
- 8~30일: 점수 chip에 "(도매 anchor 오래됨, ±N일)"
- 31일+: anchor 표시 자체를 회색, 시장 분위수 중심 표시
- 모든 소스 dead: anchor 컬럼 null, 가격대 띠만 표시. **기능 비활성화 아님.**

### C-4. 카테고리 재편 시 migration

v1의 `category_set_version`은 방향만 맞고 실행이 안 된다. v2의 "mapping table"이 옳다.

```
category_remap
─────────────────────────────────────
  id, from_set_version, to_set_version,
  from_category_id, to_category_id NULL,  -- NULL이면 미매핑 버킷
  mapping_kind ENUM(one_to_one/split/merge/unmapped),
  confidence REAL,
  decided_by ENUM(auto/manual/ai_suggested),
  created_at, decided_by_user_id NULL
```

활성 set_version 전환은 트랜잭션 한 번이지만, **mapping이 다 채워져야 전환 허용**. 미매핑이 남아있으면 "unmapped 47개 남음" 경고가 전환 버튼 옆에 뜬다. 강제 전환도 가능하나, unmapped 상품은 미분류로 떨어진다 (그 자체가 escalation 큐로 흘러감).

게시판 게시글의 카테고리 필터는 stable_id 경유라 영향 적음. 그러나 카테고리별 hotdeal 피드는 active set_version 기준으로 재계산.

### C-5. 단위 정규화 (g / 100g / 1L / 1개) + 조건부 할인

v2가 정확하게 짚었다. 단위 가격 normalize는 이미 일부 있지만 조건부 할인이 빠져 있다.

```
PriceObservation (보강)
─────────────────────────────────────
  ... (기존)
  effective_price_type   ENUM(base/sale/coupon/membership/card/bundle)
  min_purchase_qty       INTEGER DEFAULT 1
  requires_membership    BOOLEAN DEFAULT false
  requires_card          TEXT NULL          -- 카드사명
  coupon_code            TEXT NULL
  bundle_description     TEXT NULL          -- "2+1", "3개 묶음 시"
  display_price_text     TEXT               -- 원문 그대로 "990원/100g (2개 이상)"
  normalized_unit_price  INTEGER NULL
  normalized_unit_basis  ENUM(per_100g/per_1kg/per_each/per_1l/per_100ml)
  normalization_confidence REAL DEFAULT 1.0
```

**핫딜 점수 계산 시**: `effective_price_type != 'base'`면 `normalization_confidence`를 곱해 점수를 깎는다 (0 만들지는 않음). 화면에는 "쿠폰가 기준" 같은 chip이 붙는다. **숨기지 않는다.**

### C-6. 지역 가격 차이

v2 권고 수용. P1에 컬럼 자리만 미리 뚫는다.

```
PriceObservation.region_hint  TEXT NULL  -- 'SEOUL', 'BUSAN', 'ONLINE_NATIONAL', NULL
PriceObservation.store_scope  ENUM(online_national/online_region/offline_store) DEFAULT 'online_national'
```

P1 단계 분위수 계산은 전국 통합 유지(데이터 양이 적기 때문). region별 분리 분위수는 P2. 컬럼 자리는 지금 뚫어두지 않으면 마이그레이션이 더 아프다.

### C-7. 정기 세일 사이클

```
mart_sale_cycle
─────────────────────────────────────
  id, mart, category_id NULL, stable_id NULL,
  weekday_pattern_json     -- {"mon":0.1,"tue":0.4,...} 할인 출현 빈도
  monthly_day_pattern_json -- 월초/월말 패턴
  holiday_pattern_json     -- 명절/주말/멤버십 데이
  sample_count, confidence, updated_at
```

야간 배치로 observations 6개월치를 봐서 갱신. 게시글이 올라올 때 "이건 매주 화요일 가격임 (10주 중 8주)" chip을 붙일 수 있다.

### C-8. 신고 신뢰도 가중

v2의 "verdict로 score를 직접 깎지 않고 confidence로"가 정확.

```
community_price_signal
─────────────────────────────────────
  stable_id, post_id, verdict_hot_count, verdict_not_hot_count,
  verdict_neutral_count, last_updated_at,
  dispute_flag BOOLEAN     -- not_hot이 hot의 2배 이상이면 true
```

score는 그대로 두되, dispute_flag가 켜지면 게시글 옆에 "사용자 의견 분분 (찬:반 3:8)" chip. 점수에 직접 가중을 곱하지 않는다 (여론몰이 방지).

### C-9. 동시성 (트리·큐·alias)

- escalation 큐: B-3에서 claim + version 박음.
- 카테고리 트리: 편집 세션 시작 시 `tree_version` 발급. 저장 시 mismatch면 diff 보여주고 재적용 (모달, 운영자 결정). 대량 이동(>50노드)은 dry-run preview 필수 (영향 상품 수 표시).
- alias upsert: `UNIQUE(mart, mart_item_id)`로 이미 보호.

### C-10. 권한 모델 분리

v2 권고 부분 수용. db-admin role 계층은 이미 있다. 문제는 **서비스간 경계 표**가 없다는 것.

| 호출자 | 가능 | 불가 |
|---|---|---|
| crawler / service | `POST /ingest/observation`, `POST /ingest/alias` | 그 외 전부 |
| ai / ai_publisher | `POST /review/{id}/suggest`, snapshot read | resolve, alias 직접 쓰기 |
| web-api | snapshot read, `POST /public/match/candidates`, `POST /public/match/select` | 운영 DB 직접 접근, 트리 변경 |
| db-admin moderator | 큐 resolve, 트리 이동(권한별), alias 수정 | restore, set_version 전환 |
| db-admin admin | 백업/restore, set_version 전환, 권한 부여 | (전부 가능) |

이 표를 P0 문서로 박는다. 코드 enforce는 P1 (지금도 부분적으로 있음).

---

## D. 데이터 모델 보강

### D-1. 핫딜 점수 robust 산식

v1 산식이 분포 skew·표본 적음·지역 혼합에서 깨진다는 v2 지적 수용. 다시 짠다.

```
요소(요소별 0~1로 정규화, 가중합 후 100을 곱함)

p_position_robust =
  if (P50 - P10) < band_floor:                  -- 분모 폭발 방지
      band_floor = max(P50 * 0.05, 100원)
      use band_floor
  clamp((P50 - current) / (P50 - P10), 0, 1.2)  -- P10 아래는 살짝 보너스

w_against_wholesale =
  if wholesale_anchor is not null and not is_stale:
      clamp((wholesale_anchor * conv * 1.15 - current) / (wholesale_anchor * conv * 0.15), 0, 1)
  else: 0.5  (anchor 없으면 중립값, 점수에 영향 작음)

sample_confidence =
  if n < 5: 0.3
  elif n < 15: 0.6
  elif n < 50: 0.85
  else: 1.0

condition_penalty =
  base: 1.0
  sale: 0.95
  coupon/membership/card: 0.7
  bundle: 0.6

event_bonus = 0 또는 0.1 (event_labels에 값 있으면 +0.1)

raw_score = (0.5 * p_position_robust + 0.3 * w_against_wholesale + 0.2 * event_bonus) * sample_confidence * condition_penalty
final_score = round(clamp(raw_score, 0, 1) * 100)

reasons = [...]  -- 어떤 요소가 점수에 얼마나 기여했는지 chip 배열
```

**핵심 변경**:
- 분모 폭발 방지를 위한 `band_floor`.
- `sample_confidence`는 가중치가 아니라 **곱** (작은 표본은 점수가 통째로 깎임).
- 조건부 할인은 곱 페널티.
- anchor 없거나 stale → 중립값 0.5 (점수에 큰 영향 안 줌, 기능 안 끔).
- reasons chip이 항상 같이 나간다.

mart별 점수와 canonical 종합 점수를 둘 다 계산해서 둘 다 노출 (게시판은 mart 점수 우선).

### D-2. 3-layer anchor 가중치

v1은 가중치 하드코딩이었다. v2 권고대로 **카테고리 프로파일 테이블**로 뺀다.

```
pricing_profile
─────────────────────────────────────
  id, name, description,
  weight_market_quantile  REAL,   -- 분위수 비중
  weight_wholesale        REAL,   -- 도매 anchor 비중
  weight_event            REAL,   -- 이벤트/시즌 비중
  weight_sale_cycle       REAL,   -- 정기 세일 사이클 비중
  sample_min_required     INTEGER,
  band_floor_pct          REAL,   -- 분모 폭발 방지 임계
  updated_by, updated_at

category_node.pricing_profile_id  FK NULL
```

기본 프로파일 3~5개 시드 (신선식품 / 가공식품 / 생필품 / 수입가공 / 기타). 운영자가 카테고리에 붙이고 가중치를 화면에서 조정.

`scoring_profile_version` 컬럼을 snapshot에 같이 넣어, web-api가 어느 산식으로 계산된 점수인지 안다. A/B는 이 버전으로 굴린다.

### D-3. canonical_id 충돌·병합·분리

B-2의 stable_id + redirect 위에, 충돌 발견을 큐로 받는다.

```
canonical_conflict_queue
─────────────────────────────────────
  id, kind ENUM(potential_merge/ambiguous_split/brand_alias_collision/fingerprint_collision),
  stable_ids_json[],         -- 관련된 stable_id 목록
  evidence_json,             -- 왜 충돌이라 판단했는지 (AI 또는 룰)
  suggested_action ENUM(merge/split/keep_separate),
  status ENUM(open/resolved/dismissed),
  created_at, resolved_at, resolver_user_id
```

운영자가 merge → `canonical_id_redirect`에 from→to 등록 + 영향 alias/observation 이관 + AuditLog. split은 더 무겁다: 기존 observations를 어느 쪽으로 보낼지 rule(brand/mart/raw_name 패턴) 또는 수동 선택. split은 P1.

### D-4. brand_alias 오염 방지

v2 권고대로 자동 수집은 `suggested`만, 적용은 별도 액션.

```
brand_alias (보강)
─────────────────────────────────────
  alias              TEXT
  canonical_brand    TEXT
  status             ENUM(suggested/approved/rejected/rollback)
  evidence_json      -- alias가 어디서 왔는지 (마트, 빈도, AI 추천 등)
  affected_count_at_approval INTEGER NULL  -- 적용 시점 영향 canonical 수 기록
  approved_by, approved_at,
  applies_from_fingerprint_version INTEGER  -- 이 버전부터 정규화에 사용
  PRIMARY KEY (alias, canonical_brand)
```

**규칙**:
- 자동 발견 → `suggested`. 영향 canonical 수가 화면에 표시.
- 운영자가 approve → `applies_from_fingerprint_version`이 현재+1로 잡힘. 다음 fingerprint 갱신 배치부터 적용.
- 적용 후 문제 발견 → `rollback` 상태로 마킹하면 fingerprint 한 세대 더 굴려서 분리. **redirect로 복구.**
- PB상품 / 마트명 / 판매자명은 brand로 자동 채용 금지 룰셋 (`alias_blacklist` 시드).

---

## E. 관리자 UI/UX 보강

### E-1. 카테고리 트리 — 전체 depth DnD + 안전망

v2의 "3depth 이상 DnD 금지"는 거부. 대신 다음을 동시에 제공:

- **전체 depth DnD 허용.**
- 드래그 중 hover하면 destination parent의 path가 toast로 뜬다 ("식료품 > 정육 > 한우 > 등심에 이동 중").
- 놓는 순간 곧바로 commit하지 않는다. **노란 "변경 대기" 상자**에 쌓인다.
- "변경 적용" 버튼 누를 때 영향 상품 수 / 하위 노드 수 / 바뀌는 path 목록 preview.
- "적용" 클릭 후 30초간 상단에 큰 노란 띠 + "되돌리기" 버튼. 클릭하면 트랜잭션 통째 reverse (AuditLog 기반).
- 동시 편집자 충돌은 tree_version mismatch로 잡아 diff 모달.

depth 깊어지면 트리 패널에 **breadcrumb 검색 박스** 추가. "한우 등심"으로 검색하면 해당 노드까지 점프 + 자동 확장.

### E-2. escalation 큐 — 그룹화

화면 행 수 강제는 거부. 대신 그룹화:

- **같은 raw name 또는 같은 suggested_canonical_id 묶음**으로 자동 그룹화 토글.
- 그룹 단위로 "이 그룹 전체 → canonical X로 매핑" 일괄 확정.
- 그룹 안 개별 row는 expand로 본다.
- 정렬: 신뢰도 / 생성시각 / 마트 / 이유. 다중 정렬 가능.
- 페이지 크기는 운영자 설정 (저장된 user preference).
- claim 상태 표시: "@kim이 7분 전 잡음" → 다른 운영자는 read-only로 보이되, claim 만료(15분) 후 자동 해제.

### E-3. 백업·롤백 UX (안전 타령 아닌 UX)

v2의 6단계 절차 강제 거부. **한 클릭 롤백, 내부 6단계 자동.**

화면:
1. "복원" 버튼 클릭 → 모달에 백업 목록 + 각 백업의 timestamp/size/snapshot diff 요약.
2. 백업 선택 → "이 백업으로 복원하면: 카테고리 N개 추가, M개 삭제, 가격 관측 K건 사라짐" preview.
3. "복원 시작" 버튼 한 번 → 진행 표시줄 (6단계 자동 실행, 각 단계 상태 표시):
   - `[1/6] ingestion 일시정지 ✓`
   - `[2/6] 현재 DB pre-restore 백업 ✓` (자동, 별도 백업 생성)
   - `[3/6] 새 파일에 restore 중...`
   - `[4/6] integrity check ✓`
   - `[5/6] DB 핸들 교체 ✓`
   - `[6/6] ingestion 재개 ✓`
4. 실패 시 자동 abort, 운영자는 "다시 시도" 또는 "취소". DB 상태는 변경 없음.

**스냅샷 diff 뷰**: 어제 vs 오늘 snapshot을 운영자가 클릭으로 비교. 카테고리 추가/삭제/이동, canonical 신규/사라짐, price_grade 큰 변동 목록. snapshot_version 두 개를 dropdown으로 고르는 단순 UI.

### E-4. DnD + 일괄편집

- 키워드도 DnD로 카테고리 노드에 던지면 매핑 추가.
- 큐 항목 다중 선택 후 "선택 N개 → canonical X로 일괄 매핑" + "선택 N개 → AI 재추천 요청".
- alias 표에서 row 다중 선택 후 brand_alias suggest 일괄 생성.

---

## F. 사용자 UX 보강 (DB가 제공할 데이터 모양)

### F-1. 추이·적정가·점수 노출

```json
GET /public/products/{stable_id}/summary
{
  "stable_id": "01J...",
  "display_name": "서울우유 흰우유 1L",
  "current": {
    "best_offer": { "mart": "E", "price": 2480, "as_of": "...", "effective_type": "sale" },
    "hotdeal_score": 78,
    "score_reasons": [
      { "key":"vs_p50", "label":"P50보다 22% 저렴", "delta":0.42 },
      { "key":"vs_wholesale", "label":"도매가 대비 -18%", "delta":0.18 },
      { "key":"sample","label":"표본 충분 (n=64)","delta":0 },
      { "key":"condition","label":"멤버십가 아님","delta":0 }
    ],
    "dispute_flag": false
  },
  "bands": { "wholesale_anchor": 1800, "p10":2400,"p25":2600,"p50":3100,"p75":3400, "is_stale": false },
  "trend_url": "/public/products/01J.../trend?window=90d"
}
```

### F-2. "이거 핫딜 아님" 라벨 룰

- score 0~29: **"정상가 또는 비쌈"** 빨간 배지
- 30~49: **"평범"** 회색
- 50~69: **"살 만함"** 연두
- 70~89: **"핫딜"** 초록
- 90~100: **"역대급"** 진초록 + 별표

배지는 점수와 별도 컬럼이 아니라 클라이언트가 점수 받아서 매핑. 임계는 운영자가 `pricing_profile`에서 카테고리별로 조정 가능.

dispute_flag=true면 배지 옆에 회색 "의견 분분" sub-label 자동.

### F-3. A/B 스냅샷

```
snapshot_version 컬럼이 build_log/snapshot에 박혀 있다.
scoring_profile_version도 따로.

web-api 응답 헤더에 X-Snapshot-Version, X-Scoring-Profile-Version 항상 포함.
사용자/세션 단위 bucketing은 web-api가 결정 (db-admin은 두 버전 동시 제공만).
```

산식 변경 시 옛 버전 snapshot을 잠시 유지 → 비교 가능. 게시판 클릭률·verdict·재방문이 산식 검증 신호.

---

## G. 모듈 / 플러그인 보강

### G-1. API 경계 (확정판)

```
[ingestion - write only]
  POST /ingest/observation              crawler/service만
  POST /ingest/alias                    crawler/service만
  POST /ingest/wholesale                cron/manual_csv_uploader

[ai - suggest only]
  POST /review/{id}/suggest             ai/ai_publisher만
  POST /alias/suggest                   ai/ai_publisher만

[admin - mutation]
  POST /review/{id}/claim               moderator+
  POST /review/{id}/resolve             moderator+ (B-3 트랜잭션)
  POST /category/move                   moderator+ (tree_version 체크)
  POST /category/set_version/activate   admin
  POST /brand_alias/{id}/approve        admin
  POST /backup, /restore                admin

[public - read only + match API]
  GET  /public/snapshot.sqlite          web-api 토큰
  GET  /public/products/{stable_id}/summary
  GET  /public/products/{stable_id}/trend
  POST /public/match/candidates         web-api 토큰 (B-5)
  POST /public/match/select             web-api 토큰
```

운영 DB는 외부에서 직접 못 본다. 무조건 API/스냅샷 경유. (v1 원칙 유지)

### G-2. 게시판 DB 약결합

- 게시판은 web-api 소유, FK 없음.
- 공유 키는 `stable_id` 한 개. SHA1 fingerprint는 외부에 노출 안 함.
- `Post.canonical_id` 컬럼 의미는 사실상 `Post.stable_id`. (네이밍 마이그레이션은 web-api 영역이 결정)
- 게시판이 가진 verdict count는 `community_price_signal`로 web-api → db-admin pull (배치). db-admin이 게시판 DB를 직접 안 쓴다.

### G-3. category_set_version 플러그인 디테일

- `category_set` 테이블: id, version_label, status(draft/active/archived), created_at, activated_at.
- 새 셋은 draft로 import (JSON/CSV 업로드).
- `category_remap` 채우기는 운영자 책임. AI 추천이 1차 매핑을 채움 (`decided_by=ai_suggested`).
- unmapped 0이 될 때까지 활성화 버튼 비활성. 운영자가 "강제 활성" 옵션도 있음 (unmapped는 미분류로 떨어짐).
- 활성 전환 = `category_set` status 두 row를 트랜잭션으로 swap + active_set_version_id를 시스템 설정에 기록. snapshot 다음 빌드부터 active set 반영.
- 키워드 셋도 동일 패턴 (`keyword_set`, `keyword_remap`).

---

## H. 로드맵 재정렬

### P0 — 라이브 직전 필수

1. **stable_id + canonical_id_redirect** 분리 (B-2). 마이그레이션 한 번.
2. **공개 스냅샷 atomic publish** (B-4). `.next → checksum → rename`.
3. **매칭 토큰 API** `/public/match/candidates` + `/match/select` + `match_candidate_log` (B-5).
4. **escalation claim/version** (B-3). 동시 처리 충돌 가시화.
5. **price_daily_agg 캐시** (v1 그대로).
6. **카테고리 트리 DnD + preview + 즉시 undo** (E-1). 셋 다 묶음.
7. **수동 도매가 CSV 업로드** + `wholesale_baseline` + `wholesale_source_status` + freshness_decay (B-1).
8. **백업 + 한 클릭 롤백 UX (내부 6단계 자동)** (E-3).
9. **AuditLog 활성화** + "최근 내 작업 30건 → 행 단위 undo" 패널.
10. **단위 정규화 + effective_price_type/condition 컬럼군** (C-5).
11. **MartSkuAlias.availability_status** (C-1).
12. **category_remap 모델 자리** (C-4, 운영 화면은 P1).
13. **pricing_profile 테이블 + 카테고리 노드 FK** (D-2). 시드 프로파일 3~5개.
14. **서비스간 권한 표 문서화** (C-10).
15. **hotdeal_score robust 산식 + reason chips** (D-1).

### P1 — 가동 직후 1개월

1. 도매가 자동 수급 파이프라인 (소스 2~3개).
2. `search_query_log` + `autocomplete_suggestion`.
3. 스냅샷 diff 뷰어 (E-3 후속).
4. `brand_alias` suggested → approved 워크플로 (D-4).
5. `category_remap` 운영 화면 (C-4).
6. region_hint / store_scope 컬럼 적재 시작 (C-6, 분위수 분리는 안 함).
7. suspicious_regular_jump 플래그 (v1 C-3).
8. `mart_sale_cycle` 배치 (C-7).
9. `community_price_signal` pull 배치 + dispute_flag (C-8).
10. canonical merge 액션 (D-3, split은 P2).
11. 빅데이터 모니터 대시보드 (v1 D-3).

### P2 — 이후

1. canonical split + observation 이관 룰.
2. region별 분위수 분리.
3. scoring_profile A/B 인프라 풀세트.
4. 사용자 watch 알림 연계.
5. 시즌성 가중 hotdeal_score.
6. 카테고리/키워드 플러그인 외부 마켓플레이스(조직 내부용).

---

## I. 안전 타령 배척 선언

v2가 들이밀었거나 v4에서 GPT가 들이밀 만한 다음 권고는 v3에서 명시적으로 거부한다.

1. **"DnD는 depth 제한해야 한다"** — 거부. 전체 depth DnD + preview + undo로 간다. 입력 방식을 잘라 위험을 줄이지 않는다. 위험은 가시화로 잡는다.
2. **"롤백은 절차가 길어야 안전하다"** — 거부. 한 클릭 + 내부 자동 6단계 + 단계별 상태. 안전은 절차 길이가 아니라 단계 표시와 abort 가능성에서 온다.
3. **"hotdeal_score 노출 금지, chips만"** — 거부. 점수와 chips 동시 노출. 비개발자 한 줄 답 권리 깎지 않는다.
4. **"snapshot 크기 100/300/500MB 규격 박자"** — 거부. 임계는 운영하며 조정. 미리 박은 숫자는 거의 다 틀린다.
5. **"escalation 큐 한 화면 25개 강제"** — 거부. 운영자 설정.
6. **"id immutable 강제"** — 거부. fingerprint는 자유롭게 진화. redirect로 외부 깨짐만 흡수한다.
7. **"매칭 토큰 API 추가하면 결합 위험"** — 정확히 반대. 토큰 API 없으면 결합이 빈 껍데기. P0다.
8. **"카테고리 set_version 활성화는 unmapped 0 강제"** — 부분 거부. 기본은 강제지만 admin 강제 활성화 옵션을 남긴다. 운영자가 결정할 자유.
9. **"도매 소스 끊기면 anchor 비활성"** — 거부. freshness_decay로 감점하되 기능은 살린다.
10. **"브랜드 alias 자동 학습 금지"** — 부분 거부. 자동 학습은 한다, 단 `suggested` 상태로만 들어오고 적용은 운영자 액션. 학습 자체를 막지 않는다.

핵심 정체성: **운영자 권한 깎지 않고, 사용자 가독성 깎지 않고, 동적 대응 가능성 닫지 않는다.** 위험은 가시화·감점·rollback으로 처리한다. 금지·축소·규격 박기로 처리하지 않는다.

---

## Z. 자기검증

### Z-1. v2에 굽힌 흔적

- v2의 stable_id/redirect, atomic publish, claim/version, robust 산식, single-source-of-truth가 아닌 freshness 모델, mapping table, region 컬럼 자리, effective_price_type, community signal as confidence — **이건 굽힌 게 아니라 진짜 약점 수용**. v1 작성자(나)가 자수했던 5포인트와 거의 일치.
- 굽힌 흔적이라 의심해야 할 부분: **매칭 토큰 API를 P0로 격상**. v1은 P1이었다. 다만 `Post.canonical_id`가 이미 web-api에 있다는 사실관계 앞에선 P1 유지가 더 게으른 선택이라 P0가 맞다.

### Z-2. 동적 대응 차단 위험 점검

- 트리 depth 4 강제? **거부** (코드 주석/관행, DB 제약 아님 유지).
- DnD depth 제한? **거부**.
- 도매 소스 끊김 = 기능 OFF? **거부** (감점만).
- fingerprint immutable? **거부** (redirect로 흡수).
- snapshot 크기 강제 임계? **거부** (모니터만).
- escalation 화면 행 수 강제? **거부**.
- score 노출 금지? **거부**.
- restore 절차 운영자 6단계 수동? **거부** (자동 6단계).
- brand_alias 자동 학습 금지? **거부** (suggested 게이트만).
- unmapped 0 강제? **부분 거부** (admin override).

전부 점검 완료. 동적 대응 차단 없음.

### Z-3. v4가 깔만한 약점 3~5포인트

v3 내부에서 미리 자수.

1. **stable_id 마이그레이션 한 방의 위험.** 기존 SHA1을 옛 redirect from_id로 등록한다고 했지만, web-api `Post.canonical_id`에 들어있는 값이 실제로 어느 시점 fingerprint인지 추적이 약하다. fingerprint_version이 처음 도입되는 순간 옛 데이터는 version=0으로 일괄 마킹할 텐데, 마킹 누락 시 redirect 미스가 난다. → v4가 "마이그레이션 검증 스크립트와 dry-run 카운트가 P0 안에 안 보인다"고 깔 수 있다.

2. **pricing_profile 가중치 시드의 자의성.** 5개 기본 프로파일 가중치는 결국 누군가 손으로 박는다. A/B 인프라가 P2라 검증이 늦다. → v4가 "초기 가중치 정당화 부재"로 깔 수 있다. (v1의 60/20/10/10 비판이 v3에서도 형태만 바뀌어 살아있다는 공격.)

3. **community_price_signal pull 배치 주기 미정.** web-api가 verdict 갱신을 db-admin이 polling으로 가져온다고 했는데 주기·실패 처리·web-api 다운 시 신호 정체가 안 박혔다. → v4가 "두 DB 약결합이라더니 결국 동기화 의존이다"라고 깔 수 있다.

4. **canonical split을 P2로 미룬 비용.** brand_alias 오염이나 name_core 누락 케이스에서 split이 빨리 필요할 수 있는데 merge만 P1, split은 P2. 그 사이에 잘못 합쳐진 canonical이 누적되면 redirect 그래프가 지저분해진다. → v4가 "merge만 가능하면 데이터가 한 방향으로만 뭉친다"라고 깔 만하다.

5. **match_candidate_log 적재량.** 후보 5개씩, 게시글 작성마다 한 row, rejected까지 다 적재 → 빠르게 쌓인다. P0에 보관 정책(90일 hot / 그 이후 archive)이 안 박혔다. → v4가 "토큰 API 로그 폭증" 약점으로 깔 수 있다.

이상 5포인트는 v4가 깔면 받는다. v3 시점에서 더 단단히 박으면 P0가 무거워져 라이브가 늦는다는 trade-off로 일단 둔다.

---

_v3 끝. v2의 진짜 약점은 박았고, 안전 타령은 명시 배척했다. v4는 위 Z-3의 5포인트를 우선 보라._
