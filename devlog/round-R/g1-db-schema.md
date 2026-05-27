# Round R G1 DB schema evidence

## DB path discovery

- `packages\db-admin\backend\config.py` sets default DB URL to `sqlite:///` + `BASE_DIR / 'walletguardian.db'`.
- Dev SQLite path used: `packages\db-admin\backend\walletguardian.db`.

## Requested sqlite3 commands

```powershell
sqlite3 "packages\db-admin\backend\walletguardian.db" ".schema products"
sqlite3 "packages\db-admin\backend\walletguardian.db" ".schema price_history"
sqlite3 "packages\db-admin\backend\walletguardian.db" "SELECT mart, COUNT(*) FROM products WHERE mart IS NOT NULL GROUP BY mart"
```

Result: `sqlite3` CLI is not installed in this Windows environment, so the same SQLite file was dumped with Python `sqlite3`.

## Schema output

```sql
--- .schema products ---
CREATE TABLE "products" (
	id INTEGER NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	category_id VARCHAR(100), 
	unit VARCHAR(50) NOT NULL, 
	description TEXT, 
	image_url VARCHAR(500), 
	attributes JSON, 
	is_active BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	source_type VARCHAR(20) DEFAULT 'unknown', 
	categorization_confidence FLOAT, 
	categorization_method VARCHAR(20), 
	brand VARCHAR(200), 
	name_core VARCHAR(500), 
	pack_qty FLOAT, 
	pack_unit VARCHAR(50), 
	unit_kind VARCHAR(20), 
	display_name VARCHAR(400), 
	source_marts JSON, 
	aliases JSON, 
	canonical_product_id INTEGER, mart VARCHAR(20), mart_native_code VARCHAR(64), canon_hash VARCHAR(40), external_seller BOOLEAN, unit_price_displayed FLOAT, unit_price_basis_raw VARCHAR(16), mart_native_category_id VARCHAR(64), mart_native_category_path VARCHAR(500), canonical_url VARCHAR(500), mart_internal_seller_id VARCHAR(64), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_product_canonical UNIQUE (brand, name_core, pack_qty, pack_unit), 
	FOREIGN KEY(category_id) REFERENCES categories (id)
);
CREATE INDEX ix_products_brand ON products (brand);
CREATE INDEX ix_products_canon_hash ON products (canon_hash);
CREATE INDEX ix_products_canonical_product_id ON products (canonical_product_id);
CREATE INDEX ix_products_category ON products (category_id);
CREATE INDEX ix_products_mart ON products (mart);
CREATE INDEX ix_products_mart_native ON products (mart, mart_native_code);
CREATE INDEX ix_products_mart_native_category_id ON products (mart_native_category_id);
CREATE INDEX ix_products_mart_native_code ON products (mart_native_code);
CREATE INDEX ix_products_name ON products (name);
CREATE INDEX ix_products_name_core ON products (name_core);
CREATE INDEX ix_products_source_type ON products (source_type);
CREATE INDEX ix_products_unit_kind ON products (unit_kind);
--- .schema price_history ---
CREATE TABLE price_history (
	id INTEGER NOT NULL, 
	mart VARCHAR(20) NOT NULL, 
	canon_key VARCHAR(64) NOT NULL, 
	observed_at DATETIME NOT NULL, 
	price FLOAT NOT NULL, 
	sale_price FLOAT, 
	unit_price FLOAT, 
	period_start DATETIME, 
	period_end DATETIME, 
	source_run_id VARCHAR(64), 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_price_history_mart_canon_observed UNIQUE (mart, canon_key, observed_at)
);
CREATE INDEX ix_price_history_canon_key ON price_history (canon_key);
CREATE INDEX ix_price_history_mart ON price_history (mart);
CREATE INDEX ix_price_history_mart_canon_observed ON price_history (mart, canon_key, observed_at DESC);
CREATE INDEX ix_price_history_observed_at ON price_history (observed_at);
```

## Mart count query

```text
PENDING g1-seed — query returned no rows.
```

## Alembic current

Command: `cd packages\db-admin\backend; py -3 -m alembic current`

```text
b2c3d4e5f6a7 (head)
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
```
