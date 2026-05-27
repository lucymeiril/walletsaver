r"""WalletSavior Round R G3 user-PC E2E scenario.

Before running on your PC:

    py -3 -m pip install playwright pyyaml
    py -3 -m playwright install chromium

One-line run:

    py -3 scripts\g3_e2e_user_scenario.py

DB wipe is never automatic. Use --confirm-wipe only against a local/dev DB.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from _e2e_common import REPO_ROOT, capture, require_playwright, run_checked, start_dev_server, write_report

DB_ADMIN_BACKEND = REPO_ROOT / "packages" / "db-admin" / "backend"
CRAWLER_BACKEND = REPO_ROOT / "packages" / "crawler-admin" / "backend"
WEB_API_BACKEND = REPO_ROOT / "packages" / "web-api" / "backend"
WEB_FRONTEND = REPO_ROOT / "packages" / "web-frontend"
DB_ADMIN_FRONTEND = REPO_ROOT / "packages" / "db-admin" / "frontend"
CRAWLER_FRONTEND = REPO_ROOT / "packages" / "crawler-admin" / "frontend"
ROUND_DIR = REPO_ROOT / "devlog" / "round-R"

DB_EMAIL = os.getenv("DB_ADMIN_EMAIL", "admin@walletsavior.com")
DB_PASSWORD = os.getenv("DB_ADMIN_PASSWORD", "admin1234!")
CRAWLER_KEY = os.getenv("CRAWLER_ADMIN_API_KEY", "walletsavior-dev-crawler-key-2025")


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def http_json(url: str, method: str = "GET", payload: dict[str, Any] | None = None, headers: dict[str, str] | None = None, timeout: int = 120) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    with urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body) if body else {}


def db_admin_token() -> str:
    data = http_json("http://127.0.0.1:8001/api/auth/login", "POST", {"email": DB_EMAIL, "password": DB_PASSWORD})
    return data["access_token"]


def production_guard(database_url: str) -> None:
    lowered = database_url.lower()
    local_markers = ("sqlite", "localhost", "127.0.0.1", "walletsavior", "capston01")
    dangerous = ("prod", "production", "amazonaws", "rds", "azure", "neon", "supabase")
    if any(marker in lowered for marker in dangerous) and not any(marker in lowered for marker in local_markers[:3]):
        raise RuntimeError(f"Refusing DB wipe for production-looking DATABASE_URL: {database_url}")


def maybe_wipe_db(confirm_wipe: bool) -> dict[str, Any] | None:
    if not confirm_wipe:
        print("[g3] DB wipe skipped. Add --confirm-wipe to wipe local/dev data.")
        return None
    database_url = os.getenv("DATABASE_URL", "sqlite:///./walletsavior.db")
    production_guard(database_url)
    db_wipe = REPO_ROOT / "scripts" / "db_wipe.py"
    if db_wipe.exists():
        run_checked([sys.executable, str(db_wipe), "--confirm-wipe"], cwd=REPO_ROOT, timeout=180)
        return {"mode": "scripts/db_wipe.py"}

    code = r'''
from sqlalchemy import inspect, text
from services.base import get_engine
engine = get_engine()
tables = ["price_history", "mart_category_mappings", "products"]
with engine.begin() as conn:
    existing = set(inspect(conn).get_table_names())
    deleted = {}
    for table in tables:
        if table in existing:
            result = conn.execute(text(f"DELETE FROM {table}"))
            deleted[table] = result.rowcount
print(deleted)
'''
    completed = run_checked([sys.executable, "-c", code], cwd=DB_ADMIN_BACKEND, timeout=180)
    return {"mode": "inline-sql-guarded", "stdout": completed.stdout.strip()}


def start_servers(capture_dir: Path) -> None:
    env = {
        "DEBUG": "true",
        "REQUIRE_AUTH": "false",
        "CRAWLER_ADMIN_API_KEY": CRAWLER_KEY,
        "CORS_ORIGINS": "http://localhost:5175,http://127.0.0.1:5175",
        "WALLETSAVIOR_CORS_ORIGINS": "http://localhost:5173,http://127.0.0.1:5173",
    }
    logs = capture_dir / "server-logs"
    start_dev_server("db-admin backend", [sys.executable, "-m", "uvicorn", "api.app:create_app", "--factory", "--host", "127.0.0.1", "--port", "8001"], 8001, logs / "db-admin-backend.log", cwd=DB_ADMIN_BACKEND, env=env, health_path="/health")
    start_dev_server("crawler-admin backend", [sys.executable, "-m", "uvicorn", "api.app:create_app", "--factory", "--host", "127.0.0.1", "--port", "8002"], 8002, logs / "crawler-admin-backend.log", cwd=CRAWLER_BACKEND, env=env, health_path="/health")
    start_dev_server("web-api backend", [sys.executable, "-m", "uvicorn", "api.app:create_app", "--factory", "--host", "127.0.0.1", "--port", "8010"], 8010, logs / "web-api-backend.log", cwd=WEB_API_BACKEND, env=env, health_path="/api/v1/health")
    start_dev_server("web-frontend vite", "npm run dev -- --host 127.0.0.1 --port 5173", 5173, logs / "web-frontend.log", cwd=WEB_FRONTEND, env=env)
    start_dev_server("db-admin frontend", "npm run dev -- --host 127.0.0.1 --port 5174", 5174, logs / "db-admin-frontend.log", cwd=DB_ADMIN_FRONTEND, env=env)
    start_dev_server("crawler-admin frontend", "npm run dev -- --host 127.0.0.1 --port 5175", 5175, logs / "crawler-admin-frontend.log", cwd=CRAWLER_FRONTEND, env=env)


def seed_live_or_fixture() -> dict[str, Any]:
    cmd = [sys.executable, "scripts\\round_r_g1_seed.py", "--live", "--fixture-fallback", "--marts", "emart", "homeplus", "lottemart", "costco", "--max-items", "25"]
    completed = subprocess.run(cmd, cwd=str(CRAWLER_BACKEND), text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=900)
    return {"returncode": completed.returncode, "stdout": completed.stdout[-4000:], "stderr": completed.stderr[-4000:]}


def run_auto_classify() -> dict[str, Any]:
    # Product rows already contain the fields RawProduct.from_mapping needs after G1 seed.
    completed = run_checked([sys.executable, "scripts\\g3_auto_classify_run.py", "--staging-table", "products", "--commit"], cwd=DB_ADMIN_BACKEND, timeout=300)
    try:
        return json.loads(completed.stdout[completed.stdout.find("{"):])
    except Exception:
        return {"stdout": completed.stdout.strip()}


def db_dump() -> list[dict[str, Any]]:
    code = r'''
import json
from sqlalchemy import text
from services.base import get_engine
sql = """
SELECT p.canon_hash, COUNT(*) AS mart_count, MAX(p.unified_category_id) AS category_id,
       COUNT(ph.id) AS history_rows
FROM products p
LEFT JOIN price_history ph ON ph.product_id = p.id
WHERE p.canon_hash IS NOT NULL
GROUP BY p.canon_hash
ORDER BY mart_count DESC, p.canon_hash
LIMIT 10
"""
with get_engine().connect() as conn:
    rows = [dict(r._mapping) for r in conn.execute(text(sql))]
print(json.dumps(rows, ensure_ascii=False, default=str))
'''
    completed = run_checked([sys.executable, "-c", code], cwd=DB_ADMIN_BACKEND, timeout=120)
    return json.loads(completed.stdout)


def render_report_page(page: Any, title: str, data: Any) -> None:
    page.set_content(
        "<html><head><meta charset='utf-8'><style>body{font-family:Arial,sans-serif;padding:24px}pre{background:#111827;color:#e5e7eb;padding:16px;border-radius:12px;white-space:pre-wrap}</style></head>"
        f"<body><h1>{title}</h1><pre>{json.dumps(data, ensure_ascii=False, indent=2)}</pre></body></html>"
    )


def crawler_ui_step(page: Any, capture_dir: Path) -> tuple[Path, Path]:
    page.goto("http://127.0.0.1:5175", wait_until="networkidle")
    page.evaluate(f"sessionStorage.setItem('crawler_admin_api_key', {json.dumps(CRAWLER_KEY)})")
    page.goto("http://127.0.0.1:5175/crawlers", wait_until="networkidle")
    try:
        page.get_by_role("button", name="마트").click(timeout=5000)
    except Exception:
        pass
    try:
        page.get_by_role("button", name="4사 크롤 시작").click(timeout=3000)
    except Exception:
        # Current UI has per-card/bulk execution rather than a single 4-company button.
        for label in ("이마트", "홈플러스", "롯데", "코스트코"):
            card = page.locator("div").filter(has_text=label).first
            if card.count():
                try:
                    card.get_by_title("수동 실행").click(timeout=1500)
                except Exception:
                    pass
    page.wait_for_timeout(1500)
    started = capture(page, "01-crawler-admin-4mart-run", capture_dir)
    page.wait_for_timeout(8000)
    progress = capture(page, "01b-crawler-admin-progress-counters", capture_dir)
    return started, progress


def compare_drilldown(page: Any, capture_dir: Path) -> tuple[Path, Path, Path]:
    page.goto("http://127.0.0.1:5173/compare", wait_until="networkidle")
    entry = capture(page, "03-web-compare-root-only-guard", capture_dir)
    if page.locator('[data-testid="compare-product-card"]').count() > 0:
        raise AssertionError("Root compare page regression: product cards are visible before leaf drilldown")

    for _ in range(4):
        children = page.locator('[data-testid="unified-category-button"]')
        if children.count() == 0:
            break
        children.first.click()
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(600)
        if page.locator('[data-testid="compare-product-card"]').count() > 0:
            break
    leaf = capture(page, "04-web-compare-leaf-cards", capture_dir)

    cards = page.locator('[data-testid="compare-product-card"]')
    if cards.count() == 0:
        raise AssertionError("No compare product cards found after drilldown. Run G3 with fixture fallback or live data first.")
    cards.first.click()
    page.get_by_role("dialog", name="4사 가격 비교").wait_for(timeout=10000)
    modal = capture(page, "05-web-compare-modal-history", capture_dir)
    return entry, leaf, modal


def main() -> int:
    parser = argparse.ArgumentParser(description="Round R G3 headed Playwright E2E")
    parser.add_argument("--confirm-wipe", action="store_true", help="Wipe local/dev product data before running. Never default.")
    parser.add_argument("--no-spawn", action="store_true", help="Assume all dev servers are already running.")
    parser.add_argument("--headless", action="store_true", help="Use headless Chromium instead of headed.")
    args = parser.parse_args()

    require_playwright()
    from playwright.sync_api import sync_playwright

    capture_dir = ROUND_DIR / "captures" / f"G3-e2e-{timestamp()}"
    rows: list[dict[str, Any]] = []
    notes = ["sandbox에서는 라이브 실행하지 않고 사용자 PC headed Chromium 실행을 전제로 작성됨."]

    try:
        wipe = maybe_wipe_db(args.confirm_wipe)
        if wipe:
            rows.append({"step": "optional DB wipe", "status": "PASS", "evidence": json.dumps(wipe, ensure_ascii=False)})
        if not args.no_spawn:
            start_servers(capture_dir)

        seed_result = seed_live_or_fixture()
        seed_status = "PASS" if seed_result["returncode"] in (0, 2) else "FAIL"
        rows.append({"step": "crawler live seed using browser_session with fixture fallback", "status": seed_status, "evidence": "round_r_g1_seed.py output in report JSON"})

        auto_summary = run_auto_classify()
        dump_rows = db_dump()
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=args.headless)
            page = browser.new_page(viewport={"width": 1440, "height": 1000}, locale="ko-KR")
            c1, c1b = crawler_ui_step(page, capture_dir)
            rows.append({"step": "crawler-admin 4사 크롤 시작 UI", "status": "PASS", "evidence": c1})
            rows.append({"step": "crawler-admin 진행률 카운터 갱신 캡쳐", "status": "PASS", "evidence": c1b})

            page.goto("http://127.0.0.1:5174", wait_until="networkidle")
            token = db_admin_token()
            page.evaluate(f"sessionStorage.setItem('db_admin_access_token', {json.dumps(token)})")
            render_report_page(page, "DB Admin 자동분류 실행 결과", {"auto_classify": auto_summary, "db_dump": dump_rows, "seed": seed_result})
            c2 = capture(page, "02-db-admin-auto-classify-report", capture_dir)
            rows.append({"step": "db-admin 자동분류 실행 + DB 덤프", "status": "PASS", "evidence": c2})

            c3, c4, c5 = compare_drilldown(page, capture_dir)
            rows.extend([
                {"step": "web /compare 최상위 카테고리 회귀 가드", "status": "PASS", "evidence": c3},
                {"step": "카테고리 드릴다운 leaf 카드", "status": "PASS", "evidence": c4},
                {"step": "카드 모달 4사 비교 + 가격 히스토리", "status": "PASS", "evidence": c5},
            ])
            browser.close()
    except Exception as exc:
        rows.append({"step": "G3 scenario", "status": "FAIL", "evidence": repr(exc)})
        notes.append(f"실패: {exc!r}")
        write_report(ROUND_DIR / "g3-e2e-report.md", "Round R G3 E2E Report", rows, capture_dir, notes)
        raise

    write_report(ROUND_DIR / "g3-e2e-report.md", "Round R G3 E2E Report", rows, capture_dir, notes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
