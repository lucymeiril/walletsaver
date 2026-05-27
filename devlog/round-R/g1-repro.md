# Round R G1 reproduction commands

Run from repository root `E:\pdf\capston01` unless noted.

## Setup / schema
```powershell
cd packages\db-admin\backend; $env:DATABASE_URL='sqlite:///walletguardian.db'; py -3 -m alembic upgrade head; py -3 -m alembic current; cd ..\..\..
```

## Per-mart crawler tests
```powershell
py -3 -m pytest packages\crawler-admin\backend\tests -q -k emart
py -3 -m pytest packages\crawler-admin\backend\tests -q -k homeplus
py -3 -m pytest packages\crawler-admin\backend\tests -q -k lottemart
py -3 -m pytest packages\crawler-admin\backend\tests -q -k costco
```

## Seed / price-history backfill
```powershell
py -3 -m crawler_admin.backend.scripts.round_r_g1_seed
py -3 -m crawler_admin.backend.cli.cocodalin_seed --source packages\crawler-admin\backend\tests\fixtures\cocodalin\seed_sample.json --dry-run --database-url sqlite:///packages\db-admin\backend\walletguardian.db
```

Note: `g1-seed-report.md` was missing at consolidation time, so the 4-mart live seed remains PENDING until that script/report lands.

## Validate DB evidence
```powershell
sqlite3 packages\db-admin\backend\walletguardian.db ".schema products"
sqlite3 packages\db-admin\backend\walletguardian.db ".schema price_history"
sqlite3 packages\db-admin\backend\walletguardian.db "SELECT mart, COUNT(*) FROM products WHERE mart IS NOT NULL GROUP BY mart"
cd packages\db-admin\backend; $env:DATABASE_URL='sqlite:///walletguardian.db'; py -3 -m alembic current
```

If `sqlite3` is unavailable on Windows, use:
```powershell
py -3 -c "import sqlite3; con=sqlite3.connect(r'packages\db-admin\backend\walletguardian.db'); print(con.execute(\"SELECT mart, COUNT(*) FROM products WHERE mart IS NOT NULL GROUP BY mart\").fetchall())"
```
