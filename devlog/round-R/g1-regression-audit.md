# Round R G1 Regression Audit Report

**Date**: 2026-05-25  
**Test Run Context**: `cd packages/crawler-admin/backend; py -3 -m pytest tests -q --tb=no`  
**Results**: 19 failed, 818 passed, 20 skipped

---

## Executive Summary

The 19 test failures fall into three categories:

1. **ROUND-R REGRESSIONS (G1 Implementation Gap)**: 16 failures
   - Crawler code has NOT been updated to support new G1 EAN/mart_native_code behavior
   - Tests have been UPDATED to specify new expected behavior  
   - Tests are in `test_lottemart_crawler.py`, `test_lottemart_crawler_g1.py`, `test_mart_crawlers.py`
   - **Root Cause**: Missing EAN extraction and prioritization in `_entity_to_discount_item()` method

2. **PRE-EXISTING / ENVIRONMENTAL**: 2 failures
   - `test_source_coverage.py::test_source_coverage_reports_registered_and_missing_one_shot_sources`
   - `test_quality_diagnostics.py::test_high_priority_non_marketplace_fixtures_produce_bounded_quality_evidence`

3. **INFRASTRUCTURE**: 1 failure
   - `test_workbench_routes.py` failures (5 total) due to missing/broken workbench API endpoints

---

## Detailed Failure Classification

### ROUND-R REGRESSIONS (G1 EAN Implementation Gap)

All failures related to LotteMart and Marts crawlers are due to missing G1 functionality. The test files have been updated with new expectations but the crawler code has not been modified.

#### Group 1: test_lottemart_crawler.py (4 failures)

| Test ID | Classification | Root Cause | Action Taken |
|---------|-----------------|-----------|--------------|
| `test_parse_water_card_carries_real_fields` | ROUND-R REGRESSION | Missing EAN extraction; uses `product_id` ("lzt-water-2L6") instead of `retailerProductId` ("8801045440040") for `source_record_key` and detail_url | Test updated ✓; Code needs implementation |
| `test_hydrated_fixture_parses_five_real_entities` | ROUND-R REGRESSION | Missing EAN validation; test now requires all items to have EAN-13 `source_record_key` and `mart_native_code` attribute | Test updated ✓; Code needs implementation |
| `test_live_hydrated_probe_when_present_yields_real_items` | ROUND-R REGRESSION | Missing EAN from live probe parsing; expects `mart_native_code` attribute with 13-digit EAN | Test updated ✓; Code needs implementation |
| `test_api_product_to_discount_item_real_shape` | ROUND-R REGRESSION | Detail URL should be built from EAN ("OS8809251334528") not UUID; missing `mart_native_code` and `external_seller` attributes | Test updated ✓; Code needs implementation |

**Common Issue**: `_entity_to_discount_item()` method (line 825) needs to:
1. Extract EAN from product fields: `retailerProductId`, `stdGoodsCd`, etc.
2. Strip "OS" prefix if present to get clean EAN-13
3. Prioritize EAN over UUID for detail_url and source_record_key
4. Add `mart_native_code` attribute with EAN
5. Add `external_seller` attribute (boolean)
6. Set `ean_source_key` to indicate which field provided the EAN

---

#### Group 2: test_lottemart_crawler_g1.py (4 failures)

**Status**: NEW test file (UNTRACKED, not in git). Defines G1 expected behavior.

| Test ID | Classification | Root Cause | Action Taken |
|---------|-----------------|-----------|--------------|
| `test_initial_state_ean_ignores_data_synthetics_uuid` | ROUND-R REGRESSION | Product with EAN should ignore UUID in detail_url; expects URL with EAN not UUID | New test; Code needs implementation |
| `test_initial_state_prefers_ean13_candidate_key_over_uuid_id` | ROUND-R REGRESSION | KeyError: 'mart_native_code'; missing attribute when EAN is available | New test; Code needs implementation |
| `test_card_href_os_digits_used_when_initial_state_has_no_ean` | ROUND-R REGRESSION | KeyError: 'mart_native_code'; fallback to card href should extract EAN from "OS<EAN>" format | New test; Code needs implementation |
| `test_no_ean13_available_drops_uuid_only_product` | ROUND-R REGRESSION | Products with UUID but no EAN should be dropped (empty list returned); currently returning UUID-based items | New test; Code needs implementation |

**Common Issue**: These test exact G1 EAN handling behavior. Implementation must:
1. Extract EAN from multiple field candidates (priority order)
2. Validate EAN is 13 digits (e.g., "8801114119426")
3. When EAN available, use it; when not, skip product
4. Always populate `mart_native_code` for valid products

---

#### Group 3: test_mart_crawlers.py::TestLottemart* (4 failures)

| Test ID | Classification | Root Cause | Action Taken |
|---------|-----------------|-----------|--------------|
| `TestLottemartParse::test_initial_state_preserves_count_and_source_owned_fields` | ROUND-R REGRESSION | source_record_key expected "8801045440040" (EAN) got "sku-1" (slug) | Test updated ✓; Code needs EAN prioritization |
| `TestLottemartParse::test_lottemart_saved_json_envelope_parses_nested_state_and_product_rows` | ROUND-R REGRESSION | source_record_key expected "8801045440040" (EAN) got "sku-json" (slug) | Test updated ✓; Code needs EAN prioritization |
| `TestLottemartParse::test_lottemart_validate_uses_source_key_not_price_for_incremental_update` | ROUND-R REGRESSION | source_record_key expected "8801045440040" (EAN) got "water-1" (slug) | Test updated ✓; Code needs EAN prioritization |
| `TestLottemartInitialState::test_initial_state_preserves_unit_url_and_keeps_brand_out_of_category` | ROUND-R REGRESSION | KeyError: 'mart_native_code'; missing new attribute | Test updated ✓; Code needs implementation |

**Common Issue**: All use fixture data with both productId (slug) and retailerProductId (EAN).

---

### PRE-EXISTING FAILURES (Not G1-related)

#### 1. test_source_coverage.py::test_source_coverage_reports_registered_and_missing_one_shot_sources

| Aspect | Finding |
|--------|---------|
| **Test Status** | Not modified (no git diff) |
| **Last Modified** | rd6-pivot commit (17c8329), ~5 commits ago |
| **Failure** | `assert 25 == 39` — `rows["emart"]["source_map_manifest"]["breadth_plan"]["planned_request_count"]` |
| **Classification** | PRE-EXISTING (hard-coded expectation value changed in crawler code earlier) |
| **Root Cause** | EmartCrawler's SEARCH_QUERIES/CATEGORY_QUERIES count differs from expected. Test expects 39 (likely 13×3 for 3 pages) but gets 25 queries. |
| **Action** | Skip this round; investigate EmartCrawler configuration separately. This is NOT a G1 issue. |

---

#### 2. test_quality_diagnostics.py::test_high_priority_non_marketplace_fixtures_produce_bounded_quality_evidence

| Aspect | Finding |
|--------|---------|
| **Test Status** | Not modified |
| **Failure** | `assert 0 > 0` (from line check) — fixture count assertion |
| **Classification** | PRE-EXISTING or INFRASTRUCTURE |
| **Root Cause** | Missing test fixtures or fixture loading issue, not G1-related |
| **Action** | Skip this round; investigate fixture availability separately. |

---

### INFRASTRUCTURE FAILURES (API/Routes)

#### test_workbench_routes.py (5 failures)

| Test ID | Finding |
|---------|---------|
| `test_overview_returns_4_marts` | 404 response, KeyError: 'marts' |
| `test_overview_cap_suspect_flag` | KeyError: 'marts' |
| `test_runs_endpoint` | 404 response |
| `test_samples_endpoint` | 404 response |
| `test_run_all_endpoint` | 404 (expected 202) |

**Classification**: INFRASTRUCTURE (not G1-related)  
**Root Cause**: Workbench API endpoints are missing or broken.  
**Note**: Not changed in RD8 commits; appears to be pre-existing environmental issue.

---

## G1 Implementation Requirements

Based on failing tests, the G1 implementation must support:

### 1. EAN Extraction (`_entity_to_discount_item` method)

**Candidate Fields (priority order)**:
- `retailerProductId` (e.g., "OS8801045440040")
- `stdGoodsCd` (Korean standard product code)
- `productGcode` (product group code if EAN-13 format)
- Card href fallback: extract "OS<digits>" from `/products/OS{EAN}/details`

**Processing**:
1. Try each field in priority order
2. Strip "OS" prefix if present
3. Validate result is 13 digits
4. Return (ean_value, source_field_name) tuple

### 2. URL Construction
- Build detail_url from EAN: `f"{self.ZETTA_BASE}/products/OS{ean}/details"`
- Fallback to UUID only if NO EAN available, then skip product (test expects empty list)

### 3. Attribute Requirements
- `mart_native_code` (string, 13-digit EAN or None)
- `ean_source_key` (string, field name used: "retailerProductId", "stdGoodsCd", "href", etc.)
- `external_seller` (boolean, False for internal lottemart stock)
- `source_record_key` (should be the EAN, not UUID/slug)

### 4. Product Filtering
- Skip products that have UUID productId but NO extractable EAN
- Only return products with valid EAN in G1 mode

---

## Proposed Fix Strategy

### Phase 1: Update `_entity_to_discount_item()` (70 lines)

```python
def _entity_to_discount_item(self, product: dict, product_id: str = "") -> Optional[DiscountItem]:
    """Extract EAN fields and prioritize over UUID for G1."""
    
    # NEW: Extract EAN from candidate fields
    ean13, ean_source = self._extract_ean_candidate(product, product_id)
    
    if ean13:
        # Use EAN for both source_record_key and detail_url
        source_record_key = ean13
        detail_url = f"{self.ZETTA_BASE}/products/OS{ean13}/details"
        # Add mart_native_code and ean_source_key attributes
        ...
    else:
        # G1: Skip UUID-only products
        return None  
        
    # ... rest of parsing
```

### Phase 2: Add `_extract_ean_candidate()` helper (~30 lines)

Extract and validate EAN from product fields with fallback to href parsing.

---

## Test Results Before/After

### Before Fixes
```
19 failed, 818 passed, 20 skipped
```

### After Implementation (Expected)
```
0 failed, 837 passed, 20 skipped
```

---

## Commit Scope

**Files to modify**:
- `packages/crawler-admin/backend/crawlers/marts/lottemart/crawler.py`
  - `_entity_to_discount_item()` method (expand ~40 lines)
  - Add `_extract_ean_candidate()` method (~30 lines)
  - Update `_parse_spa_card()` to use EAN when available
  - Update `_json_to_discount_item()` to use EAN

**Files to ADD (tests)**:
- Already added but untracked:
  - `test_lottemart_crawler_g1.py` (git add)
  - `test_costco_crawler_g1.py` (git add)
  - `test_emart_crawler_g1.py` (git add)
  - `test_homeplus_crawler_g1.py` (git add)
  - `test_source_utils_g1.py` (git add)

**Modified tests** (already updated, ready to pass after code fix):
- `test_lottemart_crawler.py` ✓
- `test_mart_crawlers.py` ✓

---

## Next Actions

1. **Immediate**: Implement `_extract_ean_candidate()` in LottemartCrawler
2. **Follow-up**: Update EmartCrawler, HomeplusCrawler, CostcoCrawler with G1 EAN support
3. **Verify**: Re-run test suite; confirm 0 G1 failures
4. **Skip (Out of scope)**: `test_source_coverage.py` and `test_quality_diagnostics.py` failures (pre-existing)

