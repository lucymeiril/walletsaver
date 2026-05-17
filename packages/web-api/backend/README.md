# WalletSavior Public Read API (Phase E1)

Read-only FastAPI service over `.walletsavior/public_snapshot.sqlite`.

## Endpoints

- `GET /api/v1/health` — snapshot status, canonical_count, generated_at
- `GET /api/v1/categories` — hierarchical category tree
- `GET /api/v1/products/search` — search with `q`, `category`, `page`, `page_size`, `sort=hot_deal|price_asc|price_desc|recent`
- `GET /api/v1/products/{canonical_id}` — detail with price_grade + mart_aliases
- `GET /api/v1/autocomplete?prefix=...&limit=10` — prefix suggestions

## Install & Run

```powershell
cd packages\web-api\backend
py -3 -m pip install -r requirements.txt
py -3 -m uvicorn api.app:app --host 0.0.0.0 --port 8200 --reload
```

## Environment

- `WALLETSAVIOR_PUBLIC_DB` — override snapshot SQLite path (default `<repo>/.walletsavior/public_snapshot.sqlite`)
- `WALLETSAVIOR_CORS_ORIGINS` — comma-separated allowed origins (default `http://localhost:5173`)

## Tests

```powershell
cd packages\web-api\backend
py -3 -m pytest -q
```

Tests use an isolated mini-snapshot built in `tests/conftest.py` (no dependency on the real snapshot).
