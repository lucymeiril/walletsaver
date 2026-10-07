"""Remote snapshot validation must not publish offers awaiting review."""
from __future__ import annotations

import asyncio
import json
import multiprocessing
import sqlite3
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

BACKEND_ROOT = Path(__file__).parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from api.routes import admin_remote


def _catalog_snapshot(
    path: Path, offer_states: list[str], *, product_active: bool = False, revision: str = "test-revision"
) -> Path:
    """Create only the schema needed by the read-only validation boundary."""
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            "CREATE TABLE products (id INTEGER PRIMARY KEY);"
            "CREATE TABLE categories (id INTEGER PRIMARY KEY);"
            "CREATE TABLE unified_categories (id TEXT PRIMARY KEY, parent_id TEXT);"
            "CREATE TABLE snapshot_meta (id INTEGER PRIMARY KEY, revision TEXT, built_at TEXT);"
            "CREATE TABLE normalized_canonical_products ("
            "id INTEGER PRIMARY KEY, is_active BOOLEAN NOT NULL, unified_category_id TEXT);"
            "CREATE TABLE normalized_product_variants (id INTEGER PRIMARY KEY);"
            "CREATE TABLE normalized_source_listings (id INTEGER PRIMARY KEY);"
            "CREATE TABLE normalized_offer_events ("
            "id INTEGER PRIMARY KEY, offer_state VARCHAR(40) NOT NULL DEFAULT 'active');"
        )
        connection.execute("INSERT INTO unified_categories VALUES ('leaf', NULL)")
        connection.execute(
            "INSERT INTO normalized_canonical_products VALUES (1, ?, 'leaf')",
            (product_active,),
        )
        connection.execute(
            "INSERT INTO snapshot_meta VALUES (1, ?, '2026-09-03T00:00:00')", (revision,)
        )
        connection.executemany(
            "INSERT INTO normalized_offer_events (offer_state) VALUES (?)",
            [(state,) for state in offer_states],
        )
        connection.commit()
    finally:
        connection.close()
    return path


@pytest.mark.parametrize(
    "offer_states",
    [
        [],
        ["active"],
        # Historical states are strings, not a closed enum or an allowlist.
        ["active", "expired", "withdrawn", "legacy_unknown"],
    ],
)
def test_snapshot_accepts_inactive_products_and_non_pending_states(tmp_path, offer_states):
    snapshot = _catalog_snapshot(tmp_path / "catalog.sqlite", offer_states)
    original_bytes = snapshot.read_bytes()

    validation = admin_remote._validate_sqlite(
        snapshot, admin_remote._SNAPSHOT_CONFIG["catalog"][2]
    )

    assert validation["revision"] == "test-revision"
    assert "normalized_offer_events" in validation["tables"]
    assert snapshot.read_bytes() == original_bytes


@pytest.mark.parametrize("mismatch", [None, "unknown_key", "unapproved_member", "nonreciprocal", "forged_brand"])
def test_snapshot_group_source_compatibility_preserves_existing_install(tmp_path, monkeypatch, mismatch):
    import core.catalog_identity as identity
    # Current code has reviewed a third member, while this historical DB still
    # contains its original two-member family. This is compatible, not a merge.
    review = {"key": "approved-milk", "canonical_product_id": "milk-a",
              "member_product_ids": ["milk-a", "milk-b"], "canonical_name": "우유",
              "brand": "검토브랜드", "review_version": identity.GROUP_VERSION}
    registered = {**review, "member_product_ids": ["milk-a", "milk-b", "milk-c"], "leaf": "leaf"}
    monkeypatch.setattr(identity, "reviewed_registry", lambda: {"groups": [registered]})
    candidate = _catalog_snapshot(tmp_path / "candidate.sqlite", ["active"])
    other = dict(review)
    if mismatch == "unknown_key":
        review["key"] = other["key"] = "new-unshipped-definition"
    elif mismatch == "unapproved_member":
        review["member_product_ids"] = other["member_product_ids"] = ["milk-a", "unreviewed"]
    elif mismatch == "nonreciprocal":
        other["canonical_name"] = "다른 우유"
    elif mismatch == "forged_brand":
        review['brand'] = other['brand'] = '검수되지 않은 브랜드'
    with sqlite3.connect(candidate) as db:
        db.execute("ALTER TABLE normalized_canonical_products ADD COLUMN public_product_id TEXT")
        db.execute("ALTER TABLE normalized_canonical_products ADD COLUMN attributes TEXT")
        db.execute("UPDATE normalized_canonical_products SET public_product_id=?, attributes=?",
                   ("milk-a", json.dumps({"catalog_group": review})))
        db.execute("INSERT INTO normalized_canonical_products VALUES (2,1,'leaf',?,?)",
                   ("milk-b", json.dumps({"catalog_group": other})))
    installed = tmp_path / "installed.sqlite"
    installed.write_bytes(b"original account/catalog data must survive")
    original = installed.read_bytes()
    required = admin_remote._SNAPSHOT_CONFIG["catalog"][2]
    if mismatch:
        with pytest.raises(HTTPException) as error:
            admin_remote._complete_uploaded_snapshot(candidate, installed, required)
        assert error.value.status_code == 422
        assert "catalog_group_source_incompatible" in error.value.detail
        assert "matching reviewed source release" in error.value.detail
        assert installed.read_bytes() == original
    else:
        validation = admin_remote._validate_sqlite(candidate, required)
        assert validation["reviewed_groups_compatible"] == 1
        products = [{"public_product_id": pid, "unified_category_id": "leaf",
                     "attributes": {"catalog_group": review}} for pid in ["milk-a", "milk-b"]]
        assert identity.validated_group_members(products[0], {p["public_product_id"]: p for p in products}.get) == ("milk-a", "milk-b")
        assert installed.read_bytes() == original


@pytest.mark.parametrize('key', [
    'reviewed.frozen_dessert.maeil-sangha-freeze-chocolate',
    'reviewed.frozen_dessert.maeil-sangha-freeze-milk',
])
@pytest.mark.parametrize('boundary', [None, 'unapproved_category', 'mixed_reciprocal_category', 'newer_member'])
def test_snapshot_pinned_historical_group_leaf_is_bound_to_one_definition(monkeypatch, key, boundary):
    from copy import deepcopy
    import core.catalog_identity as identity

    registry = deepcopy(identity.reviewed_registry())
    current = next(row for row in registry['groups'] if row['key'] == key)
    historical = current['historical_definitions'][0]
    assert historical['approved_source_commit'] == '1da1883'
    assert historical['registry_sha256'] == '959190b31ae3dacd349292e43cb7ad893f030d70ae8601309a96e0ccaccd2744'
    review = {field: deepcopy(historical[field]) for field in (
        'key', 'canonical_product_id', 'canonical_name', 'brand', 'review_version', 'member_product_ids')}
    if boundary == 'newer_member':
        # A member approved only for the latest leaf cannot join the old leaf.
        current['member_product_ids'].append('synthetic-current-only-member')
        review['member_product_ids'].append('synthetic-current-only-member')
    products = [{'public_product_id': member, 'unified_category_id': historical['leaf'],
                 'attributes': {'catalog_group': deepcopy(review)}} for member in review['member_product_ids']]
    if boundary == 'unapproved_category':
        for product in products:
            product['unified_category_id'] = 'food.frozen.dessert.unreviewed'
    if boundary == 'mixed_reciprocal_category':
        products[-1]['unified_category_id'] = current['leaf']
    before = deepcopy(products)
    monkeypatch.setattr(identity, 'reviewed_registry', lambda: registry)
    lookup = {product['public_product_id']: product for product in products}.get
    if boundary:
        assert identity.validated_group_members(products[0], lookup) == (products[0]['public_product_id'],)
        with pytest.raises(ValueError, match='catalog_group_source_incompatible'):
            identity.validate_snapshot_groups(products)
    else:
        assert identity.validated_group_members(products[0], lookup) == tuple(review['member_product_ids'])
        assert identity.validate_snapshot_groups(products) == 1
    assert products == before


def _revision(path):
    with sqlite3.connect(f'file:{Path(path).as_posix()}?mode=ro', uri=True) as db:
        return db.execute('SELECT revision FROM snapshot_meta WHERE id=1').fetchone()[0]


def _install_process(target, candidate, started, hold_copy, release_copy, result):
    """A distinct local worker process, touching only supplied temp snapshots."""
    original_copy = admin_remote._snapshot_copy
    if hold_copy is not None:
        def paused_copy(source, destination, role):
            copied = original_copy(source, destination, role)
            if role == 'previous':
                hold_copy.set()
                if not release_copy.wait(10):
                    raise RuntimeError('test copy release timed out')
            return copied
        admin_remote._snapshot_copy = paused_copy
    started.set()
    try:
        if candidate is None:
            import os
            os.environ['WALLETSAVIOR_PUBLIC_DB'] = str(target)
            admin_remote.rollback_snapshot('catalog')
        else:
            admin_remote._install_uploaded_snapshot(Path(candidate), Path(target))
        result.put(('ok', _revision(target)))
    except Exception as exc:
        result.put((type(exc).__name__, str(exc)))


def _hold_snapshot_lock_process(target, locked, release):
    with admin_remote._snapshot_lock(Path(target)):
        locked.set()
        if not release.wait(10):
            raise RuntimeError('test lock release timed out')


@pytest.mark.parametrize('cancel_upload', [False, True])
def test_snapshot_upload_lock_wait_keeps_event_loop_responsive_and_owns_cancelled_candidate(tmp_path, monkeypatch, cancel_upload):
    target = _catalog_snapshot(tmp_path / 'current.sqlite', [], revision='initial')
    payload = _catalog_snapshot(tmp_path / 'candidate.sqlite', [], revision='candidate').read_bytes()
    monkeypatch.setenv('WALLETSAVIOR_PUBLIC_DB', str(target))
    entered = threading.Event()
    candidates = []
    validate = admin_remote._validate_sqlite
    def observe_validation(path, tables):
        candidates.append(path)
        entered.set()
        return validate(path, tables)
    monkeypatch.setattr(admin_remote, '_validate_sqlite', observe_validation)
    context = multiprocessing.get_context('spawn')
    locked, release = context.Event(), context.Event()
    owner = context.Process(target=_hold_snapshot_lock_process, args=(str(target), locked, release))
    async def check_upload():
        async def stream():
            yield payload
        started = asyncio.get_running_loop().time()
        upload = asyncio.create_task(admin_remote.upload_snapshot(SimpleNamespace(stream=stream), 'catalog'))
        try:
            while not entered.is_set():
                await asyncio.sleep(0.005)
                assert asyncio.get_running_loop().time() - started < 1
            # Another task keeps running while the worker polls an OS lock
            # owned by a different process. Completed-upload work stays off this loop.
            for _ in range(5):
                await asyncio.sleep(0.005)
            assert asyncio.get_running_loop().time() - started < 1
            assert not upload.done() and _revision(target) == 'initial'
            candidate = candidates[0]
            assert candidate.is_file()
            if cancel_upload:
                upload.cancel()
                await asyncio.sleep(0.01)
                assert not upload.done() and candidate.is_file()
            release.set()
            if cancel_upload:
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(upload, 2)
            else:
                response = await asyncio.wait_for(upload, 2)
                assert response['validation']['revision'] == 'candidate'
            assert not candidate.exists()
            assert _revision(target) == 'candidate'
            assert _revision(target.with_suffix('.sqlite.previous')) == 'initial'
        finally:
            release.set()
            try:
                await upload
            except (Exception, asyncio.CancelledError):
                pass
    try:
        owner.start()
        assert locked.wait(10)
        asyncio.run(check_upload())
    finally:
        release.set()
        owner.join(5)
        if owner.is_alive():
            owner.terminate()
            owner.join(2)
    assert owner.exitcode == 0


def test_snapshot_install_and_rollback_never_remove_current_from_readers(tmp_path, monkeypatch):
    target = _catalog_snapshot(tmp_path / 'current.sqlite', [], revision='first')
    candidate = _catalog_snapshot(tmp_path / 'candidate.sqlite', [], revision='second')
    monkeypatch.setenv('WALLETSAVIOR_PUBLIC_DB', str(target))
    replace = admin_remote._replace_with_retry
    observed = []
    def checked_replace(source, destination, **kwargs):
        observed.append(_revision(target))
        replace(source, destination, **kwargs)
        observed.append(_revision(target))
    monkeypatch.setattr(admin_remote, '_replace_with_retry', checked_replace)
    with sqlite3.connect(f'file:{target.as_posix()}?mode=ro', uri=True) as old_reader:
        assert old_reader.execute('SELECT revision FROM snapshot_meta').fetchone()[0] == 'first'
        previous = admin_remote._install_uploaded_snapshot(candidate, target)
        assert _revision(target) == 'second' and _revision(previous) == 'first'
        assert old_reader.execute('SELECT revision FROM snapshot_meta').fetchone()[0] == 'first'
    response = admin_remote.rollback_snapshot('catalog')
    assert response['validation']['revision'] == 'first'
    assert _revision(target) == 'first' and _revision(previous) == 'second'
    assert set(observed) == {'first', 'second'}


@pytest.mark.parametrize('failure_phase', ['install', 'publish_previous'])
def test_snapshot_install_failure_preserves_current_and_existing_previous(tmp_path, monkeypatch, failure_phase):
    target = _catalog_snapshot(tmp_path / 'current.sqlite', [], revision='current')
    previous = _catalog_snapshot(target.with_suffix('.sqlite.previous'), [], revision='previous')
    candidate = _catalog_snapshot(tmp_path / 'candidate.sqlite', [], revision='candidate')
    before = (target.read_bytes(), previous.read_bytes())
    replace = admin_remote._replace_with_retry
    def fail_replace(source, destination, **kwargs):
        assert target.is_file()
        if (failure_phase == 'install' and source == candidate) or (
            failure_phase == 'publish_previous' and destination == previous
        ):
            raise OSError('injected snapshot replacement failure')
        replace(source, destination, **kwargs)
        assert target.is_file()
    monkeypatch.setattr(admin_remote, '_replace_with_retry', fail_replace)
    with pytest.raises(OSError, match='injected'):
        admin_remote._install_uploaded_snapshot(candidate, target)
    assert (target.read_bytes(), previous.read_bytes()) == before
    assert not list(tmp_path.glob('current.sqlite.previous-*'))


def test_snapshot_overlapping_upload_streams_use_independent_candidates(tmp_path, monkeypatch):
    target = tmp_path / 'current.sqlite'
    monkeypatch.setenv('WALLETSAVIOR_PUBLIC_DB', str(target))
    payloads = [_catalog_snapshot(tmp_path / (revision + '.sqlite'), [], revision=revision).read_bytes()
                for revision in ('first', 'second')]
    candidates = []
    validate = admin_remote._validate_sqlite
    def record_candidate(path, tables):
        candidates.append(path)
        return validate(path, tables)
    monkeypatch.setattr(admin_remote, '_validate_sqlite', record_candidate)
    async def upload_both():
        barrier = asyncio.Barrier(2)
        def request_for(payload):
            async def stream():
                midpoint = len(payload) // 2
                yield payload[:midpoint]
                await barrier.wait()
                yield payload[midpoint:]
            return SimpleNamespace(stream=stream)
        return await asyncio.gather(*(admin_remote.upload_snapshot(request_for(body), 'catalog') for body in payloads))
    responses = asyncio.run(upload_both())
    assert {response['validation']['revision'] for response in responses} == {'first', 'second'}
    assert len(candidates) == len(set(candidates)) == 2
    assert {_revision(target), _revision(target.with_suffix('.sqlite.previous'))} == {'first', 'second'}
    assert not list(tmp_path.glob('current.sqlite.uploading-*'))


@pytest.mark.parametrize('second_operation', ['upload', 'rollback'])
def test_snapshot_install_serializes_across_worker_processes(tmp_path, second_operation):
    target = _catalog_snapshot(tmp_path / 'current.sqlite', [], revision='initial')
    _catalog_snapshot(target.with_suffix('.sqlite.previous'), [], revision='older')
    first = _catalog_snapshot(tmp_path / 'first.sqlite', [], revision='first')
    second = _catalog_snapshot(tmp_path / 'second.sqlite', [], revision='second')
    context = multiprocessing.get_context('spawn')
    first_started, second_started = context.Event(), context.Event()
    hold_copy, release_copy = context.Event(), context.Event()
    results = context.Queue()
    workers = [
        context.Process(target=_install_process, args=(str(target), str(first), first_started, hold_copy, release_copy, results)),
        context.Process(target=_install_process, args=(str(target), str(second) if second_operation == 'upload' else None,
                                                       second_started, None, None, results)),
    ]
    try:
        workers[0].start()
        assert first_started.wait(10) and hold_copy.wait(10)
        workers[1].start()
        assert second_started.wait(10)
        with pytest.raises(HTTPException) as error:
            with admin_remote._snapshot_lock(target, timeout=0.1):
                pytest.fail('separate process did not hold the target lock')
        assert error.value.status_code == 503
        assert results.empty()
        assert _revision(target) == 'initial'
        release_copy.set()
        for worker in workers:
            worker.join(10)
            assert worker.exitcode == 0
        assert all(results.get(timeout=2)[0] == 'ok' for _ in workers)
        assert _revision(target) == ('second' if second_operation == 'upload' else 'initial')
        assert _revision(target.with_suffix('.sqlite.previous')) == 'first'
    finally:
        release_copy.set()
        for worker in workers:
            if worker.pid is not None:
                worker.join(2)
                if worker.is_alive():
                    worker.terminate()
                    worker.join(2)


@pytest.mark.parametrize("product_active", [False, True])
@pytest.mark.parametrize(
    "offer_states",
    [
        ["pending_review"],
        ["active", "pending_review", "expired", "withdrawn", "pending_review"],
    ],
)
def test_snapshot_rejects_any_pending_review_without_mutating_file(
    tmp_path, product_active, offer_states
):
    snapshot = _catalog_snapshot(
        tmp_path / "catalog.sqlite", offer_states, product_active=product_active
    )
    original_bytes = snapshot.read_bytes()

    with pytest.raises(HTTPException) as error:
        admin_remote._validate_sqlite(
            snapshot, admin_remote._SNAPSHOT_CONFIG["catalog"][2]
        )

    assert error.value.status_code == 422
    assert (
        f"pending_review offers are not publishable: {offer_states.count('pending_review')}"
        in error.value.detail
    )
    assert snapshot.read_bytes() == original_bytes
