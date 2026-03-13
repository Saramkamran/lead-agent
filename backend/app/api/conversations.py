import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services.email_service import send_email

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/conversations", tags=["conversations"])


class ConversationLeadBrief(BaseModel):
    id: str
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    company: Optional[str] = None

    model_config = {"from_attributes": True}


class ConversationListItem(BaseModel):
    id: str
    lead_id: str
    status: str
    sentiment: Optional[str] = None
    thread: list[Any]
    created_at: datetime
    updated_at: datetime
    lead: Optional[ConversationLeadBrief] = None

    model_config = {"from_attributes": True}


class ConversationUpdate(BaseModel):
    status: Optional[str] = None
    sentiment: Optional[str] = None


class ManualReplyRequest(BaseModel):
    body: str


@router.get("", response_model=list[ConversationListItem])
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    result = await db.execute(
        select(Conversation)
        .options(selectinload(Conversation.lead))
        .order_by(Conversation.updated_at.desc())
    )
    return result.scalars().all()


@router.get("/{conversation_id}", response_model=ConversationListItem)
async def get_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    result = await db.execute(
        select(Conversation)
        .options(selectinload(Conversation.lead))
        .where(Conversation.id == conversation_id)
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail={"error": "Conversation not found", "code": "NOT_FOUND"})
    return conversation


@router.patch("/{conversation_id}", response_model=ConversationListItem)
async def update_conversation(
    conversation_id: str,
    data: ConversationUpdate,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    result = await db.execute(
        select(Conversation)
        .options(selectinload(Conversation.lead))
        .where(Conversation.id == conversation_id)
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail={"error": "Conversation not found", "code": "NOT_FOUND"})

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(conversation, field, value)

    conversation.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return conversation


@router.post("/{conversation_id}/reply", response_model=ConversationListItem)
async def manual_reply(
    conversation_id: str,
    data: ManualReplyRequest,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    result = await db.execute(
        select(Conversation)
        .options(selectinload(Conversation.lead))
        .where(Conversation.id == conversation_id)
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail={"error": "Conversation not found", "code": "NOT_FOUND"})

    lead = conversation.lead
    if not lead:
        lead_result = await db.execute(select(Lead).where(Lead.id == conversation.lead_id))
        lead = lead_result.scalar_one_or_none()

    # Append manual reply to thread
    thread = list(conversation.thread or [])
    thread.append({
        "role": "agent",
        "content": data.body,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    conversation.thread = thread
    conversation.updated_at = datetime.now(timezone.utc)

    # Send via Brevo if we have lead email
    if lead:
        from app.core.config import settings
        if settings.BREVO_FROM_EMAIL:
            await send_email(
                to_email=lead.email,
                to_name=f"{lead.first_name or ''} {lead.last_name or ''}".strip() or lead.email,
                subject="Following up",
                body=data.body,
                from_email=settings.BREVO_FROM_EMAIL,
                from_name=settings.BREVO_FROM_NAME,
            )

    await db.commit()
    logger.info("Manual reply sent for conversation %s", conversation_id)
    return conversation
