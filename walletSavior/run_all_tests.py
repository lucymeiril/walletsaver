"""
WalletSavior 전체 테스트 실행 스크립트.

각 패키지를 독립적으로 테스트한 후 결과를 종합한다.
패키지 간 모듈 네임스페이스 충돌을 방지하기 위해 개별 실행.
"""

import subprocess
import sys

# 각 테스트 스위트: (이름, 작업 디렉터리, pytest 경로)
TEST_SUITES = [
    ("shared", "packages/shared", "tests/"),
    ("db-admin", "packages/db-admin/backend", "tests/"),
    ("db-admin-category", "packages/db-admin/backend", "category_data/tests/"),
    ("db-admin-price", "packages/db-admin/backend", "price_data/tests/"),
    ("crawler-admin", "packages/crawler-admin/backend", "tests/"),
    ("crawler-plugins", "packages/crawler-admin/backend", "plugins/tests/"),
    ("website-backend", "packages/website/backend", "tests/"),
    ("integration", ".", "packages/integration-tests/"),
    ("user-tests", ".", "packages/user-tests/"),
    ("security-perf", ".", "packages/security-perf-tests/"),
]


def run_suite(name, cwd, path):
    """단일 테스트 스위트를 실행하고 결과를 반환한다."""
    cmd = [sys.executable, "-m", "pytest", path, "--tb=short", "-q"]
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    # 마지막 줄에서 통과/실패 수 추출
    lines = result.stdout.strip().split("\n")
    summary = lines[-1] if lines else "no output"
    return {
        "name": name,
        "returncode": result.returncode,
        "summary": summary,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def main():
    print("=" * 60)
    print("  WalletSavior 전체 테스트 실행")
    print("=" * 60)

    results = []
    total_passed = 0
    total_failed = 0

    for name, cwd, path in TEST_SUITES:
        print(f"\n▶ {name} ...", end=" ", flush=True)
        r = run_suite(name, cwd, path)
        results.append(r)

        if r["returncode"] == 0:
            # "N passed" 패턴에서 숫자 추출
            import re
            m = re.search(r"(\d+) passed", r["summary"])
            passed = int(m.group(1)) if m else 0
            total_passed += passed
            print(f"✅ {passed} passed")
        else:
            print(f"❌ FAILED")
            # 실패 시 상세 출력
            for line in r["stdout"].split("\n")[-10:]:
                print(f"  {line}")
            m_f = __import__("re").search(r"(\d+) failed", r["summary"])
            if m_f:
                total_failed += int(m_f.group(1))

    print("\n" + "=" * 60)
    print(f"  총 결과: {total_passed} passed, {total_failed} failed")
    print("=" * 60)

    # 하나라도 실패하면 exit code 1
    failed_suites = [r for r in results if r["returncode"] != 0]
    if failed_suites:
        print(f"\n실패한 스위트: {', '.join(r['name'] for r in failed_suites)}")
        sys.exit(1)
    else:
        print("\n🎉 모든 테스트 통과!")
        sys.exit(0)


if __name__ == "__main__":
    main()
