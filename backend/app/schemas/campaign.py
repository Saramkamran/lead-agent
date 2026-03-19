import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator

_URL_RE = re.compile(r"^https?://\S+\.\S+", re.IGNORECASE)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


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

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Campaign name must not be empty")
        return v

    @field_validator("sender_email")
    @classmethod
    def sender_email_format(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v.strip() == "":
            return None
        if not _EMAIL_RE.match(v.strip()):
            raise ValueError("sender_email must be a valid email address")
        return v.strip().lower()

    @field_validator("calendly_link")
    @classmethod
    def calendly_link_format(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v.strip() == "":
            return None
        if not _URL_RE.match(v.strip()):
            raise ValueError("calendly_link must be a valid URL starting with http:// or https://")
        return v.strip()


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

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Campaign name must not be empty")
        return v

    @field_validator("sender_email")
    @classmethod
    def sender_email_format(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v.strip() == "":
            return None
        if not _EMAIL_RE.match(v.strip()):
            raise ValueError("sender_email must be a valid email address")
        return v.strip().lower()

    @field_validator("calendly_link")
    @classmethod
    def calendly_link_format(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v.strip() == "":
            return None
        if not _URL_RE.match(v.strip()):
            raise ValueError("calendly_link must be a valid URL starting with http:// or https://")
        return v.strip()


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
