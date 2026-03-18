import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.outreach_account import OutreachAccount


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    first_name: Mapped[Optional[str]] = mapped_column(String(100))
    last_name: Mapped[Optional[str]] = mapped_column(String(100))
    company: Mapped[Optional[str]] = mapped_column(String(255))
    title: Mapped[Optional[str]] = mapped_column(String(255))
    website: Mapped[Optional[str]] = mapped_column(String(255))
    industry: Mapped[Optional[str]] = mapped_column(String(100))
    company_size: Mapped[Optional[str]] = mapped_column(String(50))
    source: Mapped[str] = mapped_column(String(50), default="csv")
    status: Mapped[str] = mapped_column(String(50), default="imported")
    score: Mapped[Optional[int]] = mapped_column(Integer)
    score_reason: Mapped[Optional[str]] = mapped_column(Text)
    custom_offer: Mapped[Optional[str]] = mapped_column(Text)
    outreach_account_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("outreach_accounts.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    messages: Mapped[list["Message"]] = relationship(
        "Message", back_populates="lead", cascade="all, delete-orphan"
    )
    conversations: Mapped[list["Conversation"]] = relationship(
        "Conversation", back_populates="lead", cascade="all, delete-orphan"
    )
    outreach_account: Mapped[Optional["OutreachAccount"]] = relationship(
        "OutreachAccount", back_populates="leads"
    )
