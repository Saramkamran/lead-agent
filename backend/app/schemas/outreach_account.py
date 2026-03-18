from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class OutreachAccountCreate(BaseModel):
    display_name: str
    smtp_host: str
    smtp_port: int = 587
    smtp_user: str
    smtp_pass: str
    imap_host: str
    imap_port: int = 993
    from_name: str
    from_email: str
    daily_limit: int = 40


class OutreachAccountUpdate(BaseModel):
    display_name: Optional[str] = None
    daily_limit: Optional[int] = None
    is_active: Optional[bool] = None
    smtp_pass: Optional[str] = None


class OutreachAccountOut(BaseModel):
    id: str
    display_name: str
    from_name: str
    from_email: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    imap_host: str
    imap_port: int
    daily_limit: int
    leads_assigned: int
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
