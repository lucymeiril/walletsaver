# CURRENT_STATUS.md — WalletSavior current project status

> Last verified: 2026-05-14  
> Read this with `docs\AI_HANDOFF.md` before changing AI, DB, crawler, or price logic.

## Current focus

WalletSavior is in an **AI/DB normalization phase**. The project is preparing durable product, listing, offer, and weekly comparison structures before adding more crawler sources.

The goal is trustworthy public price intelligence: users should see prices that came from real source facts, not guesses produced by AI or lossy crawler cleanup.

## Status snapshot

| Area | Status |
|---|---|
| Product goal/docs | Product goal exists in README and docs; this handoff adds current AI/DB continuation notes. |
| Shared public contracts | Implemented for Category → Canonical Product → Variant → Source Listing → Offer Event → Week Bucket. |
| Promotion semantics | Implemented with safe nullable price states and comparable-price rules. |
| AI boundaries | Implemented in contracts/tests: AI proposes labels and matches; raw source numeric facts must remain source-owned. |
| Strict matching | Implemented for human-approved source/title/package matches; source product ID alone is not identity. |
| Admin match cards | Implemented in ai-admin review routes for operator decisions. |
| DB normalized mart3 slice | Implemented and tested in db-admin models/service/tests. |
| GitHub upload readiness | Blocked pending repo-layout and tracked runtime/sensitive file cleanup. |
| Crawler expansion | Deferred until normalized AI/DB publishing is safer. |
| Scoped auth/service key | Blocked/deferred by design. |
| Source connector/readiness gap map | Implemented metadata inventory for registered connectors, skeletons, fixture diagnostics, and blocked external-service dependencies. |

## Source connector readiness gap map

This inventory is code-backed by `packages\crawler-admin\backend\crawlers\source_coverage.py`, crawler `plugin.yaml` files, and crawler-admin tests. `fixture_passing` means saved fixture or bounded diagnostic parser evidence only; it is not a live-service readiness claim.

Executable gate: every row now exposes `source_completion_gate`. Operators cannot claim a source complete unless `passed=true`; blocked, skeleton, registered-unverified, fixture-passing, and bounded-diagnostic-ready rows list exact `required_evidence` and `missing_evidence`.

| Area | Sources | Classification | Notes |
|---|---|---|---|
| mart3 | emart, homeplus, lottemart | registered_unverified; homeplus blocked_by_external_key/service | Connectors exist, but current dashboard must require quality evidence before claiming collection. Homeplus is browser/service-state dependent and live collection is disabled in metadata. |
| other mart connector | cocodalin | registered_unverified | Registered connector, not part of mart3. |
| Opinet/fuel | opinet | blocked_by_external_key/service | Registered connector; API/public-service evidence is external and not proven by fixture status. |
| hotdeal communities | algumon, arca_hotdeal, ppomppu, fmkorea, clien, quasarzone, cocodal | registered_unverified; cocodal blocked_by_external_key/service | Community connectors are registered; cocodal metadata says the site is inactive/unavailable. |
| commerce marketplace skeletons | coupang, naver_store, gmarket, 11st, aliexpress | skeleton_only, or fixture_passing when saved fixture diagnostics are attached | Skeleton adapters parse saved/mock fixtures and require bounded diagnostics plus operator approval before any live-ready or collecting claim. |
| commerce fashion | musinsa, giordano, uniqlo | registered_unverified / blocked_by_external_key/service where service/browser state is required | Connectors are registered, but no current bounded quality evidence is attached. |
| delivery/location | baemin, coupangeats, yogiyo, naver_place | blocked_by_external_key/service | Registered adapters depend on address/location context, service state, browser runtime, or provider-specific access. |

| Gate state | Evidence required before completion/live-ready claim |
|---|---|
| `blocked_by_external_key/service` | Record the external key/service/browser/location prerequisite, attach fixture/raw snapshot parser evidence, run bounded diagnostics with limits, then record operator approval. |
| `skeleton_only` | Keep fixture contract passing, attach bounded live diagnostics with run limits/evidence id, and record operator approval. |
| `registered_unverified` | Attach saved-fixture or bounded quality summary with source_raw/parsed/valid/drop/duplicate/critical-field evidence before claiming completion. |
| `fixture_passing` | Treat as parser-only evidence; add bounded diagnostics, run limits, and operator approval before live-ready or collecting claims. |
| `bounded_diagnostic_ready` | Bounded evidence exists, but completion is still blocked until operator approval and no-DB AI review requirements are recorded. |

## Key files to inspect first

| File | Why it matters |
|---|---|
| `docs\AI_HANDOFF.md` | Plain-language handoff, rules, validation commands, next work. |
| `packages\shared\core\contracts\public_catalog.py` | Public normalized catalog/pricing contract. |
| `packages\shared\core\promotion_semantics.py` | No-fake-price rules and comparable-price logic. |
| `packages\shared\core\contracts\control_plane.py` | Private control-plane contracts, match normalization, secret metadata guard. |
| `packages\ai-admin\backend\storage\models.py` | AI control DB tables including product matches. |
| `packages\ai-admin\backend\storage\repositories.py` | Strict approved match lookup behavior. |
| `packages\ai-admin\backend\api\routes\review.py` | Review/match-card API workflow. |
| `packages\db-admin\backend\storage\models.py` | Normalized DB tables for canonical products, variants, listings, offers, weeks. |
| `packages\db-admin\backend\services\normalized_mart3.py` | Current mart3 normalized publishing helper. |
| `packages\db-admin\backend\tests\test_normalized_mart3_slice.py` | Best executable example of current normalized DB behavior. |

## Working definitions for non-experts

- **Canonical product:** the real-world product name users search for.
- **Variant:** the size/count/package version of that product.
- **Source listing:** a specific store or site listing, with its own title and URL.
- **Offer event:** a price or promotion seen at a source at a point in time.
- **Week bucket:** a weekly comparison window for charting and history.
- **Comparable price:** a confirmed source price safe to compare. Hidden prices, rate-only card discounts, and unclear promotions are not comparable prices.
- **Strict match:** a remembered human-approved source listing match that still requires source, normalized title, and package agreement.
- **Matching DB:** internal operating memory for "is this the same product/listing as before?" It is not where public category/keyword facts live.

## Validation last run

```powershell
Push-Location packages\shared
py -m pytest tests\test_control_and_public_contracts.py tests\test_promotion_semantics.py
Pop-Location
```

Passed: `25 passed`.

```powershell
Push-Location packages\db-admin\backend
$env:PYTHONPATH = "..\..\shared"
py -m pytest tests\test_normalized_mart3_slice.py
Pop-Location
```

Passed: `2 passed`; existing `datetime.utcnow()` deprecation warnings remain.

```powershell
Push-Location packages\ai-admin\backend
$env:PYTHONPATH = "..\..\shared"
py -m pytest tests\test_storage.py -k strict
Pop-Location
```

Passed: `4 passed, 23 deselected`.

```powershell
py tools\one_shot_db_build_orchestrator.py --local-empty-db-rehearsal
```

Passed: fixture/stub/local in-memory rehearsal artifact reported
`overall_status=success`; this is not live crawler, live AI provider, or real
DB-admin network success.

Strict live operator readiness now uses an explicit gate and never downgrades to
fixture/stub:

```powershell
py tools\one_shot_db_build_orchestrator.py --real-readiness --crawler-batch-json <source.json> --allow-live-ai-provider --allow-live-ai-labeling --provider-id <provider> --allow-db-mutation
```

Add `--allow-live-website --website-url <url>` when website serving must be
verified. The website leg now requires semantic API round-trip evidence from
DB-admin `public_db_verification` rows; an HTTP 200 response alone blocks rather
than passing. The artifact reports each real leg, provider calls, DB
submit/final approve evidence, website verification, and exact blockers.

## Risks

- Accidentally inventing prices from AI labels or discount text would destroy trust.
- Merging listings without package checks can compare different sizes as if they are the same product.
- Deleting/rebuilding matching data can erase valuable human review history.
- Runtime DB/log/artifact files can leak local state or secrets if committed.
- Live AI validation can consume quota or expose secrets if commands are copied carelessly.
- Current git layout is risky: git root is the parent folder, while the current project lives under `walletSavior\`. Mass deletions outside `walletSavior\` may be intentional cleanup or may accidentally reshape the repository. Decide before pushing.
- `.env`, `.db`, backup DB, and log JSONL files were found as tracked files. `.gitignore` prevents new ones but does not remove files already tracked.
- The local service-key-admin override was useful for acceptance testing but must not become an accidental production auth model.

## Next work

1. Continue from tests, especially around normalized publish paths and match-card decisions.
2. Connect AI-admin reviewed outputs to DB-admin normalized tables with audit provenance.
3. Preserve nullable price states for ambiguous promotions.
4. Add deliberate scoped-auth/service-key design when unblocked.
5. Keep crawler source coverage/readiness metadata current as connectors or fixture diagnostics change.
6. Resume crawler expansion only after these data rules remain green.

## GitHub upload status

Do not force-push yet.

Current facts:

- Git root: `E:\pdf\capston01`
- Current project folder: `E:\pdf\capston01\walletSavior`
- Branch under work: `feature/monorepo-restructure`
- Remote: `https://github.com/lucymeiril/walletSavior.git`
- Upload hygiene updated `.gitignore`, but tracked sensitive/runtime files still need index cleanup.

Safe upload path:

1. Decide whether GitHub should contain the current nested `walletSavior\` folder or whether its contents should become repository root.
2. Remove tracked runtime/sensitive files from the index before commit.
3. Push a feature branch first. Do not force-push `main`.
4. Only merge after checking GitHub diff for accidental deletion of useful source files or accidental inclusion of env/db/log artifacts.

