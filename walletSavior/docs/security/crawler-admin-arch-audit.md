# Crawler Admin — Architecture-Level Security Audit

> **Package**: `packages/crawler-admin`
> **Audited**: 2025-07-04
> **Scope**: Plugin sandboxing, crawler isolation, network boundaries, pipeline integrity, scheduler security, resource limits, secrets in transit, audit trail, failure recovery, Docker security, external site interaction, rate limiting
> **Overall Risk**: 🔴 **CRITICAL** — Not production-ready without remediation

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Findings by Severity](#findings-by-severity)
   - [Critical](#critical)
   - [High](#high)
   - [Medium](#medium)
   - [Low](#low)
3. [Architecture-Area Deep Dives](#architecture-area-deep-dives)
4. [Remediation Roadmap](#remediation-roadmap)
5. [Appendix: Files Reviewed](#appendix-files-reviewed)

---

## Executive Summary

The crawler-admin sub-project is a FastAPI/React orchestration layer managing 19+ web crawlers via a plugin system with YAML manifests and dynamically loaded Python modules. It includes a multi-strategy execution engine (requests → cloudscraper → Selenium → Playwright → undetected-chromedriver), a data pipeline with validation/dedup/transform stages, and an APScheduler-based scheduler.

**Key Findings:**
- **12 Critical/High findings** spanning authentication, code execution, secret management, and network security
- **Zero authentication or authorization** on any API endpoint
- **Arbitrary Python code execution** through the plugin system with no sandboxing
- **Wildcard CORS** with credentials enabled — classic CSRF vector
- **Hardcoded credentials** in config defaults and docker-compose
- **No TLS** between internal services; no rate limiting anywhere
- **No audit trail** — crawler actions are not securely logged

---

## Findings by Severity

### Critical

---

#### CRIT-01: Zero Authentication / Authorization on All API Endpoints

| Field | Detail |
|---|---|
| **Area** | API Layer (`backend/api/`) |
| **Current State** | No authentication middleware, no JWT/OAuth/API-key checks. All 30+ endpoints (crawler CRUD, schedule management, plugin activation, log export, ingestion submission) are publicly accessible. |
| **Threat** | Any network-reachable client can: trigger crawls, modify schedules, activate/deactivate plugins, export logs, submit data to the DB admin, and bulk-run all crawlers simultaneously. Combined with CRIT-02 (wildcard CORS), this is exploitable from any website. |
| **Evidence** | `backend/api/app.py` — no `Depends()` security injection; no `HTTPBearer`, `OAuth2PasswordBearer`, or API key header checks on any route in `routes/crawlers.py`, `routes/schedules.py`, `routes/plugins.py`, `routes/ingestion.py`, `routes/logs.py`, `routes/dashboard.py`. |
| **Recommendation** | 1) Add FastAPI `Depends()` with JWT bearer validation on all routes. 2) Implement RBAC — separate `viewer`, `operator`, `admin` roles. 3) Gate destructive actions (run, bulk-run, delete schedule, plugin toggle) behind `operator`+. 4) Add API key authentication as a lightweight alternative for service-to-service calls. |
| **Implementation Effort** | **Medium** — 2-3 days. FastAPI has built-in `OAuth2PasswordBearer`; use `python-jose` for JWT. |

---

#### CRIT-02: Wildcard CORS with Credentials Enabled

| Field | Detail |
|---|---|
| **Area** | API Layer (`backend/api/app.py` lines 16-22) |
| **Current State** | `allow_origins=["*"]`, `allow_credentials=True`, `allow_methods=["*"]`, `allow_headers=["*"]`. |
| **Threat** | Any website can make credentialed cross-origin requests to the API. If cookies/sessions are ever added, they are automatically included. Even without cookies, the wildcard allows any malicious page to trigger crawler operations via JavaScript `fetch()`. This is a textbook CSRF + data-exfiltration vector. |
| **Evidence** | `backend/api/app.py`: `CORSMiddleware(allow_origins=["*"], allow_credentials=True)` |
| **Recommendation** | 1) Restrict `allow_origins` to explicit frontend URLs (`http://localhost:5174` in dev, the production domain in prod). 2) Set `allow_credentials=False` unless cookies are actually used. 3) Restrict `allow_methods` to `["GET", "POST", "PUT", "DELETE"]`. 4) Restrict `allow_headers` to `["Content-Type", "Authorization"]`. |
| **Implementation Effort** | **Low** — 15 minutes. Config change only. |

---

#### CRIT-03: Arbitrary Code Execution via Plugin System (No Sandboxing)

| Field | Detail |
|---|---|
| **Area** | Plugin System (`backend/plugins/plugin_loader.py`) |
| **Current State** | Plugins are loaded via `importlib.util.spec_from_file_location()` → `spec.loader.exec_module(module)`. Any Python code in a plugin's `crawler.py` is executed with full process privileges. No sandboxing, no import restrictions, no filesystem/network isolation. Plugins share the same process, memory space, and environment variables as the main application. |
| **Threat** | A malicious or compromised plugin can: read all secrets from `config.py` / environment, access the filesystem, open network connections to exfiltrate data, monkey-patch other modules, modify `sys.modules` to hijack other plugins, spawn subprocesses, or crash the entire application. |
| **Evidence** | `plugin_loader.py` lines 262-293: `spec.loader.exec_module(module)` with no `RestrictedPython`, no `seccomp`, no subprocess isolation. |
| **Recommendation** | **Phase 1 (Quick):** 1) Add manifest signing — HMAC-SHA256 of `plugin.yaml` with a server-side secret; reject unsigned/tampered manifests. 2) Add an import whitelist — hook `__import__` to block `os`, `subprocess`, `socket`, `ctypes`, `importlib` from plugin code. 3) Add file access audit logging. **Phase 2 (Robust):** 4) Run each plugin in a separate subprocess with `resource` limits (CPU, memory, open files). 5) Long-term: run plugins in isolated containers with network policy restrictions. |
| **Implementation Effort** | **Phase 1: Medium** (2-3 days). **Phase 2: High** (1-2 weeks). |

---

#### CRIT-04: Hardcoded Credentials in Config Defaults

| Field | Detail |
|---|---|
| **Area** | Config (`backend/config.py`), Docker (`docker-compose.yml`) |
| **Current State** | `config.py` line ~14: `DATABASE_URL` defaults to `"postgresql://user:password@localhost:5432/wallet_guardian"`. `docker-compose.yml` line 9: `POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-changeme}`. These are committed to version control. |
| **Threat** | Anyone with repository access (or who finds the repo publicly) obtains valid database credentials. The `changeme` default in docker-compose will be used in any deployment that doesn't override the environment variable — which is the common case for quick-start/dev setups. |
| **Evidence** | `backend/config.py`: `os.getenv("DATABASE_URL", "postgresql://user:password@...")` ; `docker-compose.yml`: `POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-changeme}` |
| **Recommendation** | 1) Remove all credential defaults — raise an error if `DATABASE_URL` is not set. 2) Use `.env.example` with placeholder values (never real credentials). 3) Add `.env` to `.gitignore`. 4) For Docker, use Docker secrets or require explicit env file. 5) Run `git filter-branch` or BFG Repo Cleaner to purge credentials from history if the repo is public. |
| **Implementation Effort** | **Low** — 1-2 hours. |

---

#### CRIT-05: SKIP_REVIEW Flag Bypasses Data Integrity Pipeline

| Field | Detail |
|---|---|
| **Area** | Pipeline (`backend/pipeline/pipeline.py`) |
| **Current State** | When the `SKIP_REVIEW` environment variable / config flag is set, the pipeline calls `_store_batched()` to write directly to the database, bypassing the ingestion review queue (`_store_to_ingestion()`). |
| **Threat** | If an attacker controls a crawler's output or the `SKIP_REVIEW` flag, they can inject arbitrary data directly into the production database without human review. This undermines the entire review-before-publish workflow. A compromised crawler could inject false discount/price data affecting downstream consumers. |
| **Evidence** | `pipeline.py`: `if SKIP_REVIEW: items_saved = await self._store_batched(records, errors)` |
| **Recommendation** | 1) Remove `SKIP_REVIEW` or restrict it to test environments only (check `DEBUG` mode). 2) Always route through the ingestion queue in production. 3) Add data signing — each pipeline stage signs its output; the ingestion endpoint verifies the chain. 4) Add anomaly detection — flag items with unusual price deviations (>50% from historical average). |
| **Implementation Effort** | **Low** — 1 hour to remove the flag; **Medium** — 1-2 days for data signing. |

---

#### CRIT-06: API Binds to 0.0.0.0 by Default

| Field | Detail |
|---|---|
| **Area** | Config (`backend/config.py`) |
| **Current State** | `API_HOST` defaults to `"0.0.0.0"`, exposing the API to all network interfaces. Combined with CRIT-01 (no auth), any device on the same network can control all crawlers. |
| **Threat** | In shared networks (office, cloud VPC, university), any host can discover and exploit the API. Port scanners will find port 8001 immediately. |
| **Evidence** | `config.py`: `API_HOST: str = os.getenv("API_HOST", "0.0.0.0")` |
| **Recommendation** | 1) Default to `127.0.0.1` — only accept local connections. 2) Require explicit opt-in for network binding. 3) In Docker/production, use reverse proxy (nginx) with TLS termination as the only public-facing endpoint. |
| **Implementation Effort** | **Low** — 5 minutes. Config change. |

---

### High

---

#### HIGH-01: SSRF via Unvalidated Crawler Target URLs

| Field | Detail |
|---|---|
| **Area** | API routes (`routes/crawlers.py`, `routes/plugins.py`), Engine |
| **Current State** | `target_url` from API requests is assigned directly to crawler config without validation: `current["target_url"] = body.target_url`. No scheme, host, or IP validation. The crawler engine will then `GET` this URL using requests/httpx/Playwright. |
| **Threat** | An attacker can set `target_url` to `http://127.0.0.1:5432` (PostgreSQL), `http://169.254.169.254/latest/meta-data/` (AWS metadata), `http://redis:6379` (internal Redis), or `file:///etc/passwd`. This enables Server-Side Request Forgery (SSRF) to probe/attack internal services. |
| **Evidence** | `crawlers.py` line 221: `current["target_url"] = body.target_url` — no URL validation. |
| **Recommendation** | 1) Validate URL scheme (allow only `http://` and `https://`). 2) Resolve hostname and block private IP ranges (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `127.0.0.0/8`, `169.254.0.0/16`, `::1`). 3) Block cloud metadata endpoints explicitly. 4) Maintain an allowlist of permitted domains if possible. 5) Limit redirect following to prevent redirect-based SSRF. |
| **Implementation Effort** | **Medium** — 1-2 days. Requires URL parsing + IP resolution check before crawling. |

---

#### HIGH-02: No Rate Limiting — Inbound or Outbound

| Field | Detail |
|---|---|
| **Area** | API Layer (inbound), Engine (outbound) |
| **Current State** | **Inbound:** No rate-limiting middleware on FastAPI. The `/bulk-run` endpoint accepts unlimited `crawler_ids` with no cap. **Outbound:** No per-domain or per-proxy rate limiting on crawl requests. Only a configurable random delay between requests (`CRAWL_DELAY_MIN`). |
| **Threat** | **Inbound:** Denial-of-service by flooding the API with requests; resource exhaustion via unlimited bulk-run calls. **Outbound:** Target websites may block all proxies/IPs if crawlers send too many requests. Legal risk from aggressive crawling (violating terms of service). |
| **Evidence** | No `slowapi`, `fastapi-limiter`, or custom rate-limit middleware found. `bulk-run` endpoint: `for cid in body.crawler_ids:` with no length check. |
| **Recommendation** | **Inbound:** 1) Add `slowapi` or `fastapi-limiter` — 100 req/min/IP for reads, 10 req/min/IP for writes. 2) Cap `bulk-run` to max 5 crawlers per request. **Outbound:** 3) Implement per-domain rate limiter (e.g., max 1 req/sec/domain). 4) Track per-proxy request counts and implement backoff. 5) Honor `Crawl-delay` in `robots.txt`. |
| **Implementation Effort** | **Medium** — 1-2 days. `slowapi` is a drop-in; outbound rate limiting requires a shared counter. |

---

#### HIGH-03: No TLS Between Internal Services

| Field | Detail |
|---|---|
| **Area** | Pipeline → DB Admin, Crawler Admin → PostgreSQL/Redis |
| **Current State** | Pipeline submits data to DB Admin (port 8002) via plain HTTP: `await client.post(INGESTION_API_URL, json=payload)`. Docker services communicate on a bridge network without TLS. Database connections use unencrypted PostgreSQL protocol. |
| **Threat** | Any process on the Docker network (or any host on the same bridge) can sniff inter-service traffic, including database credentials, API keys, crawled data, and ingestion payloads. Man-in-the-middle attacks can modify data in transit. |
| **Evidence** | `pipeline.py`: `httpx.AsyncClient()` with no TLS config. `docker-compose.yml`: no TLS certificates mounted, no SSL env vars for PostgreSQL. |
| **Recommendation** | 1) Enable TLS on all internal HTTP communication (use `httpx` with `verify=True` and CA certs). 2) Enable PostgreSQL SSL (`sslmode=require`). 3) For high-security: implement mTLS between services using a shared CA. 4) Use Docker secrets for certificate distribution. |
| **Implementation Effort** | **Medium-High** — 2-3 days. Requires certificate generation, distribution, and configuration per service. |

---

#### HIGH-04: Crawler Subprocess Resource Limits Not Enforced

| Field | Detail |
|---|---|
| **Area** | Engine (`backend/engine/`), strategies (Selenium, Playwright) |
| **Current State** | Selenium and Playwright strategies spawn browser subprocesses (Chrome, Chromium) with no resource constraints. No CPU, memory, file descriptor, or disk usage limits. The only control is a per-strategy timeout (60s) via `asyncio.wait_for()`. Cumulative timeout across the cascade can reach 5 × 60s = 5 minutes. |
| **Threat** | A single malicious or misbehaving target page can: consume all available RAM (JavaScript-heavy page), spawn unlimited child processes, fill disk with browser cache/screenshots, or hold CPU at 100% during the full timeout window. This affects all other crawlers running in the same process/container. |
| **Evidence** | `engine/executor.py`: only `asyncio.wait_for(strategy.fetch(), timeout=60)` — no `resource.setrlimit()`, no Docker `mem_limit`, no `ulimit` calls. |
| **Recommendation** | 1) Add cumulative timeout across all strategies (e.g., 120s total per crawl). 2) Set browser-specific flags: `--disable-dev-shm-usage`, `--js-flags="--max-old-space-size=256"`, `--single-process`. 3) In Docker: add `mem_limit: 512m`, `cpus: 0.5`, `pids_limit: 50` per crawler container. 4) Monitor resource usage and kill processes exceeding thresholds. |
| **Implementation Effort** | **Medium** — 1-2 days for timeouts/flags; 3-5 days for container-per-crawler architecture. |

---

#### HIGH-05: No Plugin Manifest Verification

| Field | Detail |
|---|---|
| **Area** | Plugin System (`backend/plugins/plugin_loader.py`) |
| **Current State** | `plugin.yaml` manifests are loaded and trusted without any integrity verification. No checksums, no digital signatures, no allowlist of approved plugins. Any file in the crawlers directory with a valid YAML structure is loaded and its Python code executed. |
| **Threat** | An attacker with filesystem write access (or a supply-chain compromise) can drop a malicious `plugin.yaml` + `crawler.py` into the crawlers directory. The system will auto-discover and load it on next restart or registry refresh. |
| **Evidence** | `plugin_loader.py`: `_import_plugin()` loads any `crawler.py` found alongside a `plugin.yaml` — no signature check. |
| **Recommendation** | 1) Add HMAC-SHA256 signing: include a `signature` field in `plugin.yaml`, verify against a server-side secret before loading. 2) Maintain a plugin allowlist (approved plugin names + version hashes). 3) Log all plugin load/unload events with file hashes. 4) Set filesystem permissions so only admin can write to the crawlers directory. |
| **Implementation Effort** | **Medium** — 1-2 days for HMAC signing; 3-4 days for a full plugin approval workflow. |

---

#### HIGH-06: Plaintext Secrets in Environment and Config Files

| Field | Detail |
|---|---|
| **Area** | Config (`backend/config.py`), Docker (`docker-compose.yml`) |
| **Current State** | `NAVER_CLIENT_SECRET`, `KAMIS_API_KEY`, `PROXY_LIST` (may contain `user:pass@host` proxy credentials), and `DATABASE_URL` are stored as plaintext in `.env` files and environment variables. No encryption at rest. All config values are globally accessible to every plugin and crawler in the same process. |
| **Threat** | A compromised plugin (CRIT-03) can read `os.environ` to harvest all API keys and database credentials. If the `.env` file is accidentally committed or the container is compromised, all secrets are exposed. |
| **Evidence** | `config.py`: `NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET", "")` — globally accessible. |
| **Recommendation** | 1) Use a secret manager (HashiCorp Vault, AWS Secrets Manager, or Docker secrets). 2) Scope secrets per component — crawlers should not have access to database credentials. 3) Rotate API keys periodically. 4) Encrypt `.env` files at rest if a secret manager is not feasible. |
| **Implementation Effort** | **Medium-High** — 2-4 days depending on chosen secret manager. |

---

### Medium

---

#### MED-01: No Audit Trail for Crawler Operations

| Field | Detail |
|---|---|
| **Area** | All layers |
| **Current State** | The application uses standard Python `logging` for operational messages, but there is no structured audit log capturing: who triggered a crawl, what data was submitted, when schedules were modified, which plugins were loaded/unloaded. `crawler_run_history.json` tracks execution results but not the actor or authorization context. |
| **Threat** | Cannot detect unauthorized access, cannot investigate incidents, cannot prove compliance. If data is tampered with via the pipeline, there is no forensic trail to trace the source. |
| **Recommendation** | 1) Add structured audit logging (JSON format) for all state-changing operations: crawl triggers, schedule CRUD, plugin toggles, data submissions, config changes. 2) Include actor identity (once auth is added), timestamp, IP address, request body hash, and result. 3) Send audit logs to an append-only store (separate from application logs). 4) Implement log integrity protection (hash chains or forward-secure logging). |
| **Implementation Effort** | **Medium** — 2-3 days for structured logging; 1 week for append-only store + integrity. |

---

#### MED-02: No robots.txt Compliance or Ethical Crawling Controls

| Field | Detail |
|---|---|
| **Area** | Engine, anti-detection (`backend/engine/anti_detect.py`) |
| **Current State** | The engine does not check `robots.txt` before crawling. Anti-detection features (random user agents, stealth plugins, undetected-chromedriver) are designed to actively circumvent bot detection. No `Crawl-delay` honoring. No `User-Agent` identification as a bot. |
| **Threat** | Legal liability under computer fraud/abuse laws (depending on jurisdiction). Target sites may pursue legal action for TOS violations. IP/proxy bans affecting all crawlers. Ethical concerns around deceptive crawling practices. |
| **Recommendation** | 1) Implement `robots.txt` parsing (`urllib.robotparser`) and respect `Disallow`/`Crawl-delay` directives. 2) Identify the crawler with a custom `User-Agent` string including contact information. 3) Document which sites have explicitly permitted crawling. 4) Add a compliance mode toggle — when enabled, strictly follow `robots.txt` and rate limits. 5) Consult legal counsel regarding web scraping regulations in target jurisdictions. |
| **Implementation Effort** | **Medium** — 1-2 days for `robots.txt` compliance; ongoing for legal review. |

---

#### MED-03: Redirect Chain Not Limited — Open Redirect / SSRF Amplification

| Field | Detail |
|---|---|
| **Area** | Engine strategies (`engine/strategies/`) |
| **Current State** | `requests.get(url, allow_redirects=True)` follows redirects without limit. Default behavior follows up to 30 redirects. No validation that the redirect target is still an allowed domain/IP. |
| **Threat** | A target site can redirect the crawler to internal services (SSRF amplification), infinitely loop redirects (resource exhaustion), or redirect to a malicious download (disk fill). Combined with HIGH-01, this expands the SSRF attack surface. |
| **Recommendation** | 1) Set `max_redirects=5` on all HTTP clients. 2) Validate each redirect destination against the same SSRF checks as the original URL (no private IPs, no cloud metadata). 3) Log all redirects for audit purposes. |
| **Implementation Effort** | **Low** — 2-4 hours. |

---

#### MED-04: Module Cache Poisoning via sys.modules

| Field | Detail |
|---|---|
| **Area** | Plugin System (`backend/plugins/plugin_loader.py`) |
| **Current State** | Loaded plugin modules are registered in `sys.modules[module_name]`. During plugin reload/hot-swap, the old module reference may persist or be replaced without clearing dependent caches. |
| **Threat** | A malicious plugin can overwrite entries in `sys.modules` to hijack imports for other plugins or the core application. For example, replacing `sys.modules["json"]` with a module that exfiltrates data on every `json.loads()` call. |
| **Recommendation** | 1) Namespace plugin modules to prevent collisions (e.g., `_plugin.{name}.crawler`). 2) Clear module and its submodules from `sys.modules` before reload. 3) Long-term: use subprocess isolation so plugins cannot access the host's `sys.modules`. |
| **Implementation Effort** | **Low-Medium** — 1 day for namespacing; subprocess isolation is part of CRIT-03 Phase 2. |

---

#### MED-05: Silent Cron Validation Failure

| Field | Detail |
|---|---|
| **Area** | Scheduler (`backend/api/routes/schedules.py`) |
| **Current State** | `_compute_next_runs()` catches all exceptions from `CronTrigger.from_crontab()` and returns an empty list `[]`. The API endpoint does not report the validation failure to the caller. A schedule with an invalid cron expression is silently accepted but never fires. |
| **Threat** | Operator configures a schedule believing it will run, but it silently does nothing. Data freshness degrades without alerting. Could also be exploited to disable crawlers by setting intentionally invalid cron expressions. |
| **Recommendation** | 1) Return a 400 error with a descriptive message when cron validation fails. 2) Validate cron expressions on create/update before persisting. 3) Add a minimum frequency check (reject anything more frequent than every 5 minutes). 4) Alert on schedules that haven't fired in their expected window. |
| **Implementation Effort** | **Low** — 2-3 hours. |

---

#### MED-06: No Security Headers on API or Frontend

| Field | Detail |
|---|---|
| **Area** | API (`backend/api/app.py`), Frontend (Vite) |
| **Current State** | No security headers are set: no `Content-Security-Policy`, no `X-Frame-Options`, no `X-Content-Type-Options`, no `Strict-Transport-Security`, no `Referrer-Policy`. |
| **Threat** | Clickjacking (iframe embedding), MIME-type sniffing attacks, XSS amplification (no CSP), information leakage via referrer headers. |
| **Recommendation** | Add middleware to set: `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Content-Security-Policy: default-src 'self'`, `Strict-Transport-Security: max-age=31536000`, `Referrer-Policy: strict-origin-when-cross-origin`. |
| **Implementation Effort** | **Low** — 1-2 hours. FastAPI middleware or Starlette `TrustedHostMiddleware`. |

---

#### MED-07: Deduplication Collision Risk

| Field | Detail |
|---|---|
| **Area** | Pipeline (`backend/pipeline/dedup.py`) |
| **Current State** | Deduplication uses `(name, price)` as the composite key. Items with identical names and prices but from different sources, dates, or with different attributes are silently dropped. |
| **Threat** | Legitimate distinct deals may be incorrectly deduplicated (data loss). Conversely, an attacker could inject a decoy item to "shadow" a legitimate one — the first-seen item wins. |
| **Recommendation** | 1) Include `source`, `crawl_date`, and `url` in the dedup key. 2) Log all deduplicated items for manual review. 3) Consider fuzzy matching with human-in-the-loop for edge cases. |
| **Implementation Effort** | **Low** — 2-3 hours. |

---

#### MED-08: Frontend Lacks CSRF Protection

| Field | Detail |
|---|---|
| **Area** | Frontend (`frontend/src/api/client.js`) |
| **Current State** | All POST/PUT/DELETE requests from the frontend use plain `fetch()` with no CSRF token. No `X-CSRF-Token` header, no double-submit cookie pattern. |
| **Threat** | Combined with CRIT-02 (wildcard CORS), any website can trigger state-changing operations. Even after CORS is fixed, if cookies are introduced without CSRF protection, the vulnerability returns. |
| **Recommendation** | 1) Implement CSRF token pattern — server generates token, frontend includes it in headers. 2) Use `SameSite=Strict` cookie attribute. 3) Validate `Origin`/`Referer` headers server-side. |
| **Implementation Effort** | **Low-Medium** — 1 day. |

---

### Low

---

#### LOW-01: ETag Cache Staleness in Frontend

| Field | Detail |
|---|---|
| **Area** | Frontend (`frontend/src/api/client.js`) |
| **Current State** | The ETag-based cache stores responses in a `Map` keyed by URL. On 304 responses, it returns the cached data. No cache invalidation on state-changing operations (POST/PUT). |
| **Threat** | After a crawl run or schedule change, the UI may display stale data until the next non-304 response. Low security impact but could mislead operators about system state. |
| **Recommendation** | 1) Invalidate relevant cache entries after POST/PUT/DELETE operations. 2) Add cache TTL (e.g., 30 seconds). |
| **Implementation Effort** | **Low** — 2-3 hours. |

---

#### LOW-02: No Dependency Vulnerability Scanning

| Field | Detail |
|---|---|
| **Area** | Dependencies (`requirements.txt`, `package.json`) |
| **Current State** | No automated vulnerability scanning for Python or Node.js dependencies. Dependencies include `cloudscraper` (known to have sporadic issues), `undetected-chromedriver` (community-maintained), and `selenium-stealth` (last updated irregularly). |
| **Threat** | Known CVEs in dependencies may go unpatched. Supply-chain attacks via compromised packages. |
| **Recommendation** | 1) Add `pip-audit` or `safety` to CI pipeline. 2) Add `npm audit` for frontend. 3) Pin exact dependency versions. 4) Set up Dependabot or Renovate for automated updates. |
| **Implementation Effort** | **Low** — 1-2 hours for CI integration. |

---

#### LOW-03: Browser Process Cleanup on Crash

| Field | Detail |
|---|---|
| **Area** | Engine (`engine/executor.py`, `engine/playwright_helper.py`) |
| **Current State** | The executor has `finally` blocks calling `strategy.cleanup()` with a 10s timeout. However, if the main process crashes or is killed (SIGKILL), spawned Chrome/Chromium processes may become orphans. |
| **Threat** | Orphaned browser processes accumulate, consuming memory and CPU. Over time, this degrades system performance and may cause disk fill (browser profiles/caches). |
| **Recommendation** | 1) Use process groups (`os.setsid()` + `os.killpg()`) for browser subprocesses. 2) Add a periodic orphan-process reaper (check for chrome/chromium processes not associated with active crawls). 3) Set browser `--user-data-dir` to a temp directory and clean up on startup. |
| **Implementation Effort** | **Low-Medium** — 1 day. |

---

#### LOW-04: schedules.json Stored with Default File Permissions

| Field | Detail |
|---|---|
| **Area** | Scheduler (`backend/api/routes/schedules.py`) |
| **Current State** | `schedules.json` is written with Python's default file permissions (typically 0644). Contains schedule definitions including cron expressions and crawler names. |
| **Threat** | Any user on the host can read and potentially modify schedule definitions. Low impact in containerized deployments but relevant for bare-metal/shared hosting. |
| **Recommendation** | 1) Set file permissions to 0600 on write. 2) Consider moving schedule persistence to a database with access controls. |
| **Implementation Effort** | **Low** — 30 minutes. |

---

## Architecture-Area Deep Dives

### Plugin Sandboxing (Focus Area 1)

**Current Architecture:** Monolithic — all plugins share one Python process. `importlib` dynamically loads `crawler.py` from each plugin directory. The only isolation is exception catching (`try/except`) and per-hook timeouts (`asyncio.wait_for(..., timeout=30)`).

**Recommended Architecture:**

```
┌─────────────────────────────────────────────┐
│  Crawler Admin (Main Process)               │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │ API      │  │ Scheduler│  │ Pipeline │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  │
│       │              │              │        │
│  ┌────▼──────────────▼──────────────▼────┐  │
│  │         Plugin Orchestrator            │  │
│  │  (manifest verify → spawn → collect)   │  │
│  └────┬──────────┬──────────┬────────────┘  │
└───────┼──────────┼──────────┼───────────────┘
   ┌────▼────┐ ┌───▼────┐ ┌──▼─────┐
   │Plugin A │ │Plugin B│ │Plugin C│  ← Subprocess / Container
   │(sandbox)│ │(sandbox│ │(sandbox│     with resource limits
   │ 256MB   │ │ 256MB) │ │ 256MB) │
   └─────────┘ └────────┘ └────────┘
```

### Crawler Isolation (Focus Area 2)

**Current:** All crawlers share one event loop. A blocking call in one crawler blocks all others. Browser processes spawned by Selenium/Playwright are independent OS processes but have no resource caps.

**Recommended:** Use `asyncio` task groups with per-crawler cancellation scopes. For browser-based strategies, enforce `--max-old-space-size=256` and `--disable-dev-shm-usage`. Add a watchdog that kills crawlers exceeding a cumulative timeout.

### Network Boundaries (Focus Area 3)

**Current:** Crawlers have unrestricted outbound network access. No firewall rules, no IP blocklists, no DNS filtering. The API server binds to `0.0.0.0`.

**Recommended Docker Network Policy:**

```yaml
services:
  crawler-admin:
    networks:
      - crawler-net      # Outbound internet access (via proxy)
      - internal-net     # Access to DB admin only
    # No access to db-net (database)

  db-admin:
    networks:
      - internal-net
      - db-net

  db:
    networks:
      - db-net           # Only DB admin can reach database
```

### Pipeline Integrity (Focus Area 4)

**Current:** Data flows from crawler → validator → dedup → transformer → HTTP POST to DB admin. No signing, no integrity verification, no schema validation on the submission payload.

**Recommended:** Add HMAC signing at each pipeline stage. The DB admin should verify the signature chain before accepting data. Add JSON Schema validation on the submission endpoint.

### Failure Recovery (Focus Area 9)

**Current:** Good — per-strategy timeout + cleanup in `finally` blocks. Per-crawler `asyncio.Lock` prevents double-execution. Job tracker records failures.

**Gaps:** No dead-letter queue for permanently failed items. No circuit breaker for repeatedly failing crawlers (they'll keep retrying on every schedule). No alerting on consecutive failures.

---

## Remediation Roadmap

### Phase 1 — Emergency (Week 1)

| ID | Action | Effort | Addresses |
|---|---|---|---|
| R-01 | Add JWT authentication to all API endpoints | 2-3 days | CRIT-01 |
| R-02 | Restrict CORS to known origins | 15 min | CRIT-02 |
| R-03 | Remove hardcoded credential defaults | 1-2 hrs | CRIT-04 |
| R-04 | Change default bind to `127.0.0.1` | 5 min | CRIT-06 |
| R-05 | Remove or gate `SKIP_REVIEW` flag | 1 hr | CRIT-05 |
| R-06 | Add URL validation (block private IPs) | 1 day | HIGH-01 |
| R-07 | Add `slowapi` rate limiting | 1 day | HIGH-02 |
| R-08 | Add security headers middleware | 1-2 hrs | MED-06 |

### Phase 2 — Hardening (Weeks 2-3)

| ID | Action | Effort | Addresses |
|---|---|---|---|
| R-09 | Plugin manifest HMAC signing | 1-2 days | CRIT-03, HIGH-05 |
| R-10 | Plugin import whitelist hook | 1-2 days | CRIT-03 |
| R-11 | Add cumulative crawl timeout | 4 hrs | HIGH-04 |
| R-12 | Browser resource flags + Docker limits | 1-2 days | HIGH-04 |
| R-13 | Structured audit logging | 2-3 days | MED-01 |
| R-14 | Cron validation with error responses | 2-3 hrs | MED-05 |
| R-15 | robots.txt compliance module | 1-2 days | MED-02 |
| R-16 | CSRF token implementation | 1 day | MED-08 |

### Phase 3 — Defense in Depth (Month 2)

| ID | Action | Effort | Addresses |
|---|---|---|---|
| R-17 | TLS between internal services | 2-3 days | HIGH-03 |
| R-18 | Secret manager integration | 2-4 days | HIGH-06 |
| R-19 | Plugin subprocess isolation | 1-2 weeks | CRIT-03 Phase 2 |
| R-20 | Docker network segmentation | 1-2 days | Focus Area 3 |
| R-21 | Dependency vulnerability scanning in CI | 2 hrs | LOW-02 |
| R-22 | Data signing across pipeline stages | 2-3 days | Focus Area 4 |

### Phase 4 — Maturity (Quarter 2+)

| ID | Action | Effort | Addresses |
|---|---|---|---|
| R-23 | Container-per-plugin architecture | 2-3 weeks | CRIT-03 long-term |
| R-24 | OAuth2 / OpenID Connect | 1-2 weeks | CRIT-01 enterprise |
| R-25 | Zero-trust network architecture | 2-4 weeks | All network areas |
| R-26 | Automated SAST/DAST in CI/CD | 1 week | All areas |
| R-27 | Penetration testing (external) | Outsource | All areas |

---

## Appendix: Files Reviewed

```
backend/
├── api/
│   ├── app.py                    # FastAPI app, CORS config
│   └── routes/
│       ├── crawlers.py           # Crawler CRUD + run + bulk-run
│       ├── schedules.py          # Schedule CRUD + cron validation
│       ├── plugins.py            # Plugin activation + settings
│       ├── ingestion.py          # Proxy to DB Admin API
│       ├── logs.py               # Log retrieval + CSV export
│       └── dashboard.py          # Statistics + dashboards
├── config.py                     # Secrets, env vars, defaults
├── crawlers/                     # Per-category crawler plugins
├── engine/
│   ├── executor.py               # Multi-strategy cascade runner
│   ├── anti_detect.py            # UA rotation, proxy cycling, delays
│   ├── playwright_helper.py      # Playwright browser pool
│   ├── diagnostics.py            # Error diagnosis
│   └── strategies/               # requests, cloudscraper, selenium, playwright, UC
├── pipeline/
│   ├── pipeline.py               # Full crawl → validate → dedup → transform → submit
│   ├── validator.py              # Required fields, price range, URL checks
│   ├── transformer.py            # Schema conversion
│   └── dedup.py                  # Hash-based deduplication
├── plugins/
│   ├── plugin_loader.py          # Dynamic module loading from YAML manifests
│   ├── plugin_manager.py         # Lifecycle management
│   ├── plugin_interface.py       # CrawlerContract extension
│   └── test_framework.py         # Compliance validation
├── scheduler/
│   ├── scheduler.py              # APScheduler wrapper + SIGTERM handling
│   └── job_tracker.py            # Execution history
└── tests/
    ├── test_crawler_api.py       # API route tests
    ├── test_pipeline.py          # Pipeline tests
    ├── test_registry.py          # Registry tests
    └── test_scheduler.py         # Scheduler tests

frontend/
├── src/
│   └── api/
│       └── client.js             # API client with ETag cache + SSE
├── package.json
└── vite.config.js

docker-compose.yml                # Root-level Docker config
docker-compose.dev.yml            # Dev overrides
```

---

*This audit covers architecture-level security concerns. For code-level vulnerability scanning, see the companion report. For the main WalletSavior API audit, see the `proj` security documentation.*
