# AI_HANDOFF.md — WalletSavior durable handoff

> Last verified: 2026-05-14  
> Purpose: let another computer or agent continue the project if task/session context is lost.

## 1. Plain-language product goal

WalletSavior answers: **"Is this price really cheap?"**

It collects grocery, mart, hotdeal, public price, gas, and local price information, then turns it into trustworthy comparisons for normal users. The system must protect users from misleading discounts, viral hotdeal posts, hidden checkout conditions, and fake "average" prices.

The current short-term goal is **not** adding many new crawlers. The priority is finishing the AI/DB normalized data architecture so future crawlers can publish clean, comparable data without corrupting the price database.

## 2. Repository map

| Area | Role |
|---|---|
| `packages\website` | Public user website and API: hotdeals, price comparison, mart sales, community, nearby prices. |
| `packages\crawler-admin` | Internal crawler control plane: source health, schedules, crawler outputs, operator workflow. |
| `packages\ai-admin` | Internal AI review/control plane: labels raw source rows, creates proposals, tracks provider aliases, review decisions, and match cards. |
| `packages\db-admin` | Internal DB management and publishing layer: turns approved/reviewed rows into public catalog and pricing tables. |
| `packages\shared` | Shared contracts, promotion semantics, AI pipeline models, public catalog contracts, control-plane contracts. |
| `packages\integration-tests`, `packages\user-tests`, `packages\security-perf-tests` | Cross-service, user-flow, security, and performance tests. |
| `docs` | Human and AI project documentation. Start with this file and `docs\CURRENT_STATUS.md`. |

## 3. Current AI/DB architecture in simple terms

The project separates "what a product is" from "where it was seen" and "what price was seen":

1. **Category** — the browsing/comparison group, e.g. `유제품 > 우유 > 초코우유`. This is not the product itself.
2. **Canonical Product** — the stable product concept, e.g. `초코에몽`, `행복생생란`, `신라면`.
3. **Variant** — package/volume/count, e.g. `300mL 1입`, `300mL 24입`, `1.8kg 30입`.
4. **Source Listing** — a source-owned listing at E-Mart/Homeplus/Lotte/etc. This owns source title, current/latest source URL, and source record key. Representative product images should live on product/listing records and should not be re-saved weekly.
5. **Offer Event** — a source-owned price or promotion fact. This owns price state, promotion type, raw evidence references, and source-observed facts.
6. **Week Bucket** — a comparison period. Offer events link to weeks without copying product fields everywhere.

This structure prevents common bad merges, such as treating a 300g tofu listing as the same price unit as a 500g tofu listing, or copying a stale mart URL onto the canonical product itself.

## 4. Critical data rules

- **No fake prices.** If a source hides price, only gives a discount rate, or has unclear checkout conditions, store nullable price facts instead of inventing `0`, estimated, or "after discount" prices.
- **Raw source facts win.** AI may classify, propose, normalize, or flag records, but it must not invent source numeric facts such as current price, original price, source URL, event period, image evidence, quantity, or discount rate.
- **Promotion semantics matter.** `final_price`, `was_now_price`, `bundle_price`, `checkout_discount`, `buy_x_get_y`, `rate_off_unclear`, and `unknown` are not interchangeable.
- **Matching DB must be preserved.** Human-approved strict matches are valuable memory. Do not wipe or rebuild them casually.
- **Strict matching is source/title/package based.** Approved allowed title patterns plus package/count signature are the primary match evidence. Source product ID is supporting evidence and must not auto-match by itself.
- **Baseline prices must not be polluted.** Hotdeal prices and temporary discounts cannot be averaged into normal baseline prices.
- **Do not commit runtime artifacts.** Keep `node_modules`, `_archive`, local DB files, logs, generated crawler artifacts, `.walletsavior-crawler`, and other runtime outputs out of commits.
- **Do not print or commit secrets.** Provider `secret_alias` values are names only; real API keys belong in local `.env` or process environment.
- **Service-key override is not a product feature.** A local service-key-admin override was used to unblock live DB mutation acceptance. Do not ship it blindly. Revisit scoped publishing auth deliberately before deployment.

## 5. What was just implemented before this handoff

Recent completed slices:

- Public normalized hierarchy contracts in `packages\shared\core\contracts\public_catalog.py`.
- Shared promotion/price safety semantics in `packages\shared\core\promotion_semantics.py`.
- Control-plane strict matching normalization and secret-bearing metadata validation in `packages\shared\core\contracts\control_plane.py`.
- AI-admin strict product match schema and lookup behavior in `packages\ai-admin\backend\storage\models.py` and `packages\ai-admin\backend\storage\repositories.py`.
- Admin match-card workflow in `packages\ai-admin\backend\api\routes\review.py`.
- Deterministic canonical/variant proposal worker behavior in `packages\ai-admin\backend\workers\canonical_matcher.py`.
- DB-admin normalized mart3 projection in `packages\db-admin\backend\storage\models.py` and `packages\db-admin\backend\services\normalized_mart3.py`.
- Tests proving hidden/rate-only prices stay nullable, package mismatches do not silently merge, and week buckets reuse normalized offer events.

## 6. Verified validation commands

These commands passed in this handoff session on Windows with Python 3.13.2. Prefer `py` on Windows; `python` may not be on PATH.

```powershell
Push-Location packages\shared
py -m pytest tests\test_control_and_public_contracts.py tests\test_promotion_semantics.py
Pop-Location
```

Result: `25 passed`.

```powershell
Push-Location packages\db-admin\backend
$env:PYTHONPATH = "..\..\shared"
py -m pytest tests\test_normalized_mart3_slice.py
Pop-Location
```

Result: `2 passed` with existing `datetime.utcnow()` deprecation warnings.

```powershell
Push-Location packages\ai-admin\backend
$env:PYTHONPATH = "..\..\shared"
py -m pytest tests\test_storage.py -k strict
Pop-Location
```

Result: `4 passed, 23 deselected`.

Broader validation also passed after the AI/DB fleet work:

```powershell
Push-Location packages\shared
py -m pytest -q
Pop-Location
```

Result: `186 passed`.

```powershell
Push-Location packages\ai-admin\backend
py -m pytest -q
Pop-Location
```

Result: `311 passed, 1 skipped`.

```powershell
Push-Location packages\db-admin\backend
py -m pytest tests\test_normalized_mart3_slice.py tests\test_models.py tests\test_ingestion_insert.py tests\test_price_calc.py -q
Pop-Location
```

Result: `86 passed` with existing `datetime.utcnow()` deprecation warnings.

```powershell
Push-Location packages\ai-admin\frontend
npm test -- --runInBand
npm run build -- --mode production
Pop-Location

Push-Location packages\db-admin\frontend
npm run build -- --mode production
Pop-Location
```

Result: AI-admin frontend tests/build passed; DB-admin frontend production build passed.

## 7. Known blocked or deferred work

- **Scoped-auth service-key redesign is intentionally blocked/deferred.** Do not quickly patch around it with weaker auth.
- **Crawler source health/calendar baselines are future work.** Do not treat them as finished.
- Public crawler expansion is lower priority until normalized AI/DB publishing remains stable.
- Live AI provider validation depends on local non-secret provider configuration and quota. Do not assume a passing health check proves provider availability.
- Some older status docs are stale relative to the normalized AI/DB work. Prefer `docs\CURRENT_STATUS.md` for current handoff status.
- GitHub upload is currently blocked pending a repository-layout decision. The Git root is `E:\pdf\capston01`, while the current project is nested under `E:\pdf\capston01\walletSavior`. Do not force-push `main` until this is resolved.
- Tracked runtime/sensitive files existed before upload hygiene: `.env`, `.db`, backup DBs, and log JSONL files. They must be removed from the index/history as appropriate before publishing a clean snapshot.

## 8. Next recommended work

1. Add/update tests before extending normalized publishing beyond the mart3 slice.
2. Wire reviewed AI-admin decisions into DB-admin normalized tables through explicit, auditable publish paths.
3. Expand match cards only in ways that preserve human-approved strict match memory.
4. Add source health/calendar baselines after the normalized offer/week model is stable.
5. Revisit scoped-auth service-key design as a deliberate security task, not as an incidental fix.
6. Only then expand new crawlers, starting with sources that provide enough raw evidence for safe price states.

## 9. Adversarial continuation checklist

Before trusting any future agent report, verify these directly:

1. **DB rows, not just API status.** For normalized publishing, inspect tables to confirm static product/category/image data is not duplicated weekly and offer events link to week buckets correctly.
2. **No fake comparable price.** Hidden price, discount-rate-only, card/coupon, 1+1, 2+1, and unknown promotion rows must not appear in default numeric price sorting.
3. **Strict match behavior.** A title match with a different package/count must become a candidate/new variant, not an automatic merge.
4. **AI source-fact boundary.** If AI proposes a different price/link/period/image than raw source evidence, source evidence must win or the row must be held.
5. **Git hygiene.** Run a tracked-file audit before commit:

   ```powershell
   git --no-pager ls-files | Where-Object { $_ -match '(^|/)(\.env|.*\.env|.*\.env\.local)$|\.db$|\.log$|(^|/)logs/|(^|/)backups/' }
   ```

6. **Repo layout.** Confirm whether the intended GitHub layout is repository root files or the nested `walletSavior\` folder before staging mass deletions/additions.

