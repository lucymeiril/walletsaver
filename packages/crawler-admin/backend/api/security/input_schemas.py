"""Validated input models shared by current crawler-admin routes."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class CleanupRequest(BaseModel):
    """Pending-ingestion cleanup request forwarded to db-admin."""

    status: list[str] = Field(...)
    older_than_days: Optional[int] = Field(None, ge=1, le=365)
    confirm: Optional[bool] = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, values: list[str]) -> list[str]:
        allowed = {"processed", "failed", "expired", "approved", "rejected"}
        for status in values:
            if status not in allowed:
                raise ValueError(
                    f"Invalid status: {status}. Allowed: {', '.join(sorted(allowed))}"
                )
        return values
