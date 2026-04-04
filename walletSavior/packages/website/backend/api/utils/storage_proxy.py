"""
Storage proxy with circuit breaker for db-admin API calls.

Wraps the DBStorage instance so that repeated DB failures
trigger fast-fail instead of hammering a dead database.
"""

import logging
from typing import Any
from api.utils.cache import CircuitBreaker

logger = logging.getLogger(__name__)

# 3 failures → 30s cooldown before retrying DB
_db_circuit = CircuitBreaker(failure_threshold=3, recovery_timeout=30)


class StorageProxy:
    """Transparent proxy around DBStorage with circuit breaker.

    All attribute access is forwarded to the underlying storage.
    Method calls are wrapped: if the circuit is open, they return
    a sensible default (empty list/dict) instead of attempting DB access.
    """

    def __init__(self, storage):
        self._storage = storage

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._storage, name)
        if not callable(attr):
            return attr

        def guarded(*args, **kwargs):
            if not _db_circuit.allow_request():
                logger.warning(
                    "[StorageProxy] 서킷 OPEN — %s() 호출 건너뜀", name
                )
                return []
            try:
                result = attr(*args, **kwargs)
                _db_circuit.record_success()
                return result
            except Exception:
                _db_circuit.record_failure()
                logger.exception(
                    "[StorageProxy] %s() 실패 (failures=%d/%d)",
                    name,
                    _db_circuit._failure_count,
                    _db_circuit._failure_threshold,
                )
                raise

        return guarded

    @property
    def circuit_state(self) -> str:
        """Expose circuit state for health check."""
        return _db_circuit.state

    def __bool__(self):
        """Allow `if storage:` checks to work like the original."""
        return self._storage is not None
