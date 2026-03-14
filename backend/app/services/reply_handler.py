import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.core.database import AsyncSessionLocal
from app.models.campaign import Campaign
from app.models.conversation import Conversation
from app.models.email_log import EmailLog
from app.models.lead import Lead
from app.services.conversation_service import classify_intent, generate_reply
from app.services.email_service import send_email

logger = logging.getLogger(__name__)


async def handle_reply(reply_data: dict) -> None:
    """
    Called by the IMAP poller for every new unseen message.
    Matches the reply to a campaign thread via Message-ID headers,
    classifies intent, and triggers an AI response.
    """
    from_email = reply_data.get("from_email", "").strip().lower()
    subject = reply_data.get("subject", "")
    body = reply_data.get("body", "")
    message_id = reply_data.get("message_id", "")
    in_reply_to = reply_data.get("in_reply_to", "").strip()
    references = reply_data.get("references", "").strip()

    if not from_email:
        logger.warning("[REPLY] No sender email in reply_data — ignoring")
        return

    # Build correlation set: all Message-IDs from References + In-Reply-To
    correlation_ids: list[str] = []
    if references:
        correlation_ids.extend(ref.strip() for ref in references.split() if ref.strip())
    if in_reply_to and in_reply_to not in correlation_ids:
        correlation_ids.append(in_reply_to)

    async with AsyncSessionLocal() as db:
        # Step 1: Find the campaign thread via email_logs
        lead_id: str | None = None
        if correlation_ids:
            log_result = await db.execute(
                select(EmailLog)
                .where(EmailLog.message_id.in_(correlation_ids), EmailLog.direction == "outbound")
                .limit(1)
            )
            matched_log = log_result.scalar_one_or_none()
            if matched_log:
                lead_id = matched_log.lead_id

        if not lead_id:
            logger.info("[REPLY] No matching campaign thread for message from %s — ignoring", from_email)
            return

        # Step 2: Load lead
        lead_result = await db.execute(select(Lead).where(Lead.id == lead_id).limit(1))
        lead = lead_result.scalar_one_or_none()
        if not lead:
            logger.warning("[REPLY] Lead %s not found — ignoring", lead_id)
            return

        # Step 3: Save inbound message to email_logs
        inbound_log = EmailLog(
            id=str(uuid.uuid4()),
            lead_id=lead.id,
            direction="inbound",
            message_id=message_id,
            subject=subject,
            body=body,
            received_at=datetime.now(timezone.utc),
        )
        db.add(inbound_log)
        await db.flush()

        # Step 4: Classify intent
        intent = await classify_intent(body)
        logger.info("[REPLY] Intent for lead %s: %s", from_email, intent)

        if intent == "negative":
            lead.status = "not_interested"
            await db.commit()
            return

        # Step 5: positive or neutral — find/create conversation
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

        # Skip AI reply if in manual mode
        if conversation.status == "manual":
            thread = list(conversation.thread or [])
            thread.append({
                "role": "lead",
                "content": body,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            conversation.thread = thread
            flag_modified(conversation, "thread")
            conversation.sentiment = intent
            await db.commit()
            return

        # Append inbound message to thread
        thread = list(conversation.thread or [])
        thread.append({
            "role": "lead",
            "content": body,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        conversation.thread = thread
        flag_modified(conversation, "thread")
        conversation.sentiment = intent
        await db.flush()

        # Step 6: Find campaign for context
        campaign_result = await db.execute(
            select(Campaign).where(Campaign.status == "active").limit(1)
        )
        campaign = campaign_result.scalar_one_or_none()
        if not campaign:
            campaign_result = await db.execute(select(Campaign).limit(1))
            campaign = campaign_result.scalar_one_or_none()

        # Step 7: Generate AI reply
        ai_reply = await generate_reply(conversation, lead, campaign)

        # Step 8: Build threading headers
        # In-Reply-To = the lead's inbound message (the one we're directly replying to)
        # References  = every Message-ID in the thread so far, in order
        all_logs_result = await db.execute(
            select(EmailLog.message_id)
            .where(EmailLog.lead_id == lead.id)
            .order_by(EmailLog.created_at.asc())
        )
        prior_message_ids = [row[0] for row in all_logs_result.fetchall() if row[0]]
        # Append the inbound message if not already saved (flush happened above)
        if message_id and message_id not in prior_message_ids:
            prior_message_ids.append(message_id)
        thread_references = " ".join(prior_message_ids) if prior_message_ids else None

        # Step 9: Send reply
        reply_subject = f"Re: {subject}" if subject and not subject.lower().startswith("re:") else subject or "Following up"
        to_name = f"{lead.first_name or ''} {lead.last_name or ''}".strip() or lead.email

        sent_message_id = await send_email(
            to_email=lead.email,
            to_name=to_name,
            subject=reply_subject,
            body_html=ai_reply,
            reply_to_message_id=message_id,   # In-Reply-To = lead's message
            thread_references=thread_references,
        )

        # Step 10: Save outbound AI reply to email_logs
        db.add(EmailLog(
            id=str(uuid.uuid4()),
            lead_id=lead.id,
            direction="outbound",
            message_id=sent_message_id,
            subject=reply_subject,
            body=ai_reply,
            received_at=datetime.now(timezone.utc),
        ))

        lead.status = "replied"
        await db.commit()
        logger.info("[REPLY] AI reply sent for lead %s", from_email)
