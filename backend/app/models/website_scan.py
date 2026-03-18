import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.lead import Lead


class WebsiteScan(Base):
    __tablename__ = "website_scans"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    lead_id: Mapped[str] = mapped_column(String, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)

    business_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    services_list: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    has_pricing_page: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    has_booking_system: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    has_contact_form: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    cta_strength: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    lead_capture_forms: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    design_quality: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    booking_method: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    detected_problem: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    hook_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scanned_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    lead: Mapped["Lead"] = relationship("Lead", back_populates="website_scan")
