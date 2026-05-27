"""Shared helpers for WalletSavior Round R user-PC E2E scripts.

The scripts are intentionally written for local developer PCs, not this sandbox.
Install browser binaries first:

    py -3 -m pip install -r packages\\crawler-admin\\requirements.txt
    py -3 -m playwright install chromium
"""
from __future__ import annotations

import atexit
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
DEV_PROCESSES: list[tuple[str, subprocess.Popen[Any]]] = []
CAPTURE_LOG: list[dict[str, Any]] = []


def _creationflags() -> int:
    if os.name != "nt":
        return 0
    return subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS


def _port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def _probe_http(port: int, path: str = "/health") -> bool:
    url = f"http://127.0.0.1:{port}{path}"
    try:
        req = Request(url, headers={"User-Agent": "WalletSavior-E2E/1.0"})
        with urlopen(req, timeout=1.5) as resp:
            return 200 <= resp.status < 500
    except URLError:
        return False
    except Exception:
        return False


def wait_for_port(port: int, *, timeout: int = 90, health_path: str | None = None) -> None:
    deadline = time.time() + timeout
    last_state = "not-started"
    while time.time() < deadline:
        if health_path:
            if _probe_http(port, health_path):
                return
            last_state = f"HTTP probe {health_path} not ready"
        elif _port_open(port):
            return
        else:
            last_state = "port closed"
        time.sleep(1)
    raise TimeoutError(f"port {port} readiness timeout ({last_state})")


def start_dev_server(name: str, cmd: list[str] | str, port: int, log_path: Path | str, *, cwd: Path | str | None = None, env: dict[str, str] | None = None, health_path: str | None = None, timeout: int = 120) -> subprocess.Popen[Any] | None:
    """Start a local dev server with subprocess.Popen and wait until it is ready.

    If the port is already open, this helper assumes the user already started the
    server and returns None, so the script will not stop that external process.
    """
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if _port_open(port):
        print(f"[e2e] {name}: port {port} already open; reusing existing server")
        return None

    command = cmd if isinstance(cmd, list) else ["cmd.exe", "/c", cmd] if os.name == "nt" else cmd
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    log_file = log_path.open("ab")
    print(f"[e2e] starting {name} on :{port}; log={log_path}")
    proc = subprocess.Popen(
        command,
        cwd=str(cwd or REPO_ROOT),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        env=merged_env,
        creationflags=_creationflags(),
    )
    DEV_PROCESSES.append((name, proc))
    try:
        wait_for_port(port, timeout=timeout, health_path=health_path)
    except Exception:
        if proc.poll() is not None:
            raise RuntimeError(f"{name} exited early with code {proc.returncode}; see {log_path}")
        raise
    return proc


def stop_all() -> None:
    """Terminate every dev server spawned by this process."""
    for name, proc in reversed(DEV_PROCESSES):
        if proc.poll() is not None:
            continue
        print(f"[e2e] stopping {name} pid={proc.pid}")
        try:
            if os.name == "nt":
                proc.send_signal(subprocess.CTRL_BREAK_EVENT)
                time.sleep(1)
            proc.terminate()
            proc.wait(timeout=8)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


atexit.register(stop_all)


def capture(page: Any, name: str, dir: Path | str) -> Path:
    """Save a full-page screenshot and append capture metadata."""
    out_dir = Path(dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in name).strip("-")
    path = out_dir / f"{safe}.png"
    page.screenshot(path=str(path), full_page=True)
    meta = {
        "name": name,
        "path": str(path),
        "url": getattr(page, "url", ""),
        "title": page.title() if hasattr(page, "title") else "",
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    CAPTURE_LOG.append(meta)
    (out_dir / "captures.json").write_text(json.dumps(CAPTURE_LOG, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[e2e] capture: {path}")
    return path


def assert_visible(page: Any, selector: str, timeout: int = 10_000) -> Any:
    """Wait for selector to be visible and raise a clear assertion on failure."""
    locator = page.locator(selector).first
    try:
        locator.wait_for(state="visible", timeout=timeout)
    except Exception as exc:
        raise AssertionError(f"visible assertion failed: {selector}") from exc
    return locator


def markdown_link(path: Path, base: Path | None = None) -> str:
    base = base or REPO_ROOT
    try:
        rel = path.resolve().relative_to(base.resolve())
    except ValueError:
        rel = path
    return str(rel).replace("\\", "/")


def write_report(path: Path | str, title: str, rows: list[dict[str, Any]], capture_dir: Path | str, notes: list[str] | None = None) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# {title}", "", f"- 실행 시각: {datetime.now().isoformat(timespec='seconds')}", f"- 캡쳐 폴더: `{markdown_link(Path(capture_dir))}`", "", "## 단계 결과", "", "| 단계 | 상태 | 증거 |", "|---|---|---|"]
    for row in rows:
        evidence = row.get("evidence") or ""
        if isinstance(evidence, Path):
            evidence = f"[{evidence.name}]({markdown_link(evidence)})"
        lines.append(f"| {row.get('step','')} | {row.get('status','')} | {evidence} |")
    if notes:
        lines.extend(["", "## 메모", ""])
        lines.extend(f"- {note}" for note in notes)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[e2e] report: {path}")


def require_playwright() -> None:
    try:
        import playwright.sync_api  # noqa: F401
    except Exception as exc:
        raise SystemExit(
            "Playwright Python이 필요합니다. 실행 전 다음 명령을 실행하세요:\n"
            "  py -3 -m pip install playwright\n"
            "  py -3 -m playwright install chromium"
        ) from exc


def run_checked(cmd: list[str], *, cwd: Path | str | None = None, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    print(f"[e2e] run: {' '.join(cmd)}")
    completed = subprocess.run(cmd, cwd=str(cwd or REPO_ROOT), text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=timeout)
    if completed.returncode != 0:
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(cmd)}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}")
    return completed
