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
- pass41 snapshot에 없는 leaf는 legacy 코드/과거 candidate 문서에 있다는 이유만으로 existing leaf로 쓰지 않는다.
- deal/promotion collection은 단일 상품으로 분류하지 않는다. promotion shelf의 individual itemView는 실제 상품 정체성이 명확하면 상품형태로 판단한다.
- proposal 파일 존재만으로 완료로 보지 않는다. **raw_record_id/source-key coverage를 실측**한다.
- uncertainty는 hold한다. 억지로 broad/오답 existing leaf에 넣지 않는다.
- 431개 explicit decisions(`review-decisions-input.json`)와 source-key collision screen을 한다.
- 각 그룹 완료 즉시 proposal/reconciliation + checkpoint + 이 파일을 갱신한다.
- DB 반영은 나중에 Codex에서 전역 reconciliation 후 한 번에 한다.

## 2. 완성까지 남은 strict-audit 상한

- 미완 strict 범위: `pending 001~018`
- 해당 원본 관측: **1,091 observations**
- pass41 전체 pending 3,916 대비 **약 27.9%**
- 관측 범위 기준 `019~451`은 약 72.1%를 strict/ordered 방식으로 지나왔다. 이것을 최종 완료율로 부르면 안 된다. 과거 proposal 중복/re-review, taxonomy holds, 최종 reconciliation이 남아 있다.
- `001~018`에도 과거 proposal과 cross-group duplicate가 있으므로 실제 새 판단량은 1,091보다 작을 수 있다.

분류 sweep 뒤 DB 반영 전 남는 단계:
1. proposal 간 raw-record/source-key dedupe
2. proposal 간 충돌표 작성/결정
3. 신규 taxonomy 후보/hold 정책 결정
4. 431 explicit decisions와 최종 충돌 검사
5. Codex에서 새 pass DB import/rebuild + 검사 + 멱등성 확인

## 3. strict reverse sweep 누계

완료 범위: **pending 019~043**

- observations opened: **792**
- already-classified exclusions: **84**
- strict/new classification reviews: **708**
- strict group source listings reviewed: **652**
- existing-leaf proposals: **305 listings**
- taxonomy/product-form/promotion/manual-review holds: **347 listings**

> 위 source-listing 수는 strict group 내부 판단 수의 누계다. 서로 다른 pending group에 같은 `source_record_key`가 재등장할 수 있으므로 글로벌 unique source-key 수로 사용하지 않는다. 최종 global dedupe에서 합친다.

최근 그룹:
- 019 `proposals/emart-noodles-canned-019.json` — 42 opened / 19 excluded / 23 new / 13 reviewed listings / existing 10 / hold 3
- 020 `proposals/emart-mealkit-convenience-020.json` — 42 opened / 6 excluded / 36 new / 18 reviewed listings / existing 4 / hold 14
- 021 `proposals/costco-kimchi-shelf-021.json` — 41 / 0 / 41 / existing 15 / hold 26
- 022 `proposals/emart-organic-022.json` — 40 / 2 / 38 / existing 31 / hold 7
- 023 `proposals/costco-tissue-shelf-023.json` — 39 / 9 / 30 / existing 13 / hold 17
- 024 `proposals/emart-coffee-tea-024.json` — 36 / 2 / 34 / existing 23 / hold 11
- 025 `proposals/emart-health-foods-025.json` — 35 / 0 / 35 / existing 0 / hold 35
- 026 `proposals/emart-dairy-026.json` — 35 / 2 / 33 / existing 32 / hold 1
- 027 `proposals/emart-best-027.json` — 33 / 0 / 33 / existing 31 / hold 2
- 028 `proposals/reconciliation-pending-028.json` — 33 pending / prior coverage 11 / uncovered 22 / final existing 28 / hold 5
- 029 `proposals/costco-cheese-shelf-029.json` — 32 / 8 / 24 / existing 5 / hold 19
- 030 `proposals/emart-obanjang-030.json` — 32 / 1 / 31 / existing 5 / hold 26
- 031 `proposals/emart-meat-eggs-031.json` — 32 / 6 / 26 / existing 15 / hold 11
- 032 `proposals/homeplus-flavored-powder-drinks-032.json` — 32 obs / 16 duplicated listings / existing 2 / hold 14
- 033 `proposals/emart-hygiene-health-033.json` — 30 / 12 / 18 / existing 5 / hold 13
- 034 `proposals/reconciliation-pending-034.json` — 29 pending / prior coverage 19 / uncovered 10 / final existing 24 / hold 5
- 035~043: see latest checkpoints.

Latest checkpoints:
- `checkpoints/checkpoint-after-pending-019.md`
- `checkpoints/checkpoint-after-pending-020.md`
- `checkpoints/checkpoint-after-pending-021.md`
- `checkpoints/checkpoint-after-pending-022.md`
- `checkpoints/checkpoint-after-pending-023.md`
- `checkpoints/checkpoint-after-pending-024.md`
- `checkpoints/checkpoint-after-pending-025.md`
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

### pending 019 — Emart `면류/통조림`
- 42 observations / 25 source listings: 17 paired listings across ingestion 89/90 + 8 singleton listings.
- 12 already-classified source listings account for 19 exclusions; strict/new classification is 23 observations / 13 source listings.
- existing-leaf proposals 10: 간편잡채 -> `food.meals.prepared.japchae`, 닭한마리 칼국수 -> `food.meals.noodles.kalguksu`, 오이피클/슬라이스피클 -> `food.preserved.sides.pickled`, 짜장면사리 -> `food.meals.noodles.black_bean`, 메밀쌀소면 -> pass41의 `food.meals.noodles.naengmyeon`, 4개 컵라면형 -> `food.meals.noodles.cup_ramen`.
- 컵 표기가 제목에 없던 4건은 exact/current retail evidence를 별도 확인했다: 불닭 70g은 작은컵, 완면각짬뽕 105g은 보통/큰컵, 삼양 1963 우지 파개장 115g은 큰컵, 불닭 105g은 큰컵 형태로 확인. 이 근거는 classification form에만 사용했고 수량/가격 정규화는 바꾸지 않았다.
- holds 3: 라면사리 -> candidate `food.meals.noodles.ramen_sari`; 밀또띠아 -> candidate `food.bakery.bread.tortilla`; 베이크드빈스 -> 기존 strict candidate `food.preserved.canned.beans` 재사용.
- current source code의 `wheat_noodle`/`buckwheat_noodle`처럼 pass41 snapshot에 없는 later leaf는 existing leaf로 취급하지 않았다. 메밀쌀소면은 frozen pass41의 표시명 `냉면·메밀면` 축과 prior strict 메밀국수 precedent를 재사용했다.
- all 25 source keys: prior proposal exact hit 0, 431 explicit decision hit 0. 13 classification-pending source keys를 개별 repository search한 결과 cross-group pending hit 0.

### pending 020 — Emart `밀키트/간편식`
- 42 observations are exactly 21 source listings repeated across ingestion 84/85.
- 3 already-classified source listings account for 6 exclusions; strict/new classification is 36 observations / 18 source listings.
- existing-leaf proposals 4: 쌈무 -> `food.preserved.sides.pickled`, 라자냐 -> `food.meals.noodles.pasta`, 닭꼬치 -> `food.meals.prepared.chicken`, 된장찌개 양념 -> `food.seasonings.sauces.stew`.
- prior strict policy was reused instead of inventing new local rules: standalone 단무지 -> candidate `food.preserved.sides.danmuji`, 도토리묵 -> candidate `food.plant.muk.acorn`, 감자튀김 -> candidate `food.meals.prepared.frozen_potato`.
- 맘마밀 이유식/오트밀 3 listings remain baby-food taxonomy holds; product-form ingredients were not used to force produce/grain/meat leaves.
- 생선까스 is held as candidate `food.meals.prepared.fish_cutlet`; 메밀김치전병 and 곤드레나물밥 remain taxonomy-policy holds; `딱 한끼(순한맛)` remains an identity hold because title alone does not identify product form.
- exact repository search across all 21 source keys surfaced 0 prior-proposal hits, 0 `review-decisions-input.json` hits and no cross-group pending hit.

### pending 021 — Costco `김치`
- 41 observations / exclusions 0 / existing 15 / hold 26.
- shelf pollution is severe: kimchi refrigerators, kitchen storage, kimchi marinade, pickles, chili powder, fermented shrimp, prepared pork/udon/side dishes, and a kimchi-fried-rice scorched-rice item all appear under `김치`.
- all 41 rows are genuinely classification-pending; no already-classified exclusions.
- existing kimchi leaves reused only when product form is explicit: cabbage, water, green-onion, and seokbakji. Mixed packs crossing current leaves were held.
- standalone 깍두기 is held as candidate `food.preserved.kimchi.kkakdugi`; the current category snapshot has no dedicated 깍두기 leaf.
- 10 LG kimchi refrigerators are held out of current taxonomy; official Costco URLs identify `Appliances/Refrigerators/Kimchi-Fridges`.
- 고춧가루 -> `food.seasonings.spices.chili_powder`; 장아찌 -> `food.preserved.sides.pickled`; 제육볶음 -> `food.meals.prepared.seasoned_meat`; explicit 우동 -> `food.meals.noodles.udon`; 멸치볶음 -> `food.preserved.sides.stir_fried`.
- 새우젓 reuses held candidate `food.seafood.fermented.shrimp_paste` from prior strict sweep.
- group-marker search found no older pending021 proposal; 41 source-key repository collision search surfaced no prior proposal hit and no `review-decisions-input.json` hit.

### pending 022 — Emart `친환경/유기농`
- 40 observations / 2 classified exclusions / 38 new; existing 31 / hold 7.
- broad organic shelf is strongly multi-department; product identity/form controlled classification.
- exact source-key overlap `1000011626449` also appears in pending026 with the same `food.dairy.yogurt.spoon` decision; preserve strict group accounting and dedupe globally later.

### pending 023 — Costco `휴지`
- 39 observations / 9 classified exclusions / 30 new; existing 13 / hold 17.
- shelf pollution includes body cooling sheet, table napkin, dry cotton/coin tissues, cleaning wipes, trash bins, and a garden hose reel.

### pending 024 — Emart `커피/원두/차`
- 36 observations / 2 classified exclusions / 34 new; existing 23 / hold 11.
- direct per-record inspection corrected an initial shallow-search exclusion miss.

### pending 025 — Emart `건강식품`
- 35 observations / exclusions 0 / existing 0 / holds 35.
- supplement candidate names from prior sweeps were not treated as confirmed pass41 leaves.

### pending 026 — Emart `우유/유제품`
- 35 observations / 2 classified exclusions / 33 new; existing 32 / hold 1.
- direct per-record status inspection corrected an earlier broad-search miss.

### raw-coverage lesson confirmed twice
- pending034: older proposal covered 19/29, missing 10.
- pending028: older proposal covered 11/33, missing 22.
- **old proposal에 group 이름이 있거나 proposal 파일이 존재하는 것만으로 완료 취급 금지. Exact raw/source-key coverage 필수.**

## 5. 이미 확인된 전역 reconciliation 사실

- pending045 proposal 누락 보수: 22 observations / 11 pizza listings -> `food.meals.prepared.pizza`.
- ordered range 110~451: **1,163 inspected / 1,113 classification reviews / 50 exclusions**. 범위 coverage이지 글로벌 unique increment가 아니다.
- 288~451: final 281 / exclusions 15 / classification-pending 266 / legacy overlap 238 / true new increment 28 observations (`288`, `292~304`).
- pending313 `농심 생생 우동 용기 276G`: older proposal `cup_ramen` vs final sweep `udon` conflict. 최종 승격 전 해결.
- 과거 `2,165`, `+266 final sweep`, `840 classification reviews 044~109` 같은 숫자를 global unique completion으로 사용하지 않는다.

## 6. 현재 재개점 — pending 018

**다음 AI는 여기서 이어간다.**

- group: `pending/018`
- mart/shelf: Emart `유아동/완구`
- index: **43 observations / 43 titles**
- files: `pending/018/001.json`, `pending/018/002.json`
- pending019 strict 완료:
  - `proposals/emart-noodles-canned-019.json`
  - `checkpoints/checkpoint-after-pending-019.md`

018 절차:
1. 두 pending 조각을 전부 fetch하고 record별 `review_status=classified` 제외 수를 직접 확정.
2. 43 observations / 43 titles가 실제로 43 source keys인지, 반복수집/동일판매페이지가 섞였는지 raw-id 기준으로 실측한다.
3. 기존 proposal의 **exact raw/source-key coverage**를 계산. group/file 이름만 믿지 않는다.
4. Emart `유아동/완구` shelf보다 title/product form을 우선하고, 431 explicit decision collision + cross-group source-key overlap을 별도로 기록한다.
5. 완료 즉시 이 파일을 `pending 017` 재개점으로 갱신.

## 7. 새 AI 문서 신뢰 순서

1. `README.md`
2. **`CURRENT_STATUS.md` (이 파일, 최우선)**
3. `PROGRESS.md` — 역사 로그, 오래된 누적치/재개점 무시 가능
4. `PENDING_INDEX.md` / `pending/index.json` — 원본 그룹 크기/진열 인덱스, 완료표 아님
5. 필요한 최신 `checkpoints/*.md`, `proposals/*.json`

최종 사실 판단은 항상 `pending/`·`raw/` 원문으로 확인한다.
