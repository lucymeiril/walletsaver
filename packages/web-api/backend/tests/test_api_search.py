def test_search_no_filters(test_client):
    r = test_client.get("/api/v1/products/search")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 5
    assert len(data["items"]) == 5
    assert data["page"] == 1


def test_search_by_query(test_client):
    r = test_client.get("/api/v1/products/search", params={"q": "두부"})
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 1
    assert any("두부" in item["name_core"] for item in data["items"])


def test_search_by_category(test_client):
    r = test_client.get("/api/v1/products/search", params={"category": "tofu_cat"})
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["items"][0]["canonical_id"] == "prod_tofu_001"


def test_search_pagination(test_client):
    r = test_client.get("/api/v1/products/search", params={"page": 1, "page_size": 2})
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 5
    assert len(data["items"]) == 2
    assert data["total_pages"] == 3


def test_search_grade_label_present(test_client):
    r = test_client.get("/api/v1/products/search")
    data = r.json()
    labels = {item["grade_label"] for item in data["items"]}
    # tofu has sufficient=1 with p50=2200, p10=1500 → OVERPRICED (p50 > p75? no, p50 within p25..p75 → NORMAL)
    assert "INSUFFICIENT_DATA" in labels  # egg/rice have sufficient=0


def test_search_invalid_sort(test_client):
    r = test_client.get("/api/v1/products/search", params={"sort": "bogus"})
    assert r.status_code == 422
