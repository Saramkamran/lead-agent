import logging
import uuid
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.campaign import Campaign
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.models.message import Message
from app.services.email_service import send_email
from app.services.message_service import generate_messages
from app.services.offer_service import generate_offer
from app.services.scoring_service import score_lead

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def job_score_new_leads() -> None:
    """Score leads with status='imported' and no score. Runs every 10 minutes."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Lead)
            .where(Lead.status == "imported", Lead.score.is_(None))
            .limit(50)
        )
        leads = list(result.scalars().all())

        if not leads:
            return

        scored = 0
        for lead in leads:
            try:
                score, reason = await score_lead(lead)
                lead.score = score
                lead.score_reason = reason

                offer = await generate_offer(lead, db)
                lead.custom_offer = offer
                lead.status = "scored"
                scored += 1
            except Exception as e:
                logger.error("[SCORE JOB] Failed to score lead %s: %s", lead.email, e)

        await db.commit()
        logger.info("[SCORE JOB] Scored %d lead(s) at %s", scored, datetime.now(timezone.utc).isoformat())


async def job_send_daily_outreach() -> None:
    """Send cold emails to scored leads. Runs daily at 9:00 AM."""
    async with AsyncSessionLocal() as db:
        campaigns_result = await db.execute(
            select(Campaign).where(Campaign.status == "active")
        )
        campaigns = list(campaigns_result.scalars().all())

        if not campaigns:
            logger.info("[OUTREACH JOB] No active campaigns at %s", datetime.now(timezone.utc).isoformat())
            return

        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        for campaign in campaigns:
            # Count emails already sent today for this campaign
            sent_today_result = await db.execute(
                select(func.count(Message.id))
                .join(Lead, Message.lead_id == Lead.id)
                .where(
                    Message.status.in_(["sent", "opened", "clicked"]),
                    Message.sent_at >= today_start,
                    Message.type == "cold_email",
                )
            )
            sent_today = sent_today_result.scalar() or 0
            remaining = campaign.daily_limit - sent_today

            if remaining <= 0:
                logger.info("[OUTREACH JOB] Daily limit reached for campaign '%s'", campaign.name)
                continue

            # Find eligible scored leads
            leads_result = await db.execute(
                select(Lead)
                .where(
                    Lead.status == "scored",
                    Lead.score >= campaign.min_score,
                )
                .limit(remaining)
            )
            leads = list(leads_result.scalars().all())

            sent = 0
            for lead in leads:
                try:
                    messages = await generate_messages(
                        lead=lead,
                        sender_name=campaign.sender_name or "",
                        sender_company=campaign.sender_company or "",
                        calendly_link=campaign.calendly_link or "",
                        db=db,
                    )

                    cold_email = next((m for m in messages if m.type == "cold_email"), None)
                    if not cold_email:
                        continue

                    message_id = await send_email(
                        to_email=lead.email,
                        to_name=f"{lead.first_name or ''} {lead.last_name or ''}".strip() or lead.email,
                        subject=cold_email.subject or "",
                        body=cold_email.body or "",
                        from_email=campaign.sender_email or "",
                        from_name=campaign.sender_name or "",
                    )

                    cold_email.provider_message_id = message_id
                    cold_email.status = "sent" if message_id else "failed"
                    cold_email.sent_at = datetime.now(timezone.utc)
                    lead.status = "contacted"
                    sent += 1
                except Exception as e:
                    logger.error("[OUTREACH JOB] Failed to process lead %s: %s", lead.email, e)

            await db.commit()
            logger.info(
                "[OUTREACH JOB] Sent %d email(s) for campaign '%s' at %s",
                sent,
                campaign.name,
                datetime.now(timezone.utc).isoformat(),
            )


async def job_send_followups() -> None:
    """Send followup emails to contacted leads. Runs daily at 9:30 AM."""
    async with AsyncSessionLocal() as db:
        leads_result = await db.execute(
            select(Lead).where(Lead.status == "contacted")
        )
        leads = list(leads_result.scalars().all())

        if not leads:
            return

        now = datetime.now(timezone.utc)
        sent = 0

        for lead in leads:
            try:
                msgs_result = await db.execute(
                    select(Message).where(Message.lead_id == lead.id)
                )
                messages = list(msgs_result.scalars().all())

                cold_email = next((m for m in messages if m.type == "cold_email"), None)
                followup_1 = next((m for m in messages if m.type == "followup_1"), None)
                followup_2 = next((m for m in messages if m.type == "followup_2"), None)

                # Find the campaign for sender context
                campaign_result = await db.execute(
                    select(Campaign).where(Campaign.status == "active").limit(1)
                )
                campaign = campaign_result.scalar_one_or_none()

                if not campaign:
                    campaign_result = await db.execute(select(Campaign).limit(1))
                    campaign = campaign_result.scalar_one_or_none()

                from_email = campaign.sender_email if campaign else ""
                from_name = campaign.sender_name if campaign else ""

                if not from_email:
                    continue

                # Send followup_1 if cold_email was sent 3+ days ago and followup_1 not yet sent
                if (
                    cold_email
                    and cold_email.sent_at
                    and cold_email.sent_at <= now - timedelta(days=3)
                    and followup_1
                    and followup_1.status == "pending"
                ):
                    message_id = await send_email(
                        to_email=lead.email,
                        to_name=f"{lead.first_name or ''} {lead.last_name or ''}".strip() or lead.email,
                        subject=followup_1.subject or "",
                        body=followup_1.body or "",
                        from_email=from_email,
                        from_name=from_name,
                    )
                    followup_1.provider_message_id = message_id
                    followup_1.status = "sent" if message_id else "failed"
                    followup_1.sent_at = now
                    sent += 1

                # Send followup_2 if followup_1 was sent 7+ days ago and followup_2 not yet sent
                elif (
                    followup_1
                    and followup_1.sent_at
                    and followup_1.sent_at <= now - timedelta(days=7)
                    and followup_2
                    and followup_2.status == "pending"
                ):
                    message_id = await send_email(
                        to_email=lead.email,
                        to_name=f"{lead.first_name or ''} {lead.last_name or ''}".strip() or lead.email,
                        subject=followup_2.subject or "",
                        body=followup_2.body or "",
                        from_email=from_email,
                        from_name=from_name,
                    )
                    followup_2.provider_message_id = message_id
                    followup_2.status = "sent" if message_id else "failed"
                    followup_2.sent_at = now
                    sent += 1

            except Exception as e:
                logger.error("[FOLLOWUP JOB] Failed to process lead %s: %s", lead.email, e)

        await db.commit()
        logger.info("[FOLLOWUP JOB] Sent %d follow-up(s) at %s", sent, now.isoformat())


async def start_scheduler() -> None:
    global _scheduler
    _scheduler = AsyncIOScheduler()

    _scheduler.add_job(
        job_score_new_leads,
        trigger=IntervalTrigger(minutes=10),
        id="score_new_leads",
        replace_existing=True,
    )

    _scheduler.add_job(
        job_send_daily_outreach,
        trigger=CronTrigger(hour=9, minute=0, timezone=settings.SCHEDULER_TIMEZONE),
        id="send_daily_outreach",
        replace_existing=True,
    )

    _scheduler.add_job(
        job_send_followups,
        trigger=CronTrigger(hour=9, minute=30, timezone=settings.SCHEDULER_TIMEZONE),
        id="send_followups",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info("[SCHEDULER] Started with timezone: %s", settings.SCHEDULER_TIMEZONE)


async def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("[SCHEDULER] Stopped")
