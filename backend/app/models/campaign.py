import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="draft")  # draft, active, paused
    sender_name: Mapped[Optional[str]] = mapped_column(String(100))
    sender_email: Mapped[Optional[str]] = mapped_column(String(255))
    sender_company: Mapped[Optional[str]] = mapped_column(String(255))
    daily_limit: Mapped[int] = mapped_column(Integer, default=30)
    min_score: Mapped[int] = mapped_column(Integer, default=50)
    send_hour: Mapped[int] = mapped_column(Integer, default=9)
    send_minute: Mapped[int] = mapped_column(Integer, default=0)
    target_industry: Mapped[Optional[str]] = mapped_column(String(100))
    calendly_link: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
