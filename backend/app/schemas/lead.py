from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, EmailStr


class LeadBase(BaseModel):
    email: EmailStr
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    company: Optional[str] = None
    title: Optional[str] = None
    website: Optional[str] = None
    industry: Optional[str] = None
    company_size: Optional[str] = None
    source: str = "csv"


class LeadCreate(LeadBase):
    pass


class LeadUpdate(BaseModel):
    email: Optional[EmailStr] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    company: Optional[str] = None
    title: Optional[str] = None
    website: Optional[str] = None
    industry: Optional[str] = None
    company_size: Optional[str] = None
    source: Optional[str] = None
    status: Optional[str] = None
    score: Optional[int] = None
    score_reason: Optional[str] = None
    custom_offer: Optional[str] = None
    outreach_account_id: Optional[str] = None


class MessageResponse(BaseModel):
    id: str
    lead_id: str
    type: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    status: str
    sent_at: Optional[datetime] = None
    provider_message_id: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationResponse(BaseModel):
    id: str
    lead_id: str
    status: str
    sentiment: Optional[str] = None
    thread: list[Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WebsiteScanResponse(BaseModel):
    id: str
    lead_id: str
    business_type: Optional[str] = None
    services_list: Optional[str] = None
    has_pricing_page: Optional[bool] = None
    has_booking_system: Optional[bool] = None
    has_contact_form: Optional[bool] = None
    cta_strength: Optional[str] = None
    lead_capture_forms: Optional[bool] = None
    design_quality: Optional[str] = None
    booking_method: Optional[str] = None
    detected_problem: Optional[str] = None
    hook_text: Optional[str] = None
    scanned_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class LeadResponse(BaseModel):
    id: str
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    company: Optional[str] = None
    title: Optional[str] = None
    website: Optional[str] = None
    industry: Optional[str] = None
    company_size: Optional[str] = None
    source: str
    status: str
    score: Optional[int] = None
    score_reason: Optional[str] = None
    custom_offer: Optional[str] = None
    outreach_account_id: Optional[str] = None
    scan_status: Optional[str] = None
    last_contacted_at: Optional[datetime] = None
    next_followup_at: Optional[datetime] = None
    reply_category: Optional[str] = None
    created_at: datetime
    messages: list[MessageResponse] = []
    conversations: list[ConversationResponse] = []

    model_config = {"from_attributes": True}


class LeadListResponse(BaseModel):
    id: str
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    company: Optional[str] = None
    title: Optional[str] = None
    score: Optional[int] = None
    status: str
    outreach_account_id: Optional[str] = None
    scan_status: Optional[str] = None
    last_contacted_at: Optional[datetime] = None
    next_followup_at: Optional[datetime] = None
    reply_category: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AccountAssignmentItem(BaseModel):
    lead_id: str
    outreach_account_id: str


class LeadAccountAssignment(BaseModel):
    assignments: list[AccountAssignmentItem]


class ImportResponse(BaseModel):
    imported: int
    skipped: int
    errors: list[str]


class PaginatedLeadsResponse(BaseModel):
    items: list[LeadListResponse]
    total: int
    page: int
    page_size: int


class LeadStatsResponse(BaseModel):
    status_counts: dict[str, int]
