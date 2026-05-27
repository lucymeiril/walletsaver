#!/usr/bin/env python3
"""Round T DB verifier for WalletSavior product crawl data.

Creates devlog/round-T/db-verify-report.md with product table counts,
fill rates, URL checks, promo labels, and duplicate canon_hash diagnostics.
Uses only the Python standard library for SQLite dev DBs.
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "devlog" / "round-T" / "db-verify-report.md"
DEFAULT_DB = ROOT / "packages" / "db-admin" / "backend" / "walletguardian.db"
ENV_FILES = (
    ROOT / "packages" / "db-admin" / "backend" / ".env",
    ROOT / "packages" / "db-admin" / "backend" / ".env.local",
)
KEY_COLUMNS = (
    "name",
    "mart",
    "mart_native_code",
    "canon_hash",
    "canonical_url",
    "promo_label",
    "brand",
    "name_core",
    "pack_qty",
    "pack_unit",
    "unit_kind",
    "unit_price_displayed",
    "mart_native_category_id",
)
URL_RE = re.compile(r"^https?://[^\s/$.?#].[^\s]*$", re.IGNORECASE)
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", re.IGNORECASE)
PROMO_NO_RE = re.compile(r"(?:promoNo|promono|promo_no|promo_no_list|dispPromoNo)=?([0-9A-Za-z_-]+)", re.IGNORECASE)


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        values[key.strip()] = value
    return values


def discover_database_url(cli_url: str | None) -> str:
    if cli_url:
        return cli_url
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    merged: dict[str, str] = {}
    for env_file in ENV_FILES:
        merged.update(parse_env_file(env_file))
    if merged.get("DATABASE_URL"):
        return merged["DATABASE_URL"]
    return f"sqlite:///{DEFAULT_DB}"


def sqlite_path_from_url(url: str) -> Path:
    if url.startswith("sqlite:///"):
        raw = unquote(url[len("sqlite:///") :])
        path = Path(raw)
        if not path.is_absolute():
            path = ROOT / path
        return path
    if url.startswith("sqlite://"):
        raw = unquote(url[len("sqlite://") :])
        return (ROOT / raw).resolve()
    return Path(url).resolve()


def q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def scalar(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> Any:
    return conn.execute(sql, params).fetchone()[0]


def table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {str(r[0]) for r in rows}


def table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in conn.execute(f"PRAGMA table_info({q(table)})").fetchall()]


def non_empty_expr(column: str) -> str:
    return f"({q(column)} IS NOT NULL AND TRIM(CAST({q(column)} AS TEXT)) <> '')"


def pct(part: int, total: int) -> str:
    if total <= 0:
        return "0.0%"
    return f"{part / total * 100:.1f}%"


def render_report(database_url: str, db_path: Path, conn: sqlite3.Connection) -> str:
    tables = table_names(conn)
    product_table = "products" if "products" in tables else ("Product" if "Product" in tables else None)
    lines: list[str] = []
    now = datetime.now(timezone.utc).isoformat()
    safe_url = database_url if database_url.startswith("sqlite") else "non-sqlite DATABASE_URL (not printed)"
    lines += [
        "# Round T DB Verify Report",
        "",
        f"- generated_at: `{now}`",
        f"- database_url: `{safe_url}`",
        f"- sqlite_path: `{db_path}`",
        "",
    ]
    if not db_path.exists():
        lines += ["## Result", "", "❌ SQLite DB file does not exist.", ""]
        return "\n".join(lines)
    if not product_table:
        lines += ["## Product SELECT", "", "❌ No `products` or `Product` table found.", ""]
        return "\n".join(lines)

    columns = table_columns(conn, product_table)
    total = int(scalar(conn, f"SELECT COUNT(*) FROM {q(product_table)}"))
    lines += ["## Product SELECT", "", f"- table: `{product_table}`", f"- rows: `{total}`", f"- columns: `{', '.join(columns)}`", ""]

    lines += ["## Mart Counts", ""]
    if "mart" in columns:
        rows = conn.execute(
            f"SELECT COALESCE(NULLIF(TRIM(CAST({q('mart')} AS TEXT)), ''), '(empty)') AS mart, COUNT(*) "
            f"FROM {q(product_table)} GROUP BY mart ORDER BY COUNT(*) DESC, mart"
        ).fetchall()
        lines += ["| mart | count |", "|---|---:|"]
        lines += [f"| {row[0]} | {row[1]} |" for row in rows]
    else:
        lines.append("- `mart` column missing; mart counts skipped.")
    lines.append("")

    lines += ["## Column Fill Rates", "", "| column | filled | total | fill_rate |", "|---|---:|---:|---:|"]
    for col in KEY_COLUMNS:
        if col not in columns:
            lines.append(f"| {col} | missing | {total} | n/a |")
            continue
        filled = int(scalar(conn, f"SELECT COUNT(*) FROM {q(product_table)} WHERE {non_empty_expr(col)}"))
        lines.append(f"| {col} | {filled} | {total} | {pct(filled, total)} |")
    lines.append("")

    lines += ["## URL Format Checks", ""]
    if "canonical_url" in columns:
        urls = [str(r[0]) for r in conn.execute(
            f"SELECT {q('canonical_url')} FROM {q(product_table)} WHERE {non_empty_expr('canonical_url')}"
        ).fetchall()]
        valid = [u for u in urls if URL_RE.match(u) and urlparse(u).scheme in {"http", "https"}]
        uuid_hits = sum(1 for u in urls if UUID_RE.search(u))
        promo_hits = sum(1 for u in urls if PROMO_NO_RE.search(u))
        invalid = [u for u in urls if u not in valid]
        lines += [
            f"- non_empty_urls: `{len(urls)}`",
            f"- valid_http_urls: `{len(valid)}` ({pct(len(valid), len(urls))})",
            f"- uuid_url_hits: `{uuid_hits}`",
            f"- promoNo_url_hits: `{promo_hits}`",
        ]
        if invalid:
            lines.append("- invalid_url_samples:")
            for u in invalid[:10]:
                lines.append(f"  - `{u}`")
    else:
        lines.append("- `canonical_url` column missing; URL checks skipped.")
    lines.append("")

    lines += ["## Promo Label Distribution", ""]
    if "promo_label" in columns:
        rows = conn.execute(
            f"SELECT COALESCE(NULLIF(TRIM(CAST({q('promo_label')} AS TEXT)), ''), '(empty)') AS promo_label, COUNT(*) "
            f"FROM {q(product_table)} GROUP BY promo_label ORDER BY COUNT(*) DESC, promo_label LIMIT 50"
        ).fetchall()
        lines += ["| promo_label | count |", "|---|---:|"]
        lines += [f"| {row[0]} | {row[1]} |" for row in rows]
    else:
        lines.append("- `promo_label` column missing in this DB; migration/schema update may be pending.")
    lines.append("")

    lines += ["## Duplicate canon_hash", ""]
    if "canon_hash" in columns:
        rows = conn.execute(
            f"SELECT {q('canon_hash')}, COUNT(*) AS n FROM {q(product_table)} "
            f"WHERE {non_empty_expr('canon_hash')} GROUP BY {q('canon_hash')} HAVING COUNT(*) > 1 ORDER BY n DESC LIMIT 50"
        ).fetchall()
        lines += [f"- duplicate_groups: `{len(rows)}`"]
        if rows:
            lines += ["", "| canon_hash | count |", "|---|---:|"]
            lines += [f"| {row[0]} | {row[1]} |" for row in rows]
    else:
        lines.append("- `canon_hash` column missing; duplicate check skipped.")
    lines.append("")

    sample_cols = [c for c in ("id", "mart", "mart_native_code", "name", "canonical_url", "promo_label", "canon_hash") if c in columns]
    lines += ["## Sample Rows", ""]
    if sample_cols and total:
        rows = conn.execute(f"SELECT {', '.join(q(c) for c in sample_cols)} FROM {q(product_table)} LIMIT 5").fetchall()
        lines.append("| " + " | ".join(sample_cols) + " |")
        lines.append("|" + "---|" * len(sample_cols))
        for row in rows:
            lines.append("| " + " | ".join(str(v) if v is not None else "" for v in row) + " |")
    else:
        lines.append("- No sample rows available.")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify WalletSavior Round T product DB state")
    parser.add_argument("--database-url", help="Override DATABASE_URL; sqlite:///... supported")
    parser.add_argument("--report", default=str(REPORT_PATH), help="Markdown report output path")
    args = parser.parse_args()

    database_url = discover_database_url(args.database_url)
    if not (database_url.startswith("sqlite") or database_url.endswith(".db") or database_url.endswith(".sqlite")):
        out = Path(args.report)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            "# Round T DB Verify Report\n\n"
            f"- generated_at: `{datetime.now(timezone.utc).isoformat()}`\n"
            "- result: non-SQLite DATABASE_URL detected; install/use project DB tooling or pass `--database-url sqlite:///...`.\n",
            encoding="utf-8",
        )
        print(f"Wrote {out}")
        return 0

    db_path = sqlite_path_from_url(database_url)
    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    if not db_path.exists():
        report = render_report(database_url, db_path, sqlite3.connect(":memory:"))
    else:
        conn = sqlite3.connect(db_path)
        try:
            report = render_report(database_url, db_path, conn)
        finally:
            conn.close()
    out.write_text(report, encoding="utf-8")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
