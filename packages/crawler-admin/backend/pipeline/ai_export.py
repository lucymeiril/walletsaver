"""Compatibility import for old fixture/tests.

Current raw DTO conversion lives in :mod:`pipeline.raw_export`. This module has
no network/provider/AI-admin behavior and should not be used by new code.
"""
from pipeline.raw_export import (  # noqa: F401
    RawExportError,
    build_raw_batch,
    build_raw_batches,
    split_raw_records,
    to_raw_record,
    to_raw_records,
    to_raw_records_with_invalid_rows,
)

# Temporary name compatibility for old fixture-only callers. Active runtime code
# must use ``split_raw_records`` from pipeline.raw_export.
split_raw_records_for_ai = split_raw_records

__all__ = [
    "RawExportError",
    "build_raw_batch",
    "build_raw_batches",
    "split_raw_records",
    "split_raw_records_for_ai",
    "to_raw_record",
    "to_raw_records",
    "to_raw_records_with_invalid_rows",
]
