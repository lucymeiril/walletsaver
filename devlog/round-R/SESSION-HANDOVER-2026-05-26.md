# WalletSavior Round R — 세션 종료 인계서 (2026-05-26 21:32 KST)

> 본 문서는 컨텍스트 한도 직전 작성. 다음 세션은 이 문서를 단일 진실로 사용해 이어가면 됨.
> 한국어 비전공자 톤. 코드/명령은 그대로.

---

## 0. 한 줄 요약

이틀 데드라인 Round R 대수술 — 4사 크롤러 + 카테고리 통합 + 자동분류 + 외부 AI 사이클 + 핫딜/오피넷/커뮤니티 리팩 — **에이전트 작업 16개 중 15개 완료**(g3-export 진행 중). MCP Playwright 기반 사용자 시나리오 E2E(g3-e2e, g4-e2e)와 비전공자용 최종 보고서(meta-final)만 남음. **메인 슬롯에서 직접 해야 하는 일이라 다음 세션이 이어받아야 함**.

---

## 1. 메타룰 (라운드 규약, 다음 세션도 동일 적용)

- **M1 공동기획자 모드** — 사용자 의도 해석 + 다음 라운드 동선 같이 짠다.
- **M2 횡단 즉시 처리** — 옆 패키지/타 게이트 문제 발견 시 즉시 수정 또는 `devlog/round-R/cross-cut/`에 기록.
- **M3 자동 연속** — 사람 승인 없이 게이트 자동 진행.
- **M4 4슬롯 유동** — background agent 4개 한도. idle 슬롯 금지(불가피한 의존성 대기는 예외).
- **M5 4종 증거** — diff + DB 덤프 + 3축 캡쳐 + 재현 명령.
- **M6 UX 회귀 체크** — 진행률 0초 멈춤 = fail.
- **M7 handover compaction 대비** — 매 게이트 진입/종료 시 인계서 갱신. (← 본 문서가 그 결과)
- **M8 비전공자 최종 보고서는 메인이 직접 작성** — 사용자 메모리에 박힌 원칙. 에이전트에 위임 금지.

---

## 2. 완료된 게이트 (G0 ~ G5 대부분)

### G0 정찰 + 스키마 (메인 Playwright MCP 직접 수행)
- `devlog/round-R/G0-emart.md`, `G0-homeplus.md`, `G0-lottemart.md`, `G0-costco.md`
- `devlog/round-R/G0-schema.md` — Product 신컬럼·PriceHistory·canon_hash 공식·4사 식별자 표.

**4사 영구 식별자**:
| 마트 | mart_native_code | 실 URL |
|---|---|---|
| emart | itemId 13자리 | `/item/itemView.ssg?itemId=&siteNo=7009&salestrNo=` |
| homeplus | itemNo 9자리 | `/item?itemNo=&storeType=HYPER\|EXP` |
| lottemart | EAN-13 | `/products/OS<EAN-13>/details` |
| costco | `/p/<digits>` | `/<Path>/<Slug>/p/<digits>` |

### G1 — 4사 크롤러 재작성 + 공용 헬퍼 + DB 신컬럼 + 프론트
- `packages/crawler-admin/backend/crawlers/marts/source_utils.py` — URL 정규화 4종, `parse_unit_price`, `compute_canon_hash`, `classify_external_seller_*`, `inject_source_field`.
- `packages/db-admin/backend/storage/models.py` — Product 신컬럼: mart / mart_native_code / canon_hash / external_seller / unit_price_displayed / unit_price_basis_raw / mart_native_category_id / mart_native_category_path / canonical_url / mart_internal_seller_id. PriceHistory 신설.
- alembic `b2c3d4e5f6a7` (G1 head).
- 4사 crawler.py 전면 재작성. 이마트 `cdtl_ico_item` 외부셀러 분류, 홈플 `HYPER_DRCT` + 동적 스크롤 + 노출 링크 정규화, 롯데 `OS<EAN-13>` 실 URL(UUID 버그 잡음 — `_entity_to_discount_item()`), 코스트코 `/p/<digits>`.
- 3 프론트(crawler-admin/db-admin/web-frontend) 신컬럼 그리드 + 카테고리 트리 뷰어 + 단위환산가 카드. 물가비교 진입 시 잎새 상품 노출 버그 1차 수정.
- 4사 fixture 시드 16건 (라이브 HTTP는 anti-bot 차단 → fixture fallback).

### G2 — 카테고리 통합 + 매핑 + 웹 재배선
- `packages/db-admin/backend/scripts/g2_category_aggregator.py` + `devlog/round-R/g2-unified-tree.yaml` (66 노드, lottemart 권위, 58 review).
- `packages/db-admin/backend/storage/models.py`에 `UnifiedCategory`, `MartCategoryMapping` 추가. Product에 `unified_category_id` FK.
- alembic `c3d4e5f6a7b8` (G2 head).
- 시드 스크립트 `g2_seed_unified_tree.py`, API `routes/categories.py`, 프론트 `UnifiedCategories/*`.
- **g2-web 작업 진행 중**(아래 §4 참조) — 물가비교 탭 web-api/web-frontend 재배선.

### G3 — 자동분류 파이프라인
- `packages/db-admin/backend/services/auto_classify.py` — mart_native_code upsert → canon_hash 묶음 → mart_category_mappings → unified_category_id 적용 → PriceHistory 주간 누적.
- alembic `c4d5e6f7a8b9` (PriceHistory week_of UNIQUE).
- CLI `scripts/g3_auto_classify_run.py`, API `POST /api/admin/auto-classify/run`.
- Trust hierarchy: human=2 > external-ai=1 > auto-aggregate=0 (matching_sync 패턴 재활용). Product 분류 trust는 전용 컬럼 없어 `categorization_method`로 human 보존 판단.
- 6 passed.
- **g3-export 작업 진행 중**(아래 §4) — 미분류 격리 + 이름 변형/할인 마커 정규화.

### G4 — 외부 AI 사이클
- 지침: `packages/ai-admin/backend/prompts/external_classify_instructions_v1.md`
- I/O 스펙: `devlog/round-R/G4-io-spec.md`
- Export: `packages/db-admin/backend/services/external_ai_export.py` — 미분류 jsonl + category_list.yaml + keyword_list.yaml + instructions.md 번들.
- Import: `external_ai_import.py` — matching_updates.jsonl, category_keyword_updates.yaml, product_updates.jsonl 트랜잭션 처리, trust 위계 적용, 부분 실패 롤백.
- API `routes/external_ai.py`, 프론트 `ExternalAIPage`.
- 한계: `keywords.category_id`가 legacy FK라 unified id 연결은 legacy category 존재 시만. Export API는 zip이 아닌 서버 로컬 번들 경로 반환.
- 6 passed.

### G5 — 핫딜 + 오피넷 + 커뮤니티
- **G5-a 커뮤니티**: `packages/web-api/auth.py` Google OAuth 복구, board/comment 라우트, `LoginPage`/`NewPostPage`/`PostDetailPage`/신규 `EditPostPage`, App.tsx 라우터. 핫딜 공유는 기존 Post 확장. backend 23 + frontend 6 passed, build OK.
- **G5-b 핫딜**: `storage/models.py` HotdealPost / HotdealCommentSnapshot 분리. `crawlers/hotdeals/algumon/crawler.py` + plugin.yaml + entrypoints + fixture. alembic `g5b0hotdeal`. 5 passed. **라이브 algumon 정찰은 메인 Playwright MCP 후속**.
- **G5-c 오피넷**: `storage/opinet_models.py` GasStation / GasStationPrice. `crawlers/opinet/crawler.py` + fixture. 프론트 `pages/FuelStationsPage.tsx` + NavBar. alembic `r_g5c_opinet`. 23 백 + 17 프론트 + 빌드 OK. **라이브 오피넷 정찰은 후속**.

### Alembic 체인 (단일 head)
`306077c6d0e2 → b2c3d4e5f6a7 (G1) → c3d4e5f6a7b8 (G2) → c4d5e6f7a8b9 (G3) → g5b0hotdeal (G5b) → r_g5c_opinet (G5c, head)`

reconcile 작업: g5b/g5c가 `down_revision=None`으로 둔 placeholder를 메인이 직접 chain 연결함. `py -3 -m alembic heads` → `r_g5c_opinet (head)` 단일 확인.

### 코코달린 시드
- `cocodalin_seed_importer.py` + CLI. 3 passed. 코스트코 가격 히스토리 dry-run/dedup.

---

## 3. 떠 있던 background agent 상태 (2026-05-26 21:35 KST 갱신)

| agent_id | 작업 | 상태 | 결과 |
|---|---|---|---|
| `g2-web` | G2-3 웹 물가비교 탭 재배선 | ✅ 완료 (1292s) | web-api 102 passed / frontend 88 passed / build OK. report=`devlog/round-R/g2-web-report.md` |
| `round-r-regression-sweep` | 전 라운드 회귀 스윕 | ✅ 완료 (184s) | report=`devlog/round-R/round-r-regression-sweep.md`. **회귀 3건 발견(§5-A 참조)** |
| `g3-export` | G3-2 미분류 export + 이름 변형 정규화 | 🔄 진행 중 (세션 종료시 죽을 수 있음) | 결과 파일 없으면 §8 부록 B로 재발진 |

g2-web 완료로 G2 게이트 전부 종료. 남은 background 미완료는 g3-export 1건.

다음 세션 첫 액션:
```sql
SELECT id, status FROM todos WHERE id IN ('g2-web','g3-export');
```
+ `Get-ChildItem E:\pdf\capston01\devlog\round-R\g2-web-report.md, g3-export-report.md, round-r-regression-sweep.md`

---

## 4. 남은 작업 (다음 세션이 이어받을 것)

### 4-1. g2-web 검증/재발진 (필요 시)
세션 죽었을 가능성 큰 1순위. 재발진 프롬프트는 본 문서 끝 §8 부록 A.

### 4-2. g3-export 검증/재발진 (필요 시)
재발진 프롬프트는 §8 부록 B.

### 4-3. g3-e2e — **메인 슬롯 Playwright MCP 필수**
사용자 시나리오 그대로:
1. db-admin/web-frontend/crawler-admin dev server 3개 detach 기동 (포트 충돌 주의).
2. crawler-admin 프론트에서 "DB wipe" 버튼 누름 → 캡쳐.
3. 4사 크롤 트리거 → 캡쳐.
4. 자동분류 트리거(`POST /api/admin/auto-classify/run`) → DB 덤프 + 캡쳐.
5. web-frontend 물가비교 탭 진입 → 최상위 카테고리만 나오는지 확인 → 드릴다운 잎새까지 → 4사 묶음 카드 확인 → 모달 → 가격 히스토리.
6. 스크린샷 3축(크롤 결과, DB 덤프 화면, 웹 렌더링) 저장 → `devlog/round-R/captures/G3-*.png`.
7. `devlog/round-R/g3-e2e-report.md` 작성.

**검증 포인트 (기능상 무용 여부)**:
- 같은 canon_hash 4사 묶음 1건 이상.
- 단위환산가가 카드에 표시.
- 진입 즉시 leaf 상품 미노출 (회귀 가드).
- 이전 주 PriceHistory가 있다면 가격 히스토리 노출.

### 4-4. g4-e2e — **메인 슬롯 Playwright MCP + 서브에이전트 협업**
1. crawler-admin/db-admin/web-frontend 가동 상태에서 db-admin "외부 AI 사이클" 페이지 진입.
2. Export 트리거 → 번들 경로 확인 → 매니페스트 검사.
3. 서브에이전트(haiku 또는 gpt-4.1)에게 **실제 시나리오 그대로 작업 시킴**:
   - 지침/카테고리 목록/키워드 목록/미분류 jsonl 전달.
   - 3종 파일 산출하라 지시.
4. Import → 결과 리포트 캡쳐.
5. DB 덤프해서 trust=external-ai 매핑이 들어갔는지 검증.
6. 다시 크롤 → 자동분류 → 웹에서 새로 분류된 상품 노출 확인.
7. `devlog/round-R/g4-e2e-report.md` + 캡쳐.

**중요**: 서브에이전트가 "분류 완료" 보고해도 무조건 신뢰하지 말 것. 산출 파일 실제로 import 통과하는지 검증.

### 4-5. meta-final — **메인이 직접 작성 (M8)**
- 위치 후보: `devlog/round-R/FINAL-REPORT-비전공자.md`
- 톤: 한국어, 비전공자가 읽어도 이해 가능한 평어체.
- 포함:
  - 무엇이 깨져 있었는가 (4사 가짜 스키마, UUID 죽은 URL, 이마트 외부셀러 오염, 동적 스크롤 누락 등).
  - 어떻게 고쳤는가 (영구 식별자 + canon_hash + 통합 카테고리 + trust hierarchy + 주간 누적 + 외부 AI 사이클).
  - 무엇이 아직 안 됐는가 (4사 라이브 시드 차단, algumon/opinet 라이브 정찰 미수, E2E 캡쳐 미수).
  - 다음 라운드 권장 (S→데이터/카테고리 보강, M→AI 사이클 자동화, L→웹 UI/UX 다듬기).

### 4-6. 라이브 데이터 시드 (사용자 환경에서)
- 본 세션 환경은 4사 라이브 HTTP 차단(403/timeout). 사용자가 본인 PC에서:
  ```
  cd packages\crawler-admin\backend
  py -3 scripts\round_r_g1_seed.py --live --marts emart,homeplus,lottemart,costco
  ```
- 그 후 자동분류 실행 → 진짜 데이터로 G3/G4 E2E 재시연.

---

## 5-A. 회귀 스윕에서 발견된 신규 회귀 (다음 세션 우선순위 1)

`devlog/round-R/round-r-regression-sweep.md` 참조.

**DB-Admin backend (2건, Round R 회귀)**:
- `test_auto_classify.py::test_same_canon_hash_groups_four_marts` — UNIQUE(brand, name_core, pack_qty, pack_unit) 위반.
- `test_unmatched_isolation.py::test_export_manifest_separates_unmatched_cases` — 동일 UNIQUE 위반.
- 추정 원인: 테스트 픽스처 간 isolation 미흡 또는 canon_hash 같으면 자연스러운 충돌인데 테이블 제약이 그걸 금지.
- **수정 방향**: (a) 테스트별 DB rollback/fixture 분리 강화 또는 (b) UNIQUE 제약을 `(mart, brand, name_core, pack_qty, pack_unit)`로 완화. canon_hash가 같으면 4사 묶음 인식이 정상 시나리오이므로 (b)가 맞을 가능성 높음. G3 작업의 의도와 직접 충돌.

**Shared (1건, Round R 회귀 가능)**:
- `test_ai_pipeline_contracts.py::test_ai_job_batch_rejects_prompt_text_over_2000_chars_without_splitting_records` — `ValidationError` 미발생.
- 추정 원인: pydantic v2 마이그레이션 또는 G4-prompt 작업 중 contract 변형. 검증 로직 점검 필요.

**Crawler-admin**: 121 passed, 3 skipped (pre-existing skip만, 회귀 0).
**3개 프론트 빌드**: 모두 성공 (crawler-admin 청크 사이즈 경고만).

**조치**: 다음 세션 첫 30분에 DB-Admin 2건 + Shared 1건 수정. UNIQUE 제약 완화 마이그레이션이 필요할 가능성 → alembic head 변경 시 본 인계서 §2 chain 갱신.

---

## 5. 알려진 한계 / 리스크

1. **4사 라이브 차단**: 본 세션 시드는 fixture 16건뿐. G2 통합 트리도 lottemart fixture 카테고리(320개)에 편향. 라이브 시드 후 g2-aggregate 재실행 권장.
2. **에이전트 자기보고 불신뢰**: g1-a3가 "done" 보고했지만 `_entity_to_discount_item()` 미수정 16건 회귀가 회귀점검에서 적발됨. 항상 별도 검증 단계 필요.
3. **algumon/opinet 라이브 정찰 미수**: 둘 다 fixture placeholder. 메인 Playwright MCP가 실제 마크업 정찰 후 fixture 교체 필요.
4. **keywords.category_id legacy FK**: G4 import에서 unified category로 잇는 부분이 legacy category 존재 시만 동작. 다음 라운드에 정리.
5. **External AI Export API zip 미지원**: 서버 로컬 번들 경로 반환. 다운로드 zip 패키징 후속 작업.
6. **Pre-existing 실패** (Round R 범위 외, 손대지 마라):
   - db-admin: `test_canonical_seed.py`, `test_category_pollution_guard.py`, `test_ingestion_insert.py`
   - crawler-admin: `test_source_coverage.py`, `test_quality_diagnostics.py`, `test_workbench_routes.py`
7. **g3-export 의존**: g3-export가 만들 `test_unmatched_isolation.py`가 없으면 회귀 스윕에서 skip 처리됨. 죽은 경우 §8 부록 B로 재발진.

---

## 6. 핵심 파일 빠른 참조

| 카테고리 | 경로 |
|---|---|
| Round R 마스터 인계서 (본 문서) | `devlog/round-R/SESSION-HANDOVER-2026-05-26.md` |
| 스키마 단일 진실 | `devlog/round-R/G0-schema.md` |
| 통합 카테고리 트리 | `devlog/round-R/g2-unified-tree.yaml` |
| AI 사이클 I/O 스펙 | `devlog/round-R/G4-io-spec.md` |
| AI 지침서 | `packages/ai-admin/backend/prompts/external_classify_instructions_v1.md` |
| 공용 크롤러 헬퍼 | `packages/crawler-admin/backend/crawlers/marts/source_utils.py` |
| 자동분류 서비스 | `packages/db-admin/backend/services/auto_classify.py` |
| 외부 AI export/import | `packages/db-admin/backend/services/external_ai_{export,import}.py` |
| Alembic head | `r_g5c_opinet` (versions/r_g5c_opinet.py) |
| 게이트별 리포트 | `devlog/round-R/g{1,2,3,4,5}*-report.md` |

---

## 7. 다음 세션 첫 30분 권장 액션

1. **5분**: 본 문서 + plan.md 읽기.
2. **5분**: 떠 있던 3개 agent 결과 파일 존재 여부 확인. 없으면 부록 A/B로 재발진.
3. **5분**: `alembic heads` 확인 → `r_g5c_opinet` 단일 head이면 OK.
4. **15분**: round-r-regression-sweep 결과 확인 (또는 직접 실행 — §8 부록 C).
5. 이후 메인 슬롯에서 g3-e2e → g4-e2e → meta-final 순차 진행.

---

## 8. 부록 — 재발진 프롬프트 (복사해서 task tool에 붙여 넣기)

### 부록 A. g2-web 재발진
```
WalletSavior Round R G2-3. 한국어. 
필독: devlog/round-R/g2-mapping-report.md, g2-unified-tree.yaml, G0-schema.md.
현재 버그: 물가비교 진입 시 leaf 상품(예: "제스프리 골드키위 5.7kg") 즉시 노출 + 코스트코만 1건. 
목표: web-api 라우트(/api/web/categories/tree, /api/web/categories/{slug}, /api/web/products/compare?canon_hash=) 신설/정비 + web-frontend 물가비교 탭 재배선 = 진입시 최상위만, 드릴다운 → leaf 도달시 canon_hash로 4사 묶음 카드 + 단위환산가 + 모달.
테스트: tree/leaf 분기, 4사 묶음, 회귀 가드(진입시 leaf 미노출), `npm run build`.
devlog: devlog/round-R/g2-web-report.md.
SQL: UPDATE todos SET status='done' WHERE id='g2-web' (끝나면).
```

### 부록 B. g3-export 재발진
```
WalletSavior Round R G3-2. 한국어.
필독: devlog/round-R/g3-matching-table-report.md, G4-io-spec.md, services/external_ai_export.py.
시나리오: 다음 주에 신상품/[행사][1+1]/태그변경/카테고리변경/가격이상치 케이스를 격리·export.
신설: services/unmatched_isolation.py — 케이스 A(새 native_code) B(이름 변형, canon_hash 안정성) C(native_category 미매핑) D(가격 50% 이상치).
정규화 헬퍼: source_utils.py에 [행사][1+1](NEW){신상} 마커 제거 → name_core 산출.
external_ai_export 확장: 케이스별 jsonl 분리 + 매니페스트.
CLI: g3_export_unmatched.py. API: POST /api/admin/unmatched/export.
테스트: tests/test_unmatched_isolation.py 4 케이스 + 회귀.
devlog: g3-export-report.md.
SQL: UPDATE todos SET status='done' WHERE id='g3-export'.
```

### 부록 C. 회귀 스윕 직접 실행
```powershell
cd E:\pdf\capston01\packages\db-admin\backend; py -3 -m alembic heads
cd E:\pdf\capston01\packages\db-admin\backend; py -3 -m pytest tests\test_g2_category_aggregator.py tests\test_g2_unified_category.py tests\test_auto_classify.py tests\test_external_ai_export.py tests\test_external_ai_import.py tests\test_external_ai_import_e2e.py -q
cd E:\pdf\capston01\packages\crawler-admin\backend; py -3 -m pytest tests\test_emart_crawler_g1.py tests\test_homeplus_crawler_g1.py tests\test_lottemart_crawler_g1.py tests\test_costco_crawler_g1.py tests\test_source_utils_g1.py tests\test_algumon_crawler.py tests\test_opinet_crawler.py tests\test_mart_crawlers.py -q
cd E:\pdf\capston01\packages\shared; py -3 -m pytest -q
cd E:\pdf\capston01\packages\db-admin\frontend; npm run build
cd E:\pdf\capston01\packages\crawler-admin\frontend; npm run build
cd E:\pdf\capston01\packages\web-frontend; npm run build
```

---

## 9. SQL todos 스냅샷 (2026-05-26 21:32 KST)

```
in_progress: meta-crosscut, meta-evidence, meta-handover, meta-slot
pending:     g3-e2e, g3-export, g4-e2e, meta-final
blocked:     g1-crawler, g2-category, g3-autoclass, g4-ai-cycle, g5-refactor  (분해된 부모, 자식 done이면 무시)
done (19):   cocodalin-seed, g0-recon, g0-schema, g1-a1~a4, g1-base, g1-frontend, g1-seed, g2-aggregate, g2-mapping, g2-web*, g3-matching-table, g4-import, g4-prompt, g5a-community, g5b-hotdeals, g5c-opinet
```
*g2-web은 background agent가 SQL UPDATE 미리 친 정황. 결과 파일(`g2-web-report.md`) 존재 여부로 실 완료 판단.

---

끝. 사용자 발언: "보고는 에이전트 돌리지 말고 니가 직접 작성하고." 본 문서는 메인 슬롯이 직접 작성함.

## 10. 세션 종료 시점 (2026-05-26 21:35 KST)

- 종료 시 떠 있던 background: g3-export 1건. detach=false라 죽을 수 있음.
- 본 문서 작성 후 메인 슬롯 stop.
- 다음 세션은 §7 30분 권장 액션부터 시작.


## 11. g3-export 사후 완료 (2026-05-26 21:38 KST)

세션 종료 직전 g3-export agent가 완료됨. 결과:
- 추가/수정: `services/unmatched_isolation.py`, `services/name_normalize.py`, `services/external_ai_export.py` 확장, `crawlers/marts/source_utils.py` 정규화 추가, CLI `scripts/g3_export_unmatched.py`, API `POST /api/admin/unmatched/export`.
- 케이스 A~D 분리 jsonl + manifest counts/recommendations 반영.
- 테스트 `tests/test_unmatched_isolation.py` 12 passed.
- devlog `devlog/round-R/g3-export-report.md`.
- 한계: Case A는 DB price_history 기준, Case D는 가장 가까운 이전 관측 주와 비교.

**→ 본 인계서 §3, §4의 g3-export 재발진 항목은 더 이상 불필요.**
**→ 회귀 스윕에서 발견된 `test_unmatched_isolation.py` UNIQUE 위반 1건은 §5-A 그대로 유효.**
**→ Round R 작업 에이전트 16개 전부 완료. 남은 건 메인 슬롯 작업(g3-e2e, g4-e2e, meta-final) + 회귀 3건 수정뿐.**

## 12. 회귀 4건 수정 완료 (2026-05-26 23:30 KST)

세션 후반 fleet 4건 동시 발진 → 전부 완료:

| 작업 | 결과 | 핵심 |
|---|---|---|
| `fix-ai-batch-validator` | shared 623 passed | AIJobBatch prompt context limit 8000→2000 + `max is 2000` 메시지 복원 |
| `fix-unique-cross-mart` | db-admin 24 passed | UNIQUE(brand,name_core,pack_qty,pack_unit) → (mart,mart_native_code)로 교체. canon_hash는 unique=False (4사 묶음 자연 시나리오). alembic head=`c5e6f7a8b9c0` |
| `fix-name-normalize` | source_utils 16 passed | `[행사][1+1][NEW]【한정】★특가★` 등 마커 strip + fold_case. compute_canon_hash가 항상 normalize 호출 |
| `fix-legacy-fetch` | G1 21 passed | **사용자 의문에 대한 답**: 옛 코드(commit `17c8329`)는 Playwright + persistent context + Chrome UA + ko-KR/Asia/Seoul + 1920x1080 + lazy-load 스크롤 + 쿠키 캐시 다 갖춰져 있었음. G1 seed live path가 그걸 다 버리고 `requests.Session` + 정적 헤더만 써서 anti-bot 403/429 받음. `crawlers/_fetch/browser_session.py` 공용 모듈로 통합 완료. 사용자 PC headed 재실행 시 작동 예상. |

회귀 스윕 v2: **db-admin 24 / crawler-admin 125 / shared 623 / 3 frontend builds 모두 PASS. 회귀 0건.**
보고서: `devlog/round-R/round-r-regression-sweep-v2.md`, `legacy-fetch-audit.md`, `fix-legacy-fetch-report.md`.

## 13. 남은 작업 (메인 슬롯)

- **g3-e2e + g4-e2e**: 본 sandbox는 라이브 차단 → `e2e-scripts` agent 발진 중. 사용자 PC에서 `py -3 scripts/g3_e2e_user_scenario.py` 한 줄 실행으로 dev server 기동 + Playwright headed + 캡쳐 + 리포트 자동 생성하게 만드는 중.
- **meta-final**: e2e 결과 나오면 메인이 직접 비전공자 보고서 작성 (M8).
