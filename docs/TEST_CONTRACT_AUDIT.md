# Test contract audit (2026-08-30)

The capstone stabilization treats tests as candidate contracts, not as an
instruction to restore retired architecture.

| Failure group | Classification | Resolution |
| --- | --- | --- |
| crawler ingestion id required an `ingrun-` prefix | Architecture-updated test | Keep the id opaque; assert non-empty and fresh identity only. |
| raw export returned 500/403 without the crawler admin key | Environment fixture | Preserve production authentication and provide the test key in the fixture. |
| DB `busy_timeout` expected 30s while the engine policy is 60s | Architecture-updated test | Assert the current 60s contention policy. |
| bulk and ingestion limits used historical literal values | Architecture-updated test | Assert `MAX_* + 1` so the security contract survives intentional limit changes. |
| suggested/ad-hoc category leaked through public reads | Actual regression | Hide review-only categories and exclude them from category aggregation. |
| unknown crawler category created a fake category row | Actual regression | Never create taxonomy nodes during row ingestion; leave the row in review. |
| web health omitted the external-hotdeal snapshot field | Architecture-updated test | Include the current split-storage health contract. |
| missing `JWT_SECRET_KEY` during web-api collection | Environment fixture | Test command supplies a non-production secret; runtime remains fail-closed. |
| crawler UI expected removed `retryLastFailed` client/API | Retired legacy behavior | Replaced with tests for the current explicit Lotte WAF-hold retry contract; fixed the store projection that dropped hold counts. |

Any deleted legacy test must be replaced by a behavior-level test for the
current normalized category/product contract before removal.

2026-09-03 additions:

- Auth API fixtures used the configured developer SQLite DB and failed after
  the keyword schema changed. Classified as an environment/fixture defect:
  isolate API tests in temporary SQLite databases; do not weaken the schema.
- `/auth/me` with a token for nonexistent user 999 previously had a conditional
  assertion that silently passed on 404. Replace it with a real-user 200 test
  and a separate missing-user 404 test, matching the existing route contract.
- Same offer imported from a later ingestion overwrote prior raw evidence.
  Actual regression: union observation provenance and test repeat imports.
- Initial catalog regression fixtures cover leaf-only topology, row accounting,
  idempotent imports, ambiguous package/brand/promotion review, and preservation
  of original source payloads. Generated fixtures never become public data.
- Matching import API's old fixture depended on host authentication settings.
  Environment/fixture defect: keep the moderator-only production contract, use
  the isolated service DB and explicit test credentials, and cover 401/403 plus
  no database access for unauthorized requests. Settings are read per request;
  a single client's key rotation test rules out stale TestClient auth caching.
- Normalized matching export omitted product/variant IDs. Actual regression:
  preserve both IDs in YAML/JSONL/CSV; missing columns in older files mean keep
  existing values, whereas explicit null is still a clear under the trust policy.

Earlier green baseline after the initial audit (not the latest test count):

- Python: crawler-admin 213 passed / 1 live skipped, db-admin 261 passed,
  shared 153 passed, web-api 60 passed (687 passed total).
- Frontend: public web 115, crawler admin 17, DB admin 16 (148 passed total).
- All three production frontend builds complete successfully.

Latest 2026-09-03 suites: DB-admin 529 passed, crawler-admin 274 passed / 1 live
deselected, web-api 67 passed. Crawler-admin frontend: 18 passed and production
build successful. Do not sum focused subsets with full suites.
See `RESUME_CHECKPOINT.md` for the current real-data rehearsal and follow-up
verification, which are separate from unit-test and fixture counts.

Later 2026-09-03 actual regressions (not obsolete test contracts):

- Normalized runtime/export trusted a matching key even for a changed original
  title, new listing or conflicting package. Require the original source
  listing/title plus an active variant belonging to the exact target product;
  preserve semantic misses in exports instead of reclassifying by key alone.
- Count ranges and unparsed mixed/multiplied packages were treated as fixed
  quantities. Stage them for review without offers/rules; explicit fixed mass
  with variable piece count remains mass-based. Retail T-count handling and
  ea/개입 equivalence are covered at the runtime package boundary.
- Public readers already excluded pending-review prices, but the snapshot file
  copied them. Exclude only those offers and their week links, and reject mixed
  snapshots at both local and remote validation boundaries. Preserve inactive
  products and non-pending historical states; keep the existing rollback test.
