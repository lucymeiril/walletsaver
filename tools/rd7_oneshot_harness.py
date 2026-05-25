"""RD7 원샷 DB 구축 반복 테스트 하네스.

목적
====
빈 DB → 크롤링(또는 fixture) → crawler-admin /api/export/raw-batch → 외부 LLM(서브
에이전트) 분류 → db-admin /api/import/bundle → 적대적 감사를 단일 명령으로 실행
한다. 외부 LLM 호출은 두 모드로 추상화되어 있다.

  manual            : invoke-llm-stub 단계에서 export 폴더 경로를 출력하고 종료.
                       호출자(상위 메인 에이전트)가 sub-agent에 폴더와 운영 매뉴얼
                       을 전달, sub-agent 산출물(3종 파일)을 같은 폴더에 떨군 뒤
                       --phase=import,audit 로 이어 실행.
  heuristic-fallback: 외부 LLM 호출 없이 휴리스틱(이름 정규화 + 기본 카테고리)으로
                       3종 파일을 자동 생성. 하네스 자체 동작 검증용.

CLI 예시
========
  py -3 tools/rd7_oneshot_harness.py --phase=all --llm-mode=heuristic-fallback --source=fixture
  py -3 tools/rd7_oneshot_harness.py --phase=reset --allow-reset
  py -3 tools/rd7_oneshot_harness.py --phase=crawl --source=fixture --marts=emart,homeplus,lottemart,costco --max-rows=200
  py -3 tools/rd7_oneshot_harness.py --phase=export
  py -3 tools/rd7_oneshot_harness.py --phase=invoke-llm-stub --llm-mode=manual --export-id=exp-...
  py -3 tools/rd7_oneshot_harness.py --phase=import --export-id=exp-...
  py -3 tools/rd7_oneshot_harness.py --phase=audit --export-id=exp-...

산출물
======
  artifacts/rd7/runs/<run_id>/
    00_reset.json           — 테이블별 row count before/after
    01_crawl_summary.json   — 마트별 batch_id / row count
    02_export.json          — export_id, miss_rows, file sha256
    03_llm_stub.json        — 3종 파일 생성 결과 (또는 manual stub 안내)
    04_import.json          — preview/confirm 응답 요약
    05_audit.json           — 정합성 점검 결과
    audit_summary.md        — 한국어 요약 리포트
    improvement_hints.md    — audit FAIL/WARN 시 자동 생성

서버 기동
=========
크롤러/ai/db-admin 백엔드 3개는 health-check 후 자동 기동(--no-spawn-servers 로
끌 수 있음). 기동된 서버는 하네스 종료 시 자동 종료. --keep-servers 로 유지 가능.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import statistics
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "rd7"
EXPORT_BASE = REPO_ROOT / "artifacts" / "exports" / "raw-batch"

AI_DB = REPO_ROOT / "packages" / "ai-admin" / "backend" / "ai_control.db"
DB_DB = REPO_ROOT / "packages" / "db-admin" / "backend" / "walletguardian.db"
CR_DB = REPO_ROOT / "packages" / "crawler-admin" / "backend" / "orchestrator.db"

# 마트 4사 + (선택) 코스트코 등 라벨
DEFAULT_MARTS = ["emart", "lottemart", "homeplus", "costco"]

# 인증 키 — 각 .env에서 가져옴. 환경변수가 있으면 그것 우선.
CRAWLER_API_KEY = os.getenv("CRAWLER_ADMIN_API_KEY", "walletsavior-dev-crawler-key-2025")
DB_API_KEY = os.getenv("DB_ADMIN_API_KEY", "D5uo6WpELKjCw3LuTnvKaheSHM0D2zOT7iqrSJWPls8")

CRAWLER_URL = os.getenv("CRAWLER_ADMIN_URL", "http://127.0.0.1:8001")
AI_URL = os.getenv("AI_ADMIN_URL", "http://127.0.0.1:8003")
DB_URL = os.getenv("DB_ADMIN_URL", "http://127.0.0.1:8002")

# Reset 대상 — root taxonomy(categories/keywords)는 보존
AI_RESET_TABLES = [
    "raw_crawl_records",
    "raw_crawl_batches",
    "ai_publish_records",
    "ai_jobs",
    "labeling_run_logs",
    "review_decisions",
    "product_matches",
    "field_proposals",
    "keyword_proposals",
    "worker_attempts",
    "alias_audit_log",
    "bulk_archive_audit",
    "learned_knowledge",
    "user_feedback",
]
DB_RESET_TABLES = [
    "baseline_prices",
    "products",
    "product_matches",
    "matching_entries",
    "pending_categorizations",
    "pending_ingestions",
    "category_corrections",
    "discount_history",
    "hotdeal_prices",
    "audit_logs",
]


# ──────────────────────────────────────────────────────────────────────────────
# 유틸
# ──────────────────────────────────────────────────────────────────────────────

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def log(msg: str) -> None:
    print(f"[{utc_now()}] {msg}", flush=True)


def http_request(
    method: str,
    url: str,
    *,
    headers: Optional[dict] = None,
    body: Optional[bytes] = None,
    timeout: float = 60.0,
) -> tuple[int, bytes, dict]:
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers) if e.headers else (e.code, e.read(), {})


def normalize_match_key(brand: Optional[str], name_core: Optional[str],
                        pack_qty: Optional[float], pack_unit: Optional[str]) -> str:
    """packages/shared/core/match_key.py 정규화 규칙과 동일."""
    b = (brand or "").strip().lower()
    n = (name_core or "").lower()
    n = re.sub(r"[^\w\s가-힣ㄱ-ㅎㅏ-ㅣ]", " ", n, flags=re.UNICODE)
    n = re.sub(r"\s+", " ", n).strip()
    if pack_qty is not None:
        q = f"{round(float(pack_qty), 1):.1f}"
    else:
        q = ""
    u = (pack_unit or "").strip().lower()
    return f"{b}|{n}|{q}|{u}"


# ──────────────────────────────────────────────────────────────────────────────
# 서버 라이프사이클
# ──────────────────────────────────────────────────────────────────────────────

class ServerSet:
    """3개 백엔드의 health-check 및 자동 기동/종료."""

    def __init__(self, spawn: bool = True):
        self.spawn = spawn
        self.procs: list[subprocess.Popen] = []

    def health(self, url: str, path: str = "/health", timeout: float = 3.0) -> bool:
        try:
            status, _, _ = http_request("GET", f"{url}{path}", timeout=timeout)
            return status < 500
        except Exception:
            return False

    def _spawn(self, cwd: Path, env_extra: dict, label: str, port: int) -> subprocess.Popen:
        env = os.environ.copy()
        env.update(env_extra)
        env.setdefault("PYTHONUNBUFFERED", "1")
        env.setdefault("PYTHONIOENCODING", "utf-8")
        shared = str(REPO_ROOT / "packages" / "shared")
        backend = str(cwd)
        existing = env.get("PYTHONPATH", "")
        sep = ";" if os.name == "nt" else ":"
        env["PYTHONPATH"] = sep.join(p for p in [shared, backend, existing] if p)
        log_path = ARTIFACT_ROOT / "server-logs" / f"{label}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(log_path, "ab")
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "api.app:create_app", "--factory",
             "--port", str(port), "--host", "127.0.0.1"],
            cwd=str(cwd),
            env=env,
            stdout=fh,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
        log(f"  spawned {label} pid={proc.pid} cwd={cwd.name}")
        self.procs.append(proc)
        return proc

    def ensure(self, which: tuple[str, ...]) -> dict:
        """필요한 서버들을 띄운다. 반환: {label: 'already-up'|'spawned'|'failed'}."""
        status = {}
        targets = {
            "crawler": (CRAWLER_URL, 8001, REPO_ROOT / "packages" / "crawler-admin" / "backend", {}),
            "ai": (AI_URL, 8003, REPO_ROOT / "packages" / "ai-admin" / "backend", {}),
            "db": (DB_URL, 8002, REPO_ROOT / "packages" / "db-admin" / "backend", {"REQUIRE_AUTH": "true"}),
        }
        for label in which:
            url, port, cwd, env_extra = targets[label]
            if self.health(url):
                status[label] = "already-up"
                log(f"  {label} ok ({url})")
                continue
            if not self.spawn:
                status[label] = "down-and-spawn-disabled"
                continue
            self._spawn(cwd, env_extra, label, port)
            # wait up to 60s
            deadline = time.time() + 60
            while time.time() < deadline:
                time.sleep(1.0)
                if self.health(url):
                    status[label] = "spawned"
                    log(f"  {label} ready ({url})")
                    break
            else:
                status[label] = "spawn-failed"
                log(f"  {label} FAILED to become ready ({url})")
        return status

    def shutdown(self) -> None:
        for proc in self.procs:
            try:
                proc.terminate()
            except Exception:
                pass
        deadline = time.time() + 5
        for proc in self.procs:
            try:
                proc.wait(timeout=max(0.1, deadline - time.time()))
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self.procs.clear()


# ──────────────────────────────────────────────────────────────────────────────
# Phase: RESET
# ──────────────────────────────────────────────────────────────────────────────

def phase_reset(run_dir: Path, allow_reset: bool) -> dict:
    if not allow_reset:
        raise RuntimeError("reset 단계는 --allow-reset 플래그가 필요합니다.")
    log("[reset] 백업 및 테이블 비우기 시작")

    backup_dir = run_dir / "db-backup"
    backup_dir.mkdir(parents=True, exist_ok=True)

    def _wipe(db_path: Path, tables: list[str], label: str) -> dict:
        if not db_path.exists():
            return {"db": str(db_path), "missing": True}
        shutil.copy2(db_path, backup_dir / f"{label}.db")
        conn = sqlite3.connect(str(db_path))
        before, after = {}, {}
        try:
            existing = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            for t in tables:
                if t not in existing:
                    before[t] = None
                    continue
                before[t] = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                conn.execute(f'DELETE FROM "{t}"')
            conn.commit()
            for t in tables:
                if t in existing:
                    after[t] = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                else:
                    after[t] = None
        finally:
            conn.close()
        return {"db": str(db_path), "before": before, "after": after}

    result = {
        "step": "reset",
        "started_at": utc_now(),
        "ai": _wipe(AI_DB, AI_RESET_TABLES, "ai_control"),
        "db": _wipe(DB_DB, DB_RESET_TABLES, "walletguardian"),
        "finished_at": utc_now(),
    }
    write_json(run_dir / "00_reset.json", result)
    log("[reset] 완료")
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Phase: CRAWL
# ──────────────────────────────────────────────────────────────────────────────

_FIXTURE_TEMPLATES = [
    ("농심", "신라면", 120.0, "g", 950, "[행사] 농심 신라면 120g"),
    ("농심", "오징어 땅콩", 85.0, "g", 1980, "[행사] 농심 오징어 땅콩 85g"),
    ("CJ", "햇반", 210.0, "g", 1690, "CJ 햇반 210g"),
    ("오뚜기", "진라면 매운맛", 120.0, "g", 870, "오뚜기 진라면 매운맛 120g"),
    ("동원", "참치 라이트", 100.0, "g", 2480, "동원 라이트참치 100g"),
    ("서울우유", "1A 우유", 1000.0, "ml", 2980, "서울우유 1A 1L"),
    ("매일유업", "바리스타룰스 라떼", 250.0, "ml", 1980, "매일 바리스타룰스 라떼 250ml"),
    ("롯데", "초코파이", 35.0, "g", 4980, "[1+1] 롯데 초코파이 12개입"),
    ("해태", "맛동산", 90.0, "g", 1880, "해태 맛동산 90g"),
    ("크라운", "쿠크다스", 75.0, "g", 1580, "크라운 쿠크다스 75g"),
    ("샘표", "맛간장 금S", 500.0, "ml", 5480, "샘표 맛간장 금S 500ml"),
    ("청정원", "고추장", 500.0, "g", 6980, "청정원 순창 찰고추장 500g"),
    ("CJ", "다시다 쇠고기", 300.0, "g", 7480, "CJ 다시다 쇠고기 300g"),
    ("브랜드없음", "골드키위 EA", 1.0, "개", 1110, "제스프리 골드키위 (EA)"),
    ("브랜드없음", "애호박 1개", 1.0, "개", 792, "[농할할인가] 애호박 1개"),
    ("브랜드없음", "행복생생란 30입", 1.8, "kg", 6990, "행복생생란 (특란, 30입) 1.8KG"),
    ("브랜드없음", "돼지 삼겹살 600g 냉장", 600.0, "g", 14900, "국내산 돼지 삼겹살 구이용 냉장 600g"),
    ("동서식품", "맥심 모카골드", 11.7, "g", 4480, "동서식품 맥심 모카골드 11.7g x 100T"),
    ("코카콜라", "코카콜라", 1500.0, "ml", 2980, "코카콜라 1.5L"),
    ("롯데칠성", "칠성사이다", 1500.0, "ml", 2680, "롯데칠성 칠성사이다 1.5L"),
]


def _build_fixture_records(mart: str, count: int, batch_id: str) -> list[dict]:
    out: list[dict] = []
    now = datetime.now(timezone.utc).isoformat()
    for i in range(count):
        t = _FIXTURE_TEMPLATES[i % len(_FIXTURE_TEMPLATES)]
        brand, name_core, pack_qty, pack_unit, price, raw_title = t
        payload = {
            "name": raw_title,
            "store": mart,
            "brand": brand,
            "name_core": name_core,
            "pack_qty": pack_qty,
            "pack_unit": pack_unit,
            "sale_price": price,
            "original_price": price,
            "attributes": {
                "source_name": mart,
                "brand": brand,
                "source_record_key": f"{mart}-fxt-{i:05d}",
            },
        }
        out.append({
            "raw_record_id": f"{mart}:fxt-{batch_id[-8:]}-{i:05d}",
            "batch_id": batch_id,
            "source_name": mart,
            "source_record_key": f"{mart}-fxt-{i:05d}",
            "source_url": f"https://example.invalid/{mart}/{i}",
            "raw_title": raw_title,
            "raw_price": price,
            "raw_payload": json.dumps(payload, ensure_ascii=False),
            "crawled_at": now,
        })
    return out


def phase_crawl(run_dir: Path, marts: list[str], max_rows: int,
                source: str, servers: ServerSet) -> dict:
    log(f"[crawl] source={source} marts={marts} max_rows={max_rows}")
    summary: dict[str, Any] = {"step": "crawl", "source": source, "marts": []}

    if source == "fixture":
        # 직접 ai-admin DB에 row 주입
        if not AI_DB.exists():
            raise RuntimeError(f"ai-admin DB가 존재하지 않습니다: {AI_DB}")
        conn = sqlite3.connect(str(AI_DB))
        try:
            for mart in marts:
                batch_id = f"rd7-{mart}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
                count = max_rows
                rows = _build_fixture_records(mart, count, batch_id)
                conn.execute("""
                    INSERT OR REPLACE INTO raw_crawl_batches
                    (batch_id, source_name, crawler_name, item_count, schema_type, status,
                     source_url, raw_artifact_uri, created_at)
                    VALUES (?, ?, ?, ?, 'DiscountItem', 'raw_ingested', NULL, NULL, ?)
                """, (batch_id, mart, mart, count, datetime.now(timezone.utc).isoformat()))
                for r in rows:
                    conn.execute("""
                        INSERT OR REPLACE INTO raw_crawl_records
                        (raw_record_id, batch_id, source_name, source_record_key,
                         source_url, raw_title, raw_price, raw_payload, crawled_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        r["raw_record_id"], r["batch_id"], r["source_name"],
                        r["source_record_key"], r["source_url"], r["raw_title"],
                        r["raw_price"], r["raw_payload"], r["crawled_at"],
                    ))
                conn.commit()
                summary["marts"].append({
                    "mart": mart, "batch_id": batch_id, "rows": count, "via": "fixture",
                })
                log(f"  fixture {mart}: {count} rows → batch_id={batch_id}")
        finally:
            conn.close()
    elif source == "live":
        # crawler-admin API 호출 — 비동기 백그라운드 실행이라 결과 polling 필요
        servers.ensure(("crawler",))
        headers = {"X-API-Key": CRAWLER_API_KEY, "Content-Type": "application/json"}
        for mart in marts:
            try:
                status, body, _ = http_request(
                    "POST", f"{CRAWLER_URL}/api/crawlers/{mart}/run",
                    headers=headers, body=b"{}", timeout=10.0,
                )
                resp = json.loads(body)
            except Exception as e:
                summary["marts"].append({"mart": mart, "error": str(e), "via": "live"})
                continue
            # poll status — up to 120s
            deadline = time.time() + 120
            final = resp
            while time.time() < deadline:
                time.sleep(3)
                try:
                    s, b, _ = http_request(
                        "GET", f"{CRAWLER_URL}/api/crawlers/{mart}/status",
                        headers=headers, timeout=10.0,
                    )
                    final = json.loads(b)
                    if final.get("status") in ("completed", "failed", "error"):
                        break
                except Exception:
                    continue
            summary["marts"].append({
                "mart": mart, "status": final.get("status"),
                "items_found": final.get("items_found"),
                "items_saved": final.get("items_saved"),
                "errors": final.get("errors", [])[:3], "via": "live",
            })
            log(f"  live {mart}: {final.get('status')} found={final.get('items_found')}")
    else:
        raise ValueError(f"unknown source: {source}")

    write_json(run_dir / "01_crawl_summary.json", summary)
    log("[crawl] 완료")
    return summary


# ──────────────────────────────────────────────────────────────────────────────
# Phase: EXPORT
# ──────────────────────────────────────────────────────────────────────────────

def phase_export(run_dir: Path, batch_ids: list[str], servers: ServerSet) -> dict:
    servers.ensure(("crawler",))
    log(f"[export] batch_ids={'all' if not batch_ids else len(batch_ids)}")
    body = json.dumps({
        "raw_batch_ids": batch_ids,
        "include_matched": False,
        "format": ["jsonl", "csv"],
    }, ensure_ascii=False).encode("utf-8")
    headers = {"X-API-Key": CRAWLER_API_KEY, "Content-Type": "application/json"}
    status, resp_bytes, _ = http_request(
        "POST", f"{CRAWLER_URL}/api/export/raw-batch",
        headers=headers, body=body, timeout=180.0,
    )
    if status != 200:
        raise RuntimeError(f"export 실패 status={status}: {resp_bytes[:500].decode('utf-8', 'replace')}")
    resp = json.loads(resp_bytes)
    export_id = resp["export_id"]
    export_dir = Path(resp["export_dir"])

    # 6 파일 검증
    expected = [
        export_dir / "raw_products.jsonl",
        export_dir / "raw_products.csv",
        export_dir / "context" / "matching_entries.jsonl",
        export_dir / "context" / "categories.yaml",
        export_dir / "context" / "keywords.yaml",
        export_dir / "manifest.json",
    ]
    file_sha256s = {}
    missing = []
    for p in expected:
        if p.exists():
            file_sha256s[p.relative_to(export_dir).as_posix()] = sha256_file(p)
        else:
            missing.append(p.relative_to(export_dir).as_posix())

    summary = {
        "step": "export",
        "export_id": export_id,
        "export_dir": str(export_dir),
        "total_rows": resp.get("total_rows"),
        "miss_rows": resp.get("miss_rows"),
        "hit_rows": resp.get("hit_rows"),
        "exported_rows": resp.get("exported_rows"),
        "file_sha256s": file_sha256s,
        "missing_files": missing,
    }
    write_json(run_dir / "02_export.json", summary)
    log(f"[export] 완료 export_id={export_id} miss={resp.get('miss_rows')}")
    return summary


# ──────────────────────────────────────────────────────────────────────────────
# Phase: INVOKE-LLM-STUB
# ──────────────────────────────────────────────────────────────────────────────

# 키워드 → 카테고리 휴리스틱 (간소화). 실제 DB의 leaf id 사용.
_KEYWORD_TO_CATEGORY = [
    (re.compile(r"(라면|면|짜장|국수|컵라면)", re.I), "processed"),
    (re.compile(r"(우유|요거트|치즈|버터|크림)", re.I), "processed"),
    (re.compile(r"(과자|스낵|초코|쿠키|파이|땅콩|비스킷)", re.I), "processed"),
    (re.compile(r"(돼지|삼겹|목심|돈)", re.I), "livestock.pork"),
    (re.compile(r"(소고기|한우|등심|안심|차돌)", re.I), "livestock.beef"),
    (re.compile(r"(닭|치킨|닭가슴)", re.I), "livestock.chicken"),
    (re.compile(r"(계란|달걀|특란|왕란)", re.I), "livestock.egg"),
    (re.compile(r"(키위|사과|배|포도|딸기|망고|바나나|오렌지|귤|감)", re.I), "agriculture.fruit"),
    (re.compile(r"(애호박|호박|상추|배추|시금치|깻잎|쌈)", re.I), "agriculture.leafy"),
    (re.compile(r"(생선|고등어|연어|갈치|참치|명태)", re.I), "seafood.fish"),
    (re.compile(r"(콜라|사이다|음료|주스|이온음료|커피)", re.I), "processed"),
    (re.compile(r"(간장|고추장|된장|식초|소금|설탕|기름|참기름)", re.I), "processed"),
]
_DEFAULT_CATEGORY = "processed"


def _categorize(name: str) -> str:
    for pat, cat in _KEYWORD_TO_CATEGORY:
        if pat.search(name or ""):
            return cat
    return _DEFAULT_CATEGORY


def _strip_promo_prefix(s: str) -> str:
    # [행사], [1+1], [농할할인가 XXX원], ★ 등 제거
    out = re.sub(r"\[[^\]]*\]", " ", s or "")
    out = out.replace("★", " ").replace("☆", " ")
    out = re.sub(r"\s+", " ", out).strip()
    return out


def phase_invoke_llm_stub(run_dir: Path, export_id: str, mode: str) -> dict:
    export_dir = EXPORT_BASE / export_id
    if not export_dir.exists():
        raise RuntimeError(f"export_id 폴더가 없습니다: {export_dir}")
    raw_jsonl = export_dir / "raw_products.jsonl"
    if not raw_jsonl.exists():
        raise RuntimeError(f"raw_products.jsonl 누락: {raw_jsonl}")

    if mode == "manual":
        summary = {
            "step": "invoke-llm-stub",
            "mode": "manual",
            "export_id": export_id,
            "export_dir": str(export_dir),
            "next_action": (
                f"메인 에이전트는 sub-agent에 docs/EXTERNAL_CLASSIFICATION_GUIDE.md "
                f"+ docs/templates/external_llm_system_prompt.md + {export_dir} "
                f"를 넘기고 3종 파일(matching_updates.jsonl, "
                f"categories_keywords_updates.yaml, products.jsonl)을 같은 폴더에 "
                f"받아온 뒤 --phase=import,audit --export-id={export_id} 로 재실행."
            ),
        }
        write_json(run_dir / "03_llm_stub.json", summary)
        log(f"[llm-stub] manual mode → 폴더 {export_dir}")
        print(str(export_dir))
        return summary

    if mode != "heuristic-fallback":
        raise ValueError(f"unknown llm-mode: {mode}")

    log(f"[llm-stub] heuristic-fallback 시작 → {export_dir}")
    # raw 파일 읽기
    rows: list[dict] = []
    with open(raw_jsonl, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))

    matching: dict[str, dict] = {}
    products: list[dict] = []
    for r in rows:
        payload = r.get("raw_payload") or {}
        # payload 상위, attributes, 그리고 raw row 자체에서 best-effort 추출
        brand = (
            payload.get("brand")
            or (payload.get("attributes") or {}).get("brand")
            or r.get("brand")
            or "브랜드없음"
        )
        name_core_src = (
            payload.get("name_core")
            or payload.get("name")
            or r.get("raw_title")
            or ""
        )
        name_core = _strip_promo_prefix(name_core_src)
        pack_qty = payload.get("pack_qty") or payload.get("package_quantity") or 1.0
        pack_unit = (
            payload.get("pack_unit")
            or payload.get("package_unit")
            or payload.get("unit")
            or "개"
        )
        try:
            pack_qty_f = float(pack_qty) if pack_qty is not None else 1.0
        except (TypeError, ValueError):
            pack_qty_f = 1.0
        if not pack_unit:
            pack_unit = "개"

        mk = normalize_match_key(brand, name_core, pack_qty_f, pack_unit)
        category_id = _categorize(name_core)

        if mk not in matching:
            matching[mk] = {
                "match_key": mk,
                "brand": brand,
                "name_core": name_core,
                "pack_qty": pack_qty_f,
                "pack_unit": pack_unit,
                "category_id": category_id,
                "keywords": [],
                "confidence": 0.5,
                "source": "external-ai",
                "aliases": [],
                "notes": "heuristic-fallback",
            }
        # promo prefix를 가진 raw_title을 aliases에 흡수
        raw_title = r.get("raw_title") or ""
        if raw_title and raw_title != name_core and raw_title not in matching[mk]["aliases"]:
            matching[mk]["aliases"].append(raw_title)

        price = (
            payload.get("sale_price")
            or payload.get("original_price")
            or r.get("raw_price")
            or 0
        )
        mart = r.get("source_name") or payload.get("store") or (payload.get("attributes") or {}).get("source_name") or "unknown"
        products.append({
            "raw_id": r.get("raw_record_id"),
            "match_key": mk,
            "mart": mart,
            "price": int(price) if price else 0,
            "discount_price": None,
            "captured_at": r.get("crawled_at"),
        })

    # 3종 파일 작성
    matching_path = export_dir / "matching_updates.jsonl"
    with open(matching_path, "w", encoding="utf-8") as f:
        for v in matching.values():
            f.write(json.dumps(v, ensure_ascii=False) + "\n")

    taxonomy_path = export_dir / "categories_keywords_updates.yaml"
    # 휴리스틱은 신규 카테고리/키워드 추가하지 않음 (기존 트리만 사용)
    taxonomy_path.write_text(
        "categories: []\nkeywords: []\n", encoding="utf-8",
    )

    products_path = export_dir / "products.jsonl"
    with open(products_path, "w", encoding="utf-8") as f:
        for p in products:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    summary = {
        "step": "invoke-llm-stub",
        "mode": "heuristic-fallback",
        "export_id": export_id,
        "raw_count": len(rows),
        "matching_keys": len(matching),
        "products_count": len(products),
        "files": {
            "matching_updates": str(matching_path),
            "categories_keywords_updates": str(taxonomy_path),
            "products": str(products_path),
        },
        "sha256": {
            "matching_updates.jsonl": sha256_file(matching_path),
            "categories_keywords_updates.yaml": sha256_file(taxonomy_path),
            "products.jsonl": sha256_file(products_path),
        },
    }
    write_json(run_dir / "03_llm_stub.json", summary)
    log(f"[llm-stub] 완료 matching_keys={len(matching)} products={len(products)}")
    return summary


# ──────────────────────────────────────────────────────────────────────────────
# Phase: IMPORT
# ──────────────────────────────────────────────────────────────────────────────

def _multipart_encode(parts: list[tuple[str, str, bytes, str]]) -> tuple[bytes, str]:
    """parts: (field, filename, content, mime)."""
    boundary = "----rd7harness" + uuid.uuid4().hex
    buf = io.BytesIO()
    for field, fname, content, mime in parts:
        buf.write(f"--{boundary}\r\n".encode())
        if fname:
            buf.write(
                f'Content-Disposition: form-data; name="{field}"; filename="{fname}"\r\n'
                f"Content-Type: {mime}\r\n\r\n".encode()
            )
            buf.write(content)
        else:
            buf.write(
                f'Content-Disposition: form-data; name="{field}"\r\n\r\n'.encode()
            )
            buf.write(content)
        buf.write(b"\r\n")
    buf.write(f"--{boundary}--\r\n".encode())
    return buf.getvalue(), f"multipart/form-data; boundary={boundary}"


def phase_import(run_dir: Path, export_id: str, servers: ServerSet,
                 mode: str = "lenient") -> dict:
    servers.ensure(("db",))
    export_dir = EXPORT_BASE / export_id
    matching_p = export_dir / "matching_updates.jsonl"
    taxonomy_p = export_dir / "categories_keywords_updates.yaml"
    products_p = export_dir / "products.jsonl"
    for p in (matching_p, taxonomy_p, products_p):
        if not p.exists():
            raise RuntimeError(f"3종 파일 누락: {p}")

    batch_id = f"imp-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    parts = [
        ("matching_file", "matching_updates.jsonl", matching_p.read_bytes(), "application/jsonl"),
        ("taxonomy_file", "categories_keywords_updates.yaml", taxonomy_p.read_bytes(), "application/yaml"),
        ("products_file", "products.jsonl", products_p.read_bytes(), "application/jsonl"),
        ("batch_id", "", batch_id.encode(), ""),
        ("mode", "", mode.encode(), ""),
    ]
    body, ctype = _multipart_encode(parts)
    headers = {"X-API-Key": DB_API_KEY, "Content-Type": ctype}

    # Preview
    status_p, prev_bytes, _ = http_request(
        "POST", f"{DB_URL}/api/import/bundle/preview",
        headers=headers, body=body, timeout=120.0,
    )
    preview = {"status": status_p}
    try:
        preview["body"] = json.loads(prev_bytes)
    except Exception:
        preview["body_raw"] = prev_bytes[:1000].decode("utf-8", "replace")

    # Confirm — 같은 body 재사용 가능
    status_c, conf_bytes, _ = http_request(
        "POST", f"{DB_URL}/api/import/bundle/confirm",
        headers=headers, body=body, timeout=300.0,
    )
    confirm = {"status": status_c}
    try:
        confirm["body"] = json.loads(conf_bytes)
    except Exception:
        confirm["body_raw"] = conf_bytes[:1000].decode("utf-8", "replace")

    # failures.csv 다운로드
    failures_csv_path = None
    if confirm.get("body", {}).get("failure_rows"):
        s, fbytes, _ = http_request(
            "GET", f"{DB_URL}/api/import/bundle/{batch_id}/failures.csv",
            headers={"X-API-Key": DB_API_KEY}, timeout=30.0,
        )
        if s == 200:
            failures_csv_path = run_dir / f"failures_{batch_id}.csv"
            failures_csv_path.write_bytes(fbytes)

    summary = {
        "step": "import",
        "batch_id": batch_id,
        "mode": mode,
        "export_id": export_id,
        "preview": preview,
        "confirm": confirm,
        "failures_csv": str(failures_csv_path) if failures_csv_path else None,
    }
    write_json(run_dir / "04_import.json", summary)
    log(f"[import] preview={status_p} confirm={status_c}")
    return summary


# ──────────────────────────────────────────────────────────────────────────────
# Phase: AUDIT
# ──────────────────────────────────────────────────────────────────────────────

def phase_audit(run_dir: Path, export_id: Optional[str]) -> dict:
    log("[audit] 적대적 정합성 점검")

    # 1) DB row counts
    ai_conn = sqlite3.connect(str(AI_DB))
    db_conn = sqlite3.connect(str(DB_DB))
    raw_count = ai_conn.execute("SELECT COUNT(*) FROM raw_crawl_records").fetchone()[0]
    matching_count = db_conn.execute("SELECT COUNT(*) FROM matching_entries").fetchone()[0]
    products_count = db_conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    baseline_count = db_conn.execute("SELECT COUNT(*) FROM baseline_prices").fetchone()[0]

    findings: list[dict] = []
    severity_counter = {"PASS": 0, "WARN": 0, "FAIL": 0}

    def add(level: str, code: str, msg: str, **extra) -> None:
        findings.append({"level": level, "code": code, "msg": msg, **extra})
        severity_counter[level] = severity_counter.get(level, 0) + 1

    # 2) export-side 비교
    products_jsonl_count = None
    matching_jsonl_count = None
    if export_id:
        export_dir = EXPORT_BASE / export_id
        raw_jsonl = export_dir / "raw_products.jsonl"
        products_jsonl = export_dir / "products.jsonl"
        matching_jsonl = export_dir / "matching_updates.jsonl"
        if raw_jsonl.exists():
            raw_jsonl_count = sum(1 for _ in open(raw_jsonl, "r", encoding="utf-8") if _.strip())
            if products_jsonl.exists():
                products_jsonl_count = sum(1 for _ in open(products_jsonl, "r", encoding="utf-8") if _.strip())
                if products_jsonl_count != raw_jsonl_count:
                    add("WARN", "products_count_mismatch",
                        f"products.jsonl 행 수({products_jsonl_count}) ≠ raw_products.jsonl 행 수({raw_jsonl_count})",
                        raw=raw_jsonl_count, products=products_jsonl_count)
                else:
                    add("PASS", "products_count_match",
                        f"products.jsonl == raw_products.jsonl ({raw_jsonl_count})")
            if matching_jsonl.exists():
                matching_jsonl_count = sum(1 for _ in open(matching_jsonl, "r", encoding="utf-8") if _.strip())

    # 3) products 카테고리 무결성
    bad_cat_products = db_conn.execute("""
        SELECT COUNT(*) FROM products p
        WHERE p.category_id IS NOT NULL
          AND p.category_id NOT IN (SELECT id FROM categories)
    """).fetchone()[0]
    if bad_cat_products == 0:
        add("PASS", "product_category_fk",
            f"모든 products.category_id가 categories에 존재 ({products_count}건)")
    else:
        add("FAIL", "product_category_fk",
            f"products.category_id가 categories에 없음: {bad_cat_products}건")

    # 4) confidence 분포
    confidences = [r[0] for r in db_conn.execute(
        "SELECT confidence FROM matching_entries WHERE confidence IS NOT NULL")]
    if confidences:
        mean_conf = statistics.mean(confidences)
        low_count = sum(1 for c in confidences if c < 0.6)
        low_ratio = low_count / len(confidences)
        if mean_conf < 0.5:
            add("WARN", "low_mean_confidence",
                f"matching_entries.confidence 평균={mean_conf:.3f} (<0.5)",
                mean=mean_conf, low_ratio=low_ratio)
        else:
            add("PASS", "confidence_mean",
                f"matching_entries.confidence 평균={mean_conf:.3f}",
                mean=mean_conf, low_ratio=low_ratio)
        if low_ratio > 0.5:
            add("WARN", "many_pending_human",
                f"confidence<0.6 비율={low_ratio:.1%} → pending_human 다수")
    else:
        add("WARN", "no_matching_entries", "matching_entries 가 비어있음")

    # 5) 카테고리 누락 raw 비율 — products는 baseline_prices 통해 mart 별 연결됨
    # 단순화: matching_entries 중 category_id NULL 비율
    null_cat = db_conn.execute(
        "SELECT COUNT(*) FROM matching_entries WHERE category_id IS NULL").fetchone()[0]
    if matching_count > 0:
        null_ratio = null_cat / matching_count
        if null_ratio > 0.2:
            add("WARN", "missing_category",
                f"matching_entries.category_id NULL 비율={null_ratio:.1%}")
        else:
            add("PASS", "category_coverage",
                f"matching_entries.category_id 충족률={1-null_ratio:.1%}")

    # 6) [행사]/[1+1] 등 prefix 가진 상품의 aliases 누락 검출
    suspect_prefix_re = re.compile(r"\[(행사|1\+1|할인|특가|농할)")
    no_alias_promo = 0
    promo_rows = db_conn.execute(
        "SELECT match_key, name_core, notes FROM matching_entries"
    ).fetchall()
    # aliases는 별도 컬럼이 없고 notes에 들어가지 않음 — heuristic: name_core에 promo 흔적 잔존
    for mk, name_core, notes in promo_rows:
        if name_core and suspect_prefix_re.search(name_core):
            no_alias_promo += 1
    if no_alias_promo > 0:
        add("WARN", "promo_prefix_in_name_core",
            f"matching_entries.name_core에 promo prefix 잔존: {no_alias_promo}건")
    else:
        add("PASS", "promo_prefix_stripped",
            "name_core에 promo prefix 잔존 없음")

    # 7) 중복 match_key — DB 레벨 UNIQUE 보장이지만 확인
    dup = db_conn.execute("""
        SELECT match_key, COUNT(*) c FROM matching_entries GROUP BY match_key HAVING c>1
    """).fetchall()
    if dup:
        add("FAIL", "duplicate_match_key",
            f"중복 match_key 존재: {len(dup)}건", sample=[r[0] for r in dup[:5]])
    else:
        add("PASS", "no_duplicate_match_key", "중복 match_key 없음")

    # 8) raw vs imported coverage — products.jsonl 기준
    if products_jsonl_count is not None and raw_count > 0:
        coverage = (products_jsonl_count / max(1, raw_count))
        if coverage < 0.95:
            add("WARN", "raw_coverage",
                f"raw {raw_count}건 중 import 시도 {products_jsonl_count}건 ({coverage:.1%})")
        else:
            add("PASS", "raw_coverage",
                f"raw vs products.jsonl coverage={coverage:.1%}")

    # 9) baseline_prices 가 products.added 와 일치
    if products_jsonl_count is not None:
        if baseline_count == 0 and products_jsonl_count > 0:
            add("WARN", "no_baseline_prices",
                f"baseline_prices=0 인데 products.jsonl={products_jsonl_count}건 — 모두 skipped 가능성")
        elif baseline_count > 0:
            add("PASS", "baseline_prices_present",
                f"baseline_prices={baseline_count}건 적재")

    db_conn.close()
    ai_conn.close()

    grade = "PASS" if severity_counter["FAIL"] == 0 and severity_counter["WARN"] == 0 else (
        "FAIL" if severity_counter["FAIL"] > 0 else "WARN"
    )

    summary = {
        "step": "audit",
        "export_id": export_id,
        "grade": grade,
        "severity_counter": severity_counter,
        "counts": {
            "ai.raw_crawl_records": raw_count,
            "db.matching_entries": matching_count,
            "db.products": products_count,
            "db.baseline_prices": baseline_count,
            "export.products.jsonl": products_jsonl_count,
            "export.matching_updates.jsonl": matching_jsonl_count,
        },
        "findings": findings,
    }
    write_json(run_dir / "05_audit.json", summary)

    # audit_summary.md
    md_lines = [
        f"# RD7 원샷 DB 구축 감사 리포트",
        "",
        f"- run_id: {run_dir.name}",
        f"- export_id: {export_id or '(N/A)'}",
        f"- 등급: **{grade}**",
        f"- PASS/WARN/FAIL: {severity_counter['PASS']}/{severity_counter['WARN']}/{severity_counter['FAIL']}",
        "",
        "## DB 행 수",
        "",
        f"- ai.raw_crawl_records: {raw_count}",
        f"- db.matching_entries: {matching_count}",
        f"- db.products: {products_count}",
        f"- db.baseline_prices: {baseline_count}",
        f"- export.products.jsonl: {products_jsonl_count}",
        f"- export.matching_updates.jsonl: {matching_jsonl_count}",
        "",
        "## 발견 사항",
        "",
    ]
    for f in findings:
        md_lines.append(f"- **[{f['level']}]** `{f['code']}` — {f['msg']}")
    (run_dir / "audit_summary.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    # improvement_hints.md — WARN/FAIL 있으면 자동 생성
    if grade != "PASS":
        hints = ["# RD7 개선 힌트 (자동 생성)", ""]
        for f in findings:
            if f["level"] == "PASS":
                continue
            code = f["code"]
            if code == "products_count_mismatch":
                hints.append("- products.jsonl 누락/중복 → system prompt에 '모든 raw_id 1:1 매핑 필수' 강조")
            elif code == "low_mean_confidence":
                hints.append("- confidence 평균 낮음 → context 파일 크기를 늘리거나 상위 모델로 1회 부트스트랩")
            elif code == "many_pending_human":
                hints.append("- pending_human 다수 → 첫 라운드는 Opus/GPT-5 등 상위 모델로 부트스트랩 후 누적")
            elif code == "missing_category":
                hints.append("- category 누락 → categories.yaml을 system prompt 본문에 그대로 포함시키고 leaf id 권장")
            elif code == "promo_prefix_in_name_core":
                hints.append("- promo prefix 잔존 → system prompt §3 '단위/이름 정규화' 규칙에 `[행사]`, `[1+1]`, `[농할할인가 ...원]` 제거 예시 추가")
            elif code == "product_category_fk":
                hints.append("- product.category_id가 categories에 없음 → import preview에서 strict 모드로 검출, system prompt에 'category_id는 반드시 categories.yaml에 등장한 id만' 강조")
            elif code == "duplicate_match_key":
                hints.append("- 중복 match_key → 정규화 규칙 누락. match_key는 build_match_key 결과만 사용하도록 prompt 보강")
            elif code == "raw_coverage":
                hints.append("- raw 대비 products coverage 낮음 → 배치를 100~300건으로 쪼개 LLM에 차례로 투입")
            elif code == "no_baseline_prices":
                hints.append("- baseline_prices=0 → products.match_key가 matching_entries에 없어 모두 skipped. matching 단계 conflict/lenient 조정")
        (run_dir / "improvement_hints.md").write_text("\n".join(hints) + "\n", encoding="utf-8")

    log(f"[audit] 완료 grade={grade} PASS/WARN/FAIL={severity_counter['PASS']}/{severity_counter['WARN']}/{severity_counter['FAIL']}")
    return summary


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="RD7 원샷 DB 구축 반복 테스트 하네스")
    p.add_argument("--phase", default="all",
                   help="콤마 구분: reset,crawl,export,invoke-llm-stub,import,audit,all")
    p.add_argument("--llm-mode", default="heuristic-fallback",
                   choices=["manual", "heuristic-fallback"])
    p.add_argument("--source", default="fixture", choices=["fixture", "live"],
                   help="crawl 단계 소스 (기본 fixture)")
    p.add_argument("--marts", default=",".join(DEFAULT_MARTS))
    p.add_argument("--max-rows", type=int, default=300)
    p.add_argument("--batch-ids", default="",
                   help="export 시 특정 raw_batch_ids만. 빈 문자열=전체.")
    p.add_argument("--export-id", default="")
    p.add_argument("--import-mode", default="lenient", choices=["strict", "lenient"])
    p.add_argument("--allow-reset", action="store_true")
    p.add_argument("--run-id", default="")
    p.add_argument("--no-spawn-servers", action="store_true")
    p.add_argument("--keep-servers", action="store_true")
    p.add_argument("--self-check", action="store_true",
                   help="하네스 자체 self-check: 핵심 함수만 검증하고 종료")
    return p.parse_args()


def _self_check() -> int:
    """경량 self-check — DB/서버 접근 없이 핵심 함수 동작 검증."""
    assert normalize_match_key("CJ", "햇반", 210.0, "g") == "cj|햇반|210.0|g"
    assert normalize_match_key("  Nongshim  ", "  신라면  ", 120.0, "G") == "nongshim|신라면|120.0|g"
    assert _strip_promo_prefix("[행사] 농심 신라면") == "농심 신라면"
    assert _strip_promo_prefix("[1+1][특가] 우유 1L") == "우유 1L"
    assert _categorize("농심 신라면 120g") == "processed"
    assert _categorize("국내산 돼지 삼겹살") == "livestock.pork"
    assert _categorize("제스프리 골드키위") == "agriculture.fruit"
    log("self-check PASS")
    return 0


def main() -> int:
    args = parse_args()
    if args.self_check:
        return _self_check()

    phases_req = [p.strip() for p in args.phase.split(",") if p.strip()]
    if "all" in phases_req:
        phases = ["reset", "crawl", "export", "invoke-llm-stub", "import", "audit"]
    else:
        phases = phases_req

    run_id = args.run_id or datetime.now(timezone.utc).strftime("run-%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    run_dir = ARTIFACT_ROOT / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log(f"=== RD7 harness run_id={run_id} phases={phases} ===")
    write_json(run_dir / "_meta.json", {
        "run_id": run_id, "started_at": utc_now(),
        "args": {k: v for k, v in vars(args).items() if not k.startswith("_")},
    })

    servers = ServerSet(spawn=not args.no_spawn_servers)
    results: dict[str, Any] = {"run_id": run_id, "phases": {}}
    export_id = args.export_id or None
    overall_ok = True

    try:
        for phase in phases:
            try:
                if phase == "reset":
                    results["phases"]["reset"] = phase_reset(run_dir, args.allow_reset or "all" in phases_req)
                elif phase == "crawl":
                    marts = [m.strip() for m in args.marts.split(",") if m.strip()]
                    results["phases"]["crawl"] = phase_crawl(
                        run_dir, marts, args.max_rows, args.source, servers,
                    )
                elif phase == "export":
                    batch_ids = [b.strip() for b in args.batch_ids.split(",") if b.strip()]
                    r = phase_export(run_dir, batch_ids, servers)
                    results["phases"]["export"] = r
                    export_id = r["export_id"]
                elif phase == "invoke-llm-stub":
                    if not export_id:
                        raise RuntimeError("invoke-llm-stub 단계에는 --export-id 또는 직전 export 결과가 필요합니다.")
                    r = phase_invoke_llm_stub(run_dir, export_id, args.llm_mode)
                    results["phases"]["invoke-llm-stub"] = r
                    if args.llm_mode == "manual":
                        log("manual 모드 — 이후 단계는 sub-agent 결과 수령 후 별도 호출하세요.")
                        break
                elif phase == "import":
                    if not export_id:
                        raise RuntimeError("import 단계에는 --export-id 가 필요합니다.")
                    results["phases"]["import"] = phase_import(
                        run_dir, export_id, servers, mode=args.import_mode,
                    )
                elif phase == "audit":
                    results["phases"]["audit"] = phase_audit(run_dir, export_id)
                else:
                    raise ValueError(f"unknown phase: {phase}")
            except Exception as e:
                overall_ok = False
                log(f"[{phase}] ERROR {type(e).__name__}: {e}")
                results["phases"][phase] = {"error": f"{type(e).__name__}: {e}"}
                # phase-별 catch — 다음 단계 계속 (단 import 의존성은 export-id 없으면 skip)
    finally:
        if not args.keep_servers:
            servers.shutdown()
        write_json(run_dir / "_summary.json", {
            **results, "ok": overall_ok, "finished_at": utc_now(),
        })

    log(f"=== run_id={run_id} done ok={overall_ok} ===")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
