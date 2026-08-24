"""Crawler pipeline package runtime contracts.

Two process-wide contracts are installed here before ``pipeline.pipeline`` is
imported:

1. Each validated crawler run gets one opaque ingestion run id. ``pipeline.py``
   copies that summary into every 100-row PendingIngestion chunk and adds the
   chunk index. The db-admin receiver combines those values into a stable
   submission key so HTTP retries reuse the same logical chunk while a later
   crawler run gets a fresh identity.
2. ``POST /api/ingestions`` is serialized and globally spaced. Crawlers may run
   concurrently, but SQLite still has a single-writer bottleneck and the old
   per-crawler sleep did not prevent independent crawlers from writing at the
   same time.

Keeping these wrappers here avoids duplicating or replacing the large pipeline
implementation while making the runtime contracts explicit.
"""
from __future__ import annotations

import uuid

from . import quality as _quality
from .ingestion_write_gate import install_httpx_ingestion_write_gate


install_httpx_ingestion_write_gate()


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
