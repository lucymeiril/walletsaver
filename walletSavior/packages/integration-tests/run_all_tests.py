"""
WalletSavior 전체 테스트 실행 스크립트.

모든 패키지의 테스트를 순차적으로 실행하고 결과를 요약한다.
사용법: py run_all_tests.py
"""

import subprocess
import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
os.chdir(ROOT)

TEST_SUITES = [
    {
        "name": "Shared (core models & contracts)",
        "path": str(ROOT / "packages" / "shared"),
        "cmd": [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short", "-q"],
    },
    {
        "name": "Integration Tests",
        "path": str(ROOT),
        "cmd": [sys.executable, "-m", "pytest", "packages/integration-tests/", "-v", "--tb=short", "-q"],
    },
]

def run_suite(suite):
    print(f"\n{'='*60}")
    print(f"  Running: {suite['name']}")
    print(f"  Path: {suite['path']}")
    print(f"{'='*60}\n")

    result = subprocess.run(
        suite["cmd"],
        cwd=suite["path"],
        capture_output=False,
        text=True,
    )
    return {
        "name": suite["name"],
        "returncode": result.returncode,
    }


def main():
    print("\n" + "="*60)
    print("  WalletSavior — 전체 테스트 실행")
    print("="*60)

    results = []
    for suite in TEST_SUITES:
        result = run_suite(suite)
        results.append(result)

    print("\n" + "="*60)
    print("  Summary")
    print("="*60)

    total_pass = 0
    total_fail = 0
    for r in results:
        status = "PASS ✓" if r["returncode"] == 0 else "FAIL ✗"
        if r["returncode"] == 0:
            total_pass += 1
        else:
            total_fail += 1
        print(f"  {status}  {r['name']}")

    print(f"\n  Total: {total_pass} passed, {total_fail} failed out of {len(results)} suites")
    print("="*60)

    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
