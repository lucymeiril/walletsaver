"""Retired three-file bundle import surface.

External classification now updates the persistent MatchingEntry knowledge base
through ``api.routes.matching_import`` only.  Taxonomy and product rows are not
accepted as part of an AI classification import.

This empty router remains temporarily so older app imports fail closed while the
obsolete bundle service files are removed.  It intentionally exposes no routes.
"""
from fastapi import APIRouter

router = APIRouter(prefix="/import", tags=["retired-import-bundle"])
