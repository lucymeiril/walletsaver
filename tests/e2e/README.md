# WalletSavior E2E Tests

## Prerequisites

1. All **6 servers** running (`start-all.ps1` or `docker-compose up`)
2. `py` (Python 3.10+) on PATH with `sqlalchemy`, `passlib[bcrypt]` installed
3. Environment variables (defaults work for dev):

```powershell
$env:REQUIRE_AUTH = 'true'
$env:CRAWLER_ADMIN_API_KEY = 'ws-crawler-admin-test-key'
```

## Quick Start

```powershell
# 1. Start all servers
.\start-all.ps1

# 2. Wait ~15 seconds, then run tests
powershell -ExecutionPolicy Bypass -File tests\e2e\run_e2e.ps1
```

## Files

| File | Purpose |
|------|---------|
| `run_e2e.ps1` | Main test runner — health checks, seed, P0 tests, summary |
| `seed_data.py` | Standalone DB seed — creates categories, products, prices, QA user |
| `README.md` | This file |

## Seed Only

```powershell
py tests\e2e\seed_data.py          # idempotent
py tests\e2e\seed_data.py --force  # re-seed
```

## Test Coverage (P0)

| # | Test | What it verifies |
|---|------|------------------|
| 1 | Health checks | All 6 services respond |
| 2 | DB-admin login | JWT token issuance |
| 3 | Crawler-admin auth | X-API-Key enforcement + SSE exception |
| 4 | Website auth | Cookie login → refresh → /me |
| 5 | Ingestion pipeline | no-auth 401 → auth 200 → detail → crawler-review → db-review → DB verify |
| 6 | Search reflection | Approved data appears in website search |
| 7 | Cart | add → fetch → field contract |
| 8 | Wishlist | add → fetch → price_at_add / current_price |
| 9 | Profile | GET → PUT → DELETE (soft) → relogin blocked |
| 10 | Activity | track → rate_limited on duplicate |
| 11 | Community | Post with product_id → DB verify |
| 12 | Search | autocomplete structured shape + submit |
| 13 | Dashboard | Aggregate shape (hotdeals, categories, etc.) |

## Output Format

Each test prints:
- `✅ PASS: description` on success
- `❌ FAIL: description` on failure

A summary block at the end shows totals and lists all failures.

## Exit Code

- `0` — all tests passed
- `1` — at least one failure
