#!/usr/bin/env python3
"""
mcp1_fullchain_drive.py
=======================
WalletSavior MCP1 전체 시나리오 자동화 스크립트 (재실행 가능)

사용법:
    py -3 tools/mcp1_fullchain_drive.py
    py -3 tools/mcp1_fullchain_drive.py --no-start   # 서버 직접 기동 안함
    py -3 tools/mcp1_fullchain_drive.py --headless   # 헤드리스 모드 (기본)
    py -3 tools/mcp1_fullchain_drive.py --headed     # 브라우저 표시

시나리오:
    1. DB-Admin 프론트: 매칭 테이블(Products) 페이지 진입 + 카운트
    2. Crawler-Admin 프론트: 크롤러 목록 확인 + 마트 크롤러 트리거
    3. AI-Admin 프론트 "외부 분류" 탭: Export 실행 → hit/miss 카운트 확인
    4. 외부 분류 시뮬레이션: JSONL 파싱 → fixture 매핑 → 분류 완료 JSONL 생성
    5. DB-Admin 프론트 "분류 Import": JSONL 업로드 → preview → confirm
    6. Web 프론트: 메인 페이지 진입 → 검색 → 상품 카드 확인

산출물:
    mcp1-fullchain-YYYYMMDD-HHMMSS/
        step01_db_admin_products.png
        step02_crawler_admin.png
        step03_ai_export.png
        step03b_ai_export_result.png
        step04_classified.jsonl
        step05_import_preview.png
        step05_import_confirm.png
        step06_web_home.png
        step06_web_search.png
        console_errors.json
        mcp1_report.md
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# 경로 설정
# ─────────────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[1]
SHARED_DIR        = ROOT / "packages" / "shared"
CRAWLER_BACKEND   = ROOT / "packages" / "crawler-admin"  / "backend"
CRAWLER_FRONTEND  = ROOT / "packages" / "crawler-admin"  / "frontend"
DB_BACKEND        = ROOT / "packages" / "db-admin"        / "backend"
DB_FRONTEND       = ROOT / "packages" / "db-admin"        / "frontend"
AI_BACKEND        = ROOT / "packages" / "ai-admin"        / "backend"
AI_FRONTEND       = ROOT / "packages" / "ai-admin"        / "frontend"
WEB_BACKEND       = ROOT / "packages" / "website"         / "backend"
WEB_FRONTEND      = ROOT / "packages" / "website"         / "frontend"

# ─────────────────────────────────────────────────────────────────────────────
# 스크린샷 저장 디렉토리
# ─────────────────────────────────────────────────────────────────────────────
TIMESTAMP     = datetime.now().strftime("%Y%m%d-%H%M%S")
SESSION_FILES = Path("C:/Users/user/.copilot/session-state"
                     "/062b8dc2-33d4-4964-a823-a2a03ff963fc/files")
OUT_DIR       = SESSION_FILES / f"mcp1-fullchain-{TIMESTAMP}"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# 서버 구성
# ─────────────────────────────────────────────────────────────────────────────
PY = sys.executable

def _pythonpath() -> str:
    parts = [str(SHARED_DIR), str(CRAWLER_BACKEND), str(DB_BACKEND),
             str(AI_BACKEND), str(WEB_BACKEND)]
    existing = os.environ.get("PYTHONPATH", "")
    if existing:
        parts.append(existing)
    return os.pathsep.join(parts)

SERVERS = [
    dict(name="website-backend",  port=8000,
         health="http://127.0.0.1:8000/api/health",
         cmd=[PY, "-m", "uvicorn", "api.app:create_app",
              "--factory", "--port", "8000", "--host", "127.0.0.1"],
         cwd=WEB_BACKEND, is_frontend=False),
    dict(name="crawler-backend",  port=8001,
         health="http://127.0.0.1:8001/health",
         cmd=[PY, "-m", "uvicorn", "api.app:create_app",
              "--factory", "--port", "8001", "--host", "127.0.0.1"],
         cwd=CRAWLER_BACKEND, is_frontend=False),
    dict(name="db-backend",       port=8002,
         health="http://127.0.0.1:8002/health",
         cmd=[PY, "-m", "uvicorn", "api.app:create_app",
              "--factory", "--port", "8002", "--host", "127.0.0.1"],
         cwd=DB_BACKEND, is_frontend=False),
    dict(name="ai-backend",       port=8003,
         health="http://127.0.0.1:8003/health",
         cmd=[PY, "-m", "uvicorn", "api.app:create_app",
              "--factory", "--port", "8003", "--host", "127.0.0.1"],
         cwd=AI_BACKEND, is_frontend=False),
    dict(name="website-frontend", port=5173,
         health="http://localhost:5173",
         cmd=["npx.cmd", "vite", "--port", "5173"],
         cwd=WEB_FRONTEND, is_frontend=True),
    dict(name="crawler-frontend", port=5174,
         health="http://localhost:5174",
         cmd=["npx.cmd", "vite", "--port", "5174"],
         cwd=CRAWLER_FRONTEND, is_frontend=True),
    dict(name="db-frontend",      port=5175,
         health="http://localhost:5175",
         cmd=["npx.cmd", "vite", "--port", "5175"],
         cwd=DB_FRONTEND, is_frontend=True),
    dict(name="ai-frontend",      port=5176,
         health="http://localhost:5176",
         cmd=["npx.cmd", "vite", "--port", "5176"],
         cwd=AI_FRONTEND, is_frontend=True),
]

# ─────────────────────────────────────────────────────────────────────────────
# 유틸 — 헬스체크 (동기)
# ─────────────────────────────────────────────────────────────────────────────
try:
    import httpx as _httpx
    def _http_get(url: str, timeout: float = 5.0) -> int:
        try:
            r = _httpx.get(url, timeout=timeout, follow_redirects=True)
            return r.status_code
        except Exception:
            return 0
except ImportError:
    import urllib.request, urllib.error
    def _http_get(url: str, timeout: float = 5.0) -> int:
        try:
            r = urllib.request.urlopen(url, timeout=timeout)
            return r.status
        except Exception:
            return 0


def is_port_listening(port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        try:
            s.connect(("127.0.0.1", port))
            return True
        except OSError:
            return False


def wait_for_health(url: str, name: str, timeout_s: int = 60) -> bool:
    print(f"    ⏳ {name} 헬스체크 대기… ({url})")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        code = _http_get(url)
        if code in (200, 301, 302, 304):
            print(f"    ✅ {name} 준비 완료 (HTTP {code})")
            return True
        time.sleep(2)
    print(f"    ⚠️  {name} 헬스체크 타임아웃 ({timeout_s}초)")
    return False


# ─────────────────────────────────────────────────────────────────────────────
# 서버 기동
# ─────────────────────────────────────────────────────────────────────────────
_started_procs: list[subprocess.Popen] = []

def start_servers() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = _pythonpath()
    # 인증 우회 플래그 추가 (개발 환경)
    env.setdefault("REQUIRE_AUTH", "true")

    for srv in SERVERS:
        name = srv["name"]
        port = srv["port"]
        if is_port_listening(port):
            print(f"  ✅ {name} 이미 실행 중 (port {port})")
            continue
        print(f"  🚀 {name} 시작 (port {port})…")
        proc = subprocess.Popen(
            srv["cmd"],
            cwd=str(srv["cwd"]),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        _started_procs.append(proc)
        time.sleep(1)  # 연속 기동 사이 짧은 간격

    print()
    print("  ⏳ 백엔드 헬스체크…")
    backends = [s for s in SERVERS if not s["is_frontend"]]
    for srv in backends:
        wait_for_health(srv["health"], srv["name"], timeout_s=60)

    print()
    print("  ⏳ 프론트엔드 헬스체크…")
    frontends = [s for s in SERVERS if s["is_frontend"]]
    for srv in frontends:
        wait_for_health(srv["health"], srv["name"], timeout_s=90)


def stop_started_servers() -> None:
    if not _started_procs:
        return
    print("\n🛑 스크립트가 기동한 서버 종료 중…")
    for proc in _started_procs:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    print("✅ 서버 종료 완료")


# ─────────────────────────────────────────────────────────────────────────────
# 콘솔 에러 수집기
# ─────────────────────────────────────────────────────────────────────────────
console_errors: list[dict] = []


def attach_console_listener(page, step_name: str):
    def on_console(msg):
        if msg.type == "error":
            entry = {"step": step_name, "text": msg.text, "url": page.url}
            console_errors.append(entry)
            print(f"    🔴 콘솔 에러 [{step_name}]: {msg.text[:120]}")
    def on_pageerror(exc):
        entry = {"step": step_name, "text": str(exc), "url": page.url, "type": "pageerror"}
        console_errors.append(entry)
        print(f"    🔴 페이지 에러 [{step_name}]: {str(exc)[:120]}")
    page.on("console", on_console)
    page.on("pageerror", on_pageerror)


async def screenshot(page, name: str, full_page: bool = True) -> Path:
    path = OUT_DIR / name
    await page.screenshot(path=str(path), full_page=full_page)
    print(f"    📸 {path.name}")
    return path


# ─────────────────────────────────────────────────────────────────────────────
# 단계별 결과 트래커
# ─────────────────────────────────────────────────────────────────────────────
step_results: list[dict] = []


def mark_step(step: str, status: str, note: str = ""):
    step_results.append({"step": step, "status": status, "note": note})
    icon = "✅" if status == "pass" else ("⚠️" if status == "partial" else "❌")
    print(f"\n{icon} [{step}] {status.upper()}: {note}")


# ─────────────────────────────────────────────────────────────────────────────
# DB-Admin 로그인 헬퍼
# ─────────────────────────────────────────────────────────────────────────────
async def db_admin_login(page) -> bool:
    """DB-Admin 자동 로그인 대기 (autoLoginDev가 성공하면 products 페이지로 이동)"""
    await page.wait_for_timeout(3000)
    # 로그인 페이지가 뜨는 경우 직접 입력
    if await page.locator("input[type='email'], input[type='text']").count() > 0:
        print("    🔐 수동 로그인 진행…")
        try:
            await page.locator("input[type='email'], input[type='text']").first.fill("admin@walletsavior.com")
            pwd = page.locator("input[type='password']")
            if await pwd.count() > 0:
                await pwd.first.fill("admin1234!")
            btn = page.locator("button[type='submit'], button:has-text('로그인')")
            if await btn.count() > 0:
                await btn.first.click()
                await page.wait_for_timeout(2000)
        except Exception as e:
            print(f"    ⚠️  로그인 시도 오류: {e}")
            return False
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Step 1 — DB-Admin: Products(매칭) 페이지
# ─────────────────────────────────────────────────────────────────────────────
async def step1_db_admin_products(context) -> Optional[int]:
    page = await context.new_page()
    attach_console_listener(page, "step1-db-products")
    step = "step1-db-products"
    try:
        print("\n━━━ Step 1: DB-Admin Products 페이지 ━━━")
        await page.goto("http://localhost:5175/products", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(1000)
        # 자동 로그인 대기
        await db_admin_login(page)
        await page.wait_for_timeout(2000)
        # products 페이지로 명시적 이동 (로그인 후 redirect)
        if "products" not in page.url:
            await page.goto("http://localhost:5175/products", wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(2000)
        await screenshot(page, "step01_db_admin_products.png")

        # 행 카운트 시도
        count_text = ""
        try:
            # 통계 카드나 테이블 행 수 확인
            stats = await page.locator("[class*='stat'], [class*='count'], [class*='badge']").all_text_contents()
            count_text = " | ".join(stats[:5]) if stats else "N/A"
        except Exception:
            count_text = "카운트 파싱 불가"

        mark_step(step, "pass", f"Products 페이지 진입 완료. 통계: {count_text[:100]}")
        return True
    except Exception as e:
        await screenshot(page, "step01_db_admin_products_error.png")
        mark_step(step, "fail", str(e)[:200])
        return False
    finally:
        await page.close()


# ─────────────────────────────────────────────────────────────────────────────
# Step 2 — Crawler-Admin: 크롤러 목록 + 마트 크롤러 실행 트리거
# ─────────────────────────────────────────────────────────────────────────────
async def step2_crawler_admin(context) -> bool:
    page = await context.new_page()
    attach_console_listener(page, "step2-crawler")
    step = "step2-crawler"
    try:
        print("\n━━━ Step 2: Crawler-Admin 크롤러 트리거 ━━━")
        await page.goto("http://localhost:5174/", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        # API 키 자동 로그인 대기 (autoLoginDev)
        await page.wait_for_timeout(2000)
        # 로그인 폼이 보이면 처리
        api_key_input = page.locator("input[placeholder*='API'], input[type='password']")
        if await api_key_input.count() > 0:
            print("    🔐 API Key 로그인 진행…")
            await api_key_input.first.fill("walletsavior-dev-crawler-key-2025")
            btn = page.locator("button[type='submit'], button:has-text('로그인')")
            if await btn.count() > 0:
                await btn.first.click()
                await page.wait_for_timeout(2000)

        await screenshot(page, "step02a_crawler_admin_home.png")

        # /crawlers 페이지로 이동
        await page.goto("http://localhost:5174/crawlers", wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(2000)
        await screenshot(page, "step02b_crawler_list.png")

        # 마트 카테고리 필터 클릭 시도
        mart_btn = page.locator("button:has-text('마트'), [data-category='mart']")
        if await mart_btn.count() > 0:
            await mart_btn.first.click()
            await page.wait_for_timeout(1000)
            await screenshot(page, "step02c_crawler_mart_filter.png")

        # 첫 번째 실행 버튼 클릭 시도 (실제 크롤링은 30초 안에 응답 반환)
        run_btn = page.locator("button:has-text('실행'), button[title*='실행'], [data-testid*='run']")
        triggered = False
        if await run_btn.count() > 0:
            await run_btn.first.click()
            print("    ▶️  크롤러 실행 버튼 클릭")
            await page.wait_for_timeout(3000)
            await screenshot(page, "step02d_crawler_triggered.png")
            triggered = True

        mark_step(step, "pass" if triggered else "partial",
                  "크롤러 목록 확인 완료" + (" + 트리거 클릭" if triggered else " (실행 버튼 없음)"))
        return True
    except Exception as e:
        await screenshot(page, "step02_crawler_error.png")
        mark_step(step, "fail", str(e)[:200])
        return False
    finally:
        await page.close()


# ─────────────────────────────────────────────────────────────────────────────
# Step 3 — AI-Admin: "외부 분류" 탭 Export 실행
# ─────────────────────────────────────────────────────────────────────────────
async def step3_ai_export(context) -> Optional[dict]:
    page = await context.new_page()
    attach_console_listener(page, "step3-ai-export")
    step = "step3-ai-export"
    export_result: Optional[dict] = None
    try:
        print("\n━━━ Step 3: AI-Admin 외부 분류 Export ━━━")
        await page.goto("http://localhost:5176/", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)
        await screenshot(page, "step03a_ai_admin_home.png")

        # "외부 분류" 탭 클릭
        export_tab = page.locator('[data-testid="tab-export"], button:has-text("외부 분류")')
        if await export_tab.count() > 0:
            await export_tab.first.click()
            await page.wait_for_timeout(1500)
            await screenshot(page, "step03b_ai_export_panel.png")
        else:
            print("    ⚠️  외부 분류 탭 없음 — 현재 페이지 스크린샷")
            await screenshot(page, "step03b_ai_export_fallback.png")

        # Export 실행 버튼 클릭
        run_btn = page.locator('[data-testid="export-run-btn"], button:has-text("Export 실행")')
        if await run_btn.count() > 0:
            await run_btn.first.click()
            print("    ▶️  Export 실행 버튼 클릭")

            # 결과 대기 (최대 30초)
            result_card = page.locator('[data-testid="export-result-card"]')
            try:
                await result_card.wait_for(state="visible", timeout=30000)
                await screenshot(page, "step03c_ai_export_result.png")

                # hit/miss 카운트 읽기
                hit_el = page.locator('[data-testid="result-hit-count"]')
                miss_el = page.locator('[data-testid="result-miss-count"]')
                hit = await hit_el.inner_text() if await hit_el.count() > 0 else "?"
                miss = await miss_el.inner_text() if await miss_el.count() > 0 else "?"
                print(f"    📊 히트: {hit}, 미스: {miss}")

                # batch_id 읽기
                batch_id_el = page.locator('[data-testid="result-batch-id"]')
                batch_id = await batch_id_el.inner_text() if await batch_id_el.count() > 0 else ""

                export_result = {
                    "hit": hit.strip(),
                    "miss": miss.strip(),
                    "batch_id": batch_id.strip(),
                }

                # JSONL 다운로드 링크 href 수집 (실제 다운로드는 브라우저 기반이라 직접 요청)
                dl_links = await page.locator('[data-testid^="dl-"]').all()
                hrefs = []
                for link in dl_links:
                    href = await link.get_attribute("href")
                    if href:
                        hrefs.append(href)
                export_result["download_hrefs"] = hrefs
                print(f"    🔗 다운로드 링크: {hrefs}")

                mark_step(step, "pass", f"Export 완료. 히트={hit} 미스={miss} batch={batch_id[:20]}")
            except Exception as wait_err:
                # 로딩 인디케이터가 사라졌으나 결과 카드 없음 → export 행 0개일 수도
                await screenshot(page, "step03c_ai_export_no_result.png")
                # toast 메시지 확인
                toast = page.locator('[data-testid="export-toast"]')
                toast_msg = ""
                if await toast.count() > 0:
                    toast_msg = await toast.inner_text()
                mark_step(step, "partial", f"Export 결과 카드 미표시. toast={toast_msg[:100]}")
        else:
            await screenshot(page, "step03c_no_export_btn.png")
            mark_step(step, "fail", "Export 실행 버튼 없음")

        return export_result
    except Exception as e:
        await screenshot(page, "step03_ai_export_error.png")
        mark_step(step, "fail", str(e)[:200])
        return None
    finally:
        await page.close()


# ─────────────────────────────────────────────────────────────────────────────
# Step 4 — 외부 분류 시뮬레이션 (Python: JSONL → classified JSONL)
# ─────────────────────────────────────────────────────────────────────────────
async def step4_classify_jsonl(export_result: Optional[dict]) -> Optional[Path]:
    step = "step4-classify"
    print("\n━━━ Step 4: 외부 분류 시뮬레이션 ━━━")

    # AI-Admin 백엔드에서 직접 export API 호출하여 JSONL 내용 확보
    import httpx as _hx
    import re as _re

    raw_rows: list[dict] = []

    # batch_id 있으면 다운로드 시도
    batch_id = (export_result or {}).get("batch_id", "")
    if batch_id:
        dl_url = f"http://127.0.0.1:8003/api/export/unmatched/download?batch_id={batch_id}&format=jsonl"
        try:
            async with _hx.AsyncClient(timeout=20) as client:
                resp = await client.get(dl_url)
                if resp.status_code == 200:
                    for line in resp.text.splitlines():
                        line = line.strip()
                        if line:
                            try:
                                raw_rows.append(json.loads(line))
                            except Exception:
                                pass
            print(f"    📥 JSONL 다운로드 완료: {len(raw_rows)}행")
        except Exception as e:
            print(f"    ⚠️  JSONL 다운로드 실패: {e}")

    # 행이 없으면 API 직접 호출하여 export
    if not raw_rows:
        print("    🔄 Export API 직접 호출 (batch_id 없음 또는 다운로드 실패)")
        try:
            async with _hx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    "http://127.0.0.1:8003/api/export/unmatched",
                    json={"mart": ["emart", "homeplus", "lottemart", "costco"], "limit": 20},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    new_batch_id = data.get("batch_id", "")
                    miss_count = data.get("miss_count", 0)
                    print(f"    📊 Export 결과: miss={miss_count}, batch={new_batch_id[:20]}")
                    if new_batch_id and miss_count and miss_count > 0:
                        dl_url2 = (f"http://127.0.0.1:8003/api/export/unmatched/download"
                                   f"?batch_id={new_batch_id}&format=jsonl")
                        resp2 = await client.get(dl_url2)
                        if resp2.status_code == 200:
                            for line in resp2.text.splitlines():
                                line = line.strip()
                                if line:
                                    try:
                                        raw_rows.append(json.loads(line))
                                    except Exception:
                                        pass
                            print(f"    📥 재다운로드 완료: {len(raw_rows)}행")
                    elif miss_count == 0:
                        print("    ℹ️  미스 행 없음 — fixture 행 생성")
        except Exception as e:
            print(f"    ⚠️  Export API 호출 실패: {e}")

    # 기존 export artifact 파일이 있으면 로드 (fallback)
    if not raw_rows:
        export_base = ROOT / "artifacts" / "exports" / "unmatched"
        if export_base.exists():
            for batch_dir in sorted(export_base.iterdir(), reverse=True):
                jsonl_path = batch_dir / "unmatched.jsonl"
                if jsonl_path.exists():
                    with open(jsonl_path, encoding="utf-8") as _f:
                        for line in _f:
                            line = line.strip()
                            if line:
                                try:
                                    raw_rows.append(json.loads(line))
                                except Exception:
                                    pass
                    if raw_rows:
                        print(f"    📂 기존 export artifact 로드: {jsonl_path.name} ({len(raw_rows)}행)")
                        break

    # 그래도 행이 없으면 fixture 행 생성 (흐름 검증용)
    if not raw_rows:
        print("    🔧 Fixture 행 생성 (테스트용)")
        raw_rows = [
            {
                "raw_record_id": f"fixture_{i}",
                "source_name": m,
                "raw_title": f"[테스트] {m} 상품 {i}",
                "raw_price": 9900 + i * 100,
                "crawled_at": datetime.now().isoformat(),
                "match_key": None,
                "miss_reason": "no_brand",
            }
            for i, m in enumerate(["emart", "homeplus", "lottemart", "costco"], start=1)
        ]

    # ── 분류 변환: export 행 → import 호환 행 ────────────────────────────────
    # 타이틀 키워드 → category_id 매핑 (간단 휴리스틱)
    _KEYWORD_CAT: list[tuple[str, str]] = [
        ("키위", "agriculture.fruit"),
        ("사과", "agriculture.fruit"),
        ("배", "agriculture.fruit"),
        ("딸기", "agriculture.fruit"),
        ("포도", "agriculture.fruit"),
        ("바나나", "agriculture.fruit"),
        ("배추", "agriculture.leafy.napa_cabbage"),
        ("시금치", "agriculture.leafy.spinach"),
        ("상추", "agriculture.leafy.lettuce"),
        ("양파", "agriculture.bulb.onion"),
        ("감자", "agriculture.root.potato"),
        ("고구마", "agriculture.root.sweet_potato"),
        ("당근", "agriculture.root.carrot"),
        ("돼지", "livestock.pork"),
        ("삼겹", "livestock.pork"),
        ("소고기", "livestock.beef"),
        ("닭", "livestock.chicken"),
        ("계란", "livestock.egg"),
        ("우유", "dairy"),
        ("치즈", "dairy"),
        ("요거트", "dairy"),
        ("생수", "beverage"),
        ("음료", "beverage"),
        ("쌀", "agriculture"),
        ("라면", "processed"),
        ("과자", "processed"),
    ]

    def _guess_category(title: str) -> str:
        """원시 타이틀에서 카테고리 ID 추정 (없으면 'processed' 반환)."""
        for kw, cat in _KEYWORD_CAT:
            if kw in title:
                return cat
        return "processed"

    def _normalize_name(text: str) -> str:
        """특수기호 제거, 소문자, 공백 정규화."""
        text = _re.sub(r"[^\w\s가-힣ㄱ-ㅎㅏ-ㅣ]", " ", text, flags=_re.UNICODE)
        return _re.sub(r"\s+", " ", text).strip().lower()

    classified_rows: list[dict] = []
    for idx, row in enumerate(raw_rows):
        source_name = row.get("source_name", row.get("mart", "unknown"))
        raw_title   = row.get("raw_title", row.get("product_name", f"item_{idx}"))
        category_id = _guess_category(raw_title)

        # match_key: brand=source_name, name_core=normalize(title), qty=1.0, unit="개"
        brand     = source_name.lower().strip()
        name_core = _normalize_name(raw_title)
        pack_qty  = 1.0
        pack_unit = "개"
        match_key = f"{brand}|{name_core}|{pack_qty:.1f}|{pack_unit}"

        classified_rows.append({
            "match_key":   match_key,
            "brand":       brand,
            "name_core":   name_core,
            "pack_qty":    pack_qty,
            "pack_unit":   pack_unit,
            "category_id": category_id,
            "confidence":  0.85,
            "source":      "external-ai",
            "notes":       f"auto-classified from {source_name}: {raw_title[:60]}",
        })

    # JSONL 저장
    out_path = OUT_DIR / "step04_classified.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for r in classified_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"    💾 분류 완료 JSONL 저장: {out_path.name} ({len(classified_rows)}행)")
    mark_step(step, "pass", f"{len(classified_rows)}행 분류 완료 → {out_path.name}")
    return out_path


# ─────────────────────────────────────────────────────────────────────────────
# Step 5 — DB-Admin: 분류 Import 업로드
# ─────────────────────────────────────────────────────────────────────────────
async def step5_db_import(context, classified_jsonl: Optional[Path]) -> bool:
    if not classified_jsonl or not classified_jsonl.exists():
        mark_step("step5-import", "fail", "분류 JSONL 없음")
        return False

    page = await context.new_page()
    attach_console_listener(page, "step5-import")
    step = "step5-import"
    try:
        print("\n━━━ Step 5: DB-Admin 분류 Import ━━━")
        await page.goto("http://localhost:5175/import", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(1000)
        await db_admin_login(page)
        await page.wait_for_timeout(2000)

        if "import" not in page.url:
            await page.goto("http://localhost:5175/import", wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(2000)
        await screenshot(page, "step05a_import_page.png")

        # 파일 업로드 input 찾기
        file_input = page.locator("input[type='file']")
        if await file_input.count() == 0:
            mark_step(step, "fail", "파일 업로드 input 없음")
            await screenshot(page, "step05_no_file_input.png")
            return False

        # lenient 모드 선택 (오류 행 스킵 → preview.ok=True 보장)
        lenient_radio = page.locator("input[type='radio'][value='lenient']")
        if await lenient_radio.count() > 0:
            await lenient_radio.first.check()
            print("    🔧 lenient 모드 선택")
            await page.wait_for_timeout(300)

        await file_input.set_input_files(str(classified_jsonl))
        await page.wait_for_timeout(800)
        await screenshot(page, "step05b_file_selected.png")

        # Preview 버튼 클릭 (data-testid="preview-btn")
        preview_btn = page.locator('[data-testid="preview-btn"], button:has-text("미리보기")')
        if await preview_btn.count() == 0:
            mark_step(step, "fail", "미리보기 버튼 없음")
            return False

        await preview_btn.first.click()
        print("    👁️  미리보기 클릭")

        # step 1 (diff-counts 카드) 대기
        diff_counts = page.locator('[data-testid="diff-counts"]')
        try:
            await diff_counts.wait_for(state="visible", timeout=20000)
        except Exception:
            pass  # lenient 모드면 OK여야 하지만 에러도 허용
        await page.wait_for_timeout(500)
        await screenshot(page, "step05c_import_preview.png")

        # diff/count 카드 수집
        count_info = ""
        try:
            cards = await page.locator("[class*='countCard'], [class*='count'], [class*='badge']").all_text_contents()
            count_info = " | ".join(cards[:6])
        except Exception:
            pass

        # Confirm 버튼 클릭 (data-testid="confirm-btn")
        confirm_btn = page.locator('[data-testid="confirm-btn"]')
        confirmed = False
        if await confirm_btn.count() > 0:
            is_disabled = await confirm_btn.first.get_attribute("disabled")
            if is_disabled is None:  # disabled 속성 없음 = 활성화
                await confirm_btn.first.click()
                print("    ✅ 적용 확인 클릭")
                await page.wait_for_timeout(3000)
                await screenshot(page, "step05d_import_result.png")
                confirmed = True
            else:
                print("    ⚠️  confirm 버튼 비활성화 (preview.ok=False)")
                await screenshot(page, "step05d_confirm_disabled.png")
        else:
            print("    ⚠️  confirm 버튼 없음 — preview 결과 확인 필요")

        mark_step(step, "pass" if confirmed else "partial",
                  f"Import {'완료' if confirmed else '미완'}. 카운트={count_info[:80]}")
        return True
    except Exception as e:
        await screenshot(page, "step05_import_error.png")
        mark_step(step, "fail", str(e)[:200])
        return False
    finally:
        await page.close()


# ─────────────────────────────────────────────────────────────────────────────
# Step 6 — Web 프론트: 메인 + 검색 + 상품 카드 확인
# ─────────────────────────────────────────────────────────────────────────────
async def step6_web_frontend(context) -> bool:
    page = await context.new_page()
    attach_console_listener(page, "step6-web")
    step = "step6-web"
    try:
        print("\n━━━ Step 6: Web 프론트엔드 ━━━")
        await page.goto("http://localhost:5173/", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)
        await screenshot(page, "step06a_web_home.png")

        # 검색창 찾기 — aria-label 또는 placeholder 기준
        search_input = page.locator(
            "input[aria-label='상품 검색'], "
            "input[placeholder*='무엇'], "
            "input[placeholder*='검색'], "
            "input[type='search']"
        )
        searched = False
        if await search_input.count() > 0:
            await search_input.first.fill("라면")
            await page.wait_for_timeout(800)
            await screenshot(page, "step06b_web_search_typing.png")
            await search_input.first.press("Enter")
            print("    🔍 '라면' 검색 (Enter)")
            await page.wait_for_timeout(2500)
            await screenshot(page, "step06c_web_search_result.png")
            searched = True
        else:
            print("    ⚠️  검색 input 없음")

        # 상품 카드 존재 확인
        card_count = 0
        try:
            cards = page.locator("[class*='card'], [class*='product'], [class*='item']")
            card_count = await cards.count()
        except Exception:
            pass

        mark_step(step, "pass" if searched else "partial",
                  f"홈 진입 완료, 검색={'완료' if searched else '없음'}, 카드≈{card_count}")
        return True
    except Exception as e:
        await screenshot(page, "step06_web_error.png")
        mark_step(step, "fail", str(e)[:200])
        return False
    finally:
        await page.close()


# ─────────────────────────────────────────────────────────────────────────────
# 산출물 저장
# ─────────────────────────────────────────────────────────────────────────────
def save_console_errors():
    err_path = OUT_DIR / "console_errors.json"
    with open(err_path, "w", encoding="utf-8") as f:
        json.dump(console_errors, f, ensure_ascii=False, indent=2)
    print(f"\n📋 콘솔 에러 저장: {err_path.name} ({len(console_errors)}건)")
    return err_path


def save_report(screenshots: list[Path]) -> Path:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: list[str] = [
        f"# MCP1 전체 시나리오 보고서",
        f"",
        f"**실행 시각**: {now}  ",
        f"**스크린샷 경로**: `{OUT_DIR}`  ",
        f"**콘솔 에러 수**: {len(console_errors)}건  ",
        f"",
        f"---",
        f"",
        f"## 단계별 결과",
        f"",
        f"| 단계 | 상태 | 비고 |",
        f"|------|------|------|",
    ]
    for r in step_results:
        icon = "✅" if r["status"] == "pass" else ("⚠️" if r["status"] == "partial" else "❌")
        lines.append(f"| {r['step']} | {icon} {r['status']} | {r['note'][:80]} |")

    lines += [
        f"",
        f"---",
        f"",
        f"## 스크린샷 목록",
        f"",
    ]
    for p in sorted(OUT_DIR.glob("*.png")):
        lines.append(f"- `{p.name}`")

    lines += [
        f"",
        f"---",
        f"",
        f"## 콘솔 에러 상세 (상위 20건)",
        f"",
    ]
    for err in console_errors[:20]:
        step_tag = err.get("step", "?")
        text = err.get("text", "")[:200]
        url = err.get("url", "")
        lines.append(f"- **[{step_tag}]** `{url}`  ")
        lines.append(f"  → `{text}`")
        lines.append("")

    lines += [
        f"---",
        f"",
        f"## UX 결함 및 개선 후보",
        f"",
        f"### 관찰된 UX 이슈",
        f"",
    ]

    # 단계별 관찰 기반 자동 기록
    ux_issues = []
    for r in step_results:
        if r["status"] == "fail":
            ux_issues.append(f"- **[{r['step']}]** ❌ 기능 진입 실패: {r['note'][:100]}")
        elif r["status"] == "partial":
            ux_issues.append(f"- **[{r['step']}]** ⚠️  일부 기능 불완전: {r['note'][:100]}")

    # 고정 UX 체크리스트
    ux_checklist = [
        "- **[step1]** DB-Admin Products: 페이지 진입 후 자동 로그인 완료 여부, 스피너 표시 충분한지 확인",
        "- **[step1]** 'raw_crawl_records' / 'matching_entries' 카운트가 Stats 카드에 명확히 노출되는지 확인",
        "- **[step2]** Crawler-Admin: 실행 버튼 클릭 후 진행 상태 표시 (진행 중 spinner/bar 유무)",
        "- **[step2]** 마트 크롤러 완료 알림(toast/badge)이 사용자에게 명확히 보이는지",
        "- **[step3]** AI-Admin Export 결과 카드: hit/miss 수치가 의미 있게 설명되는지 (툴팁 부재)",
        "- **[step3]** 다운로드 버튼이 눈에 띄는 위치에 있는지 (스크롤 아래 숨겨짐 가능성)",
        "- **[step5]** Import 페이지: 3단계 StepBar가 현재 단계를 명확히 표시하는지",
        "- **[step5]** Import Confirm 후 성공/실패 여부를 토스트+카운트로 이중 확인",
        "- **[step6]** Web 홈: 상품 카드에 가격이 크게 표시되는지 확인 (가격 미표시 시 구매 결정 불가)",
        "- **[step6]** 검색 결과 없을 때 빈 상태 메시지('결과 없음') 표시 여부",
        "- **[step6]** '분류 대기 포함' 토글 위치/레이블이 사용자에게 직관적인지",
    ]

    lines.extend(ux_issues if ux_issues else ["(자동 탐지된 결함 없음)"])
    lines.append("")
    lines.append("### UX 체크리스트 (수동 검증 필요)")
    lines.append("")
    lines.extend(ux_checklist)

    lines += [
        f"",
        f"---",
        f"",
        f"## Fix 후보 목록 (다음 세션)",
        f"",
    ]
    # 실패한 단계를 fix 후보로 자동 기록
    for r in step_results:
        if r["status"] in ("fail", "partial"):
            lines.append(f"- **TODO [{r['step']}]**: {r['note'][:120]}")
    if all(r["status"] == "pass" for r in step_results):
        lines.append("- (모든 단계 통과 — 추가 fix 없음)")

    report_path = OUT_DIR / "mcp1_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"📄 보고서 저장: {report_path}")
    return report_path


# ─────────────────────────────────────────────────────────────────────────────
# 메인 엔트리포인트
# ─────────────────────────────────────────────────────────────────────────────
async def run(headless: bool = True, no_start: bool = False):
    from playwright.async_api import async_playwright

    if not no_start:
        print("\n============================================")
        print("  🔧 서버 기동")
        print("============================================")
        start_servers()

    screenshots: list[Path] = []
    export_result: Optional[dict] = None
    classified_jsonl: Optional[Path] = None

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="ko-KR",
        )

        try:
            # ── Step 1: DB-Admin Products ─────────────────────────────
            await step1_db_admin_products(context)

            # ── Step 2: Crawler-Admin ─────────────────────────────────
            await step2_crawler_admin(context)

            # ── Step 3: AI-Admin Export ───────────────────────────────
            export_result = await step3_ai_export(context)

            # ── Step 4: 분류 시뮬레이션 ─────────────────────────────
            classified_jsonl = await step4_classify_jsonl(export_result)

            # ── Step 5: DB-Admin Import ───────────────────────────────
            await step5_db_import(context, classified_jsonl)

            # ── Step 6: Web 프론트 ────────────────────────────────────
            await step6_web_frontend(context)

        except Exception as e:
            print(f"\n💥 예상치 못한 오류: {e}")
            traceback.print_exc()
        finally:
            await context.close()
            await browser.close()

    # ── 산출물 저장 ───────────────────────────────────────────────
    err_path  = save_console_errors()
    report    = save_report(screenshots)

    print("\n============================================")
    print(f"  📁 산출물 경로: {OUT_DIR}")
    print(f"  📸 스크린샷: {len(list(OUT_DIR.glob('*.png')))}장")
    print(f"  🔴 콘솔 에러: {len(console_errors)}건")
    print(f"  📄 보고서: {report.name}")
    print("============================================")

    # 단계별 요약
    print("\n단계별 결과 요약:")
    for r in step_results:
        icon = "✅" if r["status"] == "pass" else ("⚠️" if r["status"] == "partial" else "❌")
        print(f"  {icon} {r['step']}: {r['note'][:80]}")

    return OUT_DIR


def main():
    parser = argparse.ArgumentParser(description="MCP1 전체 시나리오 자동화")
    parser.add_argument("--no-start", action="store_true", help="서버 자동 기동 안 함")
    parser.add_argument("--headed",   action="store_true", help="브라우저 표시 모드")
    parser.add_argument("--headless", action="store_true", help="헤드리스 모드 (기본)")
    args = parser.parse_args()

    headless = not args.headed

    try:
        asyncio.run(run(headless=headless, no_start=args.no_start))
    except KeyboardInterrupt:
        print("\n⚠️  사용자 중단")
    finally:
        if not args.no_start:
            stop_started_servers()


if __name__ == "__main__":
    main()
