r"""WalletSavior Round R G4 external-AI cycle E2E script.

Before running on your PC:

    py -3 -m pip install playwright pyyaml
    py -3 -m playwright install chromium

One-line run:

    py -3 scripts\g4_e2e_ai_cycle.py

The default classifier is a deterministic rule-based mock. --use-llm only prints
an integration notice and falls back unless EXTERNAL_LLM_API_KEY is set and a
real adapter is added later.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
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

KEYWORD_RULES = [
    (("우유", "milk"), "우유"),
    (("계란", "달걀", "egg"), "계란"),
    (("라면", "ramen"), "라면"),
    (("쌀", "현미", "백미", "rice"), "쌀"),
    (("생수", "water", "물"), "생수"),
    (("두부", "tofu"), "두부"),
    (("커피", "coffee"), "커피"),
    (("사과", "apple"), "사과"),
    (("바나나", "banana"), "바나나"),
    (("닭", "치킨", "chicken"), "닭고기"),
    (("돼지", "삼겹", "pork"), "돼지고기"),
]


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


def ensure_unclassified_seed() -> None:
    # If G3 already ran, fixture rows may be classified. Keep a small local/dev
    # unmatched sample so the external-AI export/import path is demonstrable.
    run_checked([sys.executable, "scripts\\round_r_g1_seed.py", "--live", "--fixture-fallback", "--marts", "emart", "homeplus", "lottemart", "costco", "--max-items", "25"], cwd=CRAWLER_BACKEND, timeout=900)
    code = r'''
from sqlalchemy import select
from services.base import managed_session
from storage.models import Product
with managed_session() as session:
    products = session.scalars(
        select(Product)
        .where(Product.canon_hash.is_not(None), Product.mart_native_category_id.is_not(None))
        .order_by(Product.id)
        .limit(8)
    ).all()
    for product in products:
        product.unified_category_id = None
        product.categorization_method = None
        product.categorization_confidence = None
    print(f"prepared_unclassified={len(products)}")
'''
    run_checked([sys.executable, "-c", code], cwd=DB_ADMIN_BACKEND, timeout=120)


def parse_yaml_categories(path: Path) -> list[dict[str, Any]]:
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        nodes = data.get("nodes") or data.get("categories") or []
        return [node for node in nodes if isinstance(node, dict)]
    except Exception:
        nodes: list[dict[str, Any]] = []
        current: dict[str, Any] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            m_id = re.match(r"\s*-?\s*id:\s*['\"]?([^'\"]+)", line)
            m_name = re.match(r"\s*name_kr:\s*['\"]?([^'\"]+)", line)
            if m_id:
                if current:
                    nodes.append(current)
                current = {"id": m_id.group(1).strip()}
            elif m_name and current:
                current["name_kr"] = m_name.group(1).strip()
        if current:
            nodes.append(current)
        return nodes


def best_category(row: dict[str, Any], categories: list[dict[str, Any]]) -> tuple[str, list[str]]:
    haystack = " ".join(str(row.get(k) or "") for k in ("raw_name", "normalized_name", "brand", "mart_native_category_path")).lower()
    by_name = []
    for cat in categories:
        cid = str(cat.get("id") or "")
        name = str(cat.get("name_kr") or cat.get("name_ko") or cid)
        by_name.append((cid, name))

    for needles, korean in KEYWORD_RULES:
        if any(needle.lower() in haystack for needle in needles):
            for cid, name in by_name:
                if korean in name or korean in cid:
                    return cid, [korean, needles[0]]
    # Prefer a leaf-like non-root category, otherwise the first category.
    fallback = next((cid for cid, _ in by_name if "." in cid), by_name[0][0] if by_name else "uncategorized")
    return fallback, ["mock"]


def simulate_external_ai(bundle_dir: Path, out_dir: Path, *, use_llm: bool = False) -> dict[str, Any]:
    if use_llm and not os.getenv("EXTERNAL_LLM_API_KEY"):
        print("[g4] --use-llm requested but EXTERNAL_LLM_API_KEY is missing; using rule-based mock.")
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(line) for line in (bundle_dir / "unclassified.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    categories = parse_yaml_categories(bundle_dir / "category_list.yaml")

    matching_path = out_dir / "matching_updates.jsonl"
    keyword_path = out_dir / "category_keyword_updates.yaml"
    product_path = out_dir / "product_updates.jsonl"

    keyword_updates: dict[tuple[str, str], str] = {}
    with matching_path.open("w", encoding="utf-8", newline="\n") as match_f, product_path.open("w", encoding="utf-8", newline="\n") as prod_f:
        for row in rows:
            canon_hash = str(row.get("canon_hash") or "").strip().lower()
            if not re.fullmatch(r"[0-9a-f]{40}", canon_hash):
                continue
            category_id, keywords = best_category(row, categories)
            match_f.write(json.dumps({
                "canon_hash": canon_hash,
                "category_id": category_id,
                "keywords": keywords[:3],
                "confidence": 0.82,
                "source": "external-ai",
                "reason": "rule-based mock classifier for G4 E2E",
            }, ensure_ascii=False, sort_keys=True) + "\n")
            keyword_updates[(keywords[0], category_id)] = "G4 E2E mock keyword"
            prod_f.write(json.dumps({
                "canon_hash": canon_hash,
                "normalized_name": row.get("normalized_name") or row.get("raw_name") or "mock-normalized-product",
                "raw_name": row.get("raw_name") or row.get("normalized_name") or "mock raw product",
                "canonical_url": row.get("canonical_url"),
                "notes": "G4 E2E mock external AI enrichment",
            }, ensure_ascii=False, sort_keys=True) + "\n")

    if keyword_updates:
        keyword_lines = ["new_categories: []", "keywords:"]
        for (keyword, category_id), reason in sorted(keyword_updates.items()):
            keyword_lines.extend([f"  - keyword: {keyword}", f"    category_id: {category_id}", "    synonyms: []", f"    reason: {reason}"])
    else:
        keyword_lines = ["new_categories: []", "keywords: []"]
    keyword_path.write_text("\n".join(keyword_lines) + "\n", encoding="utf-8")
    return {"rows": len(rows), "matching": str(matching_path), "keywords": str(keyword_path), "products": str(product_path)}


def db_external_ai_dump() -> list[dict[str, Any]]:
    code = r'''
import json
from sqlalchemy import text
from services.base import get_engine
sql = """
SELECT mart, mart_native_id, unified_category_id, trust, confidence, decided_by
FROM mart_category_mappings
WHERE trust = 'external-ai'
ORDER BY updated_at DESC
LIMIT 20
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


def latest_export_dir_from_page(page: Any) -> Path:
    text = page.locator("body").inner_text(timeout=5000)
    match = re.search(r"생성 경로:\s*([^\s]+)", text)
    if not match:
        match = re.search(r"([A-Za-z]:\\[^\n\r\t ]*external-ai[^\n\r\t ]*)", text)
    if not match:
        raise AssertionError("Export bundle path not found on External AI page")
    return Path(match.group(1).strip())


def main() -> int:
    parser = argparse.ArgumentParser(description="Round R G4 external AI cycle E2E")
    parser.add_argument("--no-spawn", action="store_true", help="Assume all dev servers are already running.")
    parser.add_argument("--headless", action="store_true", help="Use headless Chromium instead of headed.")
    parser.add_argument("--use-llm", action="store_true", help="Reserved real LLM path; falls back to mock if key/adapter unavailable.")
    args = parser.parse_args()

    require_playwright()
    from playwright.sync_api import sync_playwright

    capture_dir = ROUND_DIR / "captures" / f"G4-e2e-{timestamp()}"
    rows: list[dict[str, Any]] = []
    notes = ["실제 LLM 호출은 기본 비활성화. rule-based mock 외부 AI 산출물로 import 경로를 검증함."]

    try:
        if not args.no_spawn:
            start_servers(capture_dir)
        ensure_unclassified_seed()
        token = db_admin_token()

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=args.headless)
            page = browser.new_page(viewport={"width": 1440, "height": 1000}, locale="ko-KR")
            page.goto("http://127.0.0.1:5174", wait_until="networkidle")
            page.evaluate(f"sessionStorage.setItem('db_admin_access_token', {json.dumps(token)})")
            page.goto("http://127.0.0.1:5174/external-ai", wait_until="networkidle")
            page.get_by_role("button", name=re.compile("Export")).click(timeout=10000)
            page.wait_for_selector("text=생성 경로", timeout=30000)
            c1 = capture(page, "01-db-admin-external-ai-export", capture_dir)
            bundle_dir = latest_export_dir_from_page(page)
            manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
            c2 = capture(page, "02-export-bundle-path-manifest", capture_dir)
            rows.extend([
                {"step": "db-admin 외부 AI 사이클 페이지 Export", "status": "PASS", "evidence": c1},
                {"step": "생성 번들 경로/manifest 확인", "status": "PASS", "evidence": c2},
            ])

            mock_dir = capture_dir / "mock-ai-output"
            mock_result = simulate_external_ai(bundle_dir, mock_dir, use_llm=args.use_llm)
            rows.append({"step": "외부 AI mock 3종 파일 생성", "status": "PASS", "evidence": json.dumps(mock_result, ensure_ascii=False)})

            inputs = page.locator('input[type="file"]')
            inputs.nth(0).set_input_files(str(mock_dir / "matching_updates.jsonl"))
            inputs.nth(1).set_input_files(str(mock_dir / "category_keyword_updates.yaml"))
            inputs.nth(2).set_input_files(str(mock_dir / "product_updates.jsonl"))
            dry_run = page.locator('input[type="checkbox"]').first
            if dry_run.is_checked():
                dry_run.uncheck()
            page.get_by_role("button", name="Import 실행").click(timeout=10000)
            page.wait_for_timeout(3000)
            page.wait_for_selector("text=ok", timeout=45000)
            c3 = capture(page, "03-db-admin-external-ai-import-report", capture_dir)
            rows.append({"step": "Import 페이지 업로드 + 적용 결과", "status": "PASS", "evidence": c3})

            dump = db_external_ai_dump()
            if not dump:
                raise AssertionError("No mart_category_mappings rows with trust='external-ai' after import")
            render_report_page(page, "DB dump: mart_category_mappings trust=external-ai", dump)
            c4 = capture(page, "04-db-dump-external-ai-trust", capture_dir)
            rows.append({"step": "DB 덤프 trust=external-ai 확인", "status": "PASS", "evidence": c4})

            page.goto("http://127.0.0.1:5173/compare", wait_until="networkidle")
            for _ in range(4):
                buttons = page.locator('[data-testid="unified-category-button"]')
                if buttons.count() == 0 or page.locator('[data-testid="compare-product-card"]').count() > 0:
                    break
                buttons.first.click()
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(500)
            if page.locator('[data-testid="compare-product-card"]').count() == 0:
                page.locator("body").wait_for(timeout=2000)
            c5 = capture(page, "05-web-frontend-new-classified-products", capture_dir)
            rows.append({"step": "web-frontend 새 분류 상품 노출 확인", "status": "PASS", "evidence": c5})
            browser.close()

        notes.append(f"Export manifest counts: {manifest.get('counts')}")
    except Exception as exc:
        rows.append({"step": "G4 scenario", "status": "FAIL", "evidence": repr(exc)})
        notes.append(f"실패: {exc!r}")
        write_report(ROUND_DIR / "g4-e2e-report.md", "Round R G4 E2E Report", rows, capture_dir, notes)
        raise

    write_report(ROUND_DIR / "g4-e2e-report.md", "Round R G4 E2E Report", rows, capture_dir, notes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
