# WalletSaver 초기 DB 분류 — 현재 상태 (CANONICAL)

> **이 파일이 현재 작업 상황과 재개점을 판단하는 단일 기준이다.**
> `PROGRESS.md`와 `checkpoints/`는 시간순 작업 로그라 서로 겹치거나 오래된 누적치가 있을 수 있다. 다음 AI는 `README.md` 다음에 이 파일을 읽고, 그 뒤 `PROGRESS.md`와 `PENDING_INDEX.md`를 참고한다.

마지막 갱신: 2026-09-12
작업 브랜치: `cleanup/remove-legacy-ai-admin-coupling`
현재 모드: **GitHub read/write, proposal_only**
DB 기준선: **pass41 — 5,280 loaded / 3,916 pending**
DB import/rebuild/test: 현재 Chat 작업에서는 실행하지 않음. 위 수치는 변경되지 않았다.

## 1. 지금 무엇을 하고 있는가

pass41 pending을 상품명/원문/세부 진열 근거로 직접 검토해 통합 taxonomy 분류 제안과 hold를 남긴다. Chat 단계에서는 `proposals/*.json`과 체크포인트만 만든다. 나중에 실행 도구가 있는 Codex 환경에서 proposal 전역 dedupe/conflict reconciliation → review decision 승격 → 새 pass DB 재구축을 한 번에 한다.

절대 규칙:
- broad 마트 shelf보다 title/product form 우선.
- `review_status=classified`인데 단위/수량/행사 때문에 pending에 남은 행은 신규 classification 작업량에서 제외.
- 반복 수집은 동일 listing 결정 하나에 모든 `raw_record_ids`를 보존.
- pass41 snapshot에 없는 leaf를 legacy 코드에 있다는 이유만으로 existing leaf로 쓰지 않음.
- `proposal_only`를 DB 반영 완료로 표현하지 않음.
- deal/promotion collection을 단일 상품으로 분류하지 않음.

## 2. 완성까지 얼마나 남았나 — 안전한 숫자

현재 strict reverse audit 상한:

- `pending 001~035`: **1,681 observations**
- pass41 전체 pending 3,916 대비 약 **42.9%**
- 관측 구간 기준 `036~451`은 약 **57.1%**에 해당하지만 이를 “57.1% 최종 완료”라고 부르면 안 된다. 과거 proposal 중 중복/re-review와 taxonomy hold가 남아 있다.
- `001~035`에도 과거 proposal이 있는 그룹(예: 028, 034)이 있으므로 실제 새 판단량은 1,681보다 작을 가능성이 높다. raw-key 전역 reconciliation 전에는 더 작은 수치를 완료치로 확정하지 않는다.

분류 sweep 뒤 DB 반영 전 남는 단계:
1. proposal 간 raw-record/source-key 중복 제거
2. first-vs-final proposal 충돌표 작성 및 결정 (이미 pending 313 `cup_ramen` vs `udon` 충돌 발견)
3. 신규 taxonomy 후보/hold 정책 결정
4. 431 explicit review decisions와 최종 충돌 검사
5. Codex에서 새 pass DB import/rebuild + 관련 검사 + 멱등성 확인

## 3. 최근 strict audit 결과

### reverse sweep 036~043 — 완료
- observations opened: **202**
- already classification-complete exclusions: **15**
- new classification-review observations: **187**
- distinct newly reviewed source listings: **175**
- confirmed existing-leaf proposals: **53 listings**
- taxonomy/product-form/promotion/manual-review holds: **122 listings**

최신 체크포인트:
- `checkpoints/checkpoint-after-pending-036.md`
- `checkpoints/checkpoint-after-pending-037.md`
- `checkpoints/checkpoint-reverse-sweep-038-043.md`

그룹별 proposal:
- 043: `proposals/lottemart-vegetables-043.json` — 23 obs / existing 21 / hold 2
- 042: `proposals/homeplus-tableware-042.json` — 24 obs / 12 listings / hold 12
- 041: `proposals/costco-fish-shelf-041.json` — 24 obs / existing 13 / hold 11
- 040: `proposals/costco-vegetable-shelf-040.json` — 25 opened / 5 pre-classified excluded / existing 8 / hold 12
- 039: `proposals/emart-sports-travel-auto-039.json` — 26 obs / hold 26
- 038: `proposals/emart-stationery-038.json` — 26 obs / hold 26
- 037: `proposals/emart-beverages-037.json` — 27 opened / 6 excluded / 21 new / existing 9 / hold 12
- 036: `proposals/emart-bakery-jam-036.json` — 27 opened / 4 excluded / 23 new / existing 2 / hold 21

### pending 036 핵심
- existing: 샌드위치용 계란샐러드 -> `food.meals.prepared.salad`; 딸기버터잼 -> `food.bakery.spreads.fruit`.
- promotion/deal surface 6건은 단일 상품이 아니므로 hold.
- sweet-bun/hotteok 후보는 과거 bakery proposal 정책 재사용.
- 만주/도넛/치아바타/choux 등은 pass41 현행 leaf에 억지로 넣지 않고 후보 hold.
- 23 source key collision screen에서 `review-decisions-input.json` hit 0.

### pending 037 핵심
- existing: fruit drink 6, non-alcoholic beer 2, bottled water 1.
- hold: baby/puree 5, opaque title 1, protein drink 3, ordinary Vita500 1, Miero Fiber 1, title-only `1.8L*2입` 1.
- 21 source key collision screen에서 `review-decisions-input.json` hit 0.

### gap repair 045 — 완료
이전 문서의 “001~451 classification sweep complete” 주장과 달리 pending 045에는 proposal이 없었다. 22 observations / 11 pizza listings를 확인해 `food.meals.prepared.pizza` proposal을 추가했다.
- `proposals/homeplus-frozen-pizza-045.json`
- `checkpoints/checkpoint-gap-repair-pending-045.md`

### 044~109 — proposal 파일 존재 여부 감사 완료
- `checkpoints/checkpoint-proposal-coverage-044-109.md`
- 045가 유일한 누락 파일이었고 보수했다.
- 단, **파일 존재 = raw observation 전량 고유 검토 완료 증명은 아니다.** 최종 reconciliation에서 raw-key coverage 재확인 필요.

### 110~451 — 비중복 ordered range 회계
- 110~150: 297 inspected / 280 classification reviews / 17 exclusions
- 151~208: 308 / 292 / 16
- 209~287: 277 / 275 / 2
- 288~451: 281 / 266 / 15
- 합계: **1,163 inspected / 1,113 classification reviews / 50 exclusions**

이 숫자는 ordered range coverage이며 legacy proposal과 비교한 새 increment는 아니다.

### 288~451 reconciliation
- final sweep 281 observations
- already-classified exclusions 15
- classification-pending revalidated 266
- 과거 proposal과 겹치는 classification review 238
- 과거 proposal 대비 진짜 신규 increment **28 observations** (`288`, `292~304`)
- 해당 14 source_record_key는 431 explicit decision exact match 0
- `proposals/reconciliation-pending-288-451.json`
- `checkpoints/checkpoint-proposal-accounting-288-451.md`

## 4. 현재 재개점 — pending 035

**다음 AI는 새 그룹을 고르지 말고 여기서 이어간다.**

- group: `pending/035`
- PENDING_INDEX count: **27 observations / 27 titles**
- directory 확인 완료: `pending/035/001.json`, `pending/035/002.json` 두 파일 존재. 둘 다 읽어야 한다.
- 아직 035 strict accounting/classification은 완료되지 않았다.

작업 절차:
1. 두 파일의 27 observations 전체를 읽고 already-classified vs classification-pending 분리.
2. pending 행의 `source_record_key`, `raw_record_id`, title 수집.
3. 431 `review-decisions-input.json`과 source-key 충돌 화면.
4. existing pass41 leaf 우선 재사용, 없는 제품형태만 hold/new candidate.
5. proposal 저장 + 체크포인트.
6. 완료 즉시 이 파일의 재개점을 `034`로 넘김.

## 5. 문서 신뢰 우선순위

최초 사용자 프롬프트만 받은 다음 AI는 아래 순서로 읽는다.

1. `handoff/2026-09-11/README.md` — 작업 계약. 상단에서 이 파일로 안내.
2. **`handoff/2026-09-11/CURRENT_STATUS.md` — 현재 상태/정확한 재개점 (최우선)**
3. `handoff/2026-09-11/PROGRESS.md` — 역사 로그. 오래된 다음 재개점/누적치는 무시 가능.
4. `handoff/2026-09-11/PENDING_INDEX.md` — 원본 그룹 크기/진열 인덱스. 완료표가 아님.
5. 필요한 최신 `checkpoints/*.md`와 `proposals/*.json`.

충돌 시 **CURRENT_STATUS의 재개점과 strict accounting을 우선**하고, raw/pending 원문을 최종 증거로 삼는다.
