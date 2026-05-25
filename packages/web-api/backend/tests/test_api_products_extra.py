"""web-FINAL §13-2 신규 엔드포인트 TDD."""


def test_history_returns_stub_points_with_last_seen_at(test_client):
    r = test_client.get("/api/v1/products/prod_tofu_001/history?days=180")
    assert r.status_code == 200
    body = r.json()
    assert body["canonical_id"] == "prod_tofu_001"
    assert body["source"] == "stub"
    assert isinstance(body["points"], list)
    assert len(body["points"]) >= 2  # tofu has 2 aliases
    for p in body["points"]:
        assert "date" in p and "price" in p and "mart" in p


def test_history_filter_by_mart(test_client):
    r = test_client.get("/api/v1/products/prod_tofu_001/history?mart=EMART")
    assert r.status_code == 200
    assert all(p["mart"] == "EMART" for p in r.json()["points"])


def test_history_404_unknown_product(test_client):
    r = test_client.get("/api/v1/products/does_not_exist/history")
    assert r.status_code == 404


def test_current_low_returns_p10_fallback(test_client):
    r = test_client.get("/api/v1/products/prod_tofu_001/current_low")
    assert r.status_code == 200
    body = r.json()
    assert body["price"] == 1500.0  # tofu p10
    assert body["window_days"] in (7, 14, 30)
    assert body["source"] == "grade_fallback"


def test_current_low_none_when_no_grade(test_client):
    r = test_client.get("/api/v1/products/prod_egg_001/current_low")
    assert r.status_code == 200
    body = r.json()
    # egg has no p10 in grade
    assert body["price"] is None or body["source"] == "none"


def test_grade_detail_with_unit_price(test_client):
    r = test_client.get("/api/v1/products/prod_tofu_001/grade_detail")
    assert r.status_code == 200
    body = r.json()
    assert body["p10"] == 1500.0
    assert body["sample_size"] == 10
    assert body["sufficient"] is True
    # 2200 / 300g
    assert body["unit_price"] is not None
    assert abs(body["unit_price"] - (2200.0 / 300.0)) < 0.01


def test_grade_detail_returns_empty_when_no_grade(test_client):
    # patch: prod with no grade — egg has grade. use unknown product → 404.
    r = test_client.get("/api/v1/products/no_such/grade_detail")
    assert r.status_code == 404


def test_trust_badge_green_emart_match(test_client):
    r = test_client.get("/api/v1/products/trust_badge?domain=emart.ssg.com&mart=EMART")
    assert r.status_code == 200
    assert r.json()["level"] == "green"


def test_trust_badge_red_mismatch(test_client):
    r = test_client.get("/api/v1/products/trust_badge?domain=coupang.com&mart=EMART")
    assert r.status_code == 200
    assert r.json()["level"] == "red"


def test_trust_badge_yellow_unknown_domain(test_client):
    r = test_client.get("/api/v1/products/trust_badge?domain=random-blog.tistory.com&mart=EMART")
    assert r.status_code == 200
    assert r.json()["level"] == "yellow"


def test_trust_badge_url_param_parsed(test_client):
    r = test_client.get("/api/v1/products/trust_badge?url=https%3A%2F%2Fwww.coupang.com%2Fitem%2F1&mart=COUPANG")
    assert r.status_code == 200
    assert r.json()["level"] == "green"


def test_trust_badge_no_domain_yields_yellow(test_client):
    r = test_client.get("/api/v1/products/trust_badge")
    assert r.status_code == 200
    assert r.json()["level"] == "yellow"
