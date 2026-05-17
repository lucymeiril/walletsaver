def test_health_ok(test_client):
    r = test_client.get("/api/v1/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["snapshot_exists"] is True
    assert data["canonical_count"] == 5
