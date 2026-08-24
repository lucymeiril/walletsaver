"""MatchingEntry synchronization facade with the current trust ladder.

The implementation lives in :mod:`services.matching_sync_core`.  Older RD8 seed
rows are still valid database knowledge and must round-trip through backup/sync.
Keep sync conflict ordering aligned with matching-key migration:

    human > external-ai > rd8_c3_seed > crawler-auto
"""
from __future__ import annotations

import sys

from . import matching_sync_core as _core

_core._SOURCE_TRUST.clear()
_core._SOURCE_TRUST.update(
    {
        "crawler-auto": 0,
        "rd8_c3_seed": 1,
        "external-ai": 2,
        "human": 3,
    }
)

sys.modules[__name__] = _core
