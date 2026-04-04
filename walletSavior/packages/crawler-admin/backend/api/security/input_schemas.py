"""
Strict Pydantic models for all API inputs.

Replaces loose dict/string inputs with validated, bounded schemas.
"""

import re
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class CrawlerSettingsUpdate(BaseModel):
    """Validated crawler settings update."""

    target_url: Optional[str] = None
    delay: Optional[float] = Field(None, ge=0.1, le=60.0)
    max_items: Optional[int] = Field(None, ge=1, le=10000)

    @field_validator("target_url")
    @classmethod
    def validate_url_format(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if len(v) > 2048:
            raise ValueError("URL must not exceed 2048 characters")
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        return v


class ScheduleCreate(BaseModel):
    """Validated schedule creation."""

    crawler_name: str = Field(..., min_length=1, max_length=100)
    cron: str = Field(..., min_length=9, max_length=100)

    @field_validator("crawler_name")
    @classmethod
    def validate_crawler_name(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_\-\.]+$", v):
            raise ValueError(
                "crawler_name must contain only alphanumeric, dash, underscore, or dot"
            )
        return v

    @field_validator("cron")
    @classmethod
    def validate_cron_expression(cls, v: str) -> str:
        from apscheduler.triggers.cron import CronTrigger

        try:
            CronTrigger.from_crontab(v)
        except (ValueError, KeyError) as e:
            raise ValueError(f"Invalid cron expression: {e}")

        parts = v.strip().split()
        if len(parts) >= 2:
            minute_field = parts[0]
            hour_field = parts[1]
            if minute_field == "*" and hour_field == "*":
                raise ValueError(
                    "Schedules running every minute are not allowed. "
                    "Minimum interval is every 5 minutes (e.g., '*/5 * * * *')."
                )
            if minute_field.startswith("*/"):
                try:
                    interval = int(minute_field[2:])
                    if interval < 5 and hour_field == "*":
                        raise ValueError(
                            f"Schedule interval {interval} minutes is too frequent. "
                            f"Minimum is 5 minutes."
                        )
                except ValueError:
                    pass

        return v


class ScheduleUpdate(BaseModel):
    """Validated schedule update."""

    cron: str = Field(..., min_length=9, max_length=100)
    description: Optional[str] = None

    @field_validator("cron")
    @classmethod
    def validate_cron_expression(cls, v: str) -> str:
        return ScheduleCreate.validate_cron_expression(v)


class PluginSettingsUpdate(BaseModel):
    """Validated plugin settings update."""

    target_url: Optional[str] = None
    enabled: Optional[bool] = None
    max_items: Optional[int] = Field(None, ge=1, le=10000)
    delay: Optional[float] = Field(None, ge=0.1, le=60.0)

    @field_validator("target_url")
    @classmethod
    def validate_url_format(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if len(v) > 2048:
            raise ValueError("URL must not exceed 2048 characters")
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        return v


class BulkRunRequest(BaseModel):
    """Validated bulk-run request with bounded crawler list."""

    crawler_ids: list[str] = Field(..., min_length=1, max_length=10)

    @field_validator("crawler_ids")
    @classmethod
    def validate_ids(cls, v: list[str]) -> list[str]:
        for cid in v:
            if not re.match(r"^[a-zA-Z0-9_\-\.]+$", cid):
                raise ValueError(f"Invalid crawler_id format: {cid}")
        return v


class CleanupRequest(BaseModel):
    """Validated cleanup request for ingestion endpoint."""

    status: str = Field(..., pattern=r"^(processed|failed|expired)$")
    older_than_days: Optional[int] = Field(None, ge=1, le=365)
