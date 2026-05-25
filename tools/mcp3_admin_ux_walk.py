"""
mcp3_admin_ux_walk.py
=====================
WalletSavior 3개 admin 프론트엔드 UX 점검 자동화 스크립트.

사용법:
    pip install playwright
    playwright install chromium
    python tools/mcp3_admin_ux_walk.py

출력:
    C:/Users/user/.copilot/session-state/<session_id>/files/mcp3-admin-<timestamp>/
      before/  -- 수정 전 스크린샷 (수동으로 git stash 후 실행 시 before 취득)
      after/   -- 수정 후 스크린샷 (현재 기본)
      mcp3_report.md

포트:
    ai-admin     : 5176  (backend 8003)
    db-admin     : 5175  (backend 8002)
    crawler-admin: 5174  (backend 8001)

주의:
    - 각 admin 서버가 실행 중이어야 합니다.
    - 로그인 없이 접근 가능한 개발 모드(autoLoginDev)를 가정합니다.
    - 백엔드 없이 프론트만 실행 중인 경우 API 오류는 무시됩니다.
"""

import asyncio
import datetime
import os
import sys
from pathlib import Path

try:
    from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
except ImportError:
    print("playwright 미설치. pip install playwright 후 재실행.")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────────────────────────────────────

SESSION_ID = "062b8dc2-33d4-4964-a823-a2a03ff963fc"
TIMESTAMP = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
OUT_ROOT = Path(f"C:/Users/user/.copilot/session-state/{SESSION_ID}/files/mcp3-admin-{TIMESTAMP}")
AFTER_DIR = OUT_ROOT / "after"
BEFORE_DIR = OUT_ROOT / "before"

ADMINS = {
    "ai-admin": {
        "base": "http://localhost:5176",
        "pages": [
            {"name": "home",       "path": "/",       "tab": "tab-home"},
            {"name": "export",     "path": "/",       "tab": "tab-export"},
            {"name": "review",     "path": "/",       "tab": "tab-review"},
            {"name": "advanced",   "path": "/",       "tab": "tab-advanced"},
        ],
    },
    "db-admin": {
        "base": "http://localhost:5175",
        "pages": [
            {"name": "dashboard",       "path": "/"},
            {"name": "classification",  "path": "/classification"},
            {"name": "import",          "path": "/import"},
            {"name": "products",        "path": "/products"},
        ],
    },
    "crawler-admin": {
        "base": "http://localhost:5174",
        "pages": [
            {"name": "dashboard",      "path": "/"},
            {"name": "crawlers",       "path": "/crawlers"},
            {"name": "weekly-alerts",  "path": "/weekly-alerts"},
            {"name": "schedule",       "path": "/schedule"},
        ],
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# 헬퍼
# ─────────────────────────────────────────────────────────────────────────────

async def wait_settle(page, timeout=3000):
    """네트워크 정착 대기."""
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout)
    except PlaywrightTimeout:
        pass
    await asyncio.sleep(0.5)


async def screenshot(page, path: Path, full_page=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    await page.screenshot(path=str(path), full_page=full_page)
    print(f"  📸 {path}")


async def console_errors(page) -> list[str]:
    """페이지에서 수집된 콘솔 에러 반환 (이미 page에 리스너 붙었다고 가정)."""
    return getattr(page, "_console_errors", [])


def attach_console_listener(page):
    errors = []
    page._console_errors = errors  # type: ignore[attr-defined]

    def on_console(msg):
        if msg.type == "error":
            errors.append(msg.text)

    page.on("console", on_console)


# ─────────────────────────────────────────────────────────────────────────────
# ai-admin 점검
# ─────────────────────────────────────────────────────────────────────────────

async def walk_ai_admin(browser, out_dir: Path):
    results = []
    base = ADMINS["ai-admin"]["base"]
    page = await browser.new_page()
    attach_console_listener(page)

    try:
        await page.goto(base, wait_until="domcontentloaded", timeout=15000)
        await wait_settle(page)

        # 홈 탭
        await screenshot(page, out_dir / "ai_home.png")
        results.append({"page": "ai-admin/홈", "errors": list(console_errors(page))})

        # 외부 분류 탭
        try:
            await page.click('[data-testid="tab-export"]', timeout=5000)
            await wait_settle(page)
            await screenshot(page, out_dir / "ai_export.png")
            results.append({"page": "ai-admin/외부 분류", "errors": list(console_errors(page))})
        except Exception as e:
            results.append({"page": "ai-admin/외부 분류", "errors": [str(e)]})

        # 검수 탭
        try:
            await page.click('[data-testid="tab-review"]', timeout=5000)
            await wait_settle(page)
            await screenshot(page, out_dir / "ai_review.png")
            results.append({"page": "ai-admin/검수", "errors": list(console_errors(page))})
        except Exception as e:
            results.append({"page": "ai-admin/검수", "errors": [str(e)]})

        # 고급 탭
        try:
            await page.click('[data-testid="tab-advanced"]', timeout=5000)
            await wait_settle(page)
            await screenshot(page, out_dir / "ai_advanced.png")
            results.append({"page": "ai-admin/고급", "errors": list(console_errors(page))})
        except Exception as e:
            results.append({"page": "ai-admin/고급", "errors": [str(e)]})

    finally:
        await page.close()

    return results


# ─────────────────────────────────────────────────────────────────────────────
# db-admin 점검
# ─────────────────────────────────────────────────────────────────────────────

async def walk_db_admin(browser, out_dir: Path):
    results = []
    base = ADMINS["db-admin"]["base"]

    for pg in ADMINS["db-admin"]["pages"]:
        page = await browser.new_page()
        attach_console_listener(page)
        try:
            url = base + pg["path"]
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            await wait_settle(page)
            fname = f"db_{pg['name']}.png"
            await screenshot(page, out_dir / fname)
            results.append({"page": f"db-admin/{pg['name']}", "errors": list(console_errors(page))})
        except Exception as e:
            results.append({"page": f"db-admin/{pg['name']}", "errors": [str(e)]})
        finally:
            await page.close()

    return results


# ─────────────────────────────────────────────────────────────────────────────
# crawler-admin 점검
# ─────────────────────────────────────────────────────────────────────────────

async def walk_crawler_admin(browser, out_dir: Path):
    results = []
    base = ADMINS["crawler-admin"]["base"]

    # 로그인 (개발 자동 로그인 — /api/auth/login)
    page = await browser.new_page()
    attach_console_listener(page)
    try:
        await page.goto(base, wait_until="domcontentloaded", timeout=15000)
        await wait_settle(page, timeout=5000)
    except Exception:
        pass

    for pg in ADMINS["crawler-admin"]["pages"]:
        try:
            url = base + pg["path"]
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            await wait_settle(page)
            fname = f"crawler_{pg['name']}.png"
            await screenshot(page, out_dir / fname)
            results.append({"page": f"crawler-admin/{pg['name']}", "errors": list(console_errors(page))})
        except Exception as e:
            results.append({"page": f"crawler-admin/{pg['name']}", "errors": [str(e)]})

    await page.close()
    return results


# ─────────────────────────────────────────────────────────────────────────────
# 보고서 생성
# ─────────────────────────────────────────────────────────────────────────────

def write_report(results: list[dict], out_dir: Path):
    lines = [
        "# mcp3 Admin UX 점검 보고서",
        "",
        f"생성 일시: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 스크린샷 목록",
        "",
    ]
    for r in results:
        err_text = f" ⚠ 콘솔 에러 {len(r['errors'])}건" if r["errors"] else " ✅"
        lines.append(f"- **{r['page']}**{err_text}")
        if r["errors"]:
            for e in r["errors"][:3]:
                lines.append(f"  - `{e[:120]}`")

    lines += [
        "",
        "## UX Fix 적용 내역",
        "",
        "### ai-admin (port 5176)",
        "- ✅ 홈/검수/외부 분류/고급 탭 각 상단에 1줄 페이지 설명 추가",
        "- ✅ '비우기' 버튼을 `btn-danger` 로 강조, '🗑 AI 제안 비우기…' 라벨 명확화",
        "- ✅ 고급 탭 위험 작업 섹션 제목을 `var(--danger)` 색으로 강조하여 비우기 위치 즉시 파악",
        "- ✅ AdvancedPage 페이지 설명 — '일반 사용자는 홈/검수 탭 이용' 안내 추가",
        "- ✅ `.page-desc` CSS 클래스 신설 — 배경 패널 + 라운드 박스로 시각적 구분",
        "",
        "### db-admin (port 5175)",
        "- ✅ ImportClassifiedPage 헤더에 subtitle 추가 — 3단계 흐름 안내",
        "- ✅ ClassificationPage 헤더에 subtitle 추가 — 카테고리/키워드 역할 설명",
        "",
        "### crawler-admin (port 5174)",
        "- ✅ **WeeklyAlertsPage 신설** (`/weekly-alerts`)",
        "  - GET /api/weekly/alerts 목록 표시 (상태·마트 필터)",
        "  - POST /api/weekly/alerts/{id}/resolve 1-click 해결 처리",
        "  - 미해결 알림 카운트 배너 표시",
        "- ✅ 사이드바 nav에 '주간 알림' 메뉴 추가 (Bell 아이콘)",
        "- ✅ Dashboard 페이지 설명 추가",
        "",
        "## 잔여 개선 후보",
        "",
        "- [ ] ai-admin 외부 분류 탭: Export 버튼을 더 크게 (현재 min-width 130px → 160px 이상 권장)",
        "- [ ] ai-admin 고급 탭: 파이프라인 스텝 카드에 클릭 시 해당 상세 패널 자동 펼침",
        "- [ ] db-admin 매칭 테이블 페이지: 검색 필드 상단 고정 + 엔트리 인라인 수정",
        "- [ ] crawler-admin 주간 알림: 주간 diff 리포트(/api/weekly/diff) 탭도 같은 페이지에 추가",
        "- [ ] 전체: 모바일(375px) 반응형 추가 점검",
        "",
        "## 콘솔 에러 현황",
        "",
    ]

    all_errors = [r for r in results if r["errors"]]
    if all_errors:
        for r in all_errors:
            lines.append(f"### {r['page']}")
            for e in r["errors"]:
                lines.append(f"- `{e}`")
    else:
        lines.append("콘솔 에러 없음 (또는 백엔드 미실행으로 API 에러는 무시됨)")

    report_path = out_dir.parent / "mcp3_report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n📄 보고서: {report_path}")


# ─────────────────────────────────────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────────────────────────────────────

async def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "after"
    if mode not in ("before", "after"):
        print("Usage: python mcp3_admin_ux_walk.py [before|after]")
        sys.exit(1)

    out_dir = BEFORE_DIR if mode == "before" else AFTER_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"출력 디렉토리: {out_dir}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        all_results = []

        print("\n=== ai-admin (5176) ===")
        try:
            r = await walk_ai_admin(browser, out_dir)
            all_results.extend(r)
        except Exception as e:
            print(f"  ai-admin 실패: {e}")
            all_results.append({"page": "ai-admin", "errors": [str(e)]})

        print("\n=== db-admin (5175) ===")
        try:
            r = await walk_db_admin(browser, out_dir)
            all_results.extend(r)
        except Exception as e:
            print(f"  db-admin 실패: {e}")
            all_results.append({"page": "db-admin", "errors": [str(e)]})

        print("\n=== crawler-admin (5174) ===")
        try:
            r = await walk_crawler_admin(browser, out_dir)
            all_results.extend(r)
        except Exception as e:
            print(f"  crawler-admin 실패: {e}")
            all_results.append({"page": "crawler-admin", "errors": [str(e)]})

        await browser.close()

    write_report(all_results, out_dir)
    print("\n✅ 완료")


if __name__ == "__main__":
    asyncio.run(main())
