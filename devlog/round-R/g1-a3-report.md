# G1 A3 — Lottemart dead-UUID URL fix

## Summary
- Fixed the Lottemart crawler so tracking UUIDs from `data-synthetics="product-id:<uuid>"` are never used as product URLs.
- `__INITIAL_STATE__.data.products.productEntities` is now parsed for an EAN-13. The observed hydrated key is `retailerProductId`, whose value is `OS<EAN-13>`; documented barcode aliases (`eanCd`, `barcode`, `goodsBarCd`, `representBarcd`, `stdGoodsCd`) remain higher-priority candidates if they appear.
- `mart_native_code` is the 13-digit EAN, `canonical_url/detail_url` is `https://lottemartzetta.com/products/OS<EAN-13>/details`, and `external_seller` defaults to `False`.
- Unit-price text is parsed through `parse_unit_price`; source, canon hash, canonical URL, and native-code attributes are injected on parsed items.

## UUID block removal — exact before/after

```diff
-        # --- 상품 UUID → detail_url ---
-        detail_url = ""
-        uuid_attr = card.find(attrs={"data-synthetics": re.compile(r"^product-id:[a-f0-9-]{36}$")})
-        if uuid_attr:
-            product_uuid = uuid_attr["data-synthetics"].split(":", 1)[1]
-            detail_url = f"{self.ZETTA_BASE}/products/{product_uuid}"
-        # 폴백: href 기반 (상대 URL 보정)
-        if not detail_url:
-            link_el = card.select_one("a[href*='products']") or card.select_one("a[href]")
-            if link_el:
-                href = link_el.get("href", "")
-                detail_url = self._absolute_url(href, self.ZETTA_BASE)
+        # --- EAN-13 기반 canonical detail_url ---
+        detail_url = ""
+        ean13 = ""
+        ean_source_key = ""
+        link_el = card.select_one("a[href*='/products/OS']") or card.select_one("a[href*='products/OS']")
+        if link_el:
+            href = link_el.get("href", "")
+            ean13 = self._extract_ean13_from_lottemart_url(href)
+            if ean13:
+                ean_source_key = "href"
+                detail_url = normalize_lottemart_url(ean13)
+        if not ean13:
+            logger.warning(
+                "[롯데마트] 카드 EAN-13 없음 — data-synthetics UUID fallback 금지로 상품 스킵: %s",
+                clean_name,
+            )
+            return None
```

## Tests
- Added `packages/crawler-admin/backend/tests/test_lottemart_crawler_g1.py` covering UUID ignore, EAN canonical URL, href fallback, and UUID-only drop.
- Updated older Lottemart fixtures/assertions that used placeholder SKU/UUID URLs so they now assert EAN canonical URLs instead.
- Verification: `py -3 -m pytest packages\crawler-admin\backend\tests -q -k lottemart` → 60 passed, 1 skipped.

## FIX-UP

### What was missing in original A3
- `_entity_to_discount_item()` still built `detail_url` and `source_record_key` from UUID/product id fallbacks.
- It did not set `mart_native_code`, `ean_source_key`, `external_seller`, `canonical_url`, or `source` G1 attributes.
- UUID-only products were still accepted instead of being skipped.
- Sibling direct builders (`_parse_spa_card`, `_api_product_to_discount_item`, `_json_to_discount_item`, `_parse_product_card`) also needed the same EAN/canonical URL rules.

### `_entity_to_discount_item()` exact before/after diff
```diff
-        # 상세 URL
-        detail_url = self._absolute_url(
-            product.get("url") or product.get("productUrl") or product.get("detailUrl") or "",
-            self.ZETTA_BASE,
-        )
-        if not detail_url and product_id:
-            detail_url = f"{self.ZETTA_BASE}/products/{product_id}"
+        ean13, ean_source_key = self._extract_lottemart_ean13(product)
+        if not ean13:
+            return None
+        detail_url = normalize_lottemart_url(ean13)
@@
-        attributes = unit_metadata.get("attributes") or {}
-        if brand:
-            attributes = {**attributes, "brand": brand}
-        source_record_key = normalize_source_key("lottemart", product_id, detail_url, clean_name)
         valid_from, valid_until, period = parse_period_fields(product)
-        attributes = build_source_attributes(
-            "lottemart",
-            source_record_key=source_record_key,
+        attributes = self._lottemart_g1_attributes(
+            ean13=ean13,
+            ean_source_key=ean_source_key,
             detail_url=detail_url,
             image_url=image_url,
             category=category,
             category_path=category_path,
             period=period,
-            extra=attributes,
+            unit_metadata=unit_metadata,
+            name=clean_name,
+            brand=brand,
+            unit_text=unit,
         )
```

### Final test results
- `py -3 -m pytest packages\crawler-admin\backend\tests\test_lottemart_crawler.py packages\crawler-admin\backend\tests\test_mart_crawlers.py packages\crawler-admin\backend\tests\test_lottemart_crawler_g1.py -q -k "lottemart"` → 49 passed, 1 skipped, 44 deselected.
- `py -3 -m pytest packages\crawler-admin\backend\tests\test_mart_crawlers.py -q` → 63 passed, 3 skipped.
- `py -3 -m pytest packages\crawler-admin\backend\tests\test_lottemart_crawler_g1.py -q` → 4 passed.
- `py -3 -m pytest packages\crawler-admin\backend\tests\test_emart_crawler_g1.py packages\crawler-admin\backend\tests\test_homeplus_crawler_g1.py packages\crawler-admin\backend\tests\test_costco_crawler_g1.py packages\crawler-admin\backend\tests\test_source_utils_g1.py -q` → 29 passed.
- Broad requested `tests -q -k "lottemart"` still hits unrelated collection-time `services.*` import blockers before `-k`; rerun with those five unrelated files ignored → 60 passed, 1 skipped, 763 deselected.
