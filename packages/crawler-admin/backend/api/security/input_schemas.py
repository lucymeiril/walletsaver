"""Shared validated input models still used by current crawler-admin features."""
from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class CrawlerSettingsUpdate(BaseModel):
    target_url: Optional[str] = None
    delay: Optional[float] = Field(None, ge=0.1, le=60.0)
    max_items: Optional[int] = Field(None, ge=1, le=10000)

    @field_validator("target_url")
    @classmethod
    def validate_url_format(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        value = value.strip()
        if len(value) > 2048:
            raise ValueError("URL must not exceed 2048 characters")
        if not value.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        return value


class BulkRunRequest(BaseModel):
    crawler_ids: list[str] = Field(..., min_length=1, max_length=10)

    @field_validator("crawler_ids")
    @classmethod
    def validate_ids(cls, values: list[str]) -> list[str]:
        for crawler_id in values:
            if not re.match(r"^[a-zA-Z0-9_\-\.]+$", crawler_id):
                raise ValueError(f"Invalid crawler_id format: {crawler_id}")
        return values


class CleanupRequest(BaseModel):
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
