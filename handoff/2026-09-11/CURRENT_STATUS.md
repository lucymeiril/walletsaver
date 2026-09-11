# WalletSaver 초기 DB 분류 — 현재 상태 (CANONICAL)

> **이 파일이 현재 작업 상황과 재개점의 단일 기준이다.**
> `PROGRESS.md`와 과거 `checkpoints/`는 역사 로그이므로 오래된 누적치/재개점이 섞일 수 있다. 새 AI는 `README.md` 다음에 이 파일을 읽고, 문서가 충돌하면 이 파일의 재개점/strict accounting을 우선한다.

마지막 갱신: 2026-09-12
브랜치: `cleanup/remove-legacy-ai-admin-coupling`
현재 모드: **GitHub read/write, proposal_only**
동결 DB 기준선: **pass41 — 5,280 loaded / 3,916 pending**
Chat 단계에서는 DB import/rebuild/test를 실행하지 않는다.

## 1. 작업 계약

- pending 원문을 직접 읽고 통합 taxonomy 분류 제안/hold를 만든다.
- broad mart shelf보다 **title/product form**, 필요하면 URL taxonomy path나 exact product identity를 우선한다.
- `review_status=classified`인데 단위/수량/행사 문제로 pending에 남은 행은 신규 classification 작업량에서 제외한다.
- 반복 수집은 listing 하나의 판단으로 보되 모든 `raw_record_ids`를 보존한다.
- pass41 snapshot에 없는 leaf는 legacy 코드에 있다는 이유만으로 existing leaf로 쓰지 않는다.
- deal/promotion collection은 단일 상품으로 분류하지 않는다. promotion shelf의 individual itemView는 실제 상품 정체성이 명확하면 상품형태로 판단한다.
- proposal 파일 존재만으로 완료로 보지 않는다. **raw_record_id/source-key coverage를 실측**한다.
- uncertainty는 hold한다. 억지로 broad/오답 existing leaf에 넣지 않는다.
- 431개 explicit decisions(`review-decisions-input.json`)와 source-key collision screen을 한다.
- 각 그룹 완료 즉시 proposal/reconciliation + checkpoint + 이 파일을 갱신한다.
- DB 반영은 나중에 Codex에서 전역 reconciliation 후 한 번에 한다.

## 2. 완성까지 남은 strict-audit 상한

- 미완 strict 범위: `pending 001~025`
- 해당 원본 관측: **1,366 observations**
- pass41 전체 pending 3,916 대비 **약 34.9%**
- 관측 범위 기준 `026~451`은 약 65.1%를 strict/ordered 방식으로 지나왔다. 단, 이것을 최종 완료율로 부르면 안 된다. 과거 proposal 중복/re-review, taxonomy holds, 최종 reconciliation이 남아 있다.
- `001~025`에도 과거 proposal과 cross-group duplicate가 있으므로 실제 새 판단량은 1,366보다 작을 가능성이 높다.

분류 sweep 뒤 DB 반영 전 남는 단계:
1. proposal 간 raw-record/source-key dedupe
2. proposal 간 충돌표 작성/결정
3. 신규 taxonomy 후보/hold 정책 결정
4. 431 explicit decisions와 최종 충돌 검사
5. Codex에서 새 pass DB import/rebuild + 검사 + 멱등성 확인

## 3. strict reverse sweep 누계

완료 범위: **pending 026~043**

- observations opened: **517**
- already-classified exclusions: **46**
- strict/new classification reviews: **471**
- distinct newly reviewed source listings: **443**
- existing-leaf proposals: **209 listings**
- taxonomy/product-form/promotion/manual-review holds: **234 listings**

최근 그룹:
- 026 `proposals/emart-dairy-026.json` — 35 opened / 2 excluded / 33 new / existing 32 / hold 1
- 027 `proposals/emart-best-027.json` — 33 / 0 / 33 / existing 31 / hold 2
- 028 `proposals/reconciliation-pending-028.json` — 33 pending / prior coverage 11 / uncovered 22 / final existing 28 / hold 5
- 029 `proposals/costco-cheese-shelf-029.json` — 32 / 8 / 24 / existing 5 / hold 19
- 030 `proposals/emart-obanjang-030.json` — 32 / 1 / 31 / existing 5 / hold 26
- 031 `proposals/emart-meat-eggs-031.json` — 32 / 6 / 26 / existing 15 / hold 11
- 032 `proposals/homeplus-flavored-powder-drinks-032.json` — 32 obs / 16 duplicated listings / existing 2 / hold 14
- 033 `proposals/emart-hygiene-health-033.json` — 30 / 12 / 18 / existing 5 / hold 13
- 034 `proposals/reconciliation-pending-034.json` — 29 pending / prior coverage 19 / uncovered 10 / final existing 24 / hold 5
- 035~037: see their latest checkpoints
- 038~043: see `checkpoints/checkpoint-reverse-sweep-038-043.md`

Latest checkpoints:
- `checkpoints/checkpoint-after-pending-026.md`
- `checkpoints/checkpoint-after-pending-027.md`
- `checkpoints/checkpoint-after-pending-028-reconciliation.md`
- `checkpoints/checkpoint-after-pending-029.md`
- `checkpoints/checkpoint-after-pending-030.md`
- `checkpoints/checkpoint-after-pending-031.md`
- `checkpoints/checkpoint-after-pending-032.md`
- `checkpoints/checkpoint-after-pending-033.md`
- `checkpoints/checkpoint-after-pending-034-reconciliation.md`

## 4. 최근 중요 발견

### pending 026 — Emart `우유/유제품`
- 35 observations / **2 classified exclusions** / 33 new listings.
- exclusions: `ingestion:83:20` plain milk, `ingestion:83:69` sliced cheddar; 둘 다 classification은 이미 완료되고 다른 reconciliation issue 때문에 pending에 남아 있음.
- direct per-record status inspection corrected an earlier broad-search miss; canonical count is **2 exclusions**, never 0.
- new 33: existing 32 / hold 1. Hold is `dealItemView` cheese/butter promotion collection.
- exact form checks resolved opaque/form-sensitive items: `(200ml*3개)` -> plain milk; cheese cube -> portion; Devinci 30 slices -> sliced; A-class 900g -> spoon yogurt; Coffee Pori -> coffee milk.
- low-fat milk remains `food.dairy.milk.plain`; fat percentage is an attribute in current taxonomy.
- key `0000006615474` overlaps pending027; keep both group observations until final global source-key dedupe.
- 33 new source keys explicit-decision collision screen 0.

### pending 027 — Emart `베스트`
- 33 observations / exclusions 0 / existing 31 / hold 2.
- broad promotion surface지만 전부 individual itemView.
- holds: fresh fig -> `food.produce.fruit.fig`; hamburg steak -> `food.meals.prepared.hamburg_steak`.
- 33 source keys explicit-decision collision screen 0.

### raw-coverage lesson confirmed twice
- pending034: older proposal covered 19/29, missing 10.
- pending028: older proposal covered 11/33, missing 22.
- 따라서 **old proposal에 group 이름이 있거나 proposal 파일이 존재하는 것만으로 완료 취급 금지. Exact raw/source-key coverage 필수.**

### pending 030 — classified promotion anomaly
- `ingestion:1:25`, key `1000601687276`, `석박지/맛김치 1+1`은 mixed deal page인데 이미 `food.preserved.kimchi.cabbage`로 classified. 신규 count에서는 제외했지만 최종 global reconciliation에서 재검토.

## 5. 이미 확인된 전역 reconciliation 사실

- pending045 proposal 누락 보수: 22 observations / 11 pizza listings -> `food.meals.prepared.pizza`.
- 044~109 proposal 파일 존재 감사에서 045가 유일한 누락 파일이었지만, 파일 존재는 raw coverage 증명이 아니다.
- ordered range 110~451: **1,163 inspected / 1,113 classification reviews / 50 exclusions**. 범위 coverage이지 글로벌 unique increment가 아니다.
- 288~451: final 281 / exclusions 15 / classification-pending 266 / legacy overlap 238 / true new increment 28 observations (`288`, `292~304`).
- pending313 `농심 생생 우동 용기 276G`: older proposal `cup_ramen` vs final sweep `udon` conflict. 최종 승격 전 해결.
- 과거 `2,165`, `+266 final sweep`, `840 classification reviews 044~109` 같은 숫자를 global unique completion으로 사용하지 않는다.

## 6. 현재 재개점 — pending 025

**다음 AI는 여기서 이어간다.**

- group: `pending/025`
- mart/shelf: Emart `건강식품`
- index: **35 observations / 35 titles**
- files: `pending/025/001.json`, `pending/025/002.json`
- pending026 strict 완료:
  - `proposals/emart-dairy-026.json`
  - `checkpoints/checkpoint-after-pending-026.md`

025 절차:
1. 두 pending 조각을 전부 fetch하고 record별 `review_status=classified` 제외 수를 직접 확정. Broad string search만 믿지 않는다.
2. 025를 언급하는 기존 proposal들의 **exact raw/source-key coverage**를 계산.
3. title/product form을 우선하되 건강식품 shelf라는 이유만으로 일반 식품을 supplement leaf에 넣지 않는다.
4. 불명확한 건강기능/보충제 형태는 현재 pass41 leaf 존재 여부를 확인하고 없으면 hold.
5. 431 explicit decision collision screen.
6. 완료 즉시 이 파일을 `pending 024` 재개점으로 갱신.

## 7. 새 AI 문서 신뢰 순서

1. `README.md`
2. **`CURRENT_STATUS.md` (이 파일, 최우선)**
3. `PROGRESS.md` — 역사 로그, 오래된 누적치/재개점 무시 가능
4. `PENDING_INDEX.md` / `pending/index.json` — 원본 그룹 크기/진열 인덱스, 완료표 아님
5. 필요한 최신 `checkpoints/*.md`, `proposals/*.json`

최종 사실 판단은 항상 `pending/`·`raw/` 원문으로 확인한다.
