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

Current green baseline after the audit:

- Python: crawler-admin 213 passed / 1 live skipped, db-admin 261 passed,
  shared 153 passed, web-api 60 passed (687 passed total).
- Frontend: public web 115, crawler admin 17, DB admin 16 (148 passed total).
- All three production frontend builds complete successfully.
