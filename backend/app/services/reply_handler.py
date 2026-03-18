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
from app.services.scan_service import CALENDAR_LINK

logger = logging.getLogger(__name__)

_BOOKING_RESPONSE = """\
Hey {first_name},

Glad this caught your attention.

The easiest next step is a quick 15-minute walkthrough — I'll show exactly how this would work for {company}.

You can pick a time here:
{calendar_link}

Looking forward to it.

Hassan"""


async def handle_reply(reply_data: dict) -> None:
    """
    Called by the IMAP poller for every new unseen message.
    Matches the reply to a campaign thread via Message-ID headers,
    classifies intent, and triggers the appropriate response.
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
            # Fallback: match by sender email for mail servers that replace Message-IDs
            fallback_result = await db.execute(
                select(Lead)
                .where(
                    Lead.email == from_email,
                    Lead.status.in_(["contacted", "replied", "follow_up_1", "follow_up_2", "follow_up_3"]),
                )
                .limit(1)
            )
            fallback_lead = fallback_result.scalar_one_or_none()
            if fallback_lead:
                lead_id = fallback_lead.id
                lead = fallback_lead
                logger.info("[REPLY] Matched lead by from_email fallback: %s", from_email)
            else:
                logger.info("[REPLY] No matching campaign thread for message from %s — ignoring", from_email)
                return
        else:
            lead = None

        # Step 2: Load lead (skip if already loaded via fallback)
        if lead is None:
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

        # Step 4: Classify intent (7 categories)
        intent = await classify_intent(body)
        logger.info("[REPLY] Intent for lead %s: %s", from_email, intent)

        # ── Negative / terminal categories ─────────────────────────────────
        if intent in ("unsubscribe", "spam_complaint"):
            lead.status = "disqualified"
            lead.reply_category = intent
            await db.commit()
            logger.info("[REPLY] Disqualified lead %s (%s)", from_email, intent)
            return

        if intent == "not_interested":
            lead.status = "not_interested"
            lead.reply_category = intent
            await db.commit()
            logger.info("[REPLY] Lead %s marked not_interested", from_email)
            return

        if intent == "out_of_office":
            lead.reply_category = "out_of_office"
            # Do NOT change status — sequence will naturally pause while status stays as-is
            await db.commit()
            logger.info("[REPLY] OOO reply from %s — sequence paused", from_email)
            return

        if intent == "wrong_person":
            lead.reply_category = "wrong_person"
            lead.status = "replied"
            await db.commit()
            logger.info("[REPLY] Wrong-person reply from %s — flagged for manual review", from_email)
            return

        # ── Positive / conversational categories ───────────────────────────
        lead.reply_category = intent
        lead.status = "replied"

        if intent == "interested":
            # Auto-send booking response immediately — no AI generation needed
            to_name = f"{lead.first_name or ''} {lead.last_name or ''}".strip() or lead.email
            first_name = lead.first_name or "there"
            company = lead.company or "your company"
            booking_body = _BOOKING_RESPONSE.format(
                first_name=first_name,
                company=company,
                calendar_link=CALENDAR_LINK,
            )
            reply_subject = (
                f"Re: {subject}" if subject and not subject.lower().startswith("re:") else subject or "Following up"
            )

            # Build thread headers
            all_logs_result = await db.execute(
                select(EmailLog.message_id)
                .where(EmailLog.lead_id == lead.id)
                .order_by(EmailLog.created_at.asc())
            )
            prior_ids = [row[0] for row in all_logs_result.fetchall() if row[0]]
            if message_id and message_id not in prior_ids:
                prior_ids.append(message_id)
            thread_references = " ".join(prior_ids) if prior_ids else None

            smtp_kwargs: dict = {}
            if lead.outreach_account_id:
                from app.models.outreach_account import OutreachAccount
                from app.jobs.scheduler import _get_account_smtp_kwargs
                acc_result = await db.execute(
                    select(OutreachAccount).where(OutreachAccount.id == lead.outreach_account_id)
                )
                acc = acc_result.scalar_one_or_none()
                if acc:
                    smtp_kwargs = _get_account_smtp_kwargs(acc)

            sent_id = await send_email(
                to_email=lead.email,
                to_name=to_name,
                subject=reply_subject,
                body_html=booking_body,
                reply_to_message_id=message_id,
                thread_references=thread_references,
                **smtp_kwargs,
            )
            db.add(EmailLog(
                id=str(uuid.uuid4()),
                lead_id=lead.id,
                direction="outbound",
                message_id=sent_id,
                subject=reply_subject,
                body=booking_body,
                received_at=datetime.now(timezone.utc),
            ))
            await db.commit()
            logger.info("[REPLY] Booking response sent to %s", from_email)
            return

        # intent == "question" — generate AI reply (existing logic)
        # Step 5: find/create conversation
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
        if not ai_reply:
            logger.warning("[REPLY] generate_reply returned empty for lead %s — skipping send", from_email)
            await db.commit()
            return

        # Step 8: Build threading headers
        all_logs_result = await db.execute(
            select(EmailLog.message_id)
            .where(EmailLog.lead_id == lead.id)
            .order_by(EmailLog.created_at.asc())
        )
        prior_message_ids = [row[0] for row in all_logs_result.fetchall() if row[0]]
        if message_id and message_id not in prior_message_ids:
            prior_message_ids.append(message_id)
        thread_references = " ".join(prior_message_ids) if prior_message_ids else None

        # Step 9: Send AI reply (use lead's outreach account creds if assigned)
        reply_subject = (
            f"Re: {subject}" if subject and not subject.lower().startswith("re:") else subject or "Following up"
        )
        to_name = f"{lead.first_name or ''} {lead.last_name or ''}".strip() or lead.email

        smtp_kwargs: dict = {}
        if lead.outreach_account_id:
            from app.models.outreach_account import OutreachAccount
            from app.jobs.scheduler import _get_account_smtp_kwargs
            acc_result = await db.execute(
                select(OutreachAccount).where(OutreachAccount.id == lead.outreach_account_id)
            )
            acc = acc_result.scalar_one_or_none()
            if acc:
                smtp_kwargs = _get_account_smtp_kwargs(acc)

        sent_message_id = await send_email(
            to_email=lead.email,
            to_name=to_name,
            subject=reply_subject,
            body_html=ai_reply,
            reply_to_message_id=message_id,
            thread_references=thread_references,
            **smtp_kwargs,
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

        await db.commit()
        logger.info("[REPLY] AI reply sent for lead %s", from_email)
