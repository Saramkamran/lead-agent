from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, String, Text

from app.core.database import Base


class EmailLog(Base):
    __tablename__ = "email_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    lead_id = Column(String, ForeignKey("leads.id", ondelete="CASCADE"), nullable=True)
    direction = Column(String(20), nullable=False, default="outbound")  # outbound | inbound
    message_id = Column(String(255))  # SMTP Message-ID for thread correlation
    subject = Column(String(500))
    body = Column(Text)
    received_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
