"""Input validation security tests."""
import pytest
from pydantic import ValidationError


class TestProductValidation:
    def test_name_too_long(self):
        from api.routes.products import ProductCreate
        with pytest.raises(ValidationError):
            ProductCreate(name="x" * 256)

    def test_name_blank(self):
        from api.routes.products import ProductCreate
        with pytest.raises(ValidationError):
            ProductCreate(name="   ")

    def test_name_min_length(self):
        from api.routes.products import ProductCreate
        with pytest.raises(ValidationError):
            ProductCreate(name="")

    def test_valid_product(self):
        from api.routes.products import ProductCreate
        p = ProductCreate(name="돼지고기 삼겹살", unit="100g")
        assert p.name == "돼지고기 삼겹살"

    def test_image_url_scheme(self):
        from api.routes.products import ProductCreate
        with pytest.raises(ValidationError):
            ProductCreate(name="test", image_url="javascript:alert(1)")

    def test_bulk_delete_too_many_ids(self):
        from api.routes.products import BulkDeleteRequest
        with pytest.raises(ValidationError):
            BulkDeleteRequest(ids=list(range(501)))

    def test_bulk_delete_empty_ids(self):
        from api.routes.products import BulkDeleteRequest
        with pytest.raises(ValidationError):
            BulkDeleteRequest(ids=[])


class TestCategoryValidation:
    def test_id_format_valid(self):
        from api.routes.categories import CategoryCreate
        c = CategoryCreate(id="meat.pork.belly", name="삼겹살")
        assert c.id == "meat.pork.belly"

    def test_id_format_invalid(self):
        from api.routes.categories import CategoryCreate
        with pytest.raises(ValidationError):
            CategoryCreate(id="MEAT/pork", name="돼지")

    def test_id_too_long(self):
        from api.routes.categories import CategoryCreate
        with pytest.raises(ValidationError):
            CategoryCreate(id="a" * 101, name="test")

    def test_sort_order_negative(self):
        from api.routes.categories import CategoryCreate
        with pytest.raises(ValidationError):
            CategoryCreate(id="test", name="test", sort_order=-1)


class TestKeywordValidation:
    def test_word_too_long(self):
        from api.routes.keywords import KeywordCreate
        with pytest.raises(ValidationError):
            KeywordCreate(word="x" * 101)

    def test_too_many_synonyms(self):
        from api.routes.keywords import KeywordCreate
        with pytest.raises(ValidationError):
            KeywordCreate(word="test", synonyms=["s"] * 21)

    def test_bulk_delete_limit(self):
        from api.routes.keywords import BulkDeleteRequest
        with pytest.raises(ValidationError):
            BulkDeleteRequest(ids=list(range(501)))


class TestIngestionValidation:
    def test_too_many_items(self):
        from api.routes.ingestion import IngestionSubmit
        with pytest.raises(ValidationError):
            IngestionSubmit(
                crawler_name="test",
                items=[{"name": "x"}] * 10_001,
            )

    def test_invalid_schema_type(self):
        from api.routes.ingestion import IngestionSubmit
        with pytest.raises(ValidationError):
            IngestionSubmit(crawler_name="test", schema_type="EvilSchema")

    def test_invalid_crawl_status(self):
        from api.routes.ingestion import IngestionSubmit
        with pytest.raises(ValidationError):
            IngestionSubmit(crawler_name="test", crawl_status="hacked")

    def test_invalid_review_action(self):
        from api.routes.ingestion import ReviewRequest
        with pytest.raises(ValidationError):
            ReviewRequest(action="destroy")

    def test_cleanup_invalid_status(self):
        from api.routes.ingestion import CleanupRequest
        with pytest.raises(ValidationError):
            CleanupRequest(status=["invalid_status"], confirm=True)

    def test_valid_ingestion(self):
        from api.routes.ingestion import IngestionSubmit
        ing = IngestionSubmit(
            crawler_name="emart_crawler",
            items=[{"name": "apple", "sale_price": 1000}],
        )
        assert ing.crawler_name == "emart_crawler"
        assert len(ing.items) == 1


class TestPriceValidation:
    def test_price_must_be_positive(self):
        from api.routes.prices import PriceItem
        with pytest.raises(ValidationError):
            PriceItem(product_id=1, price=-100, source="test")

    def test_price_upper_limit(self):
        from api.routes.prices import PriceItem
        with pytest.raises(ValidationError):
            PriceItem(product_id=1, price=200_000_000, source="test")

    def test_bulk_too_many_items(self):
        from api.routes.prices import BulkPriceRequest, PriceItem
        items = [PriceItem(product_id=1, price=100, source="s")] * 5_001
        with pytest.raises(ValidationError):
            BulkPriceRequest(items=items)

    def test_invalid_data_type(self):
        from api.routes.prices import BulkPriceRequest, PriceItem
        items = [PriceItem(product_id=1, price=100, source="s")]
        with pytest.raises(ValidationError):
            BulkPriceRequest(items=items, data_type="evil")

    def test_tier_config_invalid_key(self):
        from api.routes.prices import TierConfigRequest
        with pytest.raises(ValidationError):
            TierConfigRequest(tiers={"hacker_tier": {"label": "x"}})


class TestAnalyticsValidation:
    def test_duplicate_invalid_table(self):
        from api.routes.analytics import DuplicateRequest
        with pytest.raises(ValidationError):
            DuplicateRequest(table_name="users", fields=["password"])

    def test_validate_too_many_items(self):
        from api.routes.analytics import ValidateRequest
        with pytest.raises(ValidationError):
            ValidateRequest(items=[{}] * 10_001)


class TestAdminValidation:
    def test_source_too_long(self):
        from api.routes.admin import ResetSourceRequest
        with pytest.raises(ValidationError):
            ResetSourceRequest(source="x" * 101, confirm="test")
