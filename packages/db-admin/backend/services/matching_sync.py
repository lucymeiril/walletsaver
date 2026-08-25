"""Public MatchingEntry synchronization module.

The implementation lives in :mod:`services.matching_sync_core`.  This facade
keeps the historical import path stable without altering the current trust
policy defined by the core module.
"""
from __future__ import annotations

import sys

from . import matching_sync_core as _core

sys.modules[__name__] = _core
