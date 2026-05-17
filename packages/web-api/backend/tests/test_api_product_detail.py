def test_product_detail_ok(test_client):
    r = test_client.get("/api/v1/products/prod_tofu_001")
    assert r.status_code == 200
    data = r.json()
    assert data["canonical_id"] == "prod_tofu_001"
    assert data["brand"] == "풀무원"
    assert data["price_grade"]["sufficient"] is True
    assert data["price_grade"]["p50"] == 2200.0
    assert len(data["mart_aliases"]) == 2
    marts = {a["mart"] for a in data["mart_aliases"]}
    assert marts == {"LOTTEMART", "HOMEPLUS"}


def test_product_detail_insufficient_grade(test_client):
    r = test_client.get("/api/v1/products/prod_egg_001")
    assert r.status_code == 200
    data = r.json()
    assert data["price_grade"]["sufficient"] is False
    assert data["price_grade"]["grade_label"] == "INSUFFICIENT_DATA"


def test_product_detail_not_found(test_client):
    r = test_client.get("/api/v1/products/nonexistent_id")
    assert r.status_code == 404
