"""Persist reports for locally crawled external hotdeals in server-owned storage."""
from __future__ import annotations


class HotdealReportStore:
    def __init__(self, storage):
        self.storage = storage
        self.interactions = getattr(storage, "interactions", None)
        if self.interactions is None:
            raise RuntimeError("external hotdeal interaction database is unavailable")

    def report(self, hotdeal_id: int, user_id: int, reason: str) -> dict | None:
        if self.storage.get_hotdeal_detail(hotdeal_id) is None:
            return None
        return self.interactions.report(
            hotdeal_id=int(hotdeal_id),
            user_id=int(user_id),
            reason=reason,
        )
