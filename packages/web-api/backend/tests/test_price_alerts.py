from __future__ import annotations

from copy import deepcopy
import sqlite3
import pytest
from sqlalchemy import text

from services.account_database import AccountDatabase
from services.runtime_storage import RuntimeStorage
from services.catalog_storage import CatalogUnavailable


def _product():
    return {"id": "prod-choco", "name": "초코에몽", "cur": 100, "variants": [
        {"id": f"var-{key}", "name": f"200ml×{count}", "display_unit": f"200ml×{count}",
         "package_quantity": 200, "package_unit": "ml", "bundle_count": count,
         "listings": [{"id": f"listing-{key}", "source": "synthetic", "title": f"200ml×{count}",
                       "offers": [{"id": f"offer-{key}", "listed_price": price, "total_price": price,
                                   "comparable_price": price, "total_quantity": 200 * count,
                                   "quantity_unit": "ml", "received_package_count": 1,
                                   "minimum_quantity": 1, "membership_required": False,
                                   "coupon_required": False, "promotion_type": "normal",
                                   "promotion_conditions": {}, "offer_state": "active",
                                   "is_latest": True, "current_eligible": True}]}]}
        for key, count, price in [("a", 6, 4900), ("b", 1, 100)]
    ]}


def test_homogeneous_vector_alert_requires_saved_contents_proof_and_follows_price_only():
    product = _product()
    variant = product['variants'][0]
    product['variants'] = [variant]
    variant.update(package_quantity=1, package_unit='세트', bundle_count=1,
                   quantity_components=[{'quantity':350,'unit':'g','count':1,'identity':'고추장','presentation':''},
                                        {'quantity':1500,'unit':'g','count':1,'identity':'고추장','presentation':''}])
    listing = variant['listings'][0]
    old = listing['offers'][0]
    old.update(total_quantity=1, quantity_unit='세트', pricing_measure_quantity=1850,
               pricing_measure_unit='g', pricing_measure_basis='reviewed_homogeneous_contents',
               quantity_basis='reviewed_homogeneous_contents',
               scalar_basis='one_complete_declared_vector_not_piece_count',
               received_package_count_scope='complete_declared_vector')
    row = {'variant_id':variant['id'], 'listing_id':listing['id'], 'offer_id':old['id']}
    saved = RuntimeStorage._alert_context(variant, listing, old)
    original_saved = deepcopy(saved)
    newer = {**deepcopy(old), 'id':'new-price-only', 'listed_price':6000, 'total_price':6000, 'comparable_price':6000}
    old['is_latest'] = False
    listing['offers'].insert(0, newer)
    assert RuntimeStorage._saved_receipt_state(product, row, saved) == (True, None)
    assert RuntimeStorage._alert_current(product, row, saved)[0] == 6000
    for change, reason in [({'quantity_components':None}, 'receipt_components_unconfirmed'),
                          ({'quantity_components':[{**variant['quantity_components'][0], 'count':2}]}, 'receipt_components_unconfirmed'),
                          ({'pricing_measure_quantity':None}, 'receipt_basis_revised'),
                          ({'quantity_basis':None}, 'receipt_basis_revised')]:
        held = {**saved, **change}
        assert RuntimeStorage._saved_receipt_state(product, row, held) == (False, reason)
        current, offer_id, context, observed_reason = RuntimeStorage._alert_current(product, row, held)
        assert current is None and observed_reason == reason and offer_id == 'new-price-only'
        assert context['pricing_measure_quantity'] == 1850
    newer['pricing_measure_quantity'] = 2000
    assert RuntimeStorage._alert_current(product, row, saved)[3] == 'receipt_conditions_changed'
    assert saved == original_saved and row['offer_id'] == old['id']


def test_declared_linear_receipt_proof_is_required_before_alert_follows_price_only():
    product = _product()
    variant = product['variants'][0]
    product['variants'] = [variant]
    variant.update(package_quantity=40, package_unit='m', bundle_count=3, display_unit='40m×3')
    listing = variant['listings'][0]
    old = listing['offers'][0]
    old.update(total_quantity=120, quantity_unit='m', per_100m=4083,
               pricing_measure_quantity=120, pricing_measure_unit='m',
               pricing_measure_basis='reviewed_declared_linear_contents',
               quantity_basis='reviewed_declared_linear_contents',
               scalar_basis='declared_linear_contents_not_physical_dimensions',
               received_package_count_scope='declared_linear_package_repetitions')
    row = {'variant_id':variant['id'], 'listing_id':listing['id'], 'offer_id':old['id']}
    saved = RuntimeStorage._alert_context(variant, listing, old)
    original = deepcopy(saved)
    assert saved['per_100m'] == 4083 and saved['pricing_measure_quantity'] == 120
    newer = {**deepcopy(old), 'id':'linear-price-change', 'listed_price':5000, 'total_price':5000, 'comparable_price':5000, 'per_100m':4167}
    old['is_latest'] = False
    listing['offers'].insert(0, newer)
    assert RuntimeStorage._saved_receipt_state(product, row, saved) == (True, None)
    assert RuntimeStorage._alert_current(product, row, saved)[0] == 5000
    for key in ('quantity_basis', 'scalar_basis', 'received_package_count_scope',
                'pricing_measure_quantity', 'pricing_measure_unit', 'pricing_measure_basis'):
        legacy = {k:v for k,v in saved.items() if k != key}
        assert RuntimeStorage._saved_receipt_state(product, row, legacy) == (False, 'receipt_basis_revised')
        current, _, context, reason = RuntimeStorage._alert_current(product, row, legacy)
        assert current is None and reason == 'receipt_basis_revised'
        assert context['total_quantity'] == 120 and context['per_100m'] == 4167
    assert saved == original and row['offer_id'] == old['id']


@pytest.mark.parametrize('comparison_reason,current_quote', [
    (None, 22990), (None, 24000),
    ('heterogeneous_contents_allocation_unverified', 22990),
    ('heterogeneous_contents_allocation_unverified', 24000),
    ('quantity_evidence_unverified', 22990),
])
def test_canonical_composition_hold_invalidates_legacy_receipt_and_alert_without_rewriting_history(comparison_reason, current_quote):
    # Existing explicit-eligibility test double; no account or catalog database.
    # The saved tuple has the real historical scalar basis and stale rate.
    product = _product()
    variant = product['variants'][0]
    product['variants'] = [variant]
    variant.update(package_quantity=230, package_unit='g', bundle_count=4, display_unit='230g×4')
    listing = variant['listings'][0]
    old = listing['offers'][0]
    old.update(listed_price=22990, total_price=22990, comparable_price=22990,
               total_quantity=920, quantity_unit='g', per_100g=2498.913, per_item=5747.5)
    row = {'variant_id': variant['id'], 'listing_id': listing['id'], 'offer_id': old['id']}
    saved = RuntimeStorage._alert_context(variant, listing, old)
    saved.pop('quantity_comparison_reason', None)  # Pre-correction persisted context.
    original_saved, original_row = deepcopy(saved), deepcopy(row)
    assert RuntimeStorage._saved_receipt_state(product, row, saved) == (True, None)
    if current_quote != 22990:
        newer = {**deepcopy(old), 'id': 'offer-new-price', 'listed_price': current_quote,
                 'total_price': current_quote, 'comparable_price': current_quote}
        old['is_latest'] = False
        listing['offers'].insert(0, newer)
    if comparison_reason:
        for offer in listing['offers']:
            offer.update(quantity_comparison_reason=comparison_reason, per_100g=None, per_item=None)
    assert RuntimeStorage._saved_receipt_state(product, row, saved) == (
        (False, comparison_reason) if comparison_reason else (True, None))
    current, offer_id, context, reason = RuntimeStorage._alert_current(product, row, saved)
    assert current == (None if comparison_reason else current_quote)
    assert reason == comparison_reason and offer_id == listing['offers'][0]['id']
    assert context['quantity_comparison_reason'] == comparison_reason
    assert context['listed_price'] == context['total_price'] == current_quote
    assert context['total_quantity'] == 920 and context['package_quantity'] == 230 and context['bundle_count'] == 4
    assert saved == original_saved and row == original_row
    assert saved['total_price'] == 22990 and saved['per_100g'] == 2498.913
    assert listing['offers'][-1]['id'] == row['offer_id'] and listing['offers'][-1]['listed_price'] == 22990


class _Catalog:
    def __init__(self):
        self.product = _product()

    def product_exists(self, product_id):
        return str(product_id) == "prod-choco"

    def has_normalized_catalog(self):
        return True

    def get_normalized_product_detail(self, product_id):
        if str(product_id) != "prod-choco":
            return None
        return deepcopy(self.product)


def _storage(tmp_path):
    accounts = AccountDatabase(tmp_path / "accounts.sqlite")
    accounts.initialize()
    storage = RuntimeStorage.__new__(RuntimeStorage)
    storage.accounts = accounts
    storage.SessionLocal = accounts.SessionLocal
    storage.catalog = _Catalog()
    return storage, accounts


@pytest.fixture
def stored(tmp_path):
    storage, accounts = _storage(tmp_path)
    with storage.SessionLocal() as session:
        session.execute(text("INSERT INTO users (email,nickname,role,is_active) VALUES ('alert@example.test','알림사용자','user',1)"))
        session.commit()
        uid = session.execute(text("SELECT id FROM users")).scalar_one()
    yield storage, uid
    accounts.close()


def _select(storage, uid, target=4000, key="a"):
    return storage.add_price_alert(uid, "prod-choco", target, variant_id=f"var-{key}",
                                   listing_id=f"listing-{key}", offer_id=f"offer-{key}")


def _quote(storage, key="a"):
    return storage.catalog.product["variants"][0 if key == "a" else 1]["listings"][0]["offers"][0]


def test_normalized_product_price_alert_is_persistent_idempotent_and_removable(tmp_path):
    storage, accounts = _storage(tmp_path)
    try:
        with storage.SessionLocal() as session:
            session.execute(
                text(
                    "INSERT INTO users (email, nickname, role, is_active, created_at) "
                    "VALUES ('alert@example.test', '알림사용자', 'user', 1, CURRENT_TIMESTAMP)"
                )
            )
            session.commit()
            user_id = session.execute(
                text("SELECT id FROM users WHERE email='alert@example.test'")
            ).scalar_one()

        first = storage.add_price_alert(user_id, "prod-choco", 5_000)
        second = storage.add_price_alert(user_id, "prod-choco", 4_000)
        assert first["id"] == second["id"]

        rows = storage.get_user_alerts(user_id)
        assert len(rows) == 1
        assert rows[0]["product_id"] == "prod-choco"
        assert rows[0]["current_price"] is None
        assert rows[0]["trigger_reason"] == "selection_required"
        assert rows[0]["target_price"] == 4_000
        assert rows[0]["is_triggered"] is False

        assert storage.remove_price_alert(user_id, rows[0]["id"])["status"] == "removed"
        assert storage.get_user_alerts(user_id) == []
    finally:
        accounts.close()


def test_selected_tuple_persists_independently_and_only_its_latest_receipt_triggers(stored):
    storage, uid = stored
    first = _select(storage, uid)
    second = _select(storage, uid, 5000)
    other = _select(storage, uid, 90, "b")
    assert first["id"] == second["id"] != other["id"]
    assert first["current_price"] == 4900 and first["is_triggered"] is False
    assert second["is_triggered"] is True
    assert second["offer_context"]["membership_required"] is False
    old = _quote(storage)
    old["is_latest"] = False
    new = {**old, "id": "offer-new", "is_latest": True, "total_price": 3500, "comparable_price": 3500}
    # Original immutable event may disappear; selected listing/spec remains.
    storage.catalog.product["variants"][0]["listings"][0]["offers"] = [new]
    storage.accounts.initialize()
    rows = {row["id"]: row for row in storage.get_user_alerts(uid)}
    assert rows[first["id"]]["offer_id"] == "offer-a"
    assert rows[first["id"]]["current_offer_id"] == "offer-new"
    assert rows[first["id"]]["current_price"] == 3500
    assert rows[first["id"]]["offer_context"]["total_price"] == 4900
    assert rows[first["id"]]["saved_receipt_valid"] is True  # Money is not specification identity.
    assert rows[other["id"]]["is_triggered"] is False
    storage.catalog.product["variants"][0]["id"] = "variant-corrected"
    revised = {row["id"]: row for row in storage.get_user_alerts(uid)}[first["id"]]
    assert revised["saved_receipt_valid"] is False
    assert revised["saved_receipt_reason"] == "selected_specification_revised"
    assert revised["offer_context"]["total_price"] == 4900 and revised["offer_id"] == "offer-a"
    assert revised["current_price"] is None and not revised["is_triggered"]
    storage.remove_price_alert(uid, first["id"])
    assert [row["id"] for row in storage.get_user_alerts(uid)] == [other["id"]]


@pytest.mark.parametrize("state", ["pending", "inactive"])
def test_latest_nonactive_event_never_revives_older_active_quote(stored, state):
    storage, uid = stored
    alert = _select(storage, uid, 6000)
    old = _quote(storage)
    old["is_latest"] = False
    storage.catalog.product["variants"][0]["listings"][0]["offers"].append(
        {**old, "id": "new-held", "is_latest": True, "offer_state": state, "current_eligible": False})
    row = storage.get_user_alerts(uid)[0]
    assert row["id"] == alert["id"] and row["is_active"]
    assert row["current_offer_id"] == "new-held"
    assert row["current_price"] is None and not row["is_triggered"]
    assert row["trigger_reason"] == "quote_unavailable"


@pytest.mark.parametrize("amount", [None, 0, -1, "bad"])
def test_valid_identity_unknown_or_invalid_money_is_saved_held_not_zero(stored, amount):
    storage, uid = stored
    quote = _quote(storage)
    quote.update(total_price=amount, comparable_price=None)
    row = _select(storage, uid, 6000)
    assert row["offer_id"] == "offer-a" and row["offer_context"]["listed_price"] == 4900
    assert row["current_price"] is None and not row["is_triggered"]
    assert row["quoted_price"] is None
    assert row["trigger_reason"] == "price_unconfirmed"


def test_unknown_saved_basis_is_not_silently_adopted_when_later_known(stored):
    storage, uid = stored
    quote = _quote(storage)
    quote.update(total_quantity=None, quantity_unit=None)
    row = _select(storage, uid, 6000)
    assert row["trigger_reason"] == "receipt_basis_unknown"
    quote.update(total_quantity=1200, quantity_unit="ml")
    assert storage.get_user_alerts(uid)[0]["trigger_reason"] == "receipt_basis_unknown"
    # Explicit re-save is a fresh confirmation of the same selected receipt.
    assert _select(storage, uid, 6000)["is_triggered"] is True


@pytest.mark.parametrize("change", [
    {"membership_required": True}, {"coupon_required": True}, {"membership_required": None},
    {"minimum_quantity": 2}, {"promotion_conditions": {"buy_quantity": 2, "free_quantity": 1}},
    {"promotion_condition": "회원 전용"},
])
def test_conditional_quote_retains_actual_context_but_cannot_promise_target(stored, change):
    storage, uid = stored
    _quote(storage).update(change)
    row = _select(storage, uid, 6000)
    assert row["current_price"] is None and not row["is_triggered"]
    assert row["quoted_price"] == 4900
    assert row["trigger_reason"] == (
        "membership_or_coupon_unverified" if any(key in change for key in ("membership_required", "coupon_required"))
        else "eligibility_unverified")
    for key, value in change.items():
        assert row["offer_context"][key] == value


@pytest.mark.parametrize('buy,free', [(1, 1), (2, 1)])
def test_proved_purchase_benefit_alert_uses_total_spend_and_received_quantity(stored, buy, free):
    storage, uid = stored
    quote = _quote(storage)
    quote.update(promotion_type='buy_x_get_y', minimum_quantity=buy,
                 promotion_conditions={'buy_quantity': buy, 'free_quantity': free,
                                       'minimum_quantity': buy, 'condition_text': f'{buy}+{free}'},
                 promotion_condition=f'{buy}+{free}', received_package_count=buy + free,
                 total_quantity=1200 * (buy + free), total_price=4900 * buy, comparable_price=4900 * buy)
    row = _select(storage, uid, 4900 * buy)
    assert row['is_triggered'] and row['current_price'] == 4900 * buy
    assert row['offer_context']['total_quantity'] == 1200 * (buy + free)
    quote['membership_required'] = None
    # Save the changed context explicitly; eligibility stays a separate unknown.
    row = _select(storage, uid, 4900 * buy)
    assert not row['is_triggered'] and row['trigger_reason'] == 'membership_or_coupon_unverified'


def test_proved_minimum_order_alert_uses_paid_receipt_and_keeps_eligibility_separate(stored):
    storage, uid = stored
    quote = _quote(storage)
    quote.update(promotion_type='final_price', minimum_quantity=2,
                 promotion_conditions={'minimum_quantity': 2, 'condition_text': '최소구매 2',
                                       'source_title_purchase_condition': '최소구매 2'},
                 promotion_condition='최소구매 2', received_package_count=2,
                 total_quantity=2400, total_price=9800, comparable_price=9800)
    row = _select(storage, uid, 9800)
    assert row['current_price'] == 9800 and row['is_triggered']
    assert row['offer_context']['total_quantity'] == 2400
    quote['membership_required'] = None
    row = _select(storage, uid, 9800)
    assert row['current_price'] is None and not row['is_triggered']
    assert row['trigger_reason'] == 'membership_or_coupon_unverified'


@pytest.mark.parametrize('selection,maximum,listed', [(3, 99, 3990), (4, 100, 2990)])
def test_known_basket_conditions_are_retained_with_specific_hold_and_no_paid_receipt(selection, maximum, listed):
    product = _product()
    variant = product['variants'][0]
    variant.update(package_quantity=1, package_unit='개', bundle_count=1)
    listing, offer = variant['listings'][0], variant['listings'][0]['offers'][0]
    conditions = {
        'source_condition_kind': 'selected_basket_total',
        'condition_text': f'{selection}개 담으면, 9,990원에 구매 (최대 {maximum}개까지 행사/할인 적용)',
        'required_selection_quantity': selection, 'conditional_basket_total_won': 9990,
        'source_event_maximum_quantity': maximum, 'source_order_minimum_quantity': 1,
        'source_purchase_limit': {'purchaseLimitYn': 'Y', 'purchaseLimitDuration': 'P',
                                  'purchaseLimitDay': 1, 'purchaseLimitQty': 10,
                                  'itemPurchaseLimitMessage': '1일 동안 최대 10개 구매가능'},
        'source_event_period': {'start_date': '2026-10-01', 'end_date': '2026-10-14'},
        'source_selection_price_intervals': [{'thresholdQty': selection, 'changeAmount': 9990}],
        'basket_selection_required': True, 'eligible_selection_unconfirmed': True,
        'payable_price_unconfirmed': True, 'coupon_application_unconfirmed': True,
    }
    offer.update(listed_price=listed, total_price=None, comparable_price=None,
                 total_quantity=None, quantity_unit=None, received_package_count=None, minimum_quantity=None,
                 promotion_type='unknown', promotion_conditions=conditions,
                 membership_required=None, coupon_required=None, current_eligible=False)
    row = {'variant_id': variant['id'], 'listing_id': listing['id'], 'offer_id': offer['id']}
    saved = RuntimeStorage._alert_context(variant, listing, offer)
    original_saved, original_row = deepcopy(saved), deepcopy(row)
    for changes, expected in [({}, 'basket_selection_unconfirmed'),
                              ({'current_eligible': True}, 'basket_selection_unconfirmed'),
                              ({'availability_reason': 'expired'}, 'expired'),
                              ({'availability_reason': 'not_yet_valid'}, 'not_yet_valid'),
                              ({'validity_eligible': False}, 'validity_unconfirmed'),
                              ({'offer_state': 'pending_review'}, 'quote_unavailable')]:
        original = deepcopy(offer)
        offer.update(changes)
        price, current_id, context, reason = RuntimeStorage._alert_current(product, row, saved)
        assert price is None and reason == expected and current_id == offer['id']
        assert context['promotion_conditions'] == conditions and context['listed_price'] == listed
        assert context['total_quantity'] is None and context['received_package_count'] is None
        assert context['membership_required'] is None and context['coupon_required'] is None
        assert context['package_quantity'] == 1 and context['bundle_count'] == 1
        assert saved == original_saved and row == original_row
        offer.clear()
        offer.update(original)


@pytest.mark.parametrize("change", [{"total_quantity": 2400}, {"quantity_unit": "g"},
                                  {"received_package_count": 2}, {"coupon_required": True}])
def test_changed_receipt_or_conditions_holds_same_identity_without_replacing_target(stored, change):
    storage, uid = stored
    row = _select(storage, uid, 6000)
    _quote(storage).update(change)
    current = storage.get_user_alerts(uid)[0]
    assert current["target_price"] == row["target_price"]
    assert current["current_price"] is None
    assert current["trigger_reason"] == "receipt_conditions_changed"


@pytest.mark.parametrize("selection", [
    {"variant_id": "var-a"},
    {"variant_id": "var-a", "listing_id": "listing-b", "offer_id": "offer-b"},
    {"variant_id": "var-a", "listing_id": "listing-a", "offer_id": "missing"},
])
def test_cross_tuple_partial_and_unknown_event_rejected_without_writes(stored, selection):
    storage, uid = stored
    with pytest.raises(ValueError, match="catalog_selection_invalid"):
        storage.add_price_alert(uid, "prod-choco", 5000, **selection)
    assert storage.get_user_alerts(uid) == []


@pytest.mark.parametrize("failure", [CatalogUnavailable, sqlite3.DatabaseError])
def test_catalog_failure_retains_saved_alert_with_explicit_hold(stored, failure):
    storage, uid = stored
    row = _select(storage, uid)
    storage.catalog.get_normalized_product_detail = lambda _: (_ for _ in ()).throw(failure("synthetic unavailable"))
    current = storage.get_user_alerts(uid)[0]
    assert current["id"] == row["id"] and current["is_active"]
    assert current["current_price"] is None and current["trigger_reason"] == "catalog_unavailable"


def test_authenticated_api_unavailable_catalog_cannot_create_a_guessed_alert(stored):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.routes.users import router
    from services.auth_service import create_access_token
    storage, uid = stored
    storage.catalog.get_normalized_product_detail = lambda _: (_ for _ in ()).throw(sqlite3.DatabaseError("synthetic corrupt"))
    app = FastAPI()
    app.state.storage = storage
    app.include_router(router, prefix="/api/users")
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer " + create_access_token({"sub": str(uid)})
        response = client.post("/api/users/me/alerts", json={"product_id": "prod-choco", "target_price": 5000})
        assert response.status_code == 503
        assert client.get("/api/users/me/alerts").json()["data"] == []


def test_legacy_table_upgrade_preserves_ids_targets_flags_and_autoincrement(tmp_path):
    path = tmp_path / "legacy.sqlite"
    original = AccountDatabase(path)
    with original.engine.begin() as connection:
        connection.execute(text("INSERT INTO users(id,email,nickname) VALUES(1,'legacy@example.test','legacy')"))
    original.close()
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            DROP TABLE price_alerts;
            CREATE TABLE price_alerts(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,
                product_id TEXT NOT NULL,target_price REAL NOT NULL,is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL, UNIQUE(user_id,product_id));
            INSERT INTO price_alerts VALUES(41,1,'prod-choco',3456,0,'2026-01-01');
            INSERT INTO price_alerts VALUES(99,1,'deleted',123,1,'2026-01-02');
            DELETE FROM price_alerts WHERE id=99;
        """)
    accounts = AccountDatabase(path)
    try:
        accounts.initialize()
        accounts.initialize()
        with accounts.engine.begin() as connection:
            row = connection.execute(text("SELECT * FROM price_alerts")).mappings().one()
            assert (row["id"],row["target_price"],row["is_active"],row["created_at"]) == (41,3456,0,"2026-01-01")
            assert row["offer_context"] is None
            connection.execute(text("INSERT INTO price_alerts(user_id,product_id,target_price,variant_id,listing_id,offer_id) VALUES(1,'prod-choco',5000,'v','l','o')"))
            assert connection.execute(text("SELECT MAX(id) FROM price_alerts")).scalar_one() == 100
    finally:
        accounts.close()


def test_authenticated_api_selection_roundtrip_rejections_and_cross_user_remove(stored):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.routes.users import router
    from services.auth_service import create_access_token
    storage, uid = stored
    app = FastAPI()
    app.state.storage = storage
    app.include_router(router, prefix="/api/users")
    with TestClient(app) as client:
        path = "/api/users/me/alerts"
        body = {"product_id": "prod-choco", "target_price": 5000,
                "variant_id": "var-a", "listing_id": "listing-a", "offer_id": "offer-a"}
        assert client.post(path, json=body).status_code == 401
        client.headers["Authorization"] = "Bearer " + create_access_token({"sub": str(uid)})
        response = client.post(path, json=body)
        assert response.status_code == 200
        saved = response.json()["data"]
        assert saved["offer_id"] == "offer-a" and saved["is_triggered"]
        assert client.post(path, json=body).json()["data"]["id"] == saved["id"]
        assert client.post(path, json={**body, "listing_id": "listing-b"}).status_code == 422
        assert client.post(path, json={**body, "target_price": True}).status_code == 422
        assert client.post(path, json={**body, "offer_id": None}).status_code == 422
        assert client.post(path, json={**body, "product_id": "missing"}).status_code == 404
        assert len(client.get(path).json()["data"]) == 1
        with storage.SessionLocal() as session:
            session.execute(text("INSERT INTO users(email,nickname) VALUES('other@example.test','other')"))
            session.commit()
            other_uid = session.execute(text("SELECT id FROM users WHERE email='other@example.test'")).scalar_one()
        client.headers["Authorization"] = "Bearer " + create_access_token({"sub": str(other_uid)})
        assert client.delete(f"{path}/{saved['id']}").json()["data"]["status"] == "not_found"
        client.headers["Authorization"] = "Bearer " + create_access_token({"sub": str(uid)})
        assert client.delete(f"{path}/{saved['id']}").status_code == 200
        assert client.get(path).json()["data"] == []
        _quote(storage).update(total_price=None, comparable_price=None)
        held = client.post(path, json=body)
        assert held.status_code == 200
        data = held.json()["data"]
        assert data["id"] == saved["id"] and data["offer_id"] == body["offer_id"]
        assert data["offer_context"]["listed_price"] == 4900
        assert data["current_price"] is None and data["quoted_price"] is None
        assert data["trigger_reason"] == "price_unconfirmed" and not data["is_triggered"]


@pytest.mark.parametrize("price", [4900, None, 0])
def test_legacy_numeric_alert_keeps_own_positive_quote_only(stored, price):
    storage, uid = stored
    storage.catalog.has_normalized_catalog = lambda: False
    storage.catalog.get_product_detail = lambda pid: {"id": 7, "name": "legacy", "cur": price}
    row = storage.add_price_alert(uid, 7, 5000)
    assert row["current_price"] == (4900 if price == 4900 else None)
    assert row["is_triggered"] is (price == 4900)
