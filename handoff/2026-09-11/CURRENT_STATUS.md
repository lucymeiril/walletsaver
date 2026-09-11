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
- deal/promotion collection은 단일 상품으로 분류하지 않는다. 반대로 promotion shelf의 individual itemView는 실제 상품 정체성이 명확하면 상품형태로 판단한다.
- proposal 파일 존재만으로 완료로 보지 않는다. **raw_record_id/source-key coverage를 실측**한다.
- uncertainty는 hold한다. 억지로 broad/오답 existing leaf에 넣지 않는다.
- 431개 explicit decisions(`review-decisions-input.json`)와 source-key collision screen을 한다.
- 각 그룹 완료 즉시 proposal/reconciliation + checkpoint + 이 파일을 갱신한다.
- DB 반영은 나중에 Codex에서 전역 reconciliation 후 한 번에 한다.

## 2. 완성까지 남은 strict-audit 상한

- 미완 strict 범위: `pending 001~026`
- 해당 원본 관측: **1,401 observations**
- pass41 전체 pending 3,916 대비 **약 35.8%**
- 관측 범위 기준 `027~451`은 약 64.2%를 strict/ordered 방식으로 지나왔다. 단, 이것을 최종 완료율로 부르면 안 된다. 과거 proposal 중복/re-review, taxonomy holds, 최종 reconciliation이 남아 있다.
- `001~026`에도 과거 proposal과 cross-group duplicate가 있으므로 실제 새 판단량은 1,401보다 작을 가능성이 높다.

분류 sweep 뒤 DB 반영 전 남는 단계:
1. proposal 간 raw-record/source-key dedupe
2. proposal 간 충돌표 작성/결정
3. 신규 taxonomy 후보/hold 정책 결정
4. 431 explicit decisions와 최종 충돌 검사
5. Codex에서 새 pass DB import/rebuild + 검사 + 멱등성 확인

## 3. strict reverse sweep 누계

완료 범위: **pending 027~043**

- observations opened: **482**
- already-classified exclusions: **44**
- strict/new classification reviews: **438**
- distinct newly reviewed source listings: **410**
- existing-leaf proposals: **177 listings**
- taxonomy/product-form/promotion/manual-review holds: **233 listings**

최근 그룹:
- 027 `proposals/emart-best-027.json` — 33 opened / 0 excluded / 33 new / existing 31 / hold 2
- 028 `proposals/reconciliation-pending-028.json` — 33 pending / prior coverage 11 / uncovered 22 / final existing 28 / hold 5
- 029 `proposals/costco-cheese-shelf-029.json` — 32 opened / 8 excluded / 24 new / existing 5 / hold 19
- 030 `proposals/emart-obanjang-030.json` — 32 / 1 excluded / 31 new / existing 5 / hold 26
- 031 `proposals/emart-meat-eggs-031.json` — 32 / 6 excluded / 26 new / existing 15 / hold 11
- 032 `proposals/homeplus-flavored-powder-drinks-032.json` — 32 obs / 16 duplicated listings / existing 2 / hold 14
- 033 `proposals/emart-hygiene-health-033.json` — 30 / 12 excluded / 18 new / existing 5 / hold 13
- 034 `proposals/reconciliation-pending-034.json` — 29 pending / prior coverage 19 / uncovered 10 / final existing 24 / hold 5
- 035 `proposals/costco-milk-shelf-035.json` — 27 / 2 excluded / 25 new / existing 9 / hold 16
- 036 `proposals/emart-bakery-jam-036.json` — 27 / 4 excluded / 23 new / existing 2 / hold 21
- 037 `proposals/emart-beverages-037.json` — 27 / 6 excluded / 21 new / existing 9 / hold 12
- 038~043: see `checkpoints/checkpoint-reverse-sweep-038-043.md`

Latest checkpoints:
- `checkpoints/checkpoint-after-pending-027.md`
- `checkpoints/checkpoint-after-pending-028-reconciliation.md`
- `checkpoints/checkpoint-after-pending-029.md`
- `checkpoints/checkpoint-after-pending-030.md`
- `checkpoints/checkpoint-after-pending-031.md`
- `checkpoints/checkpoint-after-pending-032.md`
- `checkpoints/checkpoint-after-pending-033.md`
- `checkpoints/checkpoint-after-pending-034-reconciliation.md`
- `checkpoints/checkpoint-reverse-sweep-038-043.md`

## 4. 최근 중요 발견

### pending 027 — Emart `베스트`
- 33 observations 전부 classification-pending, exclusions 0.
- broad promotion surface이지만 전부 individual `itemView`; title/product identity 기준으로 31 existing / 2 holds.
- holds: fresh fig -> candidate `food.produce.fruit.fig`; hamburg steak -> candidate `food.meals.prepared.hamburg_steak`.
- opaque milk titles `1000ml 나100%`와 `2.3L`은 exact retailer product identity로 서울우유 흰우유임을 확인해 `food.dairy.milk.plain`으로 제안.
- source key `0000006615474`는 pending026에도, `1000768602033` 송탄식 부대찌개는 pending020에도 존재. 027 strict group accounting에는 유지하고 최종 global source-key dedupe에서 병합한다.
- 33 source keys explicit-decision collision screen 0.

### pending 028 — second confirmed raw-coverage gap
- 33 observations 전부 classification-pending.
- older `proposals/grains-nuts-028-034.json`이 group 028을 reviewed로 표시했지만 exact raw coverage는 **11/33뿐**이었다.
- strict audit에서 **22/33 누락**을 발견해 `proposals/reconciliation-pending-028.json`으로 보완.
- earlier 11 revalidation conflict 0; final existing 28 / hold 5.

### raw-coverage lesson now confirmed twice
- pending034: older proposal covered 19/29, missing 10.
- pending028: older proposal covered 11/33, missing 22.
- 따라서 **group name/listing inside an old proposal is never completion evidence. Exact raw/source-key coverage가 남은 low-number 그룹에서도 필수다.**

### pending 030 — promotion anomaly
- 31 new reviews 중 24가 `dealItemView` promotion surface.
- pre-existing anomaly: `ingestion:1:25`, key `1000601687276`, `석박지/맛김치 1+1`은 mixed deal page인데 이미 `food.preserved.kimchi.cabbage`로 classified. 신규 count에서는 제외하되 최종 global reconciliation에서 재검토.

## 5. 이미 확인된 전역 reconciliation 사실

- pending045 proposal 누락을 발견해 22 observations / 11 pizza listings를 `food.meals.prepared.pizza` proposal로 보수.
- 044~109 proposal 파일 존재 감사에서는 045가 유일한 누락 파일이었지만, 파일 존재는 raw coverage 증명이 아니다.
- ordered range 110~451: **1,163 inspected / 1,113 classification reviews / 50 exclusions**. 범위 coverage이지 글로벌 unique increment가 아니다.
- 288~451: final 281 / exclusions 15 / classification-pending 266 / legacy overlap 238 / true new increment 28 observations (`288`, `292~304`); 해당 14 source keys explicit exact match 0.
- pending313 `농심 생생 우동 용기 276G`: older proposal `cup_ramen` vs final sweep `udon` conflict. 최종 승격 전 해결.
- 과거 `2,165`, `+266 final sweep`, `840 classification reviews 044~109` 같은 숫자를 global unique completion으로 사용하지 않는다.

## 6. 현재 재개점 — pending 026

**다음 AI는 여기서 이어간다.**

- group: `pending/026`
- mart/shelf: Emart `우유/유제품`
- index: **35 observations / 35 titles**
- files: `pending/026/001.json`, `pending/026/002.json`
- pending027 strict 완료:
  - `proposals/emart-best-027.json`
  - `checkpoints/checkpoint-after-pending-027.md`

026 절차:
1. 두 pending 조각을 전부 fetch하고 `review_status=classified` 제외 수를 먼저 확정.
2. 026을 언급하는 기존 proposal들의 **exact raw/source-key coverage**를 계산. 파일 존재/그룹명만 믿지 않는다.
3. source key `0000006615474` (`1000ml 나100%`)는 027에서 exact identity까지 검토했지만, 026의 관측은 strict group accounting에 그대로 포함한다. 최종 global dedupe에서만 source-key 중복을 제거한다.
4. 기존 proposal과 strict 재판단 conflict/누락을 명시하고 보완.
5. 431 explicit decision collision screen.
6. 완료 즉시 이 파일을 `pending 025` 재개점으로 갱신.

## 7. 새 AI 문서 신뢰 순서

1. `README.md`
2. **`CURRENT_STATUS.md` (이 파일, 최우선)**
3. `PROGRESS.md` — 역사 로그, 오래된 누적치/재개점 무시 가능
4. `PENDING_INDEX.md` / `pending/index.json` — 원본 그룹 크기/진열 인덱스, 완료표 아님
5. 필요한 최신 `checkpoints/*.md`, `proposals/*.json`

최종 사실 판단은 항상 `pending/`·`raw/` 원문으로 확인한다.
