import logging
import uuid
from datetime import datetime, timezone
from email.utils import parseaddr

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.database import get_db
from app.models.campaign import Campaign
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.models.message import Message
from app.services import classify_intent, generate_reply
from app.services.email_service import send_email

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks/brevo", tags=["webhooks"])


@router.post("/events")
async def brevo_events(payload: dict, db: AsyncSession = Depends(get_db)):
    """Handle Brevo transactional email event webhooks."""
    event = payload.get("event", "")
    provider_message_id = payload.get("messageId", "")

    logger.info("[WEBHOOK] Brevo event: %s messageId: %s", event, provider_message_id)

    if event in ("opened", "clicked", "hard_bounce", "soft_bounce") and provider_message_id:
        result = await db.execute(
            select(Message).where(Message.provider_message_id == provider_message_id).limit(1)
        )
        message = result.scalar_one_or_none()

        if message:
            if event == "opened":
                message.status = "opened"
            elif event == "clicked":
                message.status = "clicked"
            elif event in ("hard_bounce", "soft_bounce"):
                message.status = "bounced"
                lead_result = await db.execute(
                    select(Lead).where(Lead.id == message.lead_id).limit(1)
                )
                lead = lead_result.scalar_one_or_none()
                if lead:
                    lead.status = "bounced"

            await db.commit()

    return {"ok": True}


@router.post("/inbound")
async def brevo_inbound(payload: dict, db: AsyncSession = Depends(get_db)):
    """Handle Brevo inbound email parsing webhook."""
    from_field = payload.get("From", "")
    text_body = payload.get("TextBody", "")
    subject = payload.get("Subject", "")

    # Extract email address from "Name <email>" or bare "email" format
    _, sender_email = parseaddr(from_field)
    sender_email = sender_email.strip().lower()

    logger.info("[WEBHOOK] Inbound from: %s subject: %s", sender_email, subject)

    if not sender_email:
        logger.warning("[WEBHOOK] Could not parse sender email from: %s", from_field)
        return {"ok": True}

    # Find lead by email
    lead_result = await db.execute(
        select(Lead).where(Lead.email == sender_email).limit(1)
    )
    lead = lead_result.scalar_one_or_none()

    if not lead:
        logger.info("[WEBHOOK] No lead found for email: %s — ignoring", sender_email)
        return {"ok": True}

    # Classify intent
    intent = await classify_intent(text_body)
    logger.info("[WEBHOOK] Intent for lead %s: %s", sender_email, intent)

    if intent == "negative":
        lead.status = "not_interested"
        await db.commit()
        return {"ok": True}

    # positive or neutral — start/continue conversation
    # Find existing conversation (active or manual)
    conv_result = await db.execute(
        select(Conversation)
        .where(Conversation.lead_id == lead.id, Conversation.status.in_(["active", "manual"]))
        .limit(1)
    )
    conversation = conv_result.scalar_one_or_none()

    if not conversation:
        conversation = Conversation(
            id=str(uuid.uuid4()),
            lead_id=lead.id,
            status="active",
            thread=[],
        )
        db.add(conversation)
        await db.flush()

    # Append inbound message to thread
    thread = list(conversation.thread or [])
    thread.append({
        "role": "lead",
        "content": text_body,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    conversation.thread = thread
    flag_modified(conversation, "thread")
    conversation.sentiment = intent
    await db.flush()

    # Find active campaign for sender context; fallback to any campaign
    campaign_result = await db.execute(
        select(Campaign).where(Campaign.status == "active").limit(1)
    )
    campaign = campaign_result.scalar_one_or_none()

    if not campaign:
        campaign_result = await db.execute(select(Campaign).limit(1))
        campaign = campaign_result.scalar_one_or_none()

    # Skip AI reply if conversation is in manual (human take-over) mode
    if conversation.status == "manual":
        await db.commit()
        return {"ok": True}

    # Generate AI reply (appends to conversation.thread internally)
    ai_reply = await generate_reply(conversation, lead, campaign)

    # Send reply via Brevo
    if campaign:
        from_email = campaign.sender_email or ""
        from_name = campaign.sender_name or ""
    else:
        from_email = ""
        from_name = ""

    if from_email:
        await send_email(
            to_email=lead.email,
            to_name=f"{lead.first_name or ''} {lead.last_name or ''}".strip() or lead.email,
            subject=f"Re: {subject}" if subject else "Following up",
            body=ai_reply,
            from_email=from_email,
            from_name=from_name,
        )
    else:
        logger.warning("[WEBHOOK] No sender email configured — AI reply not sent for lead %s", lead.email)

    lead.status = "replied"
    await db.commit()

    return {"ok": True}
