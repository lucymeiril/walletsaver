# 라운드 V 최종 보고 (비전공자용)

D-2 발표를 앞두고 라운드 V에서 사용자가 새로 지적한 9가지 분노를 처리했습니다.
아래는 “무엇을 어떻게 고쳤고, 어디까지 검증됐는지” 입니다.

---

## 0. 한눈에

| # | 분노 | 처리 위치 | 상태 |
|---|---|---|---|
| 1 | 롯데마트 27,198건 중복·413 폭주 | v-mart-scope | ✅ |
| 2 | DB lock (bulk-approve 500) | v-db-stability | ✅ |
| 3 | 413 Content Too Large | v-db-stability + v-mart-scope | ✅ |
| 4 | 식품 외 카테고리 시간 낭비 | v-mart-scope | ✅ |
| 5 | 코스트코 JSON parse fail | v-mart-scope | ✅ |
| 6 | 매칭 테이블(상품명 기반 자동분류) 부재 | v-matching-ui | ✅ |
| 7 | 단위 환산가(unit_price_display) 누락 의심 | v-matching-ui | ✅ |
| 8 | 웹 진짜 5/24 이전 시점 롤백 | v-rollback-v2 | ✅ |
| 9 | 크롤러·DB-admin 갑자기 안 됨 | 메인 (start-all.ps1) | ✅ |

---

## 1. 슬롯별 작업 요약

### v-rollback-v2 (웹 진짜 롤백)
- `packages/web-frontend`를 **`abf6ff8` (5/17, 라운드 F4 직후)** 시점으로 강제 롤백.
- `eca2c9c` (5/25)는 사용자 컷오프 안에 포함돼 부적격.
- NavBar 5탭(동네물가/마트비교/카테고리/주유소/게시판) + `/fuels` 라우트 복원.
- `npm install` + `npm run build` 통과.
- backend/admin 코드는 건드리지 않음.

### v-mart-scope (마트 범위 축소 + 롯데 중복 제거)
- 4사 크롤러를 **식품/생필품 화이트리스트**로 제한.  
  → 의류/가전/가구/뷰티/스포츠/도서 카테고리 제외.
- 롯데마트: cursor 종료 조건 + dedup + **5,000건 unique cap**.
- 코스트코: 비식품 카테고리 차단 + browser JSON parse 실패 시 즉시 중단(과잉 탐색 X).
- 크롤러→ingestion 전송을 **500건 chunk POST**로 분할 (DLQ도 chunk 단위 기록).
- 4사 live food probe 200 확인.
- 회귀 테스트 67 passed.

### v-db-stability (DB 락 + 413)
- SQLite **WAL 모드 + busy_timeout 30s + pool_pre_ping** 적용.
- 기존 DB에도 PRAGMA 강제 — 확인: `('wal',) (30000,) (1,)`.
- `/api/ingestions` 서버 측에서 1,000건 chunk 저장.
- `/api/ingestions/bulk-approve` 100건 단위 commit + lock retry.
- 요청 본문 한도 100MB로 상향.
- 1,000건 ingestion·bulk-approve smoke + 동시 writer lock 시뮬레이션 통과.
- `test_db_engine / test_error_handling`: 18 passed.
- `test_ingestion_insert`: 20 passed.

### v-matching-ui (진짜 매칭 테이블 + 단위 환산가)
- 신규 테이블 **`product_match_rules`** (pattern_type, pattern_value, canonical_category_id, canonical_product_id, trust, hit_count, last_used_at).
- Alembic 마이그레이션 `v4m_product_match_rules`.
- ingestion 흐름에 **상품명 기반 자동분류 + hit_count 카운트** 연결.
- `unit_price_display` 필드를 DTO/ingestion raw/Product.attributes/admin 상품 화면에 모두 보존.
- DB-admin `/matching` 라우트 + 메뉴 + UI (`MatchingRulesPage.jsx`) 추가.
- 신규 API:
  - `GET /api/matching-rules` (목록·검색)
  - `GET /api/matching-rules/stats` (총합·type별·trust별)
  - `POST /api/matching-rules`, `PATCH`, `DELETE` (역할별 권한).
- 신규 backend tests 23 passed + frontend build OK.

### 메인 (라운드 V 환경 복구)
- `start-all.ps1`에 누락돼 있던 환경변수를 **자동 기본값**으로 추가:
  - `WALLETSAVIOR_PUBLIC_DB` → `walletguardian.db`
  - `REQUIRE_AUTH=false`
  - `DATABASE_URL=sqlite:///…/walletguardian.db`
  - 라운드 U mock-purge 이후 web-api/db-admin 부팅이 깨졌던 진짜 원인.
- 손상된 `walletguardian.db`(다시 malformed) 격리 → alembic head 까지 재마이그레이션 → unified seed 재투입(46 카테고리 + 113 매핑).

---

## 2. 통합 검증 결과

DB:
```
PRAGMA integrity_check      → ok
PRAGMA journal_mode         → wal
unified_categories          → 46
mart_category_mappings      → 113
product_match_rules         → 0  (정상, 사용 시 누적)
products / pending_ingestions → 0
```

3 백엔드 import / TestClient:
| 경로 | 응답 |
|---|---|
| web-api `create_app` | ✅ |
| db-admin `create_app` | ✅ |
| crawler-admin `create_app` | ✅ |
| `GET /api/categories/` | 200 |
| `GET /api/products/stats` | 200 |
| `GET /api/keywords/` | 200 |
| `GET /api/ingestions` | 200 |
| `GET /api/matching-rules` | 200 |
| `GET /api/matching-rules/stats` | 200 |

프론트엔드 빌드(각 fleet 보고서 기준):
- web-frontend `abf6ff8` → ✅
- db-admin frontend(`/matching` 포함) → ✅
- crawler-admin frontend → 변경 없음(라운드 U 그대로)

---

## 3. 사용자 시연 절차 (sandbox에 브라우저 없음 → 사용자 측 확인 필요)

1. `start_all.bat` 실행 → 8001/8002/8003/8010 + 5173/5174/5175 떠야 함.
2. **크롤러 admin (5174)**: 4사 크롤 버튼 → "found / valid / saved" 0/0/0/0 아니어야 함. 식품 카테고리만 들어오는지 카테고리 컬럼으로 확인.
3. **DB admin (5175)**:
   - `/matching` 새 메뉴 클릭 → 룰 목록·통계 화면.
   - 상품 상세에 단위 환산가(`100g당 …원`) 표시 여부.
   - 카테고리 트리 클릭 시 4사가 같은 카테고리에 묶이는지.
4. **웹 (5173)**: NavBar 5탭(동네물가/마트비교/카테고리/주유소/게시판) 정상, 디자인 5/17 시점.

---

## 4. 라운드 V에 의식적으로 *손대지 않은* 잔재

- emart `EmartEntrypoints._category_url` 부재 (라운드 T 잔재, 3 test 실패).
- `/api/health-dashboard/matching-monitor` 라우트 미등록 (라운드 U 이전 잔재).
- ai-admin은 사용자 지시대로 무시(보류).
- AI 카테고리/키워드 export → 외부 분류 → import 사이클은 라운드 W 이후로 미룸.

---

## 5. 알려진 리스크

- DB가 라운드 중에 또 `database disk image is malformed`가 발생함(원인 미상, 라운드 U/V에서 두 번째). WAL 적용 후에는 재현 없음.  
  → 만약 다시 발생하면: `walletguardian.db*` 격리 → alembic upgrade head → `scripts/seed_unified_categories.py`.
- 실제 4사 라이브 크롤은 sandbox에서 길게 돌릴 수 없어 **smoke probe 200**까지만 확인. 끝까지 적재되는지는 사용자 시연에서 검증해야 함.
- 크롤러 실행 시 “요청을 처리할 수 없다”가 또 나오면, 가장 먼저 `start-all.ps1` 환경변수가 새 default를 받는지(터미널 재시작) 확인할 것.
