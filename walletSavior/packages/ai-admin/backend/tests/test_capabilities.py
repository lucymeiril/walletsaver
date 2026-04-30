"""capabilities 엔드포인트 테스트 — shared 계약과 동기화 여부를 검증한다."""
from fastapi.testclient import TestClient

from api.app import create_app
from core.contracts.ai_pipeline import AIWorkerRole, ProviderKind


def test_capabilities_lists_all_shared_roles_and_providers():
    client = TestClient(create_app())
    res = client.get("/api/capabilities")
    assert res.status_code == 200
    body = res.json()

    assert body["service"] == "ai-admin"

    role_values = {r["value"] for r in body["roles"]}
    assert role_values == {role.value for role in AIWorkerRole}

    provider_values = {p["value"] for p in body["providers"]}
    assert provider_values == {kind.value for kind in ProviderKind}

    assert all(r["supported"] is False for r in body["roles"])
    assert all(p["supported"] is False for p in body["providers"])
