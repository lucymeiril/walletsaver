# Round R G1 3-axis screenshots pending

No browser capture performed in this consolidation pass. Main agent should capture these later via Playwright MCP.

| axis | URL paths | expected post-G1 visuals |
|---|---|---|
| crawler-admin frontend | `http://localhost:5174/crawlers`, `http://localhost:5174/data-review` | G0-schema §9: crawl progress must not freeze at `0초`; show live elapsed ticker/spinner, mart별 진행/완료/오류, 신규/중복/필터됨/오류 counters, and review grid columns for `mart_native_code`, `mart_native_category_path`, `unit_price`/basis, `external_seller`. |
| db-admin frontend | `http://localhost:5175/products` | Products grid includes `mart`, `mart_native_code`, unit price, external seller badge, `mart_native_category_path`; native category tree/sidebar skeleton groups products by mart category path for G2 mapping. |
| web frontend | `http://localhost:5173/compare`, `http://localhost:5173/c/<category-slug>`, `http://localhost:5173/p/<canonical_id>` | G0-schema §10: `/compare` entry shows top-level categories only; category page keeps breadcrumb/drilldown pinned and expands descendants; product detail mart table shows unit price for foods or pack info for non-foods plus `입점셀러` badge/canonical mart link; history modal should not break while non-Costco history is still accumulating. |
