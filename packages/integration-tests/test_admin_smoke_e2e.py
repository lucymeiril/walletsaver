"""
Admin Smoke E2E 테스트 (Task 4)

admin 3 서비스(크롤러/DB관리/AI관리) 백엔드가 실행 중일 때
헬스체크 + 기본 API 계약을 검증한다.

실행 방법:
  1. 자동: .\\tools\\admin_smoke_e2e_bootstrap.ps1 (서버 기동 + 이 테스트 실행 + 자동 종료)
  2. 수동: py -3 -m pytest packages/integration-tests/test_admin_smoke_e2e.py -v
          (수동 실행 시 먼저 .\\start-all.ps1 -Admin 으로 서버를 기동해야 함)

표시:
  pytest.mark.admin_smoke -- 서버가 실제 기동된 환경에서만 통과
  서버 미기동 시 SKIP (graceful skip)
"""

from __future__ import annotations

import sys
import pytest
import requests
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
for p in [str(ROOT), str(ROOT / "packages" / "shared")]:
    if p not in sys.path:
        sys.path.insert(0, p)

# ─── Admin 서비스 엔드포인트 정의 ────────────────────────────────────────────

ADMIN_SERVICES = {
    "크롤러 관리": {
        "base_url": "http://127.0.0.1:8001",
        "health_path": "/health",
        "expected_service_field": "crawler-admin",
    },
    "DB 관리": {
        "base_url": "http://127.0.0.1:8002",
        "health_path": "/health",
        "expected_service_field": None,  # service 필드 없을 수 있음
    },
    "AI 관리": {
        "base_url": "http://127.0.0.1:8003",
        "health_path": "/health",
        "expected_service_field": None,
    },
}

_TIMEOUT = 3  # seconds


def _is_server_up(base_url: str, health_path: str = "/health") -> bool:
    """서버 기동 여부 확인 (헬스체크)."""
    try:
        r = requests.get(f"{base_url}{health_path}", timeout=_TIMEOUT)
        return r.status_code == 200
    except Exception:
        return False


def _require_server(base_url: str, service_name: str):
    """서버 미기동 시 테스트 skip."""
    if not _is_server_up(base_url):
        pytest.skip(f"{service_name} 서버 미기동 ({base_url}) — 먼저 서버를 기동하세요")


# ─── 헬스체크 smoke ───────────────────────────────────────────────────────────

class TestAdminHealthSmoke:
    """3개 admin 서비스 헬스체크 — 서버 ready 확인."""

    @pytest.mark.parametrize("name,cfg", list(ADMIN_SERVICES.items()))
    def test_health_200(self, name, cfg):
        """각 서비스의 /health 가 200을 반환한다."""
        _require_server(cfg["base_url"], name)
        r = requests.get(f"{cfg['base_url']}{cfg['health_path']}", timeout=_TIMEOUT)
        assert r.status_code == 200, f"{name}: /health 응답 코드 {r.status_code}"

    @pytest.mark.parametrize("name,cfg", list(ADMIN_SERVICES.items()))
    def test_health_status_ok(self, name, cfg):
        """/health 응답 body에 status가 ok 또는 healthy임을 확인."""
        _require_server(cfg["base_url"], name)
        r = requests.get(f"{cfg['base_url']}{cfg['health_path']}", timeout=_TIMEOUT)
        data = r.json()
        assert data.get("status") in ("ok", "healthy"), (
            f"{name}: status가 ok/healthy 가 아님, 실제값: {data.get('status')}"
        )

    def test_crawler_health_has_service_field(self):
        """크롤러 관리 /health는 service 필드를 반환한다."""
        _require_server("http://127.0.0.1:8001", "크롤러 관리")
        r = requests.get("http://127.0.0.1:8001/health", timeout=_TIMEOUT)
        data = r.json()
        assert "service" in data, f"크롤러 /health에 service 필드 없음: {data}"
        assert data["service"] == "crawler-admin"


# ─── API 기본 계약 smoke ──────────────────────────────────────────────────────

class TestCrawlerAdminApiSmoke:
    """크롤러 관리 API 기본 계약."""

    BASE = "http://127.0.0.1:8001"

    def _skip_if_down(self):
        _require_server(self.BASE, "크롤러 관리")

    def _headers(self) -> dict:
        """크롤러 관리 API Key 헤더. 없으면 테스트 skip."""
        import os
        api_key = os.environ.get("CRAWLER_ADMIN_API_KEY", "")
        if not api_key:
            pytest.skip("CRAWLER_ADMIN_API_KEY 환경변수 미설정 — 크롤러 API 테스트 건너뜀")
        return {"X-API-Key": api_key}

    def test_crawlers_list(self):
        """GET /api/crawlers → 200 + crawlers 배열."""
        self._skip_if_down()
        r = requests.get(f"{self.BASE}/api/crawlers", headers=self._headers(), timeout=_TIMEOUT)
        if r.status_code == 401:
            pytest.skip("크롤러 API Key 없음 — CRAWLER_API_KEY 환경변수 설정 필요")
        assert r.status_code == 200
        data = r.json()
        assert "crawlers" in data, f"/api/crawlers 응답에 crawlers 없음: {data}"
        assert isinstance(data["crawlers"], list)

    def test_logs_endpoint(self):
        """GET /api/logs → 200 + logs 배열."""
        self._skip_if_down()
        r = requests.get(f"{self.BASE}/api/logs", headers=self._headers(), timeout=_TIMEOUT)
        if r.status_code == 401:
            pytest.skip("크롤러 API Key 없음")
        assert r.status_code == 200
        data = r.json()
        assert "logs" in data
        assert "total" in data

    def test_schedules_endpoint(self):
        """GET /api/schedules → 200 + schedules."""
        self._skip_if_down()
        r = requests.get(f"{self.BASE}/api/schedules", headers=self._headers(), timeout=_TIMEOUT)
        if r.status_code == 401:
            pytest.skip("크롤러 API Key 없음")
        assert r.status_code == 200
        data = r.json()
        assert "schedules" in data


class TestDbAdminApiSmoke:
    """DB 관리 API 기본 계약."""

    BASE = "http://127.0.0.1:8002"

    def _skip_if_down(self):
        _require_server(self.BASE, "DB 관리")

    def test_health(self):
        """DB 관리 /health → 200."""
        self._skip_if_down()
        r = requests.get(f"{self.BASE}/health", timeout=_TIMEOUT)
        assert r.status_code == 200

    def test_docs_accessible(self):
        """OpenAPI docs (/docs) 접근 가능 (DEBUG 모드일 때만 활성화)."""
        self._skip_if_down()
        r = requests.get(f"{self.BASE}/docs", timeout=_TIMEOUT)
        if r.status_code == 404:
            pytest.skip("DB 관리 /docs 비활성화 (비-DEBUG 모드)")
        assert r.status_code == 200


class TestAiAdminApiSmoke:
    """AI 관리 API 기본 계약."""

    BASE = "http://127.0.0.1:8003"

    def _skip_if_down(self):
        _require_server(self.BASE, "AI 관리")

    def test_health(self):
        """AI 관리 /health → 200."""
        self._skip_if_down()
        r = requests.get(f"{self.BASE}/health", timeout=_TIMEOUT)
        assert r.status_code == 200

    def test_docs_accessible(self):
        """OpenAPI docs (/docs) 접근 가능."""
        self._skip_if_down()
        r = requests.get(f"{self.BASE}/docs", timeout=_TIMEOUT)
        assert r.status_code == 200


# ─── Bootstrap 스크립트 파일 존재 검증 (오프라인) ────────────────────────────

class TestBootstrapScriptExists:
    """bootstrap 스크립트 자체가 올바른 위치에 존재하는지 오프라인으로 검증."""

    def test_bootstrap_script_exists(self):
        """tools/admin_smoke_e2e_bootstrap.ps1 파일이 존재한다."""
        script = ROOT / "tools" / "admin_smoke_e2e_bootstrap.ps1"
        assert script.exists(), f"bootstrap 스크립트 없음: {script}"

    def test_bootstrap_script_has_health_check(self):
        """bootstrap 스크립트에 헬스체크 로직이 포함된다."""
        script = ROOT / "tools" / "admin_smoke_e2e_bootstrap.ps1"
        content = script.read_text(encoding="utf-8")
        assert "/health" in content, "bootstrap 스크립트에 /health 체크 없음"
        assert "8001" in content, "bootstrap 스크립트에 크롤러 포트(8001) 없음"
        assert "8002" in content, "bootstrap 스크립트에 DB관리 포트(8002) 없음"
        assert "8003" in content, "bootstrap 스크립트에 AI관리 포트(8003) 없음"

    def test_bootstrap_script_has_auto_shutdown(self):
        """bootstrap 스크립트에 자동 종료 로직이 포함된다."""
        script = ROOT / "tools" / "admin_smoke_e2e_bootstrap.ps1"
        content = script.read_text(encoding="utf-8")
        assert "Stop-Process" in content, "bootstrap 스크립트에 자동 종료(Stop-Process) 없음"
        assert "KeepAlive" in content, "bootstrap 스크립트에 KeepAlive 옵션 없음"

    def test_bootstrap_script_runs_smoke_test(self):
        """bootstrap 스크립트가 pytest smoke 테스트를 실행한다."""
        script = ROOT / "tools" / "admin_smoke_e2e_bootstrap.ps1"
        content = script.read_text(encoding="utf-8")
        assert "pytest" in content, "bootstrap 스크립트에 pytest 실행 없음"
        assert "admin_smoke_e2e" in content, "bootstrap 스크립트가 smoke 테스트를 지정하지 않음"
