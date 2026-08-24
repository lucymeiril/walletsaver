"""Crawler pipeline package runtime contracts.

Each validated crawler run gets one opaque ingestion run id. ``pipeline.py``
then copies that quality summary into every 100-row PendingIngestion chunk and
adds the chunk index. The db-admin receiver combines those two values into a
stable submission key, so HTTP retries reuse the same logical chunk while a
later crawler run gets a fresh identity.

This is installed here because importing ``pipeline.pipeline`` always executes
the package initializer before it imports ``pipeline.quality``. Keeping the
wrapper small avoids duplicating or replacing the large pipeline implementation.
"""
from __future__ import annotations

import uuid

from . import quality as _quality


if not getattr(_quality, "_ingestion_run_identity_installed", False):
    _original_summarize_discount_run = _quality.summarize_discount_run

    def summarize_discount_run(*args, **kwargs):
        summary = _original_summarize_discount_run(*args, **kwargs)
        # A new summary corresponds to a new logical crawler run. The value is
        # intentionally random rather than content-derived so a later crawl of
        # unchanged products is never mistaken for an HTTP retry.
        summary.setdefault("ingestion_run_id", f"ingrun-{uuid.uuid4().hex}")
        return summary

    _quality.summarize_discount_run = summarize_discount_run
    _quality._ingestion_run_identity_installed = True
