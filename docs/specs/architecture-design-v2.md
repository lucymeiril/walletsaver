# WalletSavior Architecture Design v2

## 0. Scope and current-state summary

This document answers five architecture questions for the next implementation phase.

Current codebase observations:

- `packages/db-admin/backend/storage/models.py`
  - already has `PendingCategorization`, `CategoryCorrection`, and `DiscountHistory`
  - `Product.categorization_method` / `categorization_confidence` already exist
- `packages/db-admin/backend/services/auto_categorize.py`
  - current classifier is ML-free and confidence-based
  - current thresholds are effectively:
    - `>= 0.85`: auto assign
    - `0.50 ~ 0.84`: suggested + review queue
    - `< 0.50`: no safe assignment
- `packages/website/backend/api/routes/restaurants.py`
  - `avg_price` is not really computed yet
  - `/api/recipes/compare` currently falls back to hard-coded demo data
- `packages/website/frontend/src/pages/Local/utils.js`
  - representative menu price is currently a simple average
- `packages/website/frontend/src/pages/Local/LocalPage.jsx` and `.../mockData.js`
  - cook-vs-eat UI is partly static/demo-driven today

Design principle for v2:

1. Keep raw crawl data.
2. Add normalized/event tables for UX-friendly queries.
3. Make review workflows explicit.
4. Allow deterministic fallback when AI fails.

---

## 1. Auto-classification system

## 1.1 Recommendation

Support both modes behind one orchestration service:

- **Option A default**: cheaper, deterministic, explainable
- **Option B optional**: better recall for messy titles and new categories
- **Production fallback order**:
  1. Option A exact/rule classifier
  2. Option B LLM classifier for unresolved/low-confidence items
  3. manual review queue before final DB approval

```text
Crawler/Pending Ingestion
        |
        v
+---------------------------+
| Classification Orchestrator|
+---------------------------+
   | high confidence A
   |---------------> approve suggestion
   |
   | low confidence / ambiguous
   v
+------------------+       provider fail/quota
| LLM Classifier   |-------------------+
+------------------+                   |
   | success                            |
   v                                    |
+-----------------------+               |
| Manual Review Queue   |<--------------+
+-----------------------+
        |
        v
  Product + Audit + Learning
```

## 1.2 Shared components for both options

### Shared tables

Keep existing tables and add/extend below.

#### A. `pending_categorizations` (extend existing)

Add:

```sql
ALTER TABLE pending_categorizations ADD COLUMN classifier_type VARCHAR(20);  -- algorithm | llm | hybrid
ALTER TABLE pending_categorizations ADD COLUMN classifier_version VARCHAR(50);
ALTER TABLE pending_categorizations ADD COLUMN source_name VARCHAR(50);
ALTER TABLE pending_categorizations ADD COLUMN normalized_name VARCHAR(500);
ALTER TABLE pending_categorizations ADD COLUMN explanation_json JSONB;
ALTER TABLE pending_categorizations ADD COLUMN reviewed_by INTEGER;
ALTER TABLE pending_categorizations ADD COLUMN reviewed_at TIMESTAMP;
```

#### B. `category_corrections` (extend existing)

Current table is useful but too small for learning quality.

```sql
ALTER TABLE category_corrections ADD COLUMN source_name VARCHAR(50);
ALTER TABLE category_corrections ADD COLUMN normalized_name VARCHAR(500);
ALTER TABLE category_corrections ADD COLUMN token_signature VARCHAR(500);
ALTER TABLE category_corrections ADD COLUMN correction_type VARCHAR(30); -- exact_name | token_rule | negative_rule | alias
ALTER TABLE category_corrections ADD COLUMN confidence_before FLOAT;
ALTER TABLE category_corrections ADD COLUMN applied_count INTEGER DEFAULT 0;
ALTER TABLE category_corrections ADD COLUMN success_count INTEGER DEFAULT 0;
ALTER TABLE category_corrections ADD COLUMN last_applied_at TIMESTAMP;
ALTER TABLE category_corrections ADD COLUMN created_by INTEGER;
ALTER TABLE category_corrections ADD COLUMN is_active BOOLEAN DEFAULT TRUE;
```

#### C. New `classification_runs`

Tracks scheduled batches and provider/model health.

```sql
CREATE TABLE classification_runs (
    id BIGSERIAL PRIMARY KEY,
    mode VARCHAR(20) NOT NULL,              -- algorithm | llm | hybrid
    source_name VARCHAR(50),
    status VARCHAR(20) NOT NULL,            -- queued | running | completed | partial | failed
    item_count INTEGER NOT NULL DEFAULT 0,
    processed_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    provider_name VARCHAR(50),
    model_name VARCHAR(100),
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    error_summary TEXT,
    meta_json JSONB
);
```

### Shared confidence policy

| Score | Action |
|---|---|
| `>= 0.90` | auto-apply when exact historical proof exists |
| `0.75 ~ 0.89` | suggested category + review queue |
| `0.50 ~ 0.74` | review required, not inserted as final |
| `< 0.50` | unclassified |

### Shared manual review UI concept

```text
+----------------------------------------------------------------------------------+
| 자동 분류 검토                                                                   |
+----------------------------------------------------------------------------------+
| 필터: [pending] [algorithm] [llm] [마트: Emart v] [신뢰도 0.5~0.9] [검색_____] |
+----------------------------------------------------------------------------------+
| 상품명                         | 제안 카테고리      | 신뢰도 | 근거              |
|----------------------------------------------------------------------------------|
| 피코크 제주 흑돼지 목살 500g   | livestock.pork...  | 0.82   | 목살, 흑돼지      |
| 홈플러스 심플러스 참치캔 150g  | seafood.processed  | 0.61   | 참치, canned      |
| 코스트코 커클랜드 키친타올     | household.paper    | 0.48   | provider disagree |
+----------------------------------------------------------------------------------+
| 상세 패널                                                                         |
| - 정규화명: 제주 흑돼지 목살                                                     |
| - 후보: 1) pork.neck 0.82  2) pork.belly 0.44                                    |
| - LLM 설명 / 룰 설명                                                              |
| - 과거 유사 교정: 12건                                                            |
|                                                                                  |
| [승인] [다른 카테고리 선택] [규칙으로 저장] [이번만 수정] [보류] [거절]         |
+----------------------------------------------------------------------------------+
```

### Shared API surface

```text
POST /api/admin/classification/runs
GET  /api/admin/classification/runs/{run_id}
GET  /api/admin/classification/review-queue
POST /api/admin/classification/review/{pending_id}/approve
POST /api/admin/classification/review/{pending_id}/correct
POST /api/admin/classification/review/{pending_id}/skip
GET  /api/admin/classification/corrections/search
```

---

## 1.3 Option A: algorithm-based, ML-free

## 1.3.1 Design

Build on the existing `auto_categorize.py` pipeline instead of replacing it.

### Classification stages

```text
product_name
   |
   v
normalize -> parse tokens/brand/attributes
   |
   +--> exact correction rules
   +--> token correction rules
   +--> existing keyword/synonym/mapping matcher
   +--> source-specific boosts
   +--> negative rules / ambiguity penalties
   v
confidence + candidates
```

### How learning from manual correction works

When an admin changes a result:

1. save the correction row
2. derive one or more reusable rules
3. re-score future items with those rules before generic matching

#### Rule derivation logic

| Situation | Stored learning |
|---|---|
| exact same normalized name repeated | `exact_name` rule |
| same token set repeatedly maps to same category | `token_rule` |
| one wrong category repeatedly appears with token | `negative_rule` |
| brand/source-specific pattern | source-scoped rule |

Example:

```text
"제주 흑돼지 목살 500g" corrected to livestock.pork.neck
-> normalized_name = "제주 흑돼지 목살"
-> token_signature = "목살|돼지|흑돼지"
-> wrong_category_id = livestock.pork.belly
-> correct_category_id = livestock.pork.neck
```

### Rule application order

1. exact-name correction
2. normalized-name correction
3. token-signature correction
4. negative rules
5. base algorithm

### Confidence formula

```text
base_score
+ exact_rule_bonus
+ token_match_bonus
+ source_context_bonus
+ repeated_correction_bonus
- ambiguity_penalty
- category_conflict_penalty
= final_confidence
```

Suggested additions:

- `+0.25` if exact correction match exists
- `+0.15` if token rule has `success_count >= 3`
- `-0.20` if two top categories are within `0.08`
- cap auto-assign unless at least one explainable rule exists

## 1.3.2 Queue and feedback loop

```text
New item
  -> algorithm classify
      -> high confidence -> assign
      -> medium/low confidence -> pending_categorizations
          -> admin review
              -> approved -> Product.category_id update
              -> corrected -> category_corrections insert/update
                            -> rule cache refresh
                            -> future runs improved
```

## 1.3.3 Strengths / risks

**Strengths**

- cheap
- easy to audit
- fast batch processing
- no provider dependency

**Risks**

- long tail of messy product names
- rules can overfit if correction storage is too aggressive
- maintenance cost grows with category complexity

**Mitigation**

- require `success_count >= 2 or 3` before generalizing token rules
- keep exact-name rules separate from reusable token rules
- maintain weekly false-positive report

---

## 1.4 Option B: AI/LLM-based

## 1.4.1 Provider-agnostic abstraction layer

Use an adapter interface.

```python
class LLMProvider(Protocol):
    name: str

    def classify(self, items: list[dict], config: ProviderConfig) -> ProviderResult: ...
    def healthcheck(self) -> ProviderHealth: ...
    def supports_json_mode(self) -> bool: ...
    def estimate_tokens(self, text: str) -> int: ...
```

Concrete adapters:

- `OpenAIClassifierProvider`
- `AnthropicClassifierProvider`
- `GoogleGeminiClassifierProvider`
- `OllamaClassifierProvider` or `LocalVLLMProvider`

Orchestrator:

```text
ClassificationOrchestrator
  -> ProviderRegistry
  -> BatchBuilder
  -> ResponseValidator
  -> RetryPolicy
  -> FallbackManager
```

## 1.4.2 Configuration schema

Use YAML or JSON plus env-secret injection.

```yaml
classification:
  mode: hybrid               # algorithm | llm | hybrid
  review_required: true
  weekly_schedule: "0 3 * * 1"
  fallback_order: ["algorithm", "anthropic", "openai", "local"]
  llm:
    max_chars_per_call: 5000
    max_items_per_call: 30
    timeout_seconds: 25
    retry_count: 2
    require_json: true
    auto_apply_min_confidence: 0.90
    manual_review_min_confidence: 0.55
providers:
  - name: anthropic
    enabled: true
    model: claude-sonnet-4.5
    api_key_env: ANTHROPIC_API_KEY
    priority: 1
    quota_per_minute: 50
    quota_per_day: 5000
  - name: openai
    enabled: true
    model: gpt-4.1-mini
    api_key_env: OPENAI_API_KEY
    priority: 2
  - name: google
    enabled: false
    model: gemini-2.0-flash
    priority: 3
  - name: local
    enabled: true
    endpoint: http://llm-internal:11434
    model: qwen2.5:7b
    priority: 4
```

## 1.4.3 Prompt/response contract

Input per item:

```json
{
  "item_id": 123,
  "name": "피코크 제주 흑돼지 목살 500g",
  "source": "emart",
  "candidate_categories": ["livestock.pork.neck", "livestock.pork.belly", "..."],
  "allowed_output": {
    "category_id": "one of candidate_categories or null",
    "confidence": "0.0~1.0",
    "reason": "short explanation",
    "needs_review": "boolean"
  }
}
```

Response must be validated server-side:

- JSON parse success
- category must exist
- confidence range valid
- reject hallucinated categories

## 1.4.4 Batch processing flow

Constraint: **max 5000 chars per API call**.

### Batch builder

1. group items by source/mart for context consistency
2. accumulate prompt chars
3. stop when:
   - total chars would exceed 5000
   - item count would exceed configured max
4. create next batch

```text
pending items
   -> normalize payloads
   -> char-aware chunking (<= 5000)
   -> provider call
   -> validate response
   -> save to pending_categorizations
   -> manual review
   -> final write to Product
```

### Weekly cadence

Weekly is sufficient for mart promotions:

- Monday 03:00 KST: full batch for new/unclassified/suggested items
- Daily small batch: only urgent manual corrections replay + new items from latest crawl

## 1.4.5 Error handling and provider switching

| Failure | Handling |
|---|---|
| model deprecated | provider healthcheck marks unavailable, move to next provider |
| quota exceeded | exponential backoff, then next provider |
| timeout | retry once, then fallback |
| malformed JSON | one repair attempt, then fallback |
| hallucinated category | reject batch item, queue for review |
| provider outage | switch to next configured provider |

### Fallback policy

```text
LLM attempt
  -> success + valid -> review queue
  -> invalid JSON -> retry same provider once
  -> quota/deprecation/outage -> next provider
  -> all providers fail -> algorithm-only suggestion + manual review
```

## 1.4.6 Strengths / risks

**Strengths**

- better handling of unseen or messy titles
- easier source-specific reasoning
- less manual rule authoring

**Risks**

- vendor cost
- inconsistent output across model versions
- latency and quota
- prompt drift/model deprecation

**Mitigation**

- adapter layer
- strict response validation
- store provider/model/version in every run
- never insert directly to final product without review in v1

---

## 2. Discount history tracking (1-year history)

## 2.1 Evaluation of current `DiscountHistory`

Current table is **partially useful but not sufficient by itself** for the owner’s desired UI.

What it already supports:

- `product_id`
- discount price and regular price
- source/source URL
- start/end validity
- crawl timestamp
- raw payload retention

What it lacks for a 1-year history UI:

- stable event identity across repeated crawls
- explicit lifecycle state
- dedupe control for same promotion seen many times
- end-of-promotion detection when `valid_to` is missing
- easy query for “12 discount episodes in last year”

## 2.2 Recommended schema

### Keep current `discount_history` as raw observation table

Do **not** overload it for all UX queries.

### Add new `discount_events`

```sql
CREATE TABLE discount_events (
    id BIGSERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    mart_code VARCHAR(30) NOT NULL,                -- emart | homeplus | costco | lotte
    promotion_key VARCHAR(200) NOT NULL,           -- stable dedupe key
    event_name VARCHAR(200),
    status VARCHAR(20) NOT NULL,                   -- active | expiring_soon | expired | archived
    original_price NUMERIC(12,2),
    discount_price NUMERIC(12,2) NOT NULL,
    discount_amount NUMERIC(12,2),
    discount_rate NUMERIC(5,2),
    valid_from TIMESTAMP,
    valid_to TIMESTAMP,
    first_seen_at TIMESTAMP NOT NULL,
    last_seen_at TIMESTAMP NOT NULL,
    ended_at TIMESTAMP,
    source_url VARCHAR(500),
    display_priority INTEGER DEFAULT 0,
    raw_summary_json JSONB,
    UNIQUE (product_id, mart_code, promotion_key)
);

CREATE INDEX ix_discount_events_product_status_date
    ON discount_events(product_id, status, valid_from DESC);
```

### Optional small additions to raw table

```sql
ALTER TABLE discount_history ADD COLUMN mart_code VARCHAR(30);
ALTER TABLE discount_history ADD COLUMN promotion_key VARCHAR(200);
ALTER TABLE discount_history ADD COLUMN observed_status VARCHAR(20);
```

## 2.3 How event tracking works

### Promotion key generation

Use a deterministic hash of:

```text
product_id + mart_code + normalized source title + original_price + discount_price + valid_from
```

If `valid_from` is missing, use first seen date bucket.

### Upsert rules

When crawler sees an offer:

1. insert raw row into `discount_history`
2. compute `promotion_key`
3. upsert into `discount_events`
4. update `last_seen_at`
5. if first sighting, set `first_seen_at`

When an offer is no longer seen:

- if `valid_to < now`: mark `expired`
- if missing from N consecutive crawls and older than grace window: mark `expired`

Recommended grace window:

- 2 crawls for marts with daily/weekly flyer sync

```text
Crawler -> raw discount_history insert
        -> event matcher
            -> existing promotion_key? update last_seen_at
            -> new key? create discount_event
        -> lifecycle updater
```

## 2.4 Display aggregation

The owner’s sample UI is event-based, not crawl-based.

Query shape:

```sql
SELECT
    valid_from::date AS event_start_date,
    COALESCE(original_price, discount_price) AS normal_price,
    COALESCE(discount_amount, original_price - discount_price) AS discount_amount,
    discount_price,
    mart_code,
    status
FROM discount_events
WHERE product_id = :product_id
  AND valid_from >= NOW() - INTERVAL '1 year'
ORDER BY valid_from DESC;
```

## 2.5 API design

### Product discount history

```text
GET /api/products/{product_id}/discount-history?period=365&include_expired=true
```

Response:

```json
{
  "product_id": 101,
  "summary": {
    "count_last_year": 12,
    "lowest_discount_price": 10990,
    "latest_status": "expired",
    "active_event_id": null
  },
  "events": [
    {
      "event_id": 9001,
      "mart_code": "emart",
      "status": "expired",
      "event_name": "주간특가",
      "valid_from": "2026-04-13",
      "valid_to": "2026-04-19",
      "normal_price": 13990,
      "discount_amount": 3000,
      "discount_price": 10990,
      "source_url": "..."
    }
  ]
}
```

### Optional mart page endpoint

```text
GET /api/marts/products/{product_id}/offers?status=active,expiring_soon,expired
```

## 2.6 Frontend component concept

```text
+--------------------------------------------------+
| 최근 1년 할인 이력 (12회)                        |
| [활성만] [종료 포함] [마트 필터 ▼]               |
|--------------------------------------------------|
| 2026.04.13 | 정상가 13,990 | -3,000 | 10,990    |
| 2026.03.16 | 정상가 13,990 | -3,000 | 10,990    |
| 2025.05.12 | 정상가 13,990 | -2,500 | 11,490    |
|--------------------------------------------------|
| 차트: 1년 가격 타임라인                          |
|   정상가 ----                                    |
|   할인가  \__/\___/                              |
+--------------------------------------------------+
```

---

## 3. Expired discount handling and lifecycle

## 3.1 UX decision

The mart sale page should **not completely hide** expired items.

Recommended behavior:

- default list = active + expiring soon
- expired items remain visible in product detail and optionally in mart list behind a toggle
- expired items should be visually distinct:
  - gray card
  - `할인 종료` badge
  - previous discount price shown as historical info, not current claim

## 3.2 Lifecycle states

```text
active -> expiring_soon -> expired -> archived
```

### Definitions

| State | Rule | UI |
|---|---|---|
| `active` | now between start and end, or recently observed | normal emphasis |
| `expiring_soon` | `valid_to - now <= 48h` | amber badge |
| `expired` | promotion ended or not observed past grace window | gray card + historical label |
| `archived` | expired older than retention window on mart page | hidden from default mart grid, still in history |

Suggested retention:

- keep `expired` in mart page for 14 days
- move to `archived` after 14 days
- keep in product discount history for 1 year+

## 3.3 State transition job

Run after every crawl and nightly.

```text
for each discount_event:
  if status in (active, expiring_soon):
     if valid_to exists and valid_to < now -> expired
     elif valid_to within 48h -> expiring_soon
     elif not seen in last 2 crawls -> expired
     else -> active

  if status = expired and ended_at < now - 14 days:
     -> archived
```

## 3.4 API additions

```text
GET /api/marts/{mart_code}/deals?status=active,expiring_soon
GET /api/marts/{mart_code}/deals?status=expired&days=14
GET /api/products/{product_id}/discount-history
```

## 3.5 Frontend behavior

- card opacity 60% for expired
- “현재 할인 아님” sublabel
- allow sorting by:
  - active first
  - latest end date
  - biggest past discount

---

## 4. Restaurant price average clustering

## 4.1 Problem and current gap

Current simple averaging is misleading:

```text
[5000, 5000, 5000, 5000, 70000] -> naive average 18000
```

That is not a representative meal price.

Also current backend `restaurants.py` does not yet compute `avg_price` from `menu_data`.

## 4.2 Recommendation

Implement a pure-Python clustering service for `/api/local/` routes.

### Proposed module

```text
packages/website/backend/api/services/restaurant_price_cluster.py
```

### Input

- `Restaurant.menu_data`
- parsed menu items from Naver/local sources

### Output

```json
{
  "representative_price": 5000,
  "cluster_min": 4500,
  "cluster_max": 5500,
  "cluster_size": 4,
  "total_items": 5,
  "confidence": 0.92,
  "method": "adaptive_cluster"
}
```

## 4.3 Algorithm

Use an **adaptive clustering** approach without extra dependencies.

### Step-by-step

1. parse menu prices
2. discard invalid values
3. if count `< 4`, return median
4. sort ascending
5. build clusters where adjacent prices differ by at most:

```text
eps = max(800, round(median_price * 0.18))
```

6. choose best cluster by:
   1. largest size
   2. lowest relative spread
   3. lower median if tie
7. representative price = rounded mean of chosen cluster
8. if cluster confidence too low, fall back to IQR-filtered median

### Why this works

- captures “common meal band”
- ignores premium outliers
- works on Korean restaurant menus with side dishes + specials

## 4.4 Pseudocode

```python
def representative_menu_price(prices: list[int]) -> PriceClusterResult:
    prices = sorted(valid_prices(prices))
    if len(prices) < 4:
        return median_result(prices)

    median = stats.median(prices)
    eps = max(800, round(median * 0.18))

    clusters = []
    current = [prices[0]]
    for p in prices[1:]:
        if p - current[-1] <= eps:
            current.append(p)
        else:
            clusters.append(current)
            current = [p]
    clusters.append(current)

    best = sorted(
        clusters,
        key=lambda c: (-len(c), spread_ratio(c), stats.median(c))
    )[0]

    confidence = len(best) / len(prices)
    if confidence < 0.5:
        return iqr_filtered_result(prices)
    return cluster_result(best, confidence)
```

## 4.5 Edge-case policy

| Case | Rule |
|---|---|
| only 1~3 menu prices | median |
| coffee shops with sizes | cluster still works |
| menus with course + single dishes | cluster excludes course outlier |
| all prices uniformly spread | IQR fallback |
| duplicate noisy parse | dedupe by identical menu name first |

## 4.6 API changes

Use clustered result in:

```text
GET /api/restaurants/nearby
GET /api/local/naver-search
GET /api/local/subcategory-search
```

Response extension:

```json
{
  "avg_price": 5000,
  "price_summary": {
    "representative_price": 5000,
    "method": "adaptive_cluster",
    "confidence": 0.92,
    "sample_count": 14
  }
}
```

---

## 5. Cook-at-home vs eat-out comparison

## 5.1 Current-state findings

Current implementation is incomplete:

- frontend Local page uses static `RECIPES` and `calcRecipeCost`
- default comparison banner is effectively demo data
- backend `/api/recipes/compare` returns fallback examples when storage has no data
- there is no recipe DB or ingredient-price mapping yet

## 5.2 Recommended data model

### New tables

```sql
CREATE TABLE recipes (
    id BIGSERIAL PRIMARY KEY,
    slug VARCHAR(100) UNIQUE NOT NULL,
    name VARCHAR(200) NOT NULL,
    dish_category VARCHAR(100),
    servings INTEGER NOT NULL DEFAULT 2,
    difficulty VARCHAR(20),
    is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE recipe_ingredients (
    id BIGSERIAL PRIMARY KEY,
    recipe_id BIGINT NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    ingredient_name VARCHAR(200) NOT NULL,
    product_id INTEGER REFERENCES products(id),
    quantity_value NUMERIC(10,2) NOT NULL,
    quantity_unit VARCHAR(30) NOT NULL,          -- g | ml | ea
    optional BOOLEAN DEFAULT FALSE,
    waste_factor NUMERIC(5,2) DEFAULT 1.00
);

CREATE TABLE dish_aliases (
    id BIGSERIAL PRIMARY KEY,
    dish_slug VARCHAR(100) NOT NULL,
    alias VARCHAR(200) NOT NULL,
    category_hint VARCHAR(100)
);
```

### Optional materialized view / cache table

```sql
CREATE TABLE recipe_cost_snapshots (
    id BIGSERIAL PRIMARY KEY,
    recipe_id BIGINT NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    calculated_at TIMESTAMP NOT NULL,
    servings INTEGER NOT NULL,
    ingredient_total NUMERIC(12,2) NOT NULL,
    best_mart_total NUMERIC(12,2),
    baseline_total NUMERIC(12,2),
    breakdown_json JSONB NOT NULL
);
```

## 5.3 Pricing logic

For each ingredient:

1. map ingredient to normalized `product_id`
2. compute unit price from best available source:
   - active mart discount
   - recent hotdeal ingredient price if directly usable
   - baseline price fallback
3. scale to recipe quantity
4. apply waste factor and pantry rule

### Source priority

```text
active mart discount > fresh hotdeal ingredient price > baseline_price
```

### Pantry rule

Small staples should not overstate cost every time.

Examples:

- soy sauce, sugar, salt, cooking oil
- charge either:
  - proportional micro-cost, or
  - pantry flat-rule from config

## 5.4 Restaurant comparison logic

### Dish matching

Match recipe to nearby restaurant dishes via:

1. exact alias match (`dish_aliases`)
2. category/menu keyword match
3. restaurant representative cluster per matched dish family

Examples:

- `짜장면` recipe -> nearby restaurant menus containing `짜장`, `짜장면`
- `김치찌개` -> `김치찌개`, `참치김치찌개`, `돼지김치찌개`

### Output

```text
Cook at home cost
vs
Nearby restaurant representative price
vs
Optional delivery price
```

## 5.5 API design

### Main comparison endpoint

```text
GET /api/local/dishes/{dish_slug}/compare?lat=37.49&lng=127.02&radius=3000&servings=2
```

Response:

```json
{
  "dish": {
    "slug": "kimchi-jjigae",
    "name": "김치찌개",
    "servings": 2
  },
  "cook_at_home": {
    "total_cost": 5200,
    "pricing_basis": "active_mart_discount",
    "breakdown": [
      {
        "ingredient": "김치",
        "product_id": 101,
        "quantity": "300g",
        "unit_price_source": "emart",
        "cost": 1200
      }
    ]
  },
  "eat_out": {
    "representative_price": 8500,
    "sample_count": 18,
    "matched_restaurants": 7
  },
  "delivery": {
    "representative_price": 14000
  },
  "comparison": {
    "savings_vs_eat_out": 3300,
    "savings_vs_delivery": 8800
  }
}
```

### Supporting endpoints

```text
GET /api/local/recipes
GET /api/local/recipes/{slug}
POST /api/admin/recipes
POST /api/admin/recipe-ingredients/map-product
```

## 5.6 Frontend concept

```text
+------------------------------------------------------+
| 🍳 김치찌개: 외식 vs 직접 해먹기                    |
| 직접 조리 5,200원 | 외식 8,500원 | 배달 14,000원    |
|------------------------------------------------------|
| 재료비 상세                                          |
| 김치 1,200 | 돼지고기 2,300 | 두부 700 | 대파 400   |
|------------------------------------------------------|
| 가격 근거                                            |
| - 이마트 행사 기준 2개 재료                          |
| - KAMIS 기준가 2개 재료                              |
|------------------------------------------------------|
| 주변 식당 7곳 기준 대표가 8,500원                    |
| [가까운 식당 보기] [재료 최저가 보기]                |
+------------------------------------------------------+
```

## 5.7 Risks

- ingredient-to-product mapping accuracy
- serving-size normalization complexity
- restaurant dish matching ambiguity

Mitigation:

- start with 10~20 popular dishes
- admin-maintained alias table
- expose cost basis in UI so results stay explainable

---

## 6. Dependencies and implementation priority

## 6.1 Dependency graph

```text
discount lifecycle/event model
        +------------------------+
        |                        |
        v                        v
expired-item UX           cook-at-home ingredient pricing

algorithm feedback loop ----+
                            +--> hybrid classifier
llm provider layer ---------+

restaurant price clustering --> cook-vs-eat comparison quality
```

## 6.2 Priority table

| Priority | Item | Why |
|---|---|---|
| P0 | discount event model + lifecycle states | directly affects mart UX and 1-year history |
| P0 | algorithm classifier feedback loop | lowest-risk quality gain, builds on current code |
| P1 | restaurant price clustering | fixes misleading local price output |
| P1 | recipe/ingredient DB foundation | required to replace demo cook-vs-eat |
| P2 | provider-agnostic LLM layer | valuable, but should sit on top of review pipeline |
| P2 | full hybrid orchestration | after P0/P1 data quality is ready |

---

## 7. Risk assessment summary

| Area | Main risk | Severity | Mitigation |
|---|---|---|---|
| Algorithm classifier | rule overfitting | Medium | exact vs reusable rules split |
| LLM classifier | cost/provider churn | High | adapter layer + fallback |
| Discount history | duplicated event rows | High | separate raw rows from event table |
| Expired handling | false expiration from crawl miss | Medium | grace window + last_seen_at |
| Price clustering | wrong cluster for uniform menu | Medium | IQR fallback |
| Cook-vs-eat | inaccurate ingredient mapping | High | start narrow, admin mapping tools |

---

## 8. Recommended phased implementation plan

## Phase 1 — stabilize current deterministic path

Scope:

- extend `pending_categorizations`
- extend `category_corrections`
- add correction-derived rule application
- add review screen enhancements

Deliverable:

- algorithm classifier that measurably improves from admin corrections

## Phase 2 — fix mart discount lifecycle

Scope:

- add `discount_events`
- build promotion key/upsert logic
- add active/expiring/expired/archived transitions
- add `GET /api/products/{id}/discount-history`

Deliverable:

- one-year discount history and non-destructive expired UX

## Phase 3 — improve local restaurant price quality

Scope:

- implement backend clustering service
- compute `avg_price` from `menu_data`
- return `price_summary` in `/api/local/` and `/api/restaurants/nearby`

Deliverable:

- representative restaurant price instead of naive average

## Phase 4 — replace demo cook-vs-eat

Scope:

- add recipe and ingredient tables
- ingredient-to-product mapping
- dish alias matching
- new `/api/local/dishes/{dish_slug}/compare`

Deliverable:

- real ingredient breakdown and local comparison

## Phase 5 — add optional LLM classifier

Scope:

- provider abstraction
- char-aware batch builder
- weekly scheduler
- fallback manager
- provider/model observability

Deliverable:

- hybrid classification with safe manual review gate

---

## 9. Final recommendation

If only one path is funded first:

1. **Implement Option A + correction learning first**
2. **Add discount event/lifecycle model second**
3. **Fix restaurant price clustering third**
4. **Use LLM classification only after review and observability are in place**

This order gives the best ratio of user value, implementation safety, and reuse of the current WalletSavior codebase.
