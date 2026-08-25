"""Run the current WalletSavior Python test suites.

Each backend/package is executed in a separate pytest process to avoid module
namespace collisions. Only services used by the current runtime belong in this
gate; retired cross-service, UX-spec and website-generation harnesses are excluded.
Frontend Vitest suites remain separate npm tasks and are not counted here.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# (display name, working directory relative to repo root, pytest target)
TEST_SUITES = [
    ("shared", "packages/shared", "tests/"),
    ("db-admin", "packages/db-admin/backend", "tests/"),
    ("db-admin-category", "packages/db-admin/backend", "category_data/tests/"),
    ("crawler-admin", "packages/crawler-admin/backend", "tests/"),
    ("crawler-plugins", "packages/crawler-admin/backend", "plugins/tests/"),
    ("web-api", "packages/web-api/backend", "tests/"),
]


def run_suite(name: str, cwd: str, path: str) -> dict:
    workdir = (ROOT / cwd).resolve()
    target = workdir / path
    if not workdir.is_dir():
        return {
            "name": name,
            "returncode": 2,
            "summary": f"missing cwd: {workdir}",
            "stdout": "",
            "stderr": "",
        }
    if not target.exists():
        return {
            "name": name,
            "returncode": 2,
            "summary": f"missing test target: {target}",
            "stdout": "",
            "stderr": "",
        }

    cmd = [sys.executable, "-m", "pytest", path, "--tb=short", "-q"]
    result = subprocess.run(
        cmd,
        cwd=workdir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    lines = result.stdout.strip().splitlines()
    summary = lines[-1] if lines else (result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "no output")
    return {
        "name": name,
        "returncode": result.returncode,
        "summary": summary,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _count(summary: str, label: str) -> int:
    match = re.search(rf"(\d+) {re.escape(label)}", summary)
    return int(match.group(1)) if match else 0


def main() -> None:
    print("=" * 60)
    print("  WalletSavior current Python test suites")
    print("=" * 60)

    results: list[dict] = []
    total_passed = 0
    total_failed = 0

    for name, cwd, path in TEST_SUITES:
        print(f"\n▶ {name} ...", end=" ", flush=True)
        result = run_suite(name, cwd, path)
        results.append(result)

        total_passed += _count(result["summary"], "passed")
        total_failed += _count(result["summary"], "failed")

        if result["returncode"] == 0:
            print(f"✅ {result['summary']}")
        else:
            print(f"❌ {result['summary']}")
            output = result["stdout"].splitlines()[-12:]
            if not output and result["stderr"]:
                output = result["stderr"].splitlines()[-12:]
            for line in output:
                print(f"  {line}")

    print("\n" + "=" * 60)
    print(f"  total reported: {total_passed} passed, {total_failed} failed")
    print("=" * 60)

    failed_suites = [result for result in results if result["returncode"] != 0]
    if failed_suites:
        print("\nfailed suites: " + ", ".join(result["name"] for result in failed_suites))
        raise SystemExit(1)

    print("\n✅ all current Python suites passed")
    raise SystemExit(0)


if __name__ == "__main__":
    main()
