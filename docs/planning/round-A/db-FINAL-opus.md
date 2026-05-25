# DB-admin 영역 v5 최종본 (Opus, Round-A FINAL)

> 입력: v1(Opus 초안) · v2(GPT 적대) · v3(Opus 살붙임) · v4(GPT 반론)
> 작성자: Opus 4.7 (v5, 최종 취합)
> 원칙: v1~v4의 모든 결정을 단일 완성 기획서로 통합. v1~v4 원문은 수정하지 않는다. 안전 타령으로 기능을 축소하지 않는다. 동적 대응 가능성을 닫지 않는다.

---

## 서문 — v1~v4 통합 정책

### S-1. v4가 새로 제기한 약점 중 v5가 수용하는 것

| v4 지적 | 수용 여부 | v5 처리 위치 |
|---|---|---|
| DnD와 검색 기반 이동을 동등 1급 입력으로, preview는 적용 직전 최신 tree_version 기준 재계산 | 수용 | §4 D-1 |
| 한 클릭 롤백을 idempotent `restore_job_id`로, 단계별 상태/재시도/실패 후 임시파일 정리 | 수용 | §4 D-3 / §6 백업·복구 |
| score와 함께 `score_confidence`(성숙도)를 같이 노출 | 수용 | §3 사용자 UX / §2 핫딜 점수 |
| snapshot 크기 고정 MB 대신 "환경별 성능 예산"(p95 응답·빌드 시간 등) | 수용 | §6 운영/품질 |
| escalation 화면 행 수 자유 + 큐 운영 품질 지표(확정/재오픈/취소율) 노출 | 수용 | §4 D-2 |
| redirect chain 결정성 계약(terminal id, max depth, cycle 금지, snapshot/web-api까지 강제) | 수용 | §2 상품(canonical) / §5 모듈 경계 |
| 매칭 API 장애 시 web-api는 "매칭 없이 게시 후 나중에 매칭" 경로 + request idempotency + 호출량 대시보드 | 수용 | §5 / §2 매칭 |
| set_version 강제 활성 시 "미분류 처리 큐" 자동 생성 | 수용 | §2 카테고리 / §4 D-1 |
| freshness_decay에 **카테고리별 half-life** + source lineage(독립 소스인지) 구분 | 수용 | §2 도매가 anchor |
| brand_alias suggestion을 중복묶음·영향수·증거출처로 정렬, DB는 승인/evidence 소유 vs AI는 후보 생성 소유 | 수용 | §2 매칭/별칭 / §5 |
| stable_id 마이그레이션 dry-run 카운트(orphan/legacy 매칭/grade 복구) 명시 | 수용 | §2 상품 / §6 / §8 P0 |
| pricing_profile 변경 시 score reason chip에 profile **버전 diff** 동반 | 수용 | §2 핫딜 점수 / §3 |
| crawler 파서 깨짐 vs 진짜 소스 중단 구분(같은 freshness여도 액션 다름) | 수용 | §2 도매가 anchor |
| category_remap의 영향이 keyword/autocomplete/aggregation/board feed/dashboard까지 미친다는 점 명시 | 수용 | §2 카테고리 |
| match_candidate_log를 hot(90일) vs archive로 나누고 봇/스팸 표식·idempotency·필드별 마스킹 | 수용 | §2 매칭 / §6 |
| community signal에 `verdict_version` delta pull + canonical 재매칭 시 old→new 이관 이벤트 | 수용 | §2 매칭 / §5 |
| 운영 DB rollback과 public snapshot rollback이 다른 일이라는 점 — 한 쌍으로 묶어 처리 | 수용 | §4 D-3 / §6 |
| AuditLog에 대량 이동 reverse를 위한 트랜잭션 그룹 키 | 수용 | §4 D-1 / §6 |
| canonical split을 P2 풀세트가 아닌 **P1에 "신규 관측치부터 분리" 최소판** | 수용 | §8 로드맵 |
| match_candidate_log 등 행동 로그의 개인정보성 — TTL/마스킹/export·delete 키 설계 | 수용 | §6 개인정보·운영로그 |
| 결제/구매 추적 신호 자리 — DB는 집계 conversion만 받고 원장 보유 금지 | 수용 | §6 / §9 미해결 |
| 다국어/타임존 컬럼 자리(observed_at_utc, source_timezone, display_name_i18n) | 수용 | §6 다국어/타임존 |
| 봇 트래픽 caller_id/bot_like 표식, hot endpoint 캐시 hit rate | 수용 | §6 rate limit |
| anchor source class(wholesale/retail/overseas/warehouse/manual) 분류 — 같은 weight로 섞지 않음 | 수용 | §2 도매가 anchor / §7 플러그인 |
| 게시판-상품 결합도가 "0이 아니다" — 문자열 의미 계약을 stable_id/redirect/snapshot_version으로 명시화 | 수용 | §5 모듈 경계 |
| 매칭 학습·AI 경계: DB는 ground truth와 운영 확정 이력, AI는 후보 생성과 ranking | 수용 | §5 모듈 경계 |

### S-2. v4가 제시했으나 v5가 명시 배척하는 것

v4는 v3가 깐 안전 타령 배척 방향을 대체로 인정했다. 그래도 v4 안에 다시 끼어든 "안전·축소"가 있다. 다음은 v5가 거부한다.

1. **"web-api가 match API 응답을 기다리면 db-admin 장애가 글 작성 UX에 영향" → 그러니 동기 호출을 약화** — 받아들이지 않는다. 매칭은 글 작성 핵심 가치다. 응답이 늦으면 **타임아웃 후 게시 허용 + 백그라운드 매칭 재시도**로 가지, "매칭을 약화"하지 않는다. 기능은 살리고 백오프만 추가한다.
2. **"score를 사용자가 과신할 수 있으니 카테고리별 임계까지 의미를 분기" → score 의미 불확정 권고** — 거부한다. 임계는 운영자가 조정하지만 **사용자가 보는 라벨 5단계(정상가/평범/살만함/핫딜/역대급)는 전역 통일**한다. 카테고리마다 "70점의 의미가 다르다"고 흩으면 일반인 가독성이 무너진다. score_confidence를 같이 보여서 해결한다.
3. **"match_candidate_log를 학습에 쓰려면 hot/archive 분리" 자체는 수용하지만, "행동 데이터 민감하니 수집 자체를 줄이자" 식 후속 권고** — 거부. 후보 5개 JSON과 선택/거절은 그대로 다 적재한다. TTL/마스킹/익명화로 풀지, 수집 축소로 풀지 않는다.
4. **"점수 노출 의미가 흔들리니 초기 3개월 점수값 고정" 옵션** — 거부. score는 데이터가 흐르는 대로 매일 갱신된다. 운영자가 가중치를 조정할 자유와 사용자가 최신 점수를 볼 권리를 동시에 보장한다. "고정"은 동적 대응 차단이다.
5. **"split을 P1로 올리되 과거 이관은 나중" → 사실상 split 보류** — v5는 받지만 더 밀어붙인다. P1에 **split 큐 + 신규 관측치 분리 + 과거 관측치 후보별 격리 라벨**까지 넣는다. 과거 전체 자동 이관만 P2다.
6. **"행동 로그 운영 책임자는 누구? → DB가 안 가져도 됨" 톤** — 거부. 매칭/검색/community 로그는 **DB가 보유**한다(§6). 책임을 흩뜨리지 않는다.
7. **"snapshot 분리 결정 트리거를 p95 200ms·3일 연속 등 숫자로 박자"** — v4가 v3의 MB 박기를 비판한 직후에 다시 박았다. v5는 임계 자체를 박지 않고 **대시보드 + 운영자 결정**으로 굴린다. v3 입장 유지.
8. **"category 활성 후 미분류 처리 큐 자동 생성"은 수용했지만 "강제 활성을 사실상 어렵게 만들자" 톤** — 거부. admin override는 한 클릭 유지. 단지 미분류 큐로 흐를 뿐이다.

### S-3. v4의 v5 결단 질문 5개 — 직답

**Q1. stable_id 마이그레이션 성공 기준은?**
A. 다음 dry-run 카운트가 동시에 만족되어야 진행한다.
- `canonical_products`에 존재하는 id와 매칭되는 `Post.canonical_id` 비율 ≥ 98%
- snapshot에서 grade_summary가 복구되는 post 비율 ≥ 95%
- orphan(어디에도 안 맞는) `Post.canonical_id` 절대수 ≤ 50 또는 전체 post의 0.5% 중 작은 값
- 같은 legacy id가 둘 이상의 stable_id 후보로 갈라지는 케이스 = 0 (1건이라도 있으면 운영자 수동 결단 필요)
- 위 카운트는 dry-run 명령 한 줄로 출력되고, 진행 결정은 admin이 한 번 더 확인 버튼을 누른다. 자동 진행 금지.

**Q2. P0 15개 중 "테이블 자리만 P0"와 "운영 UI까지 P0" 분리?**
A. §8 로드맵에서 표로 명시. 원칙은:
- **계약(스키마/API)·데이터 무결성·redirect·atomic publish·권한 표 = 풀세트 P0** (라이브 가동 후 못 바꾸면 다 깨지는 것)
- **운영 UI 완성판 = P0-lite**: 최소 운영 가능한 형태(목록·기본 액션)는 P0, 부가 UX(검색·필터·일괄·diff 뷰)는 P1
- 예: `category_remap` 모델·트랜잭션은 P0, mapping 작업 UI는 P1. `pricing_profile` 테이블·시드 3~5개는 P0, 운영자 조정 화면은 P0-lite.

**Q3. hotdeal_score 초기값은 누가 어떤 근거로?**
A. **DB 영역 운영자(admin role)가 시드 프로파일 5개를 박는다.** 근거는 다음 3개 신호의 가중 합산이며, 모두 문서에 기록한다.
- (a) v1/v3 산식 의도(시장 분위수 우선, 도매가 보조, 표본·조건부 페널티)
- (b) 라이브 직전 1~2주 dry-run 시뮬레이션: 기존 observations에 산식을 돌려 점수 분포가 0~100에 고르게 퍼지는지 확인
- (c) 카테고리별 변동성 사전 지식(신선식품은 wholesale weight 0.4, 가공식품은 0.2 같은 보수적 기본값)
- label 임계(0/30/50/70/90)는 **전역 고정**. profile별 가중치만 조정 가능. profile 변경 시 reason chip에 `profile_version=신선v2` 같은 버전 라벨 동반.
- A/B 인프라는 P2지만 **profile 변경 이력은 P0부터 기록**(`pricing_profile_change_log`).

**Q4. web-api ↔ db-admin 약결합 계약 범위?**
A. 다음 6개 항목까지가 계약이다. 그 외는 db-admin 자유.
1. 공유 키는 `stable_id` (문자열, 영구 불변). SHA1 fingerprint는 외부 노출 금지.
2. 모든 외부 조회는 redirect resolver를 통과한다. resolver는 terminal id 반환을 보장. chain 깊이 상한 8. cycle 금지(생성 시 검증).
3. snapshot은 `.next → checksum → os.replace` atomic publish. 빌드 실패 시 이전 파일 유지. web-api는 응답 헤더에 `X-Snapshot-Version`, `X-Scoring-Profile-Version` 포함.
4. 매칭 API: `POST /public/match/candidates` + `/select|reject`. **타임아웃 800ms**(권장). 초과 시 web-api는 매칭 없이 게시 허용하고 백그라운드에서 재시도 큐로 보낸다. `request_id`는 idempotent.
5. community signal: web-api가 `(post_id, canonical_id, verdict_version)` 변경분만 노출. db-admin은 마지막 본 `verdict_version` 이후만 pull. post의 canonical_id 변경 시 delta 이벤트로 old→new 이관.
6. web-api는 운영 DB(SQLAlchemy 모델)에 절대 직접 접근하지 않는다. snapshot 파일 read + 위 API만.

**Q5. 행동 로그·백업·트래픽 운영 책임자는?**
A. **DB 영역이 다음을 소유한다**(웹/AI에 떠넘기지 않는다).
- 모든 매칭/검색/community 로그 적재·TTL·마스킹 → DB 영역
- restore drill(월 1회 자동), `PRAGMA integrity_check` 결과 보관, WAL 포함 백업, 디스크 다른 위치로 복제 → DB 영역
- caller_id별 호출량·bot_like 표식·hot endpoint 캐시 hit rate 대시보드 → DB 영역(엔드포인트 자체는 web-api지만 메트릭 수집은 DB)
- read scaling 전환 기준은 운영하며 결정. 사전 박지 않음.
- 개인정보 export/delete 요청 처리 키는 DB 영역이 설계(§6).

---

## 1. 프로젝트 맥락 + DB 책임 범위

WalletSavior는 마트별로 뒤죽박죽 표기된 상품·가격을 **하나의 캐노니컬 축**으로 묶어, **도매가 anchor 위에 분위수(P10/P25/P50/P75) 가격대와 핫딜 점수**를 객관 수치로 얹는 서비스다. 일반인은 "이거 핫딜인가" 한 줄 답을 받고, 핫딜러는 깊은 추이·필터·도매 anchor까지 본다.

**DB 영역(db-admin) 책임 7가지**
1. 캐노니컬 상품 모델과 외부 공개용 `stable_id` 계약
2. 마트 SKU 별칭(matching) 적재·승인·escalation
3. 가격 관측·분위수·일간 집계·핫딜 점수 산정
4. 도매가 anchor 다중 소스 적재 + freshness/lineage 관리
5. 카테고리/키워드 트리(버전·remap·플러그인 교체)
6. 운영 mutation의 audit/rollback/restore
7. 공개 스냅샷(atomic publish) + 좁은 API 발급

**DB 영역이 안 하는 것**
- 게시판 글/댓글 저장(web-api 소유)
- AI 모델·candidate generator(ai-admin 소유)
- 크롤링 실행·파서(crawler 소유)
- 결제/구매 원장(향후 결제 영역 소유)

---

## 2. 데이터 모델 (완성판)

### 2-1. 카테고리 트리 + version + remap

- 1~4 depth(주석/관행, DB 강제 아님). adjacency list, path 문자열, slug.
- 추가 컬럼: `display_for_consumer`, `popularity_score`, `seasonality_json`, `pricing_profile_id` FK, `set_version`.
- `category_set` 테이블: id, version_label, status(draft/active/archived), activated_at.
- `category_remap`: (from_set_version, to_set_version, from_category_id, to_category_id NULL, mapping_kind∈one_to_one/split/merge/unmapped, confidence, decided_by∈auto/manual/ai_suggested).
- 활성 set 전환: 트랜잭션 한 번에 status swap + active_set_version_id를 시스템 설정에 기록. **admin override 강제 활성화 가능**(미분류 상품은 자동으로 미분류 처리 큐로 흐름).
- remap의 영향 범위: category_id뿐 아니라 keyword, autocomplete, price aggregation, board feed facet, dashboard 통계까지 재계산 필요 → 활성 전환 직후 야간 배치가 자동 재계산.

### 2-2. 상품 — canonical_id stable + redirect 분리

```
canonical_product_identity
  stable_id              TEXT PK            -- ulid/nanoid, 외부 영구 불변
  current_fingerprint    TEXT               -- SHA1(brand_norm|name_core|pack_qty|pack_unit|fp_version)
  fingerprint_version    INTEGER
  merged_into            TEXT NULL
  split_from             TEXT NULL
  status                 ENUM(active/merged/split/dead)
  created_at, updated_at

canonical_id_redirect
  from_id   TEXT PK
  to_id     TEXT
  reason    ENUM(merge/split/brand_alias_rule/fingerprint_version_bump/manual)
  created_at, created_by_user_id
```

**resolver 계약**
- 모든 외부 조회는 `resolve(id) = follow_redirect until terminal` 강제.
- chain 최대 깊이 8, cycle 생성 시 INSERT 거부.
- snapshot 빌더와 web-api `SnapshotRepo.product_by_id`/`grade_by_id`는 resolver를 의무 통과 (구현 계약, P0).
- AI는 학습 시 legacy SHA1을 입력으로 받을 수 있으나 출력은 stable_id로 변환 후 반환.

### 2-3. 가격/스냅샷/추이 (atomic publish)

```
PriceObservation (보강)
  ... 기존 ...
  effective_price_type    ENUM(base/sale/coupon/membership/card/bundle)
  min_purchase_qty        INTEGER DEFAULT 1
  requires_membership     BOOLEAN
  requires_card           TEXT NULL
  coupon_code             TEXT NULL
  bundle_description      TEXT NULL
  display_price_text      TEXT
  normalized_unit_price   INTEGER NULL
  normalized_unit_basis   ENUM(per_100g/per_1kg/per_each/per_1l/per_100ml)
  normalization_confidence REAL DEFAULT 1.0
  region_hint             TEXT NULL                 -- P1 적재 시작
  store_scope             ENUM(online_national/online_region/offline_store)
  observed_at_utc         TIMESTAMP
  source_timezone         TEXT
  local_sale_date         DATE                       -- KST 기준
  suspicious_regular_jump BOOLEAN DEFAULT false

price_daily_agg            -- 캐시
  (stable_id, mart, local_sale_date, min/avg/max/n, has_sale, has_membership)

snapshot_build_log
  id, snapshot_version, started_at, finished_at, duration_ms,
  file_size_bytes, sha256, row_counts_json, status, error_message
```

**Atomic publish 계약**
- 빌더: `public_snapshot.sqlite.next` → fsync → sha256 사이드카 → `os.replace`로 rename.
- 빌드 실패 시 `.next` 폐기, 현재 파일 보존.
- 이전 N개(기본 7) snapshot 보관, cron이 초과분 정리. 운영자가 보관 수 조정 가능.
- web-api는 핸들 교체를 다음 요청 단위로 함. 진행 중 쿼리는 옛 핸들 유지. Windows의 열린 핸들 replace 동작은 OS 차이로 위험 → 빌더가 publish 알림 후 web-api가 명시적으로 핸들을 닫고 새로 연다.
- 스냅샷에 들어가는 것: canonical product / price_grade / category / alias / `price_daily_agg` 90일치 / `hotdeal_score` / `wholesale_anchor`. **raw observations 금지**.

### 2-4. 핫딜 점수 — robust 산식 + profile 가중치

```
요소(각 0~1로 정규화, 카테고리 pricing_profile의 가중치로 합산 후 0~100)

p_position_robust:
  band_floor = max(P50 * 0.05, 100원)
  분모 = max(P50 - P10, band_floor)
  clamp((P50 - current) / 분모, 0, 1.2)

w_against_wholesale:
  if wholesale_anchor not null and not is_stale:
    clamp((anchor*conv*1.15 - current) / (anchor*conv*0.15), 0, 1)
  else: 0.5 (중립)

sample_confidence (곱 페널티):
  n<5: 0.3 / n<15: 0.6 / n<50: 0.85 / else: 1.0

condition_penalty (곱 페널티):
  base:1.0 / sale:0.95 / coupon|membership|card:0.7 / bundle:0.6

event_bonus: 0 또는 +0.1

raw = (w_q * p_position_robust + w_w * w_against_wholesale + w_e * event_bonus)
       * sample_confidence * condition_penalty
final_score = round(clamp(raw,0,1) * 100)
```

```
pricing_profile
  id, name, description,
  weight_market_quantile REAL, weight_wholesale REAL,
  weight_event REAL, weight_sale_cycle REAL,
  sample_min_required INTEGER, band_floor_pct REAL,
  updated_by, updated_at

pricing_profile_change_log
  id, profile_id, before_json, after_json, changed_by, changed_at, note

category_node.pricing_profile_id  FK NULL
```

**시드 5개**: 신선식품 / 가공식품 / 생필품 / 수입가공 / 기타. weight는 S-3 Q3 근거로 박는다.

**노출**: score + label(전역 5단계: 0~29 "정상가/비쌈" 빨강, 30~49 "평범" 회색, 50~69 "살만함" 연두, 70~89 "핫딜" 초록, 90~100 "역대급" 진초록★) + score_confidence(0~1) + reason chips + profile_version 라벨.

mart별 점수와 canonical 종합 점수를 **둘 다 계산**. 게시판은 mart 점수 우선 표시.

### 2-5. 도매가 anchor — 3-layer + freshness_decay + fallback

```
wholesale_baseline
  id, source_code, source_class ENUM(wholesale/retail_marketplace/overseas_direct/warehouse_bulk/manual_admin),
  source_lineage_group TEXT,   -- 같은 원천 재가공이면 동일 그룹
  commodity_key, observed_date, observed_at_utc,
  unit_price_krw, unit_basis, region_hint,
  raw_payload, ingested_at

wholesale_source_status
  source_code PK, display_name,
  last_success_at, last_failure_at, failure_kind ENUM(network/parser/auth/empty),
  consecutive_fails, freshness_days,
  confidence_weight REAL, status ENUM(active/stale/dead)

wholesale_to_canonical_link
  stable_id FK, commodity_key FK, conversion_factor REAL,
  confidence ENUM(MANUAL/AI_SUGGESTED)

category_freshness_policy
  category_id PK, half_life_days INTEGER   -- 신선:7, 가공:30 등
```

**산식**: `effective_anchor = Σ(price * confidence_weight * decay(days, half_life)) / Σ(weight*decay)` — **같은 source_lineage_group은 한 표로 합산** (중복 weight 방지).
**fallback**: 모든 소스 stale → anchor 컬럼 `is_stale=true`. UI는 "도매 anchor 오래됨" 안내, 분위수 중심 표시. **기능 비활성화 아님**.
**parser 깨짐 vs 진짜 중단**: `failure_kind`로 구분. parser는 크롤러 영역 알림, 진짜 중단은 운영자 escalation.

### 2-6. 매칭/별칭 — alias availability + community signal

```
MartSkuAlias (보강)
  ... 기존 + UNIQUE(mart, mart_item_id) ...
  availability_status     ENUM(active/out_of_stock/discontinued/unknown)
  last_success_seen_at    TIMESTAMP NULL
  last_missing_seen_at    TIMESTAMP NULL
  consecutive_miss_count  INTEGER DEFAULT 0

brand_alias
  alias, canonical_brand, status ENUM(suggested/approved/rejected/rollback),
  evidence_json, affected_count_at_approval INTEGER NULL,
  approved_by, approved_at, applies_from_fingerprint_version INTEGER,
  PRIMARY KEY (alias, canonical_brand)

alias_blacklist
  pattern TEXT, kind ENUM(pb/mart_name/seller_name/generic)

match_candidate_log
  request_id PK, post_draft_id NULL, post_id NULL,
  caller_id, bot_like BOOLEAN, query_payload_json, candidates_json,
  selected_stable_id NULL, rejected_reasons_json NULL, ts,
  archived BOOLEAN DEFAULT false

community_price_signal
  stable_id, post_id,
  verdict_hot_count, verdict_not_hot_count, verdict_neutral_count,
  verdict_version INTEGER, last_pulled_at,
  dispute_flag BOOLEAN
```

**규칙**
- 7일 연속 miss → `out_of_stock`. 30일 → `discontinued` 후보 escalation. canonical 삭제 금지.
- `mart.status (active/closed)` + `closed_at` — 폐점 시 alias 전체 archive, 분위수 계산 제외.
- brand_alias 자동 학습 ON. 단 `suggested`만 자동 적재. 영향 canonical 수가 운영자 화면에 표시. approve 시 `applies_from_fingerprint_version=현재+1` → 다음 fingerprint 배치부터 적용. 적용 후 문제 시 rollback 상태로.
- match API: 후보 5개, request_id idempotent. **bot_like 표식된 요청은 학습 신호에서 제외**, 적재는 함.
- community signal은 web-api가 `verdict_version` 변경분만 노출 → db-admin이 delta pull. post의 canonical_id 변경 시 old stable에서 빼고 new stable에 더하는 명시 이벤트.

### 2-7. effective_price_type / 단위 정규화

§2-3에 포함. **사용자 화면은 "봉지당 2,000원"과 "100g당 667원"을 같이 표시**. 조건부 가격은 chip으로 명시("쿠폰가 기준", "2개 이상").

### 2-8. escalation — claim/version

```
ProductReviewQueue (보강)
  version INTEGER NOT NULL DEFAULT 0,
  claimed_by user_id NULL,
  claimed_at TIMESTAMP NULL,
  claim_expires_at TIMESTAMP NULL   -- 기본 +15분

canonical_conflict_queue
  id, kind ENUM(potential_merge/ambiguous_split/brand_alias_collision/fingerprint_collision),
  stable_ids_json[], evidence_json,
  suggested_action ENUM(merge/split/keep_separate),
  status ENUM(open/resolved/dismissed),
  created_at, resolved_at, resolver_user_id
```

resolve API는 `WHERE id=? AND resolved_at IS NULL AND version=?` 1행 갱신. 실패 시 "이미 다른 관리자(@X)가 처리함" UI 분기. claim 만료 cron 자동 해제.

5테이블 단일 트랜잭션(alias upsert / category 갱신 / 큐 resolve / AuditLog / 옵션 유사 큐 일괄 제안) — escalation 1건 ms 단위라 충분.

### 2-9. match_log + 학습 신뢰도

- `match_candidate_log` hot(90일) vs archive(이후 후보 JSON 압축 또는 집계 전환).
- 학습용 export 시 사용된 archive 시점 `training_snapshot_id` 기록.
- AI는 학습 입력으로 archive 또는 hot을 받고, alias suggestion을 `brand_alias.status=suggested`로 반환. evidence_json은 공유 스키마.

---

## 3. 사용자 UX가 보는 데이터 모양

### 3-1. 상품 요약 API 응답

```json
GET /public/products/{stable_id}/summary
{
  "stable_id": "01J...",
  "display_name": "서울우유 흰우유 1L",
  "current": {
    "best_offer": {"mart":"E","price":2480,"as_of":"...","effective_type":"sale"},
    "hotdeal_score": 78,
    "score_confidence": 0.62,
    "score_profile_version": "신선v2",
    "label": "핫딜",
    "score_reasons": [
      {"key":"vs_p50","label":"P50보다 22% 저렴","delta":0.42},
      {"key":"vs_wholesale","label":"도매가 대비 -18%","delta":0.18},
      {"key":"sample","label":"표본 충분 (n=64)","delta":0},
      {"key":"condition","label":"멤버십가 아님","delta":0}
    ],
    "dispute_flag": false
  },
  "bands": {"wholesale_anchor":1800,"p10":2400,"p25":2600,"p50":3100,"p75":3400,"is_stale":false},
  "trend_url": "/public/products/01J.../trend?window=90d"
}
```

### 3-2. 추이 그래프

```
GET /public/products/{stable_id}/trend?window=90d&granularity=day
points[], bands{}, annotations[event_labels]
```

### 3-3. "이거 핫딜 아님" 라벨 룰

§2-4 5단계 전역 통일. dispute_flag=true면 "의견 분분 (찬:반 3:8)" sub-label.

### 3-4. 매칭 후보 (게시글 작성 보조)

```
POST /public/match/candidates
  body: {title, body_excerpt?, mart_hint?, deal_url?, deal_price?, unit_hint?, request_id}
  resp: {candidates:[{stable_id, display_name, brand, pack, confidence, match_reasons, unit_basis, last_seen_at, current_price_band, score_preview}], request_id}
POST /public/match/select | /reject
```

타임아웃 800ms. 초과 시 web-api는 매칭 없이 게시 + 재시도 큐.

---

## 4. 관리자 UX (db-admin)

### 4-1. 카테고리 트리 — 전체 depth DnD + 검색 이동 + preview + undo

- DnD와 breadcrumb 검색 기반 "여기로 이동" 둘 다 1급.
- 이동은 "변경 대기" 박스에 쌓이고, **적용 직전 최신 tree_version 기준 preview 재계산**.
- 영향 상품 수 / 하위 노드 수 / 변경되는 path 목록 모달 → 적용.
- 적용 후 30초 노란 띠 + "되돌리기" — AuditLog 트랜잭션 그룹 키 기반 통째 reverse.
- 동시 편집자: tree_version mismatch → diff 모달.
- 강제 활성화 시 자동으로 "미분류 처리 큐" 생성.

### 4-2. escalation 큐 — 그룹화 + 품질 지표

- 같은 raw name / 같은 suggested_canonical_id 묶음 자동 그룹화 토글.
- 그룹 단위 일괄 확정. 그룹 bulk 확정 시 **group evidence 항상 동반 표시**.
- 페이지 크기 사용자 설정(저장됨). 행 수 강제 없음.
- 화면 상단에 운영 품질 지표: "오늘 확정 142건 / 재오픈 9건 / bulk 확정 취소 3건 / 평균 처리 4.2분".
- claim 상태 표시: "@kim이 7분 전 잡음" → 다른 운영자 read-only, 15분 후 자동 해제.

### 4-3. 스냅샷·롤백·일괄편집

**한 클릭 롤백 + idempotent restore job**
1. 모달: 백업 목록 + timestamp/size/snapshot diff 요약 + 사라질 데이터 preview.
2. "복원 시작" → `restore_job_id` 발급, 6단계 자동:
   - [1/6] ingestion pause
   - [2/6] 현재 DB pre-restore 백업
   - [3/6] 새 파일 restore
   - [4/6] `PRAGMA integrity_check`
   - [5/6] DB 핸들 교체 + snapshot 재빌드 트리거
   - [6/6] ingestion resume
3. 단계별 진행 표시. 실패 단계는 재시도 가능. abort 시 임시 파일 자동 정리.
4. 운영 DB와 public snapshot은 **한 쌍**으로 묶여 함께 되돌아간다(이전 snapshot N개 중 동시점 쌍 선택, 또는 즉시 재빌드).

**스냅샷 diff 뷰어**: snapshot_version 2개 dropdown → 카테고리 추가/삭제/이동, canonical 신규/사라짐, price_grade 큰 변동 목록.

**일괄편집**: alias 다중 선택 → brand_alias suggest 일괄 생성. 큐 다중 선택 → AI 재추천 일괄 요청. 키워드 DnD로 카테고리 매핑.

### 4-4. 누적 모니터 대시보드

- 마트별 24h/7d/30d observations 행수 sparkline
- 카테고리별 매칭률
- 가격 분포 히트맵
- escalation 큐 깊이 추이
- 도매가 anchor 최근 갱신일 (source별)
- snapshot build duration / file size / row counts (snapshot_build_log)
- API caller_id별 호출량 / bot_like 비율 / hot endpoint 캐시 hit rate
- DB 파일 크기 / vacuum 필요 여부 / 최근 쿼리 p95

---

## 5. 모듈 경계

### 5-1. API 경계

```
[ingestion - write only]
  POST /ingest/observation        crawler/service
  POST /ingest/alias              crawler/service
  POST /ingest/wholesale          cron/manual_csv_uploader

[ai - suggest only]
  POST /review/{id}/suggest       ai/ai_publisher
  POST /alias/suggest             ai/ai_publisher

[admin - mutation]
  POST /review/{id}/claim         moderator+
  POST /review/{id}/resolve       moderator+
  POST /category/move             moderator+ (tree_version 체크)
  POST /category/set_version/activate   admin
  POST /brand_alias/{id}/approve  admin
  POST /backup, /restore          admin

[public - read + match]
  GET  /public/snapshot.sqlite              web-api 토큰
  GET  /public/products/{stable_id}/summary
  GET  /public/products/{stable_id}/trend
  POST /public/match/candidates             web-api 토큰
  POST /public/match/select | /reject       web-api 토큰
  POST /public/community/pull               web-api 토큰 (verdict_version delta)
```

운영 DB 직접 접근 외부 영역 전부 금지. 무조건 API/스냅샷 경유.

### 5-2. 권한 표 (P0 문서)

| 호출자 | 가능 | 불가 |
|---|---|---|
| crawler/service | ingest/observation, ingest/alias | 그 외 전부 |
| ai/ai_publisher | review suggest, alias suggest, snapshot read | resolve, alias 직접 쓰기 |
| web-api | snapshot read, match candidates/select/reject, community pull | 운영 DB 직접, 트리 변경, restore |
| db-admin moderator | 큐 resolve, 트리 이동, alias 수정 | restore, set_version 활성, 권한 부여 |
| db-admin admin | 백업/restore, set_version 활성, 권한, brand_alias approve | (전부 가능) |

### 5-3. 게시판 DB와 약결합 (실제 계약)

v4 지적대로 결합도 0이 아니다. 실제 계약 6개(S-3 Q4)가 약결합의 본체다. 요약:
- 공유 키 `stable_id` 한 개
- redirect resolver 의무 통과
- snapshot atomic publish + version 헤더
- 매칭 API + idempotency + 타임아웃 백오프
- community delta pull
- 운영 DB 직접 접근 금지

### 5-4. AI와의 경계

- DB 소유: approved alias, rejected alias, conflict resolution, match_candidate_log, selected/rejected outcome, evidence_json 스키마
- AI 소유: candidate generator, feature extraction, model_version, confidence calculation
- 공유: evidence schema, model_version 라벨, training_snapshot_id

---

## 6. 운영/품질

### 6-1. 백업/복구 (서버 다운/디스크 손상)

- 일일 자동 백업(SQLite backup API + WAL 포함). 백업 직후 `PRAGMA integrity_check` 자동, 결과 `backup_log`에 저장.
- 백업 파일은 **다른 디스크 위치**(혹은 외부 스토리지)로 복제.
- 월 1회 **restore drill** 자동 실행 → 별도 임시 DB에 복원 → integrity check → 결과 보관. 실패 시 admin 알림.
- 운영 DB rollback과 public snapshot rollback은 한 쌍(§4-3).
- 디스크 손상 시: 가장 최근 integrity_check ok 백업으로 restore. WAL 있는 경우 우선 시도.

### 6-2. 동시성/트랜잭션

- escalation: claim + optimistic version (§2-8).
- 카테고리: tree_version mismatch → diff 모달.
- alias: UNIQUE(mart, mart_item_id) DB 제약.
- 5테이블 묶음 트랜잭션은 ms 단위로 짧음. 비관 락 없음.
- 대량 이동(>50노드)은 AuditLog 트랜잭션 그룹 키로 묶고 통째 reverse 가능.

### 6-3. Read replica / 스케일

- 공개 조회는 snapshot 파일(여러 web-api 인스턴스가 같은 파일 읽기).
- 학습/행동 로그(match_candidate_log, search_query_log)는 별도 append-only 테이블 또는 별도 DB로 분리 가능한 구조 P0부터(같은 SQLite 안에서도 테이블 분리).
- 운영 mutation은 admin DB 단일.
- 분리 전환 기준은 **숫자로 미리 박지 않는다**(§S-2.7). 대시보드 + 운영자 결정.

### 6-4. 도매 anchor 끊김 시 fallback

§2-5. freshness_decay + lineage. 모든 소스 dead → 분위수 중심 표시, **기능 비활성화 없음**.

### 6-5. API rate limit

- caller_id별 호출량/분당 한도(기본값 운영자 조정 가능).
- 초과 시 429 + Retry-After.
- request_id idempotency: 같은 request_id로 재시도 시 동일 응답 캐시.
- bot_like 휴리스틱(UA, 빈도, 후보 reject 0%) → 표식만, 차단은 운영자 결정.
- hot endpoint(summary, candidates) 짧은 캐시(최대 60초) 권장.

### 6-6. 개인정보 / 활동 로그 (GDPR 어휘 아닌 운영 요구)

- 사용자별 export/delete 요청 처리 키: `session_hash`(또는 user_id) 기준 인덱스.
- `match_candidate_log.query_payload`의 title/body_excerpt/deal_url는 hot 90일, archive 단계에서 후보 JSON 압축 + 본문 필드 마스킹(URL 도메인만 보존 등).
- session_hash는 분기별 rotation(재식별 방지).
- AuditLog는 운영자 행위 기록 → 보존 대상. 별도 키 분리.
- 결제 원장이 들어오면 **DB는 집계 conversion만** 보유. 원본 결제는 결제 영역.

### 6-7. 다국어 / 타임존

- KST 우선. `observed_at_utc` + `source_timezone` + `local_sale_date` 컬럼 자리 P0.
- `display_name_i18n` JSON 컬럼 자리 P1(실제 다국어 채움은 P2+).
- 카테고리 locale label P1 자리.
- 통화 / fx_rate_at_observed / shipping 포함여부 / 세금 포함여부 — anchor source_class 단위로 채워 P1+에 본격 사용.

---

## 7. 플러그인 메커니즘

### 7-1. category_set_version

- `category_set` + `category_remap`(§2-1). draft import → AI 1차 매핑 → 운영자 검토 → 활성 swap.
- admin override 강제 활성 가능. 미분류는 자동 큐.
- 키워드 셋도 동일 패턴(`keyword_set`, `keyword_remap`).

### 7-2. 도매 anchor 어댑터(새 소스 추가)

- `wholesale_baseline.source_code` + `source_class` + `source_lineage_group` 만 채우면 신규 소스 등록 완료.
- 소스별 어댑터는 crawler 영역(파서·인증·갱신주기 소유).
- DB는 status / freshness / confidence_weight만 본다.
- `confidence_weight`는 운영자가 화면에서 0.0~1.0 조정.
- KAMIS는 코드 주석 박힌 대로 source_code에 등록 금지(시드 blacklist).

### 7-3. 단위 / 카테고리 매핑 룰

- `normalization_rule` 테이블(P1): 패턴 → unit_basis 변환 규칙. 운영자 편집 가능.
- 카테고리별 default unit_basis(예: 정육은 per_100g, 음료는 per_1l) — pricing_profile과 연결.

### 7-4. scoring_profile 버전 + A/B

- `pricing_profile_change_log`로 모든 변경 이력 보관(P0).
- snapshot에 `scoring_profile_version` 동행. 산식 변경 후에도 옛 버전 일정 기간 유지 가능(이전 7개 snapshot).
- 풀세트 A/B(사용자 bucketing, 비교 메트릭)는 P2.

---

## 8. 로드맵 P0/P1/P2

### P0 — 라이브 직전 필수

| # | 항목 | 형태 |
|---|---|---|
| 1 | `stable_id` + `canonical_id_redirect` 분리, 마이그레이션 dry-run 카운트 출력(S-3 Q1) | 풀세트 |
| 2 | 공개 스냅샷 atomic publish (`.next → checksum → rename`) + snapshot_build_log | 풀세트 |
| 3 | 매칭 토큰 API `/public/match/candidates` + `/select|reject` + `match_candidate_log` (hot 90일 정책 포함) | 풀세트 |
| 4 | escalation `version` + `claim*` + 5테이블 단일 트랜잭션 resolve | 풀세트 |
| 5 | `price_daily_agg` 캐시 + 야간 빌드 | 풀세트 |
| 6 | 카테고리 트리 DnD + 검색 이동 + preview + undo | 풀세트 |
| 7 | 수동 CSV 업로드 도매가 + `wholesale_baseline`/`wholesale_source_status`/lineage/freshness_decay/half_life | 풀세트(자동 수급은 P1) |
| 8 | 한 클릭 idempotent restore job (6단계 자동) + 운영 DB·snapshot 쌍 롤백 | 풀세트 |
| 9 | AuditLog 활성 + 트랜잭션 그룹 키 + "최근 내 작업 30건 undo" | 풀세트 |
| 10 | `effective_price_type` + 조건부 컬럼군 + 단위 정규화 | 풀세트 |
| 11 | `MartSkuAlias.availability_status` + 단종 룰 | 풀세트 |
| 12 | `category_remap` 모델·트랜잭션 + admin override + 미분류 큐 자동 생성 | 모델 풀세트 / 운영 화면 P1 |
| 13 | `pricing_profile` + 시드 5개 + `pricing_profile_change_log` | 모델 풀세트 / 조정 화면 P0-lite |
| 14 | 서비스간 권한 표 문서화 + scope enforce 최소판 | 문서 풀세트 / 코드 enforce 부분 P1 |
| 15 | hotdeal_score robust 산식 + reason chips + score_confidence + label 5단계 전역 | 풀세트 |
| 16 | `observed_at_utc` / `source_timezone` / `local_sale_date` 컬럼 자리 | 풀세트 |
| 17 | caller_id 호출량 / bot_like 표식 / request_id idempotency | 풀세트(대시보드는 P0-lite) |
| 18 | community `verdict_version` delta pull 인터페이스 | 풀세트 |

### P1 — 가동 직후 1개월

1. 도매가 자동 수급 어댑터 2~3개(crawler와 협의)
2. `search_query_log` + `autocomplete_suggestion`
3. 스냅샷 diff 뷰어
4. `brand_alias` suggested → approved 운영 화면
5. `category_remap` 운영 화면(미매핑 큐 포함)
6. `region_hint` / `store_scope` 적재 시작(분위수 분리는 P2)
7. `suspicious_regular_jump` 플래그
8. `mart_sale_cycle` 배치
9. `community_price_signal` 풀세트(canonical 재매칭 시 delta 이관)
10. canonical merge 액션 + **split 최소판**(신규 관측치 분리 + 과거 관측치 격리 라벨)
11. 누적 모니터 대시보드 전체
12. `normalization_rule` 운영자 편집
13. `display_name_i18n` / locale label 자리 적재 시작
14. restore drill 자동화 + `backup_log.integrity_result`

### P2 — 이후

1. canonical split 풀세트(과거 관측치 자동 이관 룰)
2. region별 분위수 분리
3. scoring_profile A/B 인프라(사용자 bucketing·메트릭)
4. 사용자 watch 알림 연계
5. 시즌성 가중 hotdeal_score
6. 외부 다국어/통화/세금/배송 본격화
7. 결제 영역 결합(집계 conversion만)
8. 학습 archive 압축/포맷 전환

---

## 9. 미해결 / 추후 결단 (라이브 후 데이터 보고)

- snapshot 분리(파일 쪼개기) 트리거: p95 응답·빌드 시간·메모리 사용률 — 숫자 미리 박지 않음.
- read replica 도입 시점.
- pricing_profile 가중치의 운영자 조정 빈도 정책(주 1회 vs 일 단위).
- 결제 conversion 신호 들어올 때 점수 자동 보정 여부.
- AI candidate generator의 model_version과 db-admin alias 승인 사이의 정확한 학습 루프(현재 evidence_json 공유까지만 정함).
- 외부 다국어 본격화 시 카테고리 path 표현(slug vs locale label) 결정.

이 항목들은 **데이터 흐르는 모양을 보고 결정**한다. 사전에 박으면 거의 다 틀린다.

---

## 10. v1~v4 추적 매트릭스

| 결정 항목 | v1 | v2 | v3 | v4 | v5 결단 |
|---|---|---|---|---|---|
| canonical_id 안정성 | SHA1 그대로(자수) | stable_id + redirect 박살 | 분리 수용, fingerprint 자유 | redirect chain 결정성 추가 요구 | **stable_id PK + redirect + resolver 의무 통과 + chain 깊이 8** |
| 게시판 결합 | "없음"(오판) | `Post.canonical_id` 이미 있음 정정 | 토큰 API P1→P0 격상 | 결합 0 아님, 6개 계약 명시 요구 | **6개 약결합 계약 §S-3 Q4** |
| snapshot publish | "atomic rename" 기획만 | unlink 후 재생성 정정 | atomic publish P0, 7개 보관 | Windows 핸들/web-api 핸들 교체 빈칸 | **`.next → checksum → os.replace` + publish 알림 + web-api 명시 핸들 교체** |
| 핫딜 점수 | 60/20/10/10 하드코딩 | skew·표본·지역 취약 | robust 산식 + profile + chips | score_confidence·profile_version 동반 요구 | **§2-4 robust + label 전역 5단계 + confidence + profile_version chip** |
| 도매 anchor 소스 | 테이블만, 소스 비어 | 다중화 + freshness + confidence | freshness_decay + 운영자 조정 | half-life 카테고리별 + lineage + parser/소스중단 구분 | **§2-5 + `source_class` + `source_lineage_group` + `category_freshness_policy` + `failure_kind`** |
| escalation 동시성 | 5테이블 트랜잭션(자수) | claim/version 박살 | optimistic version + 5테이블 트랜잭션 | (대체로 수용) | **§2-8 그대로** |
| 매칭 토큰 API | 2단계 | P0 격상 요구 | P0 + match_candidate_log | 타임아웃 백오프 + idempotency + 호출량 | **§3-4 + 800ms 타임아웃 + 백그라운드 재시도** |
| 카테고리 set_version | "트랜잭션 한 방" | mapping table 필요 | category_remap + admin override | 강제 활성 후 미분류 큐 자동 생성 | **§2-1 + 미분류 자동 큐** |
| DnD | P0로 박음 | depth 제한 권고 | 전체 depth + preview + undo | DnD/검색 둘 다 1급 + 최신 tree_version 재계산 | **§4-1 양쪽 1급 + 적용 직전 재계산** |
| Rollback UX | 백업 코드 있음 | 6단계 절차 강제 권고 | 한 클릭 + 자동 6단계 거부 | idempotent restore_job + 임시파일 정리 + snapshot 쌍 | **§4-3 한 클릭 + restore_job_id + DB·snapshot 쌍 롤백** |
| brand_alias | brand_alias 단순 도입 | 자동 학습 오염 위험 | suggested 상태 게이트 | 정렬·DB/AI 경계 명시 | **§2-6 + blacklist + 영향수 정렬 + AI 경계 §5-4** |
| 조건부 가격 | 없음 | effective_price_type 신설 | 컬럼군 풀세트 | (수용) | **§2-3 풀세트** |
| 단종/폐점 | 미언급 | availability 신설 요구 | availability_status 풀세트 | (수용) | **§2-6** |
| region/store_scope | 미언급 | 컬럼 자리 P0/P1 | P1 자리 | (수용) | **§2-3 자리 P0, 적재 P1** |
| 권한 표 | 자수(약함) | 서비스간 계약 요구 | 표 박음 P0 문서 | (수용) | **§5-2 P0 문서** |
| match log 정책 | 없음 | (미언급) | log 신설 | hot/archive + 마스킹 + bot_like | **§2-6 / §6-6** |
| community 신호 | 없음 | verdict 활용 권고 | dispute_flag로 confidence만 | verdict_version delta + canonical 재매칭 이관 | **§2-6 + §5 delta pull** |
| 백업/복구 | 백업 코드 있음, restore 약함 | restore 안전 절차 | 한 클릭 자동 | integrity_check + drill + 외부 복제 | **§6-1 + 월 1회 drill** |
| 개인정보/로그 TTL | 미언급 | 부분 언급 | 미언급(자수) | TTL·마스킹·session rotation 요구 | **§6-6 적재 유지 + TTL·마스킹·rotation** |
| 타임존 | 미언급 | 미언급 | 미언급 | UTC + KST + local_sale_date 요구 | **§2-3 P0 컬럼 자리** |
| 다국어 | 자수 | 미언급 | 미언급 | display_name_i18n 등 자리 | **§6-7 자리 P1+** |
| split 시점 | 미언급 | (수동 권고) | P2 풀세트 | P1로 올리되 최소판 | **P1 최소판(신규 분리+과거 격리), P2 풀세트** |
| API rate limit | 미언급 | (부분) | 미언급 | caller_id + bot_like + idempotency 요구 | **§6-5 P0** |
| 결제 conversion | 미언급 | 미언급 | 미언급 | 집계만 받기 권고 | **§9 미해결 + 원장 보유 금지 원칙** |

---

## 11. 안전 타령 배척 + 동적 대응 차단 배척 최종 선언

다음을 v5는 **명시 거부**한다(v3 선언 + v4에서 다시 끼어든 것 포함):

1. DnD depth 제한 — 거부. 전체 depth DnD + 검색 이동 동등 1급(§4-1).
2. 롤백 절차 운영자 수동 강제 — 거부. 한 클릭 + idempotent job(§4-3).
3. score 노출 금지 / chips만 / 카테고리별 임계 분기 — 거부. score + label 전역 5단계 + confidence 동시 노출(§2-4, §3).
4. snapshot 크기 고정 임계(100/300/500MB) — 거부. 대시보드 + 운영자 결정(§6-3).
5. escalation 화면 행 수 강제(25/50/100) — 거부. 운영자 설정 + 품질 지표(§4-2).
6. fingerprint immutable 강제 — 거부. fingerprint 자유 진화 + redirect 흡수(§2-2).
7. 매칭 토큰 API 약화/축소 — 거부. P0, 타임아웃 + 백그라운드 재시도(§3-4).
8. category set 활성화 unmapped 0 강제 — 거부. admin override + 미분류 자동 큐(§2-1).
9. 도매 anchor 끊김 시 기능 OFF — 거부. freshness_decay + lineage, 분위수 fallback(§2-5).
10. brand_alias 자동 학습 금지 — 거부. suggested 게이트 + DB/AI 경계(§2-6).
11. match_candidate_log 수집 축소 — 거부. 적재 유지, TTL·마스킹·bot_like 표식으로(§6-6).
12. score 초기 N개월 고정 — 거부. 매일 갱신, 운영자 가중치 조정 자유.
13. 분리 트리거 숫자 사전 박기(p95 200ms 등) — 거부. 운영하며 결정(§9).
14. snapshot 분리 결정의 운영자 권한 약화 — 거부.
15. category 활성화 admin override 어렵게 만들기 — 거부. 한 클릭 유지.

**핵심 정체성**: 운영자 권한·사용자 가독성·동적 대응 가능성을 깎지 않는다. 위험은 **가시화·감점·rollback·idempotency**로 처리한다. 금지·축소·규격 박기로 처리하지 않는다.

---

## 12. 자기검증

### 12-1. v4가 깐 약점 응답 체크

| v4 약점 | v5 응답 위치 | 응답 완전성 |
|---|---|---|
| stable_id 마이그레이션 dry-run 카운트 | §S-3 Q1, §8 P0#1 | ✅ 카운트 5개 명시 |
| pricing_profile 가중치 자의성 | §S-3 Q3, §2-4 | ✅ 시드 근거 3개 + change_log + label 전역 고정 |
| community pull 주기·canonical 재매칭 이관 | §S-3 Q4, §2-6, §5 | ✅ verdict_version delta + delta 이벤트 |
| split P2 비용 | §S-2.5, §8 P1#10 | ✅ P1 최소판으로 격상 |
| match log 폭증·개인정보 | §2-6, §6-6 | ✅ hot/archive·마스킹·rotation·bot_like |
| redirect chain 결정성 | §2-2 | ✅ chain 깊이 8, cycle 금지, resolver 의무 |
| robust 산식 가정의 자의성 | §2-4, §S-3 Q3 | ✅ 시드 근거 + change_log + score_confidence |
| freshness 단일성 | §2-5 | ✅ category_freshness_policy + lineage + failure_kind |
| category_remap 영향 범위 | §2-1 | ✅ keyword/autocomplete/agg/feed/dashboard 재계산 명시 |
| atomic publish의 핸들 교체 | §2-3 | ✅ publish 알림 + web-api 명시 핸들 교체 |
| AuditLog 대량 reverse | §4-1, §6-2 | ✅ 트랜잭션 그룹 키 |
| rollback DB·snapshot 쌍 | §4-3 | ✅ 한 쌍 롤백 |
| community count 수정/삭제 반영 | §2-6 | ✅ verdict_version + delta |
| pricing_profile 변경 설명 가능성 | §2-4 | ✅ profile_version chip + change_log |
| 결제/구매 추적 자리 | §9 | ✅ 집계만 수용, 원장 보유 금지 |
| GDPR/개인정보 운영 | §6-6 | ✅ TTL·마스킹·session rotation·export 키 |
| 디스크 손상/restore drill | §6-1 | ✅ 월 1회 drill + integrity_check |
| 다국어/타임존 | §6-7, §2-3 | ✅ UTC/KST/i18n 자리 |
| API rate limit/봇 | §6-5 | ✅ caller_id/idempotency/bot_like |
| anchor source class | §2-5 | ✅ source_class 5종 |
| AI 경계 | §5-4 | ✅ 소유 구분 표 |
| 게시판 결합 실체 명시 | §5-3, §S-3 Q4 | ✅ 6개 계약 |

### 12-2. 사용자 헌법 위반 점검

| 헌법 | v5 위반 여부 |
|---|---|
| **복잡하지 않게** | 모델 추가는 많지만 운영자 한 화면 클릭 흐름 유지(DnD 한 번·롤백 한 번·resolve 한 번). 사용자 화면도 score+label+chips로 한 줄 답. ✅ |
| **유연한 동적 대응** | 임계 사전 박기 거부, set_version 플러그인, profile 가중치 운영자 조정, brand_alias suggested 게이트, source 어댑터 플러그인. ✅ |
| **모듈화** | API 경계 §5-1, 권한 표 §5-2, 게시판 약결합 §5-3, AI 경계 §5-4. ✅ |
| **플러그인** | category_set_version, anchor source class, normalization_rule, scoring_profile 모두 플러그인 패턴. ✅ |

### 12-3. 다른 영역 충돌 점검

- **crawler**: ingest API 2개와 `failure_kind` 구분, 도매 자동 수급 어댑터 P1. crawler 영역 기획과 충돌 없음(쓰기 권한·파서 소유는 crawler).
- **ai-admin**: candidate generator·model_version·feature extraction 소유는 AI. DB는 evidence schema 공유와 alias 승인 결과만 보유. 학습용 archive export 인터페이스만 추가 필요.
- **web-api**: `Post.canonical_id` 의미가 stable_id로 마이그레이션. snapshot 핸들 교체 계약 강화. 매칭 API 타임아웃 백오프 경로 추가. community delta pull 노출 의무. 모두 v5의 6개 계약(§S-3 Q4) 안에서 정리.
- **web-frontend**: 변경 없음(공개 API 응답 모양만 약간 풍부해짐 — score_confidence, profile_version 등 추가 필드).

코드 변경 권고는 v5에서 일체 하지 않았다. 데이터 모델·API·운영 흐름 계약만 박았다.

---

_v5 끝. v1~v4의 모든 결정을 통합했고, v4의 5개 결단 질문에 직답했으며, 안전 타령으로 끼어든 7항목을 명시 배척했다. 라이브 가동 후 데이터가 흐르는 모양을 보면서 §9 미해결 항목만 다시 결단하면 된다._
