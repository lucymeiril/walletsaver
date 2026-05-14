# DB Admin Security Audit — Architecture Level

> **Audit Date**: 2025-07-18
> **Scope**: `packages/db-admin` (FastAPI backend on :8002, React frontend on :5175)
> **Auditor**: Automated Architecture Security Review
> **Total Endpoints Analyzed**: 64 across 9 routers
> **Overall Risk Rating**: **CRITICAL** — System is not production-ready without remediation

---

## Table of Contents

1. [Critical Design Issues](#critical-design-issues)
2. [High Priority Issues](#high-priority-issues)
3. [Medium Priority Issues](#medium-priority-issues)
4. [Low Priority Issues](#low-priority-issues)
5. [Recommended Security Architecture](#recommended-security-architecture)
6. [Summary & Remediation Roadmap](#summary--remediation-roadmap)

---

## Critical Design Issues

### Issue 1: Complete Absence of Authentication

- **Risk**: CRITICAL
- **Current State**: All 64 API endpoints are publicly accessible. No authentication middleware, no JWT validation, no session management, no API key checks exist anywhere in the codebase. The `User` model with `hashed_password` and `UserRole` enum (user/admin/moderator) are defined in `storage/models.py` but never referenced by any route or middleware. The frontend has no login page, no auth guards, no token storage.
- **Threat**: Any network-reachable client can perform full CRUD on all product data, trigger database resets (`POST /api/admin/reset-all`), bulk-delete products, approve crawler ingestions, and export all data. An attacker on the same network (or the internet, if exposed) has unrestricted administrative access to the entire database.
- **Recommendation**:
  1. Implement JWT-based authentication middleware as a FastAPI dependency (`Depends(get_current_user)`)
  2. Add login endpoint that validates credentials against the existing `User` table
  3. Issue short-lived access tokens (15 min) with refresh tokens (7 days)
  4. Add `Authorization: Bearer <token>` header requirement to all routes except `/health`
  5. Add auth guard wrapper in the React frontend that redirects to login when no valid token exists
- **Implementation Effort**: High (2–3 weeks for full auth flow including frontend)

### Issue 2: Unrestricted CORS with Credentials

- **Risk**: CRITICAL
- **Current State**: CORS middleware is configured as:
  ```python
  CORSMiddleware(
      allow_origins=["*"],
      allow_credentials=True,
      allow_methods=["*"],
      allow_headers=["*"],
  )
  ```
  This is the most permissive CORS configuration possible. Combined with `allow_credentials=True`, this creates a direct CSRF vector.
- **Threat**: A malicious website can make authenticated cross-origin requests to the DB Admin API. If a user with network access to the admin panel visits a crafted page, JavaScript on that page can issue `DELETE /api/admin/reset-all` or `POST /api/products/bulk-delete` requests that the browser will execute with full permissions. The wildcard origin with credentials is explicitly forbidden by the CORS specification for good reason — browsers may reject it, but this signals dangerous intent and misconfiguration.
- **Recommendation**:
  1. Replace `allow_origins=["*"]` with explicit allowed origins: `["http://localhost:5175", "http://127.0.0.1:5175"]`
  2. In production, set origins to the actual admin panel domain only
  3. Load allowed origins from environment variable `CORS_ALLOWED_ORIGINS`
  4. Consider removing `allow_credentials=True` if not using cookie-based auth
- **Implementation Effort**: Low (< 1 hour)

### Issue 3: Destructive Admin Operations Lack Multi-Factor Protection

- **Risk**: CRITICAL
- **Current State**: Three endpoints can destroy the entire database:
  - `POST /api/admin/reset-source` — deletes all data for a source (requires `DELETE_<SOURCE>`)
  - `POST /api/admin/reset-products` — deletes all products and prices (requires `DELETE_ALL_PRODUCTS`)
  - `POST /api/admin/reset-all` — wipes the entire database (requires `RESET_ALL_DATA`)

  The only protection is a confirmation string that must match exactly. There is no authentication, no rate limiting, no audit trail beyond a `logger.warning()` call, and no backup-before-delete mechanism.
- **Threat**: Since there is no authentication, any HTTP client can send `POST /api/admin/reset-all` with `{"confirm": "RESET_ALL_DATA"}` and the entire database is wiped. The confirmation strings are static and predictable — they can be discovered from frontend source code (`AdminResetModal.jsx`). Even with authentication, a single compromised admin account or XSS vulnerability enables complete data destruction with no recovery path.
- **Recommendation**:
  1. Require authentication with `admin` role for all `/api/admin/*` routes
  2. Implement mandatory database backup before any destructive operation
  3. Add time-delayed execution (e.g., 30-second cooldown with cancel option)
  4. Require re-authentication (password re-entry) for destructive operations
  5. Add per-IP rate limiting on admin endpoints (max 3 attempts per hour)
  6. Log all admin operations to a separate, append-only audit table
  7. Consider soft-delete with configurable retention period instead of hard deletes
- **Implementation Effort**: Medium (1–2 weeks)

### Issue 4: No Network Isolation — Admin Panel Binds to 0.0.0.0

- **Risk**: CRITICAL
- **Current State**: The backend binds to `0.0.0.0` via `uvicorn.run("main:app", host="0.0.0.0", port=8002)`, meaning it accepts connections from any network interface. The frontend Vite dev server also accepts all connections. There is no reverse proxy, firewall rule, or IP whitelist configured for the db-admin service. The `docker-compose.yml` does not include db-admin as a service, suggesting it runs outside Docker directly on the host machine.
- **Threat**: If the host machine has a public IP or is on a shared network, the admin panel is accessible to anyone who can reach port 8002 or 5175. Combined with the lack of authentication, this means the database is fully exposed. Even on internal networks, lateral movement from a compromised host gives an attacker complete database control.
- **Recommendation**:
  1. Bind to `127.0.0.1` instead of `0.0.0.0` for local-only access
  2. Add db-admin to `docker-compose.yml` as an internal service (no exposed ports)
  3. Route external access through nginx reverse proxy with IP whitelist
  4. Implement VPN-only access for production admin panel
  5. Add the admin panel to the existing Docker network (`walletSavior-network`) as an internal-only service
- **Implementation Effort**: Low (2–4 hours)

---

## High Priority Issues

### Issue 5: No Rate Limiting on Any Endpoint

- **Risk**: HIGH
- **Current State**: No rate limiting library is installed (`requirements.txt` contains no `slowapi`, `limits`, or similar). All 64 endpoints can be called unlimited times per second. Bulk operations (`bulk-delete`, `bulk-approve`, `bulk-category`) have no throttling. Dashboard and analytics endpoints have TTL caching (60s/120s) but no request-rate limits.
- **Threat**:
  - **DoS attack**: Rapid requests to expensive endpoints like `/api/analytics/quality-report` (full DB scan) or `/api/analytics/duplicates` (cross-table joins) can exhaust DB connections and crash the service
  - **Data manipulation**: Automated scripts can bulk-delete thousands of products per second
  - **Resource exhaustion**: Unlimited CSV/JSON export requests (`/api/prices/export`, `/api/analytics/export/*`) can consume all server memory and bandwidth
- **Recommendation**:
  1. Install `slowapi` and add global rate limiting (100 requests/minute per IP)
  2. Add stricter limits on destructive endpoints (5/minute for delete operations)
  3. Add stricter limits on export endpoints (10/minute)
  4. Add per-user rate limiting once authentication is implemented
- **Implementation Effort**: Low (2–4 hours)

### Issue 6: Inter-Service Communication is Unauthenticated

- **Risk**: HIGH
- **Current State**: The crawler submits data to db-admin via `POST /api/ingestions` with no authentication. The ingestion endpoint accepts any JSON payload with a `crawler_name` string — there is no verification that the request actually comes from a legitimate crawler service. The website and other services can also query db-admin APIs freely.
- **Threat**:
  - **Data poisoning**: An attacker can submit fake crawl data with fabricated prices, creating incorrect price baselines and misleading discount calculations
  - **Impersonation**: Any client can claim to be any `crawler_name` (e.g., "emart_crawler") and inject malicious data
  - **Pipeline corruption**: Bulk-approved fake ingestions get inserted into production tables via `BackgroundTasks`, contaminating the entire price database
- **Recommendation**:
  1. Implement service-to-service authentication using pre-shared API keys or mutual TLS
  2. Each crawler should have a unique API key stored as an environment variable
  3. Validate `crawler_name` against a whitelist of registered crawlers
  4. Add request signing (HMAC) for ingestion payloads to detect tampering
  5. Implement IP allowlisting for known crawler service IPs in Docker network
- **Implementation Effort**: Medium (1 week)

### Issue 7: SQLite Concurrency and File Security

- **Risk**: HIGH
- **Current State**: Development uses SQLite (`sqlite:///walletguardian.db`) with `check_same_thread=False` and `StaticPool`. The database file (`walletguardian.db`) exists at the project root with standard user permissions. SQLite uses file-level locking — concurrent writes are serialized, and long transactions can block all other writes. There is no encryption at rest.
- **Threat**:
  - **Concurrent write failures**: Multiple API requests writing simultaneously can cause `database is locked` errors, especially during bulk operations
  - **File access**: Anyone with filesystem access to the host can copy, modify, or delete the `.db` file directly, bypassing all application-level controls
  - **No encryption**: Database contents (product data, prices, potentially sensitive business data) are stored in plaintext on disk
  - **Backup risk**: The `.db` file can be corrupted if copied while a write transaction is in progress
- **Recommendation**:
  1. Use PostgreSQL for production (already configured in `docker-compose.yml` as `walletsavior-db`)
  2. For SQLite development: enable WAL mode (`PRAGMA journal_mode=WAL`) for better concurrency
  3. Set restrictive file permissions on the `.db` file (`chmod 600`)
  4. Add `.db` files to `.gitignore` (prevent accidental commits of data)
  5. For production PostgreSQL: use SSL connections, encrypted storage volumes, and least-privilege DB users
- **Implementation Effort**: Low for WAL mode; Medium for full PostgreSQL migration

### Issue 8: Ingestion Pipeline Data Validation is Insufficient

- **Risk**: HIGH
- **Current State**: The ingestion pipeline performs quality scoring but does not reject malicious payloads. The `validate_crawl_data()` function checks for required fields and types but does not sanitize values. The `items_json` field in `PendingIngestion` stores raw crawler output as a large JSON string with no size limit. Quality scores are informational — they do not block ingestion.
- **Threat**:
  - **JSON bomb**: A crawler (or attacker impersonating one) can submit a multi-GB JSON payload, exhausting server memory
  - **Price manipulation**: Submitting extreme prices (e.g., $0.01 for a $100 product) can skew baseline calculations since the IQR outlier detection only runs on query, not on insert
  - **Stored XSS**: Product names, URLs, or description fields from crawler data are stored without sanitization and could contain script tags that execute when rendered in the admin frontend
  - **SQL injection via raw_data**: The `raw_data` JSON field stores arbitrary crawler data — while SQLAlchemy's ORM prevents direct SQL injection, JSON fields queried with raw SQL could be vulnerable
- **Recommendation**:
  1. Enforce maximum payload size (e.g., 10MB) at the ASGI server level
  2. Validate and sanitize all string fields (strip HTML tags, limit length)
  3. Enforce price range validation (e.g., reject prices < $0.01 or > $1,000,000)
  4. Auto-reject ingestions with quality scores below a configurable threshold
  5. Add URL validation for `source_url` and `image_url` fields (allowlist of domains)
  6. Implement content-type validation for all incoming data
- **Implementation Effort**: Medium (1 week)

### Issue 9: No Audit Trail for Data Modifications

- **Risk**: HIGH
- **Current State**: Admin reset operations log to Python's `logging` module at WARNING level, but there is no persistent audit trail. Product CRUD operations (create, update, delete), category changes, keyword modifications, price bulk inserts, and ingestion approvals are not logged at all. The `CrawlLog` table tracks crawler activity but not admin actions. There is no way to answer "who deleted product X and when?" or "who approved ingestion Y?"
- **Threat**:
  - **Untraceable data loss**: If products are accidentally or maliciously deleted, there is no record of what was deleted, when, or by whom
  - **Compliance risk**: No ability to produce audit reports for data governance
  - **Incident response**: After a security incident, there is no forensic evidence of what actions were taken
  - **Insider threat**: A malicious admin can modify data and cover their tracks
- **Recommendation**:
  1. Create an `audit_log` table: `(id, timestamp, user_id, action, entity_type, entity_id, old_value, new_value, ip_address)`
  2. Add audit logging middleware that captures all write operations
  3. Make the audit table append-only (no UPDATE or DELETE permissions for the application user)
  4. Log at minimum: all DELETE operations, all admin/* operations, all bulk operations, all ingestion approvals
  5. Implement log rotation and archival strategy
- **Implementation Effort**: Medium (1 week)

---

## Medium Priority Issues

### Issue 10: No HTTPS/TLS Enforcement

- **Risk**: MEDIUM
- **Current State**: The FastAPI backend runs plain HTTP on port 8002. The Vite dev server runs plain HTTP on port 5175. The `docker-compose.yml` references nginx with ports 80 and 443, but the nginx configuration directory (`./nginx/`) does not exist — meaning TLS is not actually configured. Inter-service communication (crawler → db-admin, website → db-admin) uses plain HTTP.
- **Threat**:
  - **Credential interception**: When authentication is implemented, login credentials sent over HTTP can be captured by any network observer
  - **Data exposure**: Product prices, business analytics, and admin operations are transmitted in plaintext
  - **Man-in-the-middle**: An attacker on the network can intercept and modify API requests (e.g., changing prices in transit)
- **Recommendation**:
  1. Create the nginx configuration with TLS termination using Let's Encrypt certificates
  2. Redirect all HTTP traffic to HTTPS
  3. Add HSTS headers
  4. For inter-service communication within Docker, plain HTTP is acceptable if the network is isolated
  5. Add `Strict-Transport-Security`, `X-Content-Type-Options`, `X-Frame-Options` response headers
- **Implementation Effort**: Medium (3–5 days including certificate setup)

### Issue 11: No Backup or Recovery Strategy

- **Risk**: MEDIUM
- **Current State**: There is no backup mechanism for the SQLite database or the PostgreSQL production database. The `docker-compose.yml` uses Docker volumes (`postgres_data`) for persistence but has no backup job. Destructive admin operations (`reset-all`, `reset-products`, `reset-source`) perform immediate hard deletes with no pre-deletion snapshot. Cascade deletes on products remove all associated price history permanently.
- **Threat**:
  - **Accidental data loss**: A misclicked "Reset All" (even with confirmation string) permanently destroys all data
  - **Ransomware**: Database encryption by ransomware with no backup means total data loss
  - **Corruption**: SQLite file corruption or PostgreSQL volume corruption with no backup is unrecoverable
  - **No point-in-time recovery**: Cannot restore to a specific state before a bad data import
- **Recommendation**:
  1. Implement automated daily backups of the PostgreSQL database using `pg_dump`
  2. Store backups in a separate storage location (different volume, cloud storage)
  3. Add a pre-deletion backup step in admin reset endpoints
  4. Implement soft-delete with configurable retention (30 days) instead of hard deletes
  5. Test backup restoration regularly
  6. For SQLite development: add a backup script using SQLite's `.backup` command
  7. Implement WAL-based continuous archiving for PostgreSQL
- **Implementation Effort**: Medium (1 week)

### Issue 12: Hardcoded Default Credentials in Configuration

- **Risk**: MEDIUM
- **Current State**: Multiple configuration files contain default credentials:
  - `docker-compose.yml`: `POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-changeme}`
  - `alembic.ini`: `sqlalchemy.url = postgresql://walletsavior:changeme@localhost:5432/walletsavior`
  - `docker-compose.dev.yml`: Exposes PostgreSQL on port 5432 with default credentials
- **Threat**:
  - **Default credential exploitation**: If deployed without changing defaults, the database password is `changeme` — trivially guessable
  - **Credential leakage**: `alembic.ini` with hardcoded password is committed to version control
  - **Development credential reuse**: Developers may use the same `changeme` password in production
- **Recommendation**:
  1. Remove hardcoded passwords from `alembic.ini` — use `alembic.env.py` to read from environment variables
  2. Use Docker secrets or a secrets manager for production passwords
  3. Add pre-commit hooks to scan for credential patterns
  4. Document that default passwords must be changed before deployment
  5. Add a startup check that rejects `changeme` as a production password
- **Implementation Effort**: Low (2–4 hours)

### Issue 13: Bulk Operations Lack Safeguards

- **Risk**: MEDIUM
- **Current State**: Several endpoints accept arrays of IDs for bulk operations with no size limit:
  - `POST /api/products/bulk-delete` — accepts `{"ids": [...]}` with no maximum
  - `POST /api/products/bulk-category` — bulk category reassignment
  - `POST /api/keywords/bulk-delete` — bulk keyword deletion
  - `POST /api/ingestions/bulk-approve` — bulk approval and background insert
  - `POST /api/prices/bulk` — bulk price insertion

  While `MAX_RESULT_LIMIT=1000` exists for queries, there is no corresponding limit for write operations. The `per_page` parameter caps at 200 for reads but no such cap exists for bulk writes.
- **Threat**:
  - **Accidental mass deletion**: A frontend bug or API misuse could send all product IDs for deletion
  - **Resource exhaustion**: Bulk inserting millions of price records in a single request can crash the server
  - **Transaction timeout**: Very large bulk operations may exceed database transaction timeouts
- **Recommendation**:
  1. Add maximum batch size limits (e.g., 500 items per bulk request)
  2. Require additional confirmation for bulk operations exceeding a threshold (e.g., > 100 items)
  3. Implement pagination for bulk operations (process in chunks)
  4. Add a "dry run" mode that shows what would be affected before executing
  5. Return detailed results (success count, failure count, skipped items)
- **Implementation Effort**: Low (3–5 days)

### Issue 14: Background Task Error Handling is Weak

- **Risk**: MEDIUM
- **Current State**: Bulk ingestion approval uses FastAPI's `BackgroundTasks` for async database insertion. The error handler catches exceptions with `logger.error()` but does not update the ingestion status, notify the reviewer, or retry the operation:
  ```python
  except Exception as e:
      logger.error("백그라운드 벌크 삽입 실패: %s", e)
  ```
  If the background task fails, the ingestion remains marked as "approved" but the data is never actually inserted.
- **Threat**:
  - **Silent data loss**: Approved ingestions may never be persisted, with no indication to the user
  - **Inconsistent state**: Ingestion status shows "approved" but corresponding price records don't exist
  - **No retry mechanism**: Transient failures (DB connection timeout, disk full) are not retried
- **Recommendation**:
  1. Update ingestion status to "failed" on background task error
  2. Implement a retry mechanism with exponential backoff (max 3 retries)
  3. Add a dead-letter queue for permanently failed ingestions
  4. Send notifications (log alert, webhook) on background task failures
  5. Add a reconciliation endpoint that checks for approved-but-not-inserted ingestions
- **Implementation Effort**: Medium (3–5 days)

---

## Low Priority Issues

### Issue 15: No Content Security Policy (CSP) Headers

- **Risk**: LOW
- **Current State**: The FastAPI backend does not set any security response headers. The Vite development server does not configure CSP. No `X-Content-Type-Options`, `X-Frame-Options`, `X-XSS-Protection`, or `Content-Security-Policy` headers are returned.
- **Threat**: If an XSS vulnerability is introduced (e.g., via stored product names from crawler data rendered without escaping), the lack of CSP allows unrestricted script execution.
- **Recommendation**:
  1. Add security headers middleware to FastAPI
  2. Set `X-Content-Type-Options: nosniff`
  3. Set `X-Frame-Options: DENY` (admin panel should not be iframed)
  4. Set `Content-Security-Policy: default-src 'self'`
  5. Set `Referrer-Policy: strict-origin-when-cross-origin`
- **Implementation Effort**: Low (1–2 hours)

### Issue 16: No API Versioning

- **Risk**: LOW
- **Current State**: All routes are under `/api/*` with no version prefix. There is no API versioning strategy.
- **Threat**: Breaking API changes affect all consumers (website, crawler) simultaneously with no migration path. Rolling deployments become risky.
- **Recommendation**:
  1. Prefix routes with `/api/v1/*`
  2. Document API versioning strategy in project docs
  3. Maintain backward compatibility for at least one version
- **Implementation Effort**: Low (2–4 hours)

### Issue 17: Debug Mode Configuration Risk

- **Risk**: LOW
- **Current State**: `DEBUG` defaults to `false` but is controlled by environment variable. When `DEBUG=true`, Uvicorn runs with `--reload` and provides detailed error tracebacks. FastAPI in debug mode returns full Python stack traces in HTTP 500 responses.
- **Threat**: If accidentally enabled in production, stack traces expose internal file paths, library versions, and potentially database query details to external clients.
- **Recommendation**:
  1. Add startup validation that `DEBUG=true` is not set when `ENVIRONMENT=production`
  2. Use structured error responses that never expose internal details in production
  3. Add custom exception handlers that return generic error messages
- **Implementation Effort**: Low (1–2 hours)

### Issue 18: Export Endpoints Lack Access Controls

- **Risk**: LOW
- **Current State**: Data export endpoints return complete datasets:
  - `GET /api/prices/export` — CSV export of all prices (StreamingResponse)
  - `GET /api/analytics/export/products` — JSON export of all products
  - `GET /api/analytics/export/prices/{pid}` — CSV export per product

  These endpoints have no authentication, no rate limiting, and no watermarking.
- **Threat**: Complete database contents can be exfiltrated via export endpoints. Competitor intelligence gathering is trivial.
- **Recommendation**:
  1. Require authentication for all export endpoints
  2. Add rate limiting (max 10 exports per hour per user)
  3. Log all export operations with user identity and exported data scope
  4. Consider adding watermarking to exported data for leak tracing
- **Implementation Effort**: Low (after auth is implemented)

### Issue 19: Redis Configured but Unused

- **Risk**: LOW
- **Current State**: `config.py` reads `REDIS_URL` and `redis` is listed in `requirements.txt`, but no Redis client is instantiated anywhere in the db-admin codebase. Caching is done with in-memory TTL dictionaries. The main `docker-compose.yml` runs a Redis container.
- **Recommendation**:
  1. Either implement Redis-based caching/session storage or remove the dependency
  2. Unused dependencies increase the attack surface (Redis library vulnerabilities)
- **Implementation Effort**: Low (remove unused dependency or implement caching)

---

## Recommended Security Architecture

### Target Architecture (Production-Ready)

```
┌─────────────────────────────────────────────────────────────────────┐
│                        INTERNET / VPN                               │
└─────────────────────┬───────────────────────────────────────────────┘
                      │ HTTPS only (TLS 1.3)
                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    NGINX REVERSE PROXY                               │
│  • TLS termination (Let's Encrypt)                                   │
│  • IP allowlist (VPN/office IPs only for admin)                      │
│  • Rate limiting (100 req/min global, 10 req/min for admin)          │
│  • Security headers (CSP, HSTS, X-Frame-Options)                     │
│  • Request size limits (10MB max body)                                │
│  • /api/v1/admin/* → requires VPN IP                                 │
└─────────────────────┬───────────────────────────────────────────────┘
                      │ HTTP (internal Docker network only)
                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    FASTAPI (db-admin backend)                        │
│                                                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐               │
│  │ Auth         │  │ Rate Limit   │  │ Audit Log    │               │
│  │ Middleware   │  │ Middleware   │  │ Middleware   │               │
│  │ (JWT)        │  │ (slowapi)    │  │ (append-only)│               │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘               │
│         │                 │                 │                        │
│         ▼                 ▼                 ▼                        │
│  ┌──────────────────────────────────────────────────┐               │
│  │              ROUTE HANDLERS                       │               │
│  │  • RBAC: admin, moderator, viewer roles           │               │
│  │  • Input validation (Pydantic + sanitization)     │               │
│  │  • Bulk operation size limits (max 500)            │               │
│  │  • Confirmation + re-auth for destructive ops     │               │
│  └──────────────────────┬───────────────────────────┘               │
│                         │                                            │
│  ┌──────────────────────▼───────────────────────────┐               │
│  │              SERVICE LAYER                        │               │
│  │  • Business logic validation                      │               │
│  │  • Price range enforcement                        │               │
│  │  • Auto-backup before destructive operations      │               │
│  └──────────────────────┬───────────────────────────┘               │
│                         │                                            │
│  ┌──────────────────────▼───────────────────────────┐               │
│  │              DATA ACCESS LAYER                    │               │
│  │  • SQLAlchemy ORM (SQL injection protection)      │               │
│  │  • Connection pooling (PostgreSQL)                │               │
│  │  • Read replicas for analytics queries            │               │
│  └──────────────────────┬───────────────────────────┘               │
└─────────────────────────┼───────────────────────────────────────────┘
                          │ SSL connection
                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    POSTGRESQL (production)                            │
│  • Encrypted storage volume                                          │
│  • Least-privilege DB user (no DROP/CREATE permissions)               │
│  • Separate audit_log table (append-only, different DB user)         │
│  • Automated daily backups (pg_dump → encrypted cloud storage)       │
│  • WAL archiving for point-in-time recovery                          │
└─────────────────────────────────────────────────────────────────────┘
```

### Service-to-Service Authentication

```
┌──────────────┐     API Key + HMAC Signature     ┌──────────────┐
│   Crawler    │ ──────────────────────────────► │  DB Admin    │
│   Service    │   POST /api/v1/ingestions        │  Backend     │
│              │   X-API-Key: crawler_emart_xxx    │              │
│              │   X-Signature: HMAC-SHA256(body)  │              │
└──────────────┘                                   └──────────────┘

┌──────────────┐     Internal API Key              ┌──────────────┐
│   Website    │ ──────────────────────────────► │  DB Admin    │
│   Backend    │   GET /api/v1/products           │  Backend     │
│              │   X-Service-Key: website_xxx      │  (read-only) │
└──────────────┘                                   └──────────────┘
```

### Role-Based Access Control (RBAC) Matrix

| Endpoint Group | `viewer` | `moderator` | `admin` |
|---------------|----------|-------------|---------|
| GET /products, /prices, /categories | ✅ | ✅ | ✅ |
| GET /dashboard, /analytics | ✅ | ✅ | ✅ |
| GET /export/* | ❌ | ✅ | ✅ |
| POST /products, /categories, /keywords | ❌ | ✅ | ✅ |
| PUT /products/*, /categories/* | ❌ | ✅ | ✅ |
| DELETE /products/*, /categories/* | ❌ | ❌ | ✅ |
| POST /*/bulk-delete, /*/bulk-* | ❌ | ❌ | ✅ |
| POST /ingestions/bulk-approve | ❌ | ✅ | ✅ |
| POST /admin/reset-* | ❌ | ❌ | ✅ + re-auth |
| GET /admin/data-summary | ❌ | ✅ | ✅ |

### Audit Log Schema

```sql
CREATE TABLE audit_log (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_id INTEGER REFERENCES users(id),
    user_email VARCHAR(255),
    action VARCHAR(50) NOT NULL,        -- CREATE, UPDATE, DELETE, BULK_DELETE, RESET, EXPORT, LOGIN, APPROVE
    entity_type VARCHAR(50) NOT NULL,   -- product, category, keyword, price, ingestion
    entity_id VARCHAR(255),
    old_value JSONB,
    new_value JSONB,
    ip_address INET,
    user_agent TEXT,
    request_id UUID,
    metadata JSONB                      -- additional context (bulk count, export format, etc.)
);

-- Append-only: application DB user has INSERT only, no UPDATE/DELETE
-- Separate index for time-range and entity queries
CREATE INDEX idx_audit_timestamp ON audit_log(timestamp);
CREATE INDEX idx_audit_entity ON audit_log(entity_type, entity_id);
CREATE INDEX idx_audit_user ON audit_log(user_id);
```

---

## Summary & Remediation Roadmap

### Risk Distribution

| Severity | Count | Issues |
|----------|-------|--------|
| **CRITICAL** | 4 | #1 No Auth, #2 Open CORS, #3 Unprotected Destructive Ops, #4 Network Exposure |
| **HIGH** | 5 | #5 No Rate Limiting, #6 Unauthenticated Inter-service, #7 SQLite Security, #8 Ingestion Validation, #9 No Audit Trail |
| **MEDIUM** | 5 | #10 No TLS, #11 No Backup, #12 Default Credentials, #13 Bulk Safeguards, #14 Background Task Errors |
| **LOW** | 5 | #15 No CSP, #16 No API Versioning, #17 Debug Mode Risk, #18 Export Access, #19 Unused Redis |

### Recommended Remediation Order

**Phase 1 — Immediate (Week 1-2): Stop the Bleeding**
1. ~~Fix CORS~~ — Restrict `allow_origins` to specific frontend URLs (Issue #2) — **1 hour**
2. ~~Bind to localhost~~ — Change `host="0.0.0.0"` to `host="127.0.0.1"` (Issue #4) — **5 minutes**
3. Add rate limiting with `slowapi` (Issue #5) — **4 hours**
4. Add request body size limits in Uvicorn config — **30 minutes**
5. Remove hardcoded password from `alembic.ini` (Issue #12) — **1 hour**

**Phase 2 — Short Term (Week 3-4): Authentication & Authorization**
1. Implement JWT authentication middleware (Issue #1) — **1 week**
2. Add RBAC to all route handlers (Issue #1) — **3 days**
3. Add login page and auth guards to frontend (Issue #1) — **3 days**
4. Add service-to-service API key authentication (Issue #6) — **3 days**

**Phase 3 — Medium Term (Week 5-6): Data Protection**
1. Implement audit logging middleware (Issue #9) — **1 week**
2. Add pre-deletion backup for admin operations (Issue #11) — **3 days**
3. Enhance ingestion pipeline validation (Issue #8) — **1 week**
4. Add bulk operation safeguards (Issue #13) — **3 days**
5. Fix background task error handling (Issue #14) — **3 days**

**Phase 4 — Production Readiness (Week 7-8): Infrastructure**
1. Create nginx configuration with TLS (Issue #10) — **3 days**
2. Add security response headers (Issue #15) — **2 hours**
3. Containerize db-admin in Docker Compose — **2 days**
4. Set up automated PostgreSQL backups (Issue #11) — **2 days**
5. Add API versioning (Issue #16) — **4 hours**
6. Add production environment validation (Issue #17) — **2 hours**

### Key Metrics to Track Post-Remediation

| Metric | Target |
|--------|--------|
| Authenticated endpoints | 100% (except /health) |
| Audit log coverage | All write operations logged |
| Backup frequency | Daily automated + pre-destructive-op |
| Mean time to detect unauthorized access | < 1 hour |
| Rate limit effectiveness | 0 successful DoS attempts |
| TLS coverage | 100% external traffic |

---

> **Note**: This audit focuses on architecture-level security. A separate code-level security audit should examine SQL query construction, input sanitization patterns, dependency vulnerability scanning (e.g., `pip audit`), and frontend XSS prevention in detail. The existing `packages/security-perf-tests/` test suite covers some of these concerns but is not integrated into the db-admin CI pipeline.
