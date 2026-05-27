from __future__ import annotations

import json

import pytest

from crawlers.marts.lottemart.crawler import LottemartCrawler
from crawlers.marts.source_utils import normalize_lottemart_url


UUID = "9f4a776d-108c-47c8-aa28-416123cdb058"
EAN13 = "8801114119426"


def _initial_state_html(product_extra: dict[str, str] | None = None, card_href: str = "") -> str:
    href_attr = f' href="{card_href}"' if card_href else ""
    product = {
        "productId": UUID,
        "name": "오늘좋은 테스트 상품 450ml",
        "price": {"current": {"amount": "3490"}, "original": {"amount": "3990"}},
        "image": {"src": "https://lottemartzetta.com/images/test.jpg"},
        "categoryPath": ["식품", "테스트"],
        "size": {"value": "450ml 10ml당 78원"},
        "offer": {"description": "주간특가"},
        **(product_extra or {}),
    }
    state_json = json.dumps(
        {"data": {"products": {"productEntities": {UUID: product}}}},
        ensure_ascii=False,
    )
    return f"""
    <!doctype html><html><body>
      <script>window.__INITIAL_STATE__={state_json};</script>
      <div class="product-card-container" data-synthetics="product-id:{UUID}">
        <a data-test="fop-product-link"{href_attr}><span>오늘좋은 테스트 상품</span></a>
        <h3 class="product-name">오늘좋은 테스트 상품 450ml</h3>
        <span data-test="fop-price" class="sale_price">3,490원</span>
      </div>
    </body></html>
    """


@pytest.mark.asyncio
async def test_initial_state_ean_ignores_data_synthetics_uuid():
    html = _initial_state_html({"retailerProductId": f"OS{EAN13}"})
    items = await LottemartCrawler().parse(html)

    assert len(items) == 1
    item = items[0]
    assert UUID not in item.detail_url
    assert item.attributes["mart_native_code"] == EAN13
    assert item.attributes["source_record_key"] == EAN13
    assert item.detail_url == f"https://lottemartzetta.com/products/OS{EAN13}/details"
    assert item.attributes["canonical_url"] == item.detail_url
    assert item.attributes["external_seller"] is False
    assert item.attributes["source"] == "lottemart"
    assert item.attributes["ean_source_key"] == "retailerProductId"
    assert item.attributes["unit_price"] == 78
    assert item.attributes["unit_price_basis"].lower() == "10ml"
    assert item.attributes["canon_hash"]


@pytest.mark.asyncio
async def test_initial_state_prefers_ean13_candidate_key_over_uuid_id():
    html = _initial_state_html({"productId": UUID, "stdGoodsCd": EAN13})
    items = await LottemartCrawler().parse(html)

    assert len(items) == 1
    assert items[0].attributes["mart_native_code"] == EAN13
    assert items[0].detail_url == f"https://lottemartzetta.com/products/OS{EAN13}/details"


@pytest.mark.asyncio
async def test_card_href_os_digits_used_when_initial_state_has_no_ean():
    html = _initial_state_html(card_href=f"/products/OS{EAN13}/details")
    crawler = LottemartCrawler()
    # Exercise card fallback explicitly: state product lacks an EAN and is skipped, then HTML href supplies OS<EAN>.
    items = await crawler.parse(html)

    assert len(items) == 1
    assert items[0].attributes["mart_native_code"] == EAN13
    assert items[0].attributes["ean_source_key"] == "href"
    assert items[0].detail_url == f"https://lottemartzetta.com/products/OS{EAN13}/details"


@pytest.mark.asyncio
async def test_uuid_href_without_ean13_is_rejected():
    html = _initial_state_html(card_href=f"/products/{UUID}")
    items = await LottemartCrawler().parse(html)

    assert items == []


@pytest.mark.asyncio
async def test_initial_state_uuid_url_converts_to_os_detail_url_when_ean13_exists():
    html = _initial_state_html({"goodsUrl": f"/products/{UUID}", "retailerProductId": f"OS{EAN13}"})
    items = await LottemartCrawler().parse(html)

    assert len(items) == 1
    assert UUID not in items[0].detail_url
    assert items[0].detail_url == f"https://lottemartzetta.com/products/OS{EAN13}/details"


@pytest.mark.asyncio
async def test_no_ean13_available_drops_uuid_only_product():
    html = _initial_state_html()
    items = await LottemartCrawler().parse(html)

    assert items == []


def test_normalize_lottemart_url_builds_os_detail_and_rejects_uuid():
    assert normalize_lottemart_url(EAN13) == f"https://lottemartzetta.com/products/OS{EAN13}/details"
    assert normalize_lottemart_url(f"OS{EAN13}") == f"https://lottemartzetta.com/products/OS{EAN13}/details"
    with pytest.raises(ValueError):
        normalize_lottemart_url(UUID)


@pytest.mark.asyncio
async def test_lottemart_promo_label_1_plus_1_from_offer():
    html = _initial_state_html({"retailerProductId": f"OS{EAN13}", "offer": {"description": "1+1 행사"}})
    items = await LottemartCrawler().parse(html)

    assert len(items) == 1
    assert items[0].promo_label == "1+1"
    assert items[0].promo_type == "buy_x_get_y"
    assert items[0].attributes["promo_label"] == "1+1"
