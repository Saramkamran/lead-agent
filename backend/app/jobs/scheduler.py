import logging
import uuid
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.campaign import Campaign
from app.models.email_log import EmailLog
from app.models.lead import Lead
from app.models.message import Message
from app.models.outreach_account import OutreachAccount
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


def _get_account_smtp_kwargs(account: OutreachAccount | None) -> dict:
    """Build smtp kwargs for send_email from an OutreachAccount (decrypting the password)."""
    if account is None:
        return {}
    from app.core.crypto import decrypt_secret
    try:
        plain_pass = decrypt_secret(account.smtp_pass)
    except Exception as e:
        logger.error("[SMTP] Failed to decrypt smtp_pass for account %s: %s", account.id, e)
        return {}
    return {
        "smtp_host": account.smtp_host,
        "smtp_port": account.smtp_port,
        "smtp_user": account.smtp_user,
        "smtp_pass": plain_pass,
        "from_name": account.from_name,
        "from_email": account.from_email,
    }


async def _resolve_send_account(lead: Lead, db: AsyncSession) -> OutreachAccount | None:
    """
    Return the OutreachAccount to use for this lead.
    - If lead.outreach_account_id is set, load and return that account.
    - Otherwise, find the first active account with remaining capacity and auto-assign.
    - Returns None to signal fall back to global env vars.
    """
    if lead.outreach_account_id:
        result = await db.execute(
            select(OutreachAccount).where(OutreachAccount.id == lead.outreach_account_id)
        )
        return result.scalar_one_or_none()

    # Auto-assign: pick first active account with capacity
    result = await db.execute(
        select(OutreachAccount)
        .where(
            OutreachAccount.is_active.is_(True),
            OutreachAccount.leads_assigned < OutreachAccount.daily_limit,
        )
        .order_by(OutreachAccount.created_at)
        .limit(1)
    )
    account = result.scalar_one_or_none()
    if account:
        lead.outreach_account_id = account.id
    return account


async def job_send_daily_outreach() -> int:
    """Send cold emails to scored leads. Runs daily at 9:00 AM."""
    async with AsyncSessionLocal() as db:
        campaigns_result = await db.execute(
            select(Campaign).where(Campaign.status == "active")
        )
        campaigns = list(campaigns_result.scalars().all())

        if not campaigns:
            logger.info("[OUTREACH JOB] No active campaigns at %s", datetime.now(timezone.utc).isoformat())
            return 0

        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        total_sent = 0

        for campaign in campaigns:
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

            leads_result = await db.execute(
                select(Lead)
                .where(
                    Lead.status == "scored",
                    Lead.score >= campaign.min_score,
                )
                .limit(remaining)
            )
            leads = list(leads_result.scalars().all())

            if not leads:
                logger.info(
                    "[OUTREACH JOB] No eligible leads for campaign '%s' (min_score=%d)",
                    campaign.name, campaign.min_score,
                )
                continue

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

                    account = await _resolve_send_account(lead, db)
                    smtp_kwargs = _get_account_smtp_kwargs(account)

                    message_id = await send_email(
                        to_email=lead.email,
                        to_name=f"{lead.first_name or ''} {lead.last_name or ''}".strip() or lead.email,
                        subject=cold_email.subject or "",
                        body_html=cold_email.body or "",
                        **smtp_kwargs,
                    )

                    if message_id:
                        cold_email.status = "sent"
                        cold_email.sent_at = datetime.now(timezone.utc)
                        db.add(EmailLog(
                            id=str(uuid.uuid4()),
                            lead_id=lead.id,
                            direction="outbound",
                            message_id=message_id,
                            subject=cold_email.subject,
                            body=cold_email.body,
                            received_at=datetime.now(timezone.utc),
                        ))
                        lead.status = "contacted"
                        if account:
                            account.leads_assigned += 1
                        sent += 1
                        logger.info(
                            "[OUTREACH JOB] Sent to %s via account '%s'",
                            lead.email,
                            account.display_name if account else "global",
                        )
                    else:
                        cold_email.status = "failed"
                        cold_email.sent_at = datetime.now(timezone.utc)
                        logger.error("[OUTREACH JOB] SMTP send failed for lead %s — status stays scored", lead.email)
                except Exception as e:
                    logger.error("[OUTREACH JOB] Failed to process lead %s: %s", lead.email, e)

            await db.commit()
            logger.info(
                "[OUTREACH JOB] Sent %d email(s) for campaign '%s' at %s",
                sent,
                campaign.name,
                datetime.now(timezone.utc).isoformat(),
            )
            total_sent += sent

        return total_sent


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

                log_result = await db.execute(
                    select(EmailLog)
                    .where(EmailLog.lead_id == lead.id, EmailLog.direction == "outbound")
                    .order_by(EmailLog.created_at.desc())
                    .limit(1)
                )
                recent_log = log_result.scalar_one_or_none()
                reply_to_mid = recent_log.message_id if recent_log else None

                # Load the account for this lead (for per-account SMTP)
                account: OutreachAccount | None = None
                if lead.outreach_account_id:
                    acc_result = await db.execute(
                        select(OutreachAccount).where(OutreachAccount.id == lead.outreach_account_id)
                    )
                    account = acc_result.scalar_one_or_none()
                smtp_kwargs = _get_account_smtp_kwargs(account)

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
                        body_html=followup_1.body or "",
                        reply_to_message_id=reply_to_mid,
                        **smtp_kwargs,
                    )
                    followup_1.status = "sent" if message_id else "failed"
                    followup_1.sent_at = now
                    if message_id:
                        db.add(EmailLog(
                            id=str(uuid.uuid4()),
                            lead_id=lead.id,
                            direction="outbound",
                            message_id=message_id,
                            subject=followup_1.subject,
                            body=followup_1.body,
                            received_at=now,
                        ))
                        sent += 1

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
                        body_html=followup_2.body or "",
                        reply_to_message_id=reply_to_mid,
                        **smtp_kwargs,
                    )
                    followup_2.status = "sent" if message_id else "failed"
                    followup_2.sent_at = now
                    if message_id:
                        db.add(EmailLog(
                            id=str(uuid.uuid4()),
                            lead_id=lead.id,
                            direction="outbound",
                            message_id=message_id,
                            subject=followup_2.subject,
                            body=followup_2.body,
                            received_at=now,
                        ))
                        sent += 1

            except Exception as e:
                logger.error("[FOLLOWUP JOB] Failed to process lead %s: %s", lead.email, e)

        await db.commit()
        logger.info("[FOLLOWUP JOB] Sent %d follow-up(s) at %s", sent, now.isoformat())


async def job_reset_daily_limits() -> None:
    """Reset leads_assigned to 0 for all outreach accounts. Runs daily at midnight."""
    async with AsyncSessionLocal() as db:
        await db.execute(update(OutreachAccount).values(leads_assigned=0))
        await db.commit()
        logger.info("[RESET JOB] Reset leads_assigned for all outreach accounts at %s", datetime.now(timezone.utc).isoformat())


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

    _scheduler.add_job(
        job_reset_daily_limits,
        trigger=CronTrigger(hour=0, minute=0, timezone=settings.SCHEDULER_TIMEZONE),
        id="reset_daily_limits",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info("[SCHEDULER] Started with timezone: %s", settings.SCHEDULER_TIMEZONE)


async def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("[SCHEDULER] Stopped")
