"""Retired whole-catalog synchronization surface.

The current external-classification workflow exchanges unresolved matching rows,
not full category/product catalog bundles.  General DB maintenance remains under
the dedicated maintenance/admin APIs.

This empty router remains temporarily so the application import stays safe while
obsolete catalog-sync implementation files are removed.  It exposes no routes.
"""
from fastapi import APIRouter

router = APIRouter(prefix="/admin/catalog-sync", tags=["retired-catalog-sync"])
