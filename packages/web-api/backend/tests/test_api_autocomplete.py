def test_autocomplete_prefix(test_client):
    r = test_client.get("/api/v1/autocomplete", params={"prefix": "두"})
    assert r.status_code == 200
    data = r.json()
    assert data["prefix"] == "두"
    assert isinstance(data["suggestions"], list)
    # Should find "두부" category at minimum
    tokens = {s["token"] for s in data["suggestions"]}
    assert any(t.startswith("두") for t in tokens)


def test_autocomplete_brand(test_client):
    r = test_client.get("/api/v1/autocomplete", params={"prefix": "풀무원"})
    assert r.status_code == 200
    data = r.json()
    sources = {s["source"] for s in data["suggestions"]}
    assert "brand" in sources


def test_autocomplete_empty_prefix(test_client):
    r = test_client.get("/api/v1/autocomplete", params={"prefix": ""})
    assert r.status_code == 422  # min_length=1


def test_autocomplete_limit(test_client):
    r = test_client.get("/api/v1/autocomplete", params={"prefix": "ㄱ", "limit": 3})
    assert r.status_code == 200
    data = r.json()
    assert len(data["suggestions"]) <= 3
