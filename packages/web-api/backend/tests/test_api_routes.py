"""Focused route regressions for the current web API runtime.

The public API must be testable without opening the repository's real catalog DB.
Community tests use temporary, physically separate account and board SQLite files.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.auth_service import create_token_pair
from services.user_storage import PublicUserStore


@pytest.fixture(autouse=True)
def isolated_board(tmp_path, monkeypatch):
    board_path = tmp_path / "board.sqlite"
    monkeypatch.setenv("WALLETSAVIOR_BOARD_DB", str(board_path))

    from services import board_storage

    board_storage.reset_board_engine()
    # The current board runtime creates only schema. Tests create their own data.
    board_storage.get_board_engine()
    yield board_path
    board_storage.reset_board_engine()


@pytest.fixture()
def account_db(tmp_path):
    from services.account_database import AccountDatabase

    db = AccountDatabase(tmp_path / "accounts.sqlite")
    yield db
    db.close()


@pytest.fixture()
def app(account_db):
    from api.app import create_app

    return create_app(storage=account_db)


@pytest.fixture()
def client(app):
    return TestClient(app)


def _identity(account_db, email: str, nickname: str) -> tuple[dict, dict[str, str]]:
    """Create a real persistent test account and its access-token header."""
    user = PublicUserStore(account_db).create_password_user(
        email=email,
        nickname=nickname,
        hashed_password="test-only-unused-password-hash",
    )
    tokens = create_token_pair(user["id"], user["email"], user["role"])
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    return user, headers


@pytest.mark.parametrize('product_id,quote,held', [(17, 9000, False), ('prod-linked', 9000, False), ('opaque:reviewed', 9000, False), ('prod-held', 2899000, True)])
def test_account_payload_catalog_ids_preserve_existing_product_id_storage_type(client, account_db, product_id, quote, held):
    product = {'id': product_id, 'name': '검증 상품', 'unit': '', 'price': 0 if held else quote,
               'cur': 0 if held else quote}
    if isinstance(product_id, str):
        product.update(public_product_id=product_id, best_offer=None if held else {'comparable_price': quote},
                       variants=[{'package_quantity': None, 'listings': [{'offers': [{'listed_price': quote}]}]}])
    account_db.get_product_detail = lambda value: product if value == product_id else None
    _user, headers = _identity(account_db, 'catalog-test@example.invalid', 'catalog-test')
    response = client.post('/api/cart', headers=headers, json={
        'product_id': product_id, 'item_name': '검증 상품', 'item_price': quote, 'quantity': 2,
    })
    assert response.status_code == 200
    assert response.json()['data']['product_id'] == product_id
    assert response.json()['data']['item_price'] == quote
    assert response.json()['data']['quantity'] == 2
    response = client.post('/api/wishlist', headers=headers, json={
        'product_id': product_id, 'item_name': '검증 상품', 'price_at_add': quote, 'current_price': quote,
    })
    assert response.status_code == 200
    assert response.json()['data']['product_id'] == product_id
    assert response.json()['data']['current_price'] == (None if isinstance(product_id, str) else quote)
    if isinstance(product_id, str):
        assert response.json()['data']['comparison_reason'] == 'selection_context_missing'
    with sqlite3.connect(account_db.path) as connection:
        for table in ('cart_items', 'wishlist_items'):
            saved = connection.execute(f'SELECT product_id,typeof(product_id) FROM {table}').fetchone()
            assert saved == (product_id, 'text' if isinstance(product_id, str) else 'integer')


def test_account_unknown_catalog_price_rejects_zero_cart_but_preserves_unlinked_manual_free(client, account_db):
    account_db.get_product_detail = lambda value: {
        'id': value, 'public_product_id': value, 'price': 0, 'best_offer': None,
        'variants': [{'listings': [{'offers': [{'listed_price': 0, 'price_state': 'price_hidden'}]}]}],
    }
    _user, headers = _identity(account_db, 'unknown-price@example.invalid', 'unknown-price')
    response = client.post('/api/cart', headers=headers, json={
        'product_id': 'prod-unknown', 'item_name': '가격 미확인', 'item_price': 0,
    })
    assert response.status_code == 422
    assert '표시 가격이 확인되지 않아' in response.json()['detail']
    response = client.post('/api/cart', headers=headers, json={'item_name': '수동 무료 상품', 'item_price': 0})
    assert response.status_code == 200
    assert response.json()['data']['product_id'] is None
    assert response.json()['data']['item_price'] == 0
    response = client.post('/api/wishlist', headers=headers, json={
        'product_id': 'prod-unknown', 'item_name': '가격 미확인', 'current_price': 123,
    })
    assert response.status_code == 200
    assert response.json()['data']['current_price'] is None


def test_selected_cart_retains_exact_quote_spec_conditions_and_separate_offer_identity(client, account_db):
    product = {
        'id': 'prod-selected', 'public_product_id': 'prod-selected', 'unit': '100g',
        'best_offer': {'id': 'offer-a', 'comparable_price': 1000},
        'variants': [
            {'id': 'variant-a', 'name': '100g', 'display_unit': '100g', 'listings': [
                {'id': 'listing-a', 'source': '같은 마트', 'title': '100g 원문', 'url': 'https://example.invalid/a',
                 'offers': [{'id': 'offer-a', 'listed_price': 1000, 'total_price': 1000}]},
            ]},
            {'id': 'variant-b', 'name': '200g', 'display_unit': '200g', 'package_quantity': 200,
             'package_unit': 'g', 'bundle_count': 1, 'listings': [
                {'id': 'listing-b', 'source': '같은 마트', 'title': '200g 원문', 'url': 'https://example.invalid/b',
                 'offers': [
                     {'id': 'offer-b', 'listed_price': 1500, 'total_price': 3000, 'comparable_price': 3000,
                      'total_quantity': 600, 'quantity_unit': 'g', 'received_package_count': 3,
                      'minimum_quantity': 2, 'membership_required': True, 'coupon_required': False,
                      'promotion_conditions': {'buy_quantity': 2, 'free_quantity': 1},
                      'promotion_condition': '회원 2+1', 'current_eligible': True,
                      'quantity_comparison_reason': 'heterogeneous_contents_allocation_unverified',
                      'quantity_basis': 'reviewed_source_component_vector_v1',
                      'scalar_basis': 'one_complete_declared_vector_not_piece_count',
                      'received_package_count_scope': 'complete_declared_vector'},
                     {'id': 'offer-old-b', 'listed_price': 4000, 'total_price': 4000, 'comparable_price': 4000,
                      'current_eligible': False},
                 ]},
            ]},
        ],
    }
    account_db.get_product_detail = lambda value: product if value == 'prod-selected' else None
    _user, headers = _identity(account_db, 'selected-cart@example.invalid', 'selected-cart')
    payload = {'product_id': 'prod-selected', 'variant_id': 'variant-b', 'listing_id': 'listing-b',
               'offer_id': 'offer-b', 'item_name': '선택 규격', 'item_price': 3000, 'quantity': 1,
               'store_name': '조작한 판매처', 'source_url': 'https://example.invalid/wrong'}
    response = client.post('/api/cart', headers=headers, json=payload)
    assert response.status_code == 200, response.text
    saved = response.json()['data']
    assert (saved['variant_id'], saved['listing_id'], saved['offer_id']) == ('variant-b', 'listing-b', 'offer-b')
    assert saved['item_price'] == 3000 and saved['quantity'] == 1  # One priced 2+1 transaction.
    assert saved['unit'] == '200g'
    assert saved['store_name'] == '같은 마트' and saved['source_url'] == 'https://example.invalid/b'
    context = saved['offer_context']
    assert context['total_quantity'] == 600 and context['received_package_count'] == 3
    assert context['minimum_quantity'] == 2 and context['promotion_conditions'] == {'buy_quantity': 2, 'free_quantity': 1}
    assert context['membership_required'] is True and context['coupon_required'] is False
    assert context['source_title'] == '200g 원문'
    assert context['quantity_comparison_reason'] == 'heterogeneous_contents_allocation_unverified'
    assert context['received_package_count_scope'] == 'complete_declared_vector'
    assert context['quantity_basis'] == 'reviewed_source_component_vector_v1'
    assert context['scalar_basis'] == 'one_complete_declared_vector_not_piece_count'
    same = client.post('/api/cart', headers=headers, json=payload).json()['data']
    assert same['cart_id'] == saved['cart_id'] and same['quantity'] == 2
    for selection in (
        {'variant_id': 'variant-a', 'listing_id': 'listing-a', 'offer_id': 'offer-a', 'item_price': 1000},
        {'offer_id': 'offer-old-b', 'item_price': 4000},
    ):
        response = client.post('/api/cart', headers=headers, json={**payload, **selection})
        assert response.status_code == 200, response.text
        assert response.json()['data']['cart_id'] != saved['cart_id']
    reloaded = client.get('/api/cart', headers=headers).json()['data']
    assert len(reloaded) == 3
    assert next(row for row in reloaded if row['offer_id'] == 'offer-b')['offer_context'] == context

    # A watch follows this exact variant/listing across price events, never the
    # product's cheaper best offer. Conditions and received quantity stay bound.
    offer = product['variants'][1]['listings'][0]['offers'][0]
    # The preceding canonical context exercise intentionally held comparison;
    # this existing watch case now uses its proven homogeneous count receipt.
    for field in ('quantity_comparison_reason', 'quantity_basis', 'scalar_basis', 'received_package_count_scope'):
        offer.pop(field)
    offer.update(is_latest=True, offer_state='active', promotion_type='buy_x_get_y',
                 membership_required=False, promotion_condition='2+1',
                 promotion_conditions={'buy_quantity': 2, 'free_quantity': 1, 'minimum_quantity': 2,
                                       'condition_text': '2+1'})
    wish_payload = {key: payload[key] for key in ('product_id', 'variant_id', 'listing_id', 'offer_id', 'item_name')}
    wish_payload['price_at_add'] = 3000
    wish = client.post('/api/wishlist', headers=headers, json=wish_payload).json()['data']
    assert wish['current_price'] == 3000 and wish['price_at_add'] == 3000
    assert wish['offer_context']['total_quantity'] == 600
    assert wish['source_url'] == 'https://example.invalid/b' and wish['variant_id'] == 'variant-b'
    offer.update(id='offer-new-b', listed_price=1200, total_price=2400, comparable_price=2400)
    watch = client.get('/api/wishlist', headers=headers).json()['data'][0]
    assert watch['id'] == wish['id'] and watch['offer_id'] == 'offer-b'
    assert watch['current_offer_id'] == 'offer-new-b'
    assert watch['current_price'] == 2400 and watch['price_at_add'] == 3000
    again = client.post('/api/wishlist', headers=headers, json={**wish_payload, 'offer_id': 'offer-new-b',
                                                             'price_at_add': 2400}).json()['data']
    assert again['id'] == wish['id']
    offer['total_quantity'] = 200
    held = client.get('/api/wishlist', headers=headers).json()['data'][0]
    assert held['current_price'] is None and held['comparison_reason'] == 'receipt_conditions_changed'
    invalid = client.post('/api/wishlist', headers=headers, json={**wish_payload, 'listing_id': 'listing-a'})
    assert invalid.status_code == 422
    # A derived specification correction must not rewrite saved selections or
    # continue endorsing their obsolete received quantities/unit prices.
    product['variants'][1].update(id='variant-corrected', package_quantity=2, package_unit='개')
    old_cart = next(item for item in client.get('/api/cart', headers=headers).json()['data']
                    if item['cart_id'] == saved['cart_id'])
    assert old_cart['saved_receipt_valid'] is False
    assert old_cart['saved_receipt_reason'] == 'selected_specification_revised'
    assert old_cart['variant_id'] == 'variant-b' and old_cart['offer_id'] == 'offer-b'
    assert old_cart['item_price'] == 3000 and old_cart['offer_context'] == context
    old_wish = client.get('/api/wishlist', headers=headers).json()['data'][0]
    assert old_wish['saved_receipt_valid'] is False and old_wish['current_price'] is None
    assert old_wish['variant_id'] == 'variant-b' and old_wish['price_at_add'] == 2400


def test_selected_cart_rejects_cross_context_missing_money_and_unproven_zero(client, account_db):
    product = {'id': 'prod-held-selection', 'public_product_id': 'prod-held-selection', 'best_offer': None,
               'variants': [{'id': 'variant-held', 'name': '규격 미확인', 'listings': [
                   {'id': 'listing-held', 'source': '검증 마트', 'title': '원문', 'url': 'https://example.invalid/held',
                    'offers': [{'id': 'offer-held', 'listed_price': 9000, 'total_price': 9000,
                                'comparable_price': None, 'current_eligible': False},
                               {'id': 'offer-unknown', 'listed_price': None, 'total_price': None},
                               {'id': 'offer-listed-only', 'listed_price': 9000, 'total_price': None},
                               {'id': 'offer-zero', 'listed_price': 0, 'total_price': 0, 'price_state': 'price_hidden'}]},
               ]}]}
    account_db.get_product_detail = lambda _value: product
    _user, headers = _identity(account_db, 'held-selection@example.invalid', 'held-selection')
    payload = {'product_id': 'prod-held-selection', 'variant_id': 'variant-held', 'listing_id': 'listing-held',
               'offer_id': 'offer-held', 'item_name': '근거 있는 표시 가격', 'item_price': 9000}
    for change, expected in (
        ({'variant_id': None}, 422), ({'listing_id': 'other-listing'}, 422),
        ({'offer_id': 'other-offer'}, 422), ({'offer_id': 'offer-unknown', 'item_price': 0}, 422),
        ({'offer_id': 'offer-listed-only'}, 422),
        ({'offer_id': 'offer-zero', 'item_price': 0}, 422),
        ({'item_price': 0}, 409), ({'item_price': 8999}, 409),
    ):
        response = client.post('/api/cart', headers=headers, json={**payload, **change})
        assert response.status_code == expected, response.text
    assert client.get('/api/cart', headers=headers).json()['data'] == []
    response = client.post('/api/cart', headers=headers, json=payload)
    assert response.status_code == 200
    saved = response.json()['data']
    assert saved['item_price'] == 9000
    assert saved['offer_context']['comparable_price'] is None
    assert saved['offer_context']['current_eligible'] is False


def test_cart_merge_receipt_is_persistent_per_user_and_returns_current_canonical_cart(client, account_db):
    _user, headers = _identity(account_db, 'merge-retry@example.invalid', 'merge-retry')
    _other, other_headers = _identity(account_db, 'merge-other@example.invalid', 'merge-other')
    batch = {'merge_id': 'stable-guest-batch', 'items': [
        {'item_name': '수동 상품', 'item_price': 1500, 'quantity': 2},
    ]}
    first = client.post('/api/cart/merge', headers=headers, json=batch)
    assert first.status_code == 200, first.text
    saved = first.json()['data'][0]
    assert saved['id'] == saved['cart_id'] and saved['quantity'] == 2
    client.put('/api/cart/' + str(saved['cart_id']), headers=headers, json={'quantity': 5})
    # A new request/store instance reads the committed receipt. The response is
    # the current canonical cart, not a stale cached merge response.
    repeat = client.post('/api/cart/merge', headers=headers, json=batch)
    assert repeat.status_code == 200 and repeat.json()['data'][0]['quantity'] == 5
    changed = {**batch, 'items': [{**batch['items'][0], 'quantity': 3}]}
    assert client.post('/api/cart/merge', headers=headers, json=changed).status_code == 409
    assert client.get('/api/cart', headers=headers).json()['data'][0]['quantity'] == 5
    other = client.post('/api/cart/merge', headers=other_headers, json=batch)
    assert other.status_code == 200 and other.json()['data'][0]['quantity'] == 2
    # Old clients without a merge ID retain their explicitly additive behavior.
    legacy = client.post('/api/cart/merge', headers=headers, json={'items': batch['items']})
    assert legacy.status_code == 200 and legacy.json()['data'][0]['quantity'] == 7


def test_cart_merge_rolls_back_receipt_and_items_together_on_invalid_selected_quote(client, account_db):
    account_db.get_product_detail = lambda value: {
        'id': value, 'public_product_id': value, 'price': None, 'best_offer': None,
    }
    _user, headers = _identity(account_db, 'merge-atomic@example.invalid', 'merge-atomic')
    manual = {'item_name': '수동 상품', 'item_price': 1500, 'quantity': 2}
    bad = {'product_id': 'unknown', 'item_name': '가격 미확인', 'item_price': 0}
    batch = {'merge_id': 'rolled-back-batch', 'items': [manual, bad]}
    assert client.post('/api/cart/merge', headers=headers, json=batch).status_code == 422
    assert client.get('/api/cart', headers=headers).json()['data'] == []
    # The failed batch never acquired a committed receipt, so a corrected
    # request may use the same ID without an artificial conflict.
    result = client.post('/api/cart/merge', headers=headers, json={**batch, 'items': [manual]})
    assert result.status_code == 200 and result.json()['data'][0]['quantity'] == 2


def test_concurrent_cart_merge_retry_commits_selected_tuples_exactly_once(account_db):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from services.account_feature_storage import AccountFeatureStore

    user, _headers = _identity(account_db, 'merge-race@example.invalid', 'merge-race')
    account_db.get_product_detail = lambda value: {
        'id': value, 'public_product_id': value, 'variants': [
            {'id': 'variant', 'display_unit': '200g', 'listings': [
                {'id': 'listing-a', 'source': '마트', 'url': 'https://example.invalid/a',
                 'offers': [{'id': 'offer-a', 'total_price': 2000}]},
                {'id': 'listing-b', 'source': '마트', 'url': 'https://example.invalid/b',
                 'offers': [{'id': 'offer-b', 'total_price': 3000}]},
            ]},
        ],
    }
    items = [
        {'product_id': 'product', 'variant_id': 'variant', 'listing_id': listing, 'offer_id': offer,
         'item_name': '같은 규격', 'item_price': price, 'quantity': 2}
        for listing, offer, price in [('listing-a', 'offer-a', 2000), ('listing-b', 'offer-b', 3000)]
    ]
    barrier = Barrier(2)
    def merge():
        barrier.wait(timeout=5)
        return AccountFeatureStore(account_db).merge_cart(user['id'], items, merge_id='concurrent-batch')
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: merge(), range(2)))
    assert all(len(rows) == 2 for rows in results)
    rows = AccountFeatureStore(account_db).list_cart(user['id'])
    assert {(row['listing_id'], row['offer_id'], row['quantity']) for row in rows} == {
        ('listing-a', 'offer-a', 2), ('listing-b', 'offer-b', 2),
    }


def test_health_uses_injected_storage_without_repository_db(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": "0.1.0",
        "catalog": "injected",
        "accounts": "ok",
        "external_hotdeals": "injected",
    }


def _opinet_snapshot(path: Path, marker: str) -> bytes:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            "CREATE TABLE fuel_stations (id TEXT PRIMARY KEY, name TEXT);"
            "CREATE TABLE fuel_prices (station_id TEXT, fuel_type TEXT, price REAL);"
            "CREATE TABLE marker (value TEXT);"
        )
        connection.execute("INSERT INTO marker VALUES (?)", (marker,))
        connection.commit()
    return path.read_bytes()


def test_remote_snapshot_upload_is_authenticated_and_rollbackable(
    client, tmp_path, monkeypatch
):
    target = tmp_path / "deployed-opinet.sqlite"
    monkeypatch.setenv("OPINET_DB_PATH", str(target))
    monkeypatch.setenv("WALLETSAVIOR_REMOTE_ADMIN_TOKEN", "snapshot-test-token")
    headers = {
        "X-WalletSavior-Admin-Token": "snapshot-test-token",
        "Content-Type": "application/octet-stream",
    }

    first = _opinet_snapshot(tmp_path / "first.sqlite", "first")
    assert client.put(
        "/api/admin/remote/snapshots/opinet", content=first, headers=headers
    ).status_code == 200
    second = _opinet_snapshot(tmp_path / "second.sqlite", "second")
    assert client.put(
        "/api/admin/remote/snapshots/opinet", content=second, headers=headers
    ).status_code == 200

    denied = client.post("/api/admin/remote/snapshots/opinet/rollback")
    assert denied.status_code == 401
    rolled_back = client.post(
        "/api/admin/remote/snapshots/opinet/rollback", headers=headers
    )
    assert rolled_back.status_code == 200
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT value FROM marker").fetchone()[0] == "first"


def test_community_database_is_physically_separate(isolated_board, client):
    response = client.get("/api/posts")
    assert response.status_code == 200
    assert isolated_board.is_file()

    with sqlite3.connect(isolated_board) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

    assert {
        "community_users",
        "community_posts",
        "community_comments",
        "community_votes",
    }.issubset(tables)
    # Product/catalog tables belong to the replaceable catalog snapshot, never the board file.
    assert "products" not in tables
    assert "matching_entries" not in tables
    assert "pending_ingestions" not in tables


def test_empty_board_is_readable_from_isolated_database(client):
    response = client.get("/api/posts")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"] == []
    assert body["meta"]["total"] == 0


def _seed_community_posts(*specs):
    """Seed only the temporary board with ranked posts and synthetic voters."""
    from datetime import datetime
    from services import board_storage as board

    with board.get_board_session_factory()() as session:
        voters = max((spec.get("hot", 0) + spec.get("not_", 0) for spec in specs), default=1)
        session.add_all([
            board.User(id=user_id, email=f"board-{user_id}@example.invalid", nickname=f"board-{user_id}")
            for user_id in range(1, max(voters, 1) + 1)
        ])
        session.flush()
        for post_id, spec in enumerate(specs, 1):
            session.add(board.Post(
                id=post_id, author_id=1, post_type=board.PostType(spec.get("post_type", "hotdeal")),
                title=spec.get("title", f"게시글 {post_id}"), content=spec.get("content", "본문"),
                custom_category=spec.get("category", "food"), category_id=spec.get("category_id"),
                view_count=spec.get("views", 0), is_deleted=spec.get("deleted", False),
                created_at=spec.get("created_at", datetime(2026, 10, 3)),
            ))
            session.flush()
            hot, not_ = spec.get("hot", 0), spec.get("not_", 0)
            session.add_all([
                board.Vote(post_id=post_id, user_id=user_id,
                           vote_type=board.VoteType.HOT if user_id <= hot else board.VoteType.NOT)
                for user_id in range(1, hot + not_ + 1)
            ])
            session.add_all([
                board.Comment(post_id=post_id, author_id=1, content="합성 댓글", is_deleted=deleted)
                for deleted in [False] * spec.get("comments", 0) + [True] * spec.get("deleted_comments", 0)
            ])
        session.commit()


def test_community_partition_filters_raw_hot_candidates_before_main_pagination(client):
    _seed_community_posts(
        {"hot": 2}, {"hot": 2}, {"hot": 2}, {"hot": 1, "not_": 4},
        {}, {"not_": 1}, {"hot": 8, "category": "other"},
        {"hot": 8, "deleted": True}, {"hot": 8, "post_type": "free"},
    )
    params = {"post_type": "hotdeal", "category": "food", "partition_pinned": True, "per_page": 2}
    first = client.get("/api/posts", params={**params, "page": 1}).json()
    second = client.get("/api/posts", params={**params, "page": 2}).json()
    outside = client.get("/api/posts", params={**params, "page": 3}).json()
    assert [post["id"] for post in first["pinned_posts"]] == [3, 2, 1]
    assert first["pinned_posts"] == second["pinned_posts"] == outside["pinned_posts"]
    assert [post["id"] for post in first["data"]] == [6, 5]
    assert [post["id"] for post in second["data"]] == [4]
    assert outside["data"] == []
    assert first["meta"] == {"page": 1, "per_page": 2, "total": 3, "total_pages": 2}
    assert outside["meta"] == {"page": 3, "per_page": 2, "total": 3, "total_pages": 2}
    negative = client.get("/api/posts", params={**params, "q": "게시글 4"}).json()
    assert negative["pinned_posts"] == [] and negative["meta"]["total"] == 1
    # Raw HOT presence is sufficient even when net votes are negative; NOT-only
    # and unvoted rows are never promoted when fewer than three candidates exist.
    with_negative = client.get("/api/posts", params={**params, "category": "other"}).json()
    assert [post["id"] for post in with_negative["pinned_posts"]] == [7]
    from services import board_storage as board
    with board.get_board_session_factory()() as session:
        for post_id in (1, 2, 3):
            session.get(board.Post, post_id).is_deleted = True
        session.commit()
    reduced = client.get("/api/posts", params=params).json()
    assert [post["id"] for post in reduced["pinned_posts"]] == [4]
    assert reduced["meta"]["total"] == 2


@pytest.mark.parametrize("q,expected", [(" MiXeD ", [1]), ("%", [1]), ("_", [1]), ("/", [1]), ("\\", [1]), ("없는검색", [])])
def test_community_search_is_literal_title_or_content_and_disables_pins(client, q, expected):
    _seed_community_posts(
        {"title": "title%_ /\\", "content": "Mixed 본문", "hot": 1},
        {"title": "titleAB", "content": "plain"},
        {"title": "title%_ /\\", "content": "Mixed 본문", "category": "other"},
        {"title": "title%_ /\\", "content": "Mixed 본문", "post_type": "free"},
        {"title": "title%_ /\\", "content": "Mixed 본문", "deleted": True},
    )
    result = client.get("/api/posts", params={
        "post_type": "hotdeal", "category": "food", "q": q, "partition_pinned": True,
    }).json()
    assert [post["id"] for post in result["data"]] == expected
    assert result["pinned_posts"] == []
    assert result["meta"]["total"] == len(expected)


def test_community_sort_semantics_and_default_unpartitioned_response(client):
    from datetime import datetime
    _seed_community_posts(
        {"hot": 2, "not_": 3, "views": 100, "comments": 1, "deleted_comments": 8},
        {"hot": 1, "views": 2, "comments": 2},
        {"hot": 1, "views": 1, "comments": 2},
        {"hot": 1, "created_at": datetime(2026, 10, 2)},
        {"post_type": "free", "views": 10},
        {"post_type": "free", "views": 100, "category_id": "tag"},
        {"post_type": "free", "views": 100},
    )
    popular = client.get("/api/posts", params={"post_type": "hotdeal", "sort": "popular"}).json()
    assert [post["id"] for post in popular["data"]] == [3, 2, 4, 1]
    assert popular["pinned_posts"] == [] and popular["meta"]["total"] == 4
    recent = client.get("/api/posts", params={"post_type": "hotdeal", "q": "  "}).json()
    assert [post["id"] for post in recent["data"]] == [3, 2, 1, 4]
    blank_partition = client.get("/api/posts", params={
        "post_type": "hotdeal", "q": "  ", "partition_pinned": True,
    }).json()
    assert [post["id"] for post in blank_partition["pinned_posts"]] == [3, 2, 4]
    assert [post["id"] for post in blank_partition["data"]] == [1]
    comments = client.get("/api/posts", params={"post_type": "hotdeal", "sort": "comments"}).json()
    assert [post["id"] for post in comments["data"]] == [3, 2, 1, 4]
    assert comments["data"][2]["comments_count"] == 1
    free = client.get("/api/posts", params={
        "post_type": "free", "sort": "popular", "partition_pinned": True,
    }).json()
    assert [post["id"] for post in free["data"]] == [7, 6, 5] and free["pinned_posts"] == []
    tag = client.get("/api/posts", params={"post_type": "free", "category": "tag"}).json()
    assert [post["id"] for post in tag["data"]] == [6]


def test_community_partition_count_and_rows_share_snapshot_during_concurrent_write(client, isolated_board):
    from sqlalchemy import event
    from services import board_storage as board
    _seed_community_posts({"hot": 1}, {})
    engine = board.get_board_engine()
    writes = []

    def after_count(_connection, _cursor, statement, _parameters, _context, _executemany):
        if writes or not statement.lstrip().startswith("SELECT count("):
            return
        # The WAL writer commits between the list's count and page SELECT.
        with sqlite3.connect(isolated_board) as writer:
            writer.execute("UPDATE community_posts SET is_deleted=1 WHERE id=2")
            for post_id in (3, 4):
                writer.execute(
                    "INSERT INTO community_posts (id,author_id,post_type,title,content,view_count,is_deleted,created_at,updated_at) "
                    "VALUES (?,1,'hotdeal','new','new',0,0,'2026-10-03','2026-10-03')", (post_id,),
                )
        writes.append(True)

    event.listen(engine, "after_cursor_execute", after_count)
    try:
        result = client.get("/api/posts", params={"post_type": "hotdeal", "partition_pinned": True}).json()
    finally:
        event.remove(engine, "after_cursor_execute", after_count)
    assert writes == [True]
    assert [post["id"] for post in result["pinned_posts"]] == [1]
    assert [post["id"] for post in result["data"]] == [2]
    assert result["meta"]["total"] == 1
    subsequent = client.get("/api/posts", params={"post_type": "hotdeal", "partition_pinned": True}).json()
    assert [post["id"] for post in subsequent["data"]] == [4, 3]
    assert subsequent["meta"]["total"] == 2


@pytest.mark.parametrize('viewer,expected', [
    ('hot_owner', 'hot'), ('not_owner', 'not'), ('no_vote', None),
    ('anonymous', None), ('invalid_access', None),
])
def test_community_cold_reads_restore_only_authenticated_subject_vote(client, account_db, viewer, expected):
    _, hot_headers = _identity(account_db, 'hot-owner@example.invalid', '찬성')
    _, not_headers = _identity(account_db, 'not-owner@example.invalid', '반대')
    _, no_vote_headers = _identity(account_db, 'no-vote@example.invalid', '미투표')
    created = client.post('/api/posts', headers=hot_headers, json={
        'title': '현재 사용자 선택만 복원', 'content': '총 투표는 사용자 선택이 아니다',
        'post_type': 'hotdeal', 'category': 'test',
    })
    assert created.status_code == 200
    post_id = created.json()['data']['id']
    assert created.json()['data']['user_vote'] is None
    assert client.post(f'/api/posts/{post_id}/vote', headers=hot_headers,
                       json={'vote_type': 'hot'}).status_code == 200
    assert client.post(f'/api/posts/{post_id}/vote', headers=not_headers,
                       json={'vote_type': 'not'}).status_code == 200
    headers = {'hot_owner': hot_headers, 'not_owner': not_headers, 'no_vote': no_vote_headers,
               'anonymous': {}, 'invalid_access': {'Authorization': 'Bearer invalid-test-token'}}[viewer]
    detail = client.get(f'/api/posts/{post_id}', headers=headers)
    listing = client.get('/api/posts', headers=headers, params={'post_type': 'hotdeal'})
    partitioned = client.get('/api/posts', headers=headers,
                             params={'post_type': 'hotdeal', 'partition_pinned': True})
    assert detail.status_code == listing.status_code == partitioned.status_code == 200
    assert partitioned.json()['data'] == [] and partitioned.json()['meta']['total'] == 0
    for post in (detail.json()['data'], listing.json()['data'][0], partitioned.json()['pinned_posts'][0]):
        assert post['id'] == post_id and post['user_vote'] == expected
        assert post['hot_votes'] == post['not_votes'] == 1
    # A user-supplied subject parameter cannot impersonate another account.
    anonymous = client.get(f'/api/posts/{post_id}', params={'user_id': 1, 'user_vote': 'hot'})
    assert anonymous.json()['data']['user_vote'] is None


def test_authenticated_community_crud_comment_and_vote_flow(client, account_db):
    user, headers = _identity(account_db, "community@example.com", "커뮤니티유저")

    created = client.post(
        "/api/posts",
        json={
            "title": "격리 게시판 테스트",
            "content": "board.sqlite에만 저장되어야 합니다.",
            "post_type": "free",
            "category": "test",
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    post = created.json()["data"]
    post_id = post["id"]
    assert post["author_id"] == user["id"]

    first_get = client.get(f"/api/posts/{post_id}")
    second_get = client.get(f"/api/posts/{post_id}")
    assert first_get.status_code == 200
    assert second_get.json()["data"]["views"] == first_get.json()["data"]["views"] + 1

    updated = client.put(
        f"/api/posts/{post_id}",
        json={"title": "수정된 격리 게시판 테스트"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["title"] == "수정된 격리 게시판 테스트"

    comment = client.post(
        f"/api/posts/{post_id}/comments",
        json={"content": "댓글도 board DB에 저장"},
        headers=headers,
    )
    assert comment.status_code == 200
    assert comment.json()["data"]["author_id"] == user["id"]

    voted = client.post(
        f"/api/posts/{post_id}/vote",
        json={"vote_type": "hot"},
        headers=headers,
    )
    assert voted.status_code == 200
    assert voted.json()["data"]["user_vote"] == "hot"
    assert voted.json()["data"]["hot_votes"] == 1
    assert client.get(f"/api/posts/{post_id}", headers=headers).json()["data"]["user_vote"] == "hot"

    toggled = client.post(
        f"/api/posts/{post_id}/vote",
        json={"vote_type": "hot"},
        headers=headers,
    )
    assert toggled.status_code == 200
    assert toggled.json()["data"]["user_vote"] is None
    assert toggled.json()["data"]["hot_votes"] == 0
    assert client.get(f"/api/posts/{post_id}", headers=headers).json()["data"]["user_vote"] is None

    deleted = client.delete(f"/api/posts/{post_id}", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()["data"]["status"] == "deleted"
    assert client.get(f"/api/posts/{post_id}").status_code == 404


def test_other_user_cannot_modify_or_delete_post(client, account_db):
    _, owner_headers = _identity(account_db, "owner@example.com", "글쓴이")
    _, other_headers = _identity(account_db, "other@example.com", "다른유저")

    created = client.post(
        "/api/posts",
        json={"title": "권한 테스트", "content": "owner only", "post_type": "free"},
        headers=owner_headers,
    )
    assert created.status_code == 200
    post_id = created.json()["data"]["id"]

    update = client.put(
        f"/api/posts/{post_id}",
        json={"title": "남의 글 수정"},
        headers=other_headers,
    )
    delete = client.delete(f"/api/posts/{post_id}", headers=other_headers)

    assert update.status_code == 403
    assert delete.status_code == 403


def test_comment_and_vote_require_authentication(client):
    post_id = 1
    assert client.post(
        f"/api/posts/{post_id}/comments",
        json={"content": "anonymous"},
    ).status_code == 401
    assert client.post(
        f"/api/posts/{post_id}/vote",
        json={"vote_type": "hot"},
    ).status_code == 401


def test_mart_sql_read_does_not_block_health_and_preserves_lotte_alias(client, account_db):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    entered, release = Event(), Event()
    sources = []

    def read_mart(store=None):
        sources.append(store)
        entered.set()
        assert release.wait(2), "test cleanup must release the synthetic SQL read"
        return {store: {"name": "합성 마트", "items": [{"sale": 1000}], "last_crawled_at": "2026-10-03"}}

    account_db.get_mart_deals = read_mart
    with ThreadPoolExecutor(max_workers=2) as pool:
        mart = pool.submit(client.get, "/api/marts/lotte/promotions")
        assert entered.wait(1)
        health = pool.submit(client.get, "/api/health")
        try:
            assert health.result(timeout=1).status_code == 200
        finally:
            release.set()
        assert mart.result(timeout=1).json()["data"]["items"] == [{"sale": 1000}]
    assert sources == ["lottemart"]
    marts = client.get("/api/marts").json()["data"]
    assert [mart["key"] for mart in marts] == ["emart", "homeplus", "lotte", "costco"]
    assert all(mart["deals_count"] == 1 for mart in marts)


def test_dashboard_recent_observations_keep_active_order_without_per_product_scan():
    from contextlib import contextmanager
    from types import SimpleNamespace
    from api.app import _recent_dashboard_products
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE normalized_canonical_products(public_product_id TEXT PRIMARY KEY, is_active INTEGER);
        CREATE TABLE normalized_product_variants(public_variant_id TEXT PRIMARY KEY, public_product_id TEXT, is_active INTEGER);
        CREATE TABLE normalized_source_listings(public_source_listing_id TEXT PRIMARY KEY, public_variant_id TEXT, is_active INTEGER);
        CREATE TABLE normalized_offer_events(public_offer_event_id TEXT PRIMARY KEY, public_source_listing_id TEXT, offer_state TEXT, crawled_at TEXT);
        CREATE INDEX ix_norm_offer_state ON normalized_offer_events(offer_state);
    """)
    for i in range(400):
        key = f"p{i:03}"
        db.execute("INSERT INTO normalized_canonical_products VALUES (?,1)", (key,))
        db.execute("INSERT INTO normalized_product_variants VALUES (?,?,1)", (key,key))
        db.execute("INSERT INTO normalized_source_listings VALUES (?,?,1)", (key,key))
        db.execute("INSERT INTO normalized_offer_events VALUES (?,?,'active','2026-01-01')", (key,key))
    db.execute("UPDATE normalized_offer_events SET crawled_at='2026-02-01' WHERE public_offer_event_id IN ('p398','p399')")
    # Newer held observations/inactive graph nodes must not win recency.
    db.execute("INSERT INTO normalized_offer_events VALUES ('held','p000','pending_review','2030-01-01')")
    db.execute("INSERT INTO normalized_product_variants VALUES ('inactive-v','p001',0)")
    db.execute("INSERT INTO normalized_source_listings VALUES ('inactive-v','inactive-v',1)")
    db.execute("INSERT INTO normalized_offer_events VALUES ('inactive-v','inactive-v','active','2030-01-01')")
    db.execute("INSERT INTO normalized_source_listings VALUES ('inactive-l','p002',0)")
    db.execute("INSERT INTO normalized_offer_events VALUES ('inactive-l','inactive-l','active','2030-01-01')")
    db.execute("UPDATE normalized_canonical_products SET is_active=0 WHERE public_product_id='p397'")
    db.execute("INSERT INTO normalized_canonical_products VALUES ('empty',1)")
    ticks = 0
    def bounded_work():
        nonlocal ticks
        ticks += 1
        return ticks > 200  # Fail quadratic scans, independent of wall-clock speed.
    db.set_progress_handler(bounded_work, 1000)
    @contextmanager
    def connection():
        yield db
    catalog = SimpleNamespace(connection=connection,
        _table=lambda conn, name: True,
        _normalized_product=lambda conn, row, include_all: {'id':row['public_product_id']})
    try:
        result = _recent_dashboard_products(SimpleNamespace(catalog=catalog), limit=3)
        assert [row['id'] for row in result] == ['p399','p398','p396']
        assert result[0]['observed_at'] == '2026-02-01'
        result = _recent_dashboard_products(SimpleNamespace(catalog=catalog), limit=405)
        assert len(result) == 400 and result[-1] == {'id':'empty','observed_at':''}
    finally:
        db.close()
