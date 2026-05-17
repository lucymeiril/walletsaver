def test_categories_tree(test_client):
    r = test_client.get("/api/v1/categories")
    assert r.status_code == 200
    data = r.json()
    assert data["total_nodes"] == 6
    roots = data["categories"]
    root_ids = {n["id"] for n in roots}
    assert {"fresh_food", "processed_food", "dairy"} <= root_ids

    fresh = next(n for n in roots if n["id"] == "fresh_food")
    child_ids = {c["id"] for c in fresh["children"]}
    assert {"vegetable", "egg_cat"} <= child_ids
