from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from api.app import create_app


def _client(monkeypatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("REQUIRE_AUTH", "false")
    monkeypatch.setenv("OPERATOR_SOURCE_WORKBENCH_DIR", str(tmp_path / "workbench"))
    monkeypatch.setenv("SOURCE_RUN_DIR", str(tmp_path / "source_runs"))
    return TestClient(create_app())


def test_source_workbench_capture_saved_source_feeds_ai_handoff(monkeypatch, tmp_path: Path):
    fixture = (
        Path(__file__).resolve().parent / "fixtures" / "marketplace_skeleton" / "coupang.html"
    ).read_text(encoding="utf-8")
    client = _client(monkeypatch, tmp_path)

    resp = client.post(
        "/api/source-workbench/captures",
        json={
            "crawler_name": "coupang",
            "source_name": "coupang_operator",
            "schema_type": "marketplace_discount",
            "source_url": "https://www.coupang.com/np/search?q=operator",
            "source_input": fixture,
            "operator_notes": "human saved public search results page",
            "network_events": [
                {
                    "url": "https://www.coupang.com/np/search?q=operator",
                    "method": "GET",
                    "status_code": 200,
                    "request_headers": {"cookie": "must-not-be-stored"},
                }
            ],
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["safety_policy"]["automated_captcha_attempt"] is True
    assert data["capture"]["source_health"]["collection_status"] == "captured_with_evidence"
    assert data["capture"]["network_events"][0]["status_code"] == 200
    assert "request_headers" not in data["capture"]["network_events"][0]
    assert Path(data["capture"]["artifact"]["path"]).exists()
    assert data["run"]["status"] == "success"
    assert data["run"]["records_handed_off"] == 1


def test_source_workbench_registers_unverified_public_source(monkeypatch, tmp_path: Path):
    client = _client(monkeypatch, tmp_path)

    resp = client.post(
        "/api/source-workbench/sources",
        json={
            "crawler_name": "coupang",
            "source_name": "coupang_weekly_query",
            "schema_type": "marketplace_discount",
            "source_url": "https://www.coupang.com/np/search?q=coffee",
            "cadence_cron": "0 8 * * *",
            "tags": ["marketplace", "operator"],
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["source_health"]["collection_status"] == "registered_unverified"
    assert data["source_health"]["live_network_default"] == "disabled"
    assert data["safety_policy"]["bypass_code_in_live_web_backend"] is False

    listed = client.get("/api/source-workbench/sources").json()
    assert listed["sources"][0]["source_name"] == "coupang_weekly_query"
