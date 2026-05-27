# Round V DB Stability Report

## Changes
- Enabled SQLite 30s connection timeout, `check_same_thread=False`, `pool_pre_ping=True`.
- Enabled SQLite WAL pragmas on connect: `journal_mode=WAL`, `busy_timeout=30000`, `synchronous=NORMAL`.
- Raised DB Admin request body middleware limit to 100MB.
- Added server-side ingestion safety chunking: incoming `/api/ingestions` payloads are stored as 1,000-item pending-ingestion chunks.
- Changed `/api/ingestions/bulk-approve` to commit every 100 IDs and retry transient SQLite `database is locked` errors.
- Increased bulk approve request cap to 1,000 IDs.

## Manual PRAGMA
```text
('wal',) (30000,) (1,)
```

## Verification
- `py -3 -m pytest tests\test_db_engine.py tests\test_error_handling.py -q` → 18 passed.
- `py -3 -m pytest tests\test_ingestion_insert.py -q` → 20 passed.
- Smoke: POST `/api/ingestions` with 1,000 fake records → 200, pending row created.
- Smoke: POST `/api/ingestions/bulk-approve` with 1,000 fake IDs → 200, approved=1000, chunks_committed=10.
- Smoke: held one SQLite `BEGIN IMMEDIATE` writer while another writer waited; writer completed after release with no `database is locked` error.

## Notes
- Uvicorn does not expose a stable `--limit-max-http-body` option in this environment; the existing FastAPI middleware is the enforced 100MB body guard.
- Client-side chunking remains recommended; server-side 1,000-record chunking is the backend safety net.
