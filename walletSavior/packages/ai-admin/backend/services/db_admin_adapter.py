"""DB-admin ingestion boundary for AI-reviewed publish records."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx


def build_db_admin_ingestion_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    item = candidate["item"]
    return {
        "crawler_name": f"ai-admin:{candidate['source_name']}",
        "crawl_status": "success",
        "items": [item],
        "schema_type": "DiscountItem",
        "strategy_used": "ai_review_publish",
        "duration_seconds": 0,
        "errors": [],
        "source_url": item.get("source_url"),
    }


@dataclass(frozen=True)
class DBAdminAdapter:
    ingestion_url: str
    api_key: str
    timeout_seconds: float = 20.0

    @classmethod
    def from_env(cls) -> "DBAdminAdapter":
        base_url = os.getenv("DB_ADMIN_URL", "http://localhost:8002").rstrip("/")
        ingestion_url = os.getenv(
            "DB_ADMIN_INGESTION_URL",
            f"{base_url}/api/ingestions",
        ).rstrip("/")
        return cls(
            ingestion_url=ingestion_url,
            api_key=os.getenv("DB_ADMIN_API_KEY", ""),
        )

    def headers(self) -> dict[str, str]:
        if not self.api_key:
            raise ValueError(
                "DB_ADMIN_API_KEY is required to publish AI-reviewed records to DB-admin."
            )
        return {"X-API-Key": self.api_key}

    async def submit_ingestion(self, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                self.ingestion_url,
                json=payload,
                headers=self.headers(),
            )
            response.raise_for_status()
            return response.json()


async def submit_to_db_admin(payload: dict[str, Any]) -> dict[str, Any]:
    return await DBAdminAdapter.from_env().submit_ingestion(payload)
