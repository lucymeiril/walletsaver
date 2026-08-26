"""Persistent reports for public hotdeal entries."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from storage.models import Base


class HotdealReport(Base):
    __tablename__ = "hotdeal_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hotdeal_id: Mapped[int] = mapped_column(
        ForeignKey("hotdeal_prices.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("hotdeal_id", "user_id", name="uq_hotdeal_report_hotdeal_user"),
        Index("ix_hotdeal_reports_hotdeal", "hotdeal_id"),
        Index("ix_hotdeal_reports_status", "status", "created_at"),
        Index("ix_hotdeal_reports_user", "user_id", "created_at"),
    )
