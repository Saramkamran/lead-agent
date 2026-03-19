from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class CampaignCreate(BaseModel):
    name: str
    sender_name: Optional[str] = None
    sender_email: Optional[str] = None
    sender_company: Optional[str] = None
    daily_limit: int = 30
    min_score: int = 50
    send_hour: int = 9
    send_minute: int = 0
    target_industry: Optional[str] = None
    calendly_link: Optional[str] = None


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    sender_name: Optional[str] = None
    sender_email: Optional[str] = None
    sender_company: Optional[str] = None
    daily_limit: Optional[int] = None
    min_score: Optional[int] = None
    send_hour: Optional[int] = None
    send_minute: Optional[int] = None
    target_industry: Optional[str] = None
    calendly_link: Optional[str] = None


class CampaignResponse(BaseModel):
    id: str
    name: str
    status: str
    sender_name: Optional[str] = None
    sender_email: Optional[str] = None
    sender_company: Optional[str] = None
    daily_limit: int
    min_score: int
    send_hour: int = 9
    send_minute: int = 0
    target_industry: Optional[str] = None
    calendly_link: Optional[str] = None
    created_at: datetime
    lead_count: int = 0

    model_config = {"from_attributes": True}
