"""PendingIngestion API runtime contracts.

The large route implementation remains in :mod:`api.routes.ingestion_core`.
This facade installs narrow current-runtime contracts without duplicating that
file:

1. rows already resolved by crawler MatchingEntry knowledge reuse the trusted
   ``canonical_product_id`` before legacy name fallback;
2. crawler PendingIngestion retries are idempotent. A crawler run id plus client
   chunk index becomes a submission key stored in the existing ``quality_details``
   JSON. A unique expression index protects that key without adding a schema
   column or depending on the repository's fragmented Alembic graph;

At the end of import this module aliases itself to ``ingestion_core`` so existing
imports and monkeypatches keep targeting the same module globals as before.
"""
import sys
from contextvars import ContextVar
from threading import Lock

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError

from . import ingestion_core as _core
from storage.models import PendingIngestion, Product


# ---------------------------------------------------------------------------
# Canonical Product reuse
# ---------------------------------------------------------------------------

_CANONICAL_PRODUCT_ID: ContextVar[int | str | None] = ContextVar(
    "ingestion_canonical_product_id",
    default=None,
)

if not getattr(_core, "_canonical_product_resolution_installed", False):
    _original_ensure_product = _core._ensure_product
    _original_insert_items = _core._insert_items

    def _ensure_product(
        session,
        name: str,
        crawler_source: str | None = None,
        *,
        category_id: str | None = None,
        image_url: str | None = None,
        unit: str | None = None,
        attributes: dict | None = None,
        promo_label: str | None = None,
        promo_type: str | None = None,
    ) -> int:
        """Reuse a trusted canonical Product ID before legacy name lookup."""
        canonical_id = _CANONICAL_PRODUCT_ID.get()
        product = None
        if canonical_id not in (None, ""):
            try:
                canonical_id_int = int(canonical_id)
            except (TypeError, ValueError):
                _core.logger.warning(
                    "_ensure_product: invalid canonical_product_id=%r; falling back to name",
                    canonical_id,
                )
            else:
                with session.no_autoflush:
                    candidate = session.get(Product, canonical_id_int)
                if candidate is not None and candidate.is_active:
                    product = candidate
                elif candidate is not None:
                    _core.logger.warning(
                        "_ensure_product: canonical Product id=%s is inactive; falling back to name",
                        canonical_id_int,
                    )
                else:
                    _core.logger.warning(
                        "_ensure_product: canonical Product id=%s not found; falling back to name",
                        canonical_id_int,
                    )

        if product is None:
            return _original_ensure_product(
                session,
                name,
                crawler_source,
                category_id=category_id,
                image_url=image_url,
                unit=unit,
                attributes=attributes,
                promo_label=promo_label,
                promo_type=promo_type,
            )

        source_type = (
            _core._SOURCE_TYPE_MAP.get(crawler_source, "unknown")
            if crawler_source
            else "unknown"
        )
        if source_type != "unknown" and product.source_type in (None, "", "unknown"):
            product.source_type = source_type
        _core._apply_approved_product_metadata(
            session,
            product,
            category_id=category_id,
            image_url=image_url,
            unit=unit,
            attributes=attributes,
        )
        if promo_label:
            product.promo_label = str(promo_label)
        if promo_type:
            product.promo_type = str(promo_type)
        return product.id

    def _insert_items(session, items: list[dict], schema_type: str) -> int:
        """Set canonical Product context per row, preserving legacy insert semantics."""
        saved = 0
        for item in items:
            canonical_id = (
                item.get("canonical_product_id")
                if schema_type != "HotdealPost"
                else None
            )
            token = _CANONICAL_PRODUCT_ID.set(canonical_id)
            try:
                saved += _original_insert_items(session, [item], schema_type)
            finally:
                _CANONICAL_PRODUCT_ID.reset(token)
        return saved

    _core._ensure_product = _ensure_product
    _core._insert_items = _insert_items
    _core._canonical_product_resolution_installed = True


# ---------------------------------------------------------------------------
# PendingIngestion retry idempotency
# ---------------------------------------------------------------------------

_SUBMISSION_INDEX_NAME = "ux_pending_ingestions_submission_key_json"
_SUBMISSION_INDEX_LOCK = Lock()
_SUBMISSION_INDEX_ENGINES: set[int] = set()


def _submission_base_key(body) -> str | None:
    """Return a client-chunk identity only for explicitly stamped crawler runs."""
    details = body.quality_details or {}
    if not isinstance(details, dict):
        return None

    run_id = str(details.get("ingestion_run_id") or "").strip()
    chunk = details.get("ingestion_chunk") or {}
    if not run_id or len(run_id) > 128 or not isinstance(chunk, dict):
        return None
    try:
        chunk_index = int(chunk.get("index"))
    except (TypeError, ValueError):
        return None
    if chunk_index < 1:
        return None
    return f"{run_id}:chunk:{chunk_index}"


def _server_submission_key(base_key: str | None, server_chunk_index: int, server_chunks: int) -> str | None:
    if base_key is None:
        return None
    if server_chunks <= 1:
        return base_key
    return f"{base_key}:server:{server_chunk_index}"


def _install_submission_index_once() -> None:
    """Install a DB-level unique guard using the existing JSON column.

    Existing rows predate this contract and therefore have no submission key, so
    the partial/expression index is backward compatible. The operation is kept
    out of Alembic because the checked-in migration graph currently has multiple
    independent heads while application startup does not run migrations.
    """
    session = _core.get_session()
    try:
        bind = session.get_bind()
        engine_id = id(bind)
        if engine_id in _SUBMISSION_INDEX_ENGINES:
            return

        with _SUBMISSION_INDEX_LOCK:
            if engine_id in _SUBMISSION_INDEX_ENGINES:
                return

            dialect = bind.dialect.name
            if dialect == "sqlite":
                session.execute(
                    text(
                        f"CREATE UNIQUE INDEX IF NOT EXISTS {_SUBMISSION_INDEX_NAME} "
                        "ON pending_ingestions ("
                        "CASE WHEN json_valid(quality_details) "
                        "THEN json_extract(quality_details, '$.ingestion_submission_key') "
                        "ELSE NULL END"
                        ") WHERE quality_details IS NOT NULL"
                    )
                )
            elif dialect == "postgresql":
                session.execute(
                    text(
                        f"CREATE UNIQUE INDEX IF NOT EXISTS {_SUBMISSION_INDEX_NAME} "
                        "ON pending_ingestions ((quality_details ->> 'ingestion_submission_key')) "
                        "WHERE (quality_details ->> 'ingestion_submission_key') IS NOT NULL"
                    )
                )
            else:
                _core.logger.warning(
                    "PendingIngestion submission-key unique index unsupported for dialect=%s; "
                    "using application-level duplicate lookup only",
                    dialect,
                )
            session.commit()
            _SUBMISSION_INDEX_ENGINES.add(engine_id)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _ensure_submission_index() -> None:
    _core._with_sqlite_lock_retry(
        _install_submission_index_once,
        operation_name="ensure_ingestion_submission_index",
        context={"index": _SUBMISSION_INDEX_NAME},
    )


def _find_existing_submission(session, submission_key: str | None) -> PendingIngestion | None:
    if not submission_key:
        return None

    dialect = session.get_bind().dialect.name
    if dialect == "sqlite":
        existing_id = session.execute(
            text(
                "SELECT id FROM pending_ingestions "
                "WHERE quality_details IS NOT NULL "
                "AND CASE WHEN json_valid(quality_details) "
                "THEN json_extract(quality_details, '$.ingestion_submission_key') "
                "ELSE NULL END = :submission_key "
                "LIMIT 1"
            ),
            {"submission_key": submission_key},
        ).scalar()
    elif dialect == "postgresql":
        existing_id = session.execute(
            text(
                "SELECT id FROM pending_ingestions "
                "WHERE quality_details ->> 'ingestion_submission_key' = :submission_key "
                "LIMIT 1"
            ),
            {"submission_key": submission_key},
        ).scalar()
    else:
        existing_id = None
        for row in session.query(PendingIngestion).filter(PendingIngestion.quality_details.is_not(None)).all():
            details = row.quality_details or {}
            if isinstance(details, dict) and details.get("ingestion_submission_key") == submission_key:
                existing_id = row.id
                break

    return session.get(PendingIngestion, existing_id) if existing_id is not None else None


def _existing_submission_result(submission_key: str) -> dict | None:
    session = _core.get_session()
    try:
        row = _find_existing_submission(session, submission_key)
        if row is None:
            return None
        return {
            "id": row.id,
            "items_count": row.items_count,
            "quality_score": row.quality_score,
            "idempotent": True,
        }
    finally:
        session.close()


def _quality_for_chunk(body, item_chunk: list[dict], server_chunks: int) -> tuple[float | None, dict]:
    incoming_details = body.quality_details if isinstance(body.quality_details, dict) else {}
    if body.quality_score is not None and server_chunks == 1:
        return body.quality_score, dict(incoming_details)

    quality_score, calculated = _core._calculate_quality(item_chunk, body.schema_type)
    # Match the original server-chunk behaviour (per-chunk quality) while
    # retaining only the retry identity needed by this contract.
    for key in ("ingestion_run_id", "ingestion_chunk"):
        if key in incoming_details:
            calculated[key] = incoming_details[key]
    return quality_score, calculated


def _submit_ingestion_idempotent_impl(body, identity: dict) -> dict:
    """Original submit behaviour plus retry-safe logical chunk identity."""
    if identity["role"] not in ("service", "moderator", "admin"):
        raise _core.HTTPException(403, "크롤러 서비스 또는 관리자 권한이 필요합니다.")

    item_chunks = _core._chunked(body.items, _core.INGESTION_SERVER_CHUNK_SIZE) or [[]]
    base_key = _submission_base_key(body)
    if base_key is not None:
        _ensure_submission_index()

    created_rows: list[dict] = []
    for chunk_index, item_chunk in enumerate(item_chunks, start=1):
        submission_key = _server_submission_key(base_key, chunk_index, len(item_chunks))

        if submission_key is not None:
            existing = _existing_submission_result(submission_key)
            if existing is not None:
                created_rows.append(existing)
                continue

        def insert_chunk() -> dict:
            with _core.managed_session() as session:
                quality_score, quality_details = _quality_for_chunk(
                    body,
                    item_chunk,
                    len(item_chunks),
                )
                if submission_key is not None:
                    quality_details["ingestion_submission_key"] = submission_key

                strategy = body.strategy_used
                if len(item_chunks) > 1:
                    suffix = f"server_chunk={chunk_index}/{len(item_chunks)} size={len(item_chunk)}"
                    strategy = f"{strategy}; {suffix}" if strategy else suffix

                row = PendingIngestion(
                    crawler_name=body.crawler_name,
                    crawl_status=body.crawl_status,
                    strategy_used=strategy,
                    items_count=len(item_chunk),
                    items_json=_core.json.dumps(item_chunk, ensure_ascii=False, default=str),
                    schema_type=body.schema_type,
                    quality_score=quality_score,
                    quality_details=quality_details,
                    errors_json=(
                        _core.json.dumps(body.errors, ensure_ascii=False, default=str)
                        if body.errors and chunk_index == 1
                        else None
                    ),
                    status=_core.IngestionStatus.PENDING,
                    crawled_at=_core.datetime.utcnow(),
                    duration_seconds=body.duration_seconds,
                    source_url=body.source_url,
                )
                session.add(row)
                session.flush()
                session.refresh(row)
                return {
                    "id": row.id,
                    "items_count": row.items_count,
                    "quality_score": quality_score,
                    "idempotent": False,
                }

        try:
            created_rows.append(
                _core._with_sqlite_lock_retry(
                    insert_chunk,
                    operation_name="submit_ingestion_chunk",
                    context={
                        "crawler_name": body.crawler_name,
                        "chunk_index": chunk_index,
                        "chunks": len(item_chunks),
                        "chunk_size": len(item_chunk),
                        "submission_key": submission_key,
                    },
                )
            )
        except IntegrityError:
            # Another request with the same retry identity may have won the race
            # after our pre-check. The unique expression index makes that safe;
            # return the already committed logical chunk instead of a 500.
            if submission_key is not None:
                existing = _existing_submission_result(submission_key)
                if existing is not None:
                    created_rows.append(existing)
                    continue
            raise
        except OperationalError as exc:
            if _core._is_sqlite_locked(exc):
                raise _core._retryable_lock_http_error(
                    "submit_ingestion_chunk",
                    exc,
                    {
                        "crawler_name": body.crawler_name,
                        "chunk_index": chunk_index,
                        "chunks": len(item_chunks),
                        "chunk_size": len(item_chunk),
                        "submission_key": submission_key,
                    },
                )
            raise

    if len(created_rows) == 1:
        row = created_rows[0]
        return {
            "id": row["id"],
            "status": "pending",
            "quality_score": row["quality_score"],
            "idempotent": bool(row.get("idempotent")),
        }

    return {
        "ids": [row["id"] for row in created_rows],
        "status": "pending",
        "chunks": len(created_rows),
        "chunk_size": _core.INGESTION_SERVER_CHUNK_SIZE,
        "total_items": len(body.items),
        "items_per_chunk": [row["items_count"] for row in created_rows],
        "idempotent_chunks": sum(1 for row in created_rows if row.get("idempotent")),
    }


if not getattr(_core, "_ingestion_submission_idempotency_installed", False):
    @_core.limiter.limit(_core.INGESTION_LIMIT)
    def _idempotent_submit_ingestion(
        request: _core.StarletteRequest,
        body: _core.IngestionSubmit,
        identity: dict = _core.Depends(_core.get_current_identity),
    ):
        return _submit_ingestion_idempotent_impl(body, identity)

    _replaced = False
    for _route in _core.router.routes:
        if (
            getattr(_route, "path", None) == "/api/ingestions"
            and "POST" in (getattr(_route, "methods", set()) or set())
        ):
            _route.endpoint = _idempotent_submit_ingestion
            _route.dependant.call = _idempotent_submit_ingestion
            _replaced = True
            break

    if not _replaced:
        raise RuntimeError("PendingIngestion POST route not found for idempotency installation")

    _core.submit_ingestion = _idempotent_submit_ingestion
    _core._submit_ingestion_idempotent_impl = _submit_ingestion_idempotent_impl
    _core._ingestion_submission_idempotency_installed = True


# Preserve the historical module identity for callers/tests: importing
# ``api.routes.ingestion`` returns the implementation module whose globals are
# patched above, not a second facade namespace.
sys.modules[__name__] = _core
