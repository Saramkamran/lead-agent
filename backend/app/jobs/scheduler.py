import asyncio
import logging
import random
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

# Statuses that mean a lead's sequence should not continue
_STOP_STATUSES = frozenset(["replied", "booked", "not_interested", "disqualified", "follow_up_3", "bounced"])

# Max emails to the same domain per day
MAX_EMAILS_PER_DOMAIN = 3

# Bounce threshold: mark lead as bounced after this many consecutive send failures
BOUNCE_THRESHOLD = 3


def _is_weekday() -> bool:
    """Return True if today is Monday–Friday (weekday() 0–4)."""
    return datetime.now(timezone.utc).weekday() < 5


async def job_scan_leads() -> None:
    """Scan websites for newly imported leads. Runs every 5 minutes."""
    from app.services.scan_service import scan_website

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Lead)
            .where(Lead.status == "imported", Lead.scan_status == "pending")
            .limit(5)
        )
        leads = list(result.scalars().all())

        if not leads:
            return

        scanned = 0
        for lead in leads:
            try:
                lead.scan_status = "scanning"
                await db.flush()

                ws = await scan_website(lead, db)

                if ws:
                    lead.scan_status = "success"
                    scanned += 1
                elif lead.scan_retry_count == 0:
                    # Retry once on next run
                    lead.scan_retry_count = 1
                    lead.scan_status = "pending"
                    logger.info("[SCAN JOB] Queuing retry for lead %s", lead.email)
                else:
                    # Second failure — mark failed, generic email will be used
                    lead.scan_status = "failed"
                    scanned += 1
                    logger.warning("[SCAN JOB] Scan failed for lead %s — will use generic template", lead.email)

            except Exception as e:
                logger.error("[SCAN JOB] Error scanning lead %s: %s", lead.email, e)
                lead.scan_status = "failed"

        await db.commit()
        logger.info("[SCAN JOB] Processed %d lead(s) at %s", scanned, datetime.now(timezone.utc).isoformat())


async def job_score_new_leads() -> None:
    """Score leads with status='imported' and no score. Runs every 10 minutes."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Lead)
            .where(
                Lead.status == "imported",
                Lead.score.is_(None),
                Lead.scan_status.notin_(["pending", "scanning"]),
            )
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
    """
    Send cold emails to scored leads.
    Runs on an hourly interval; checks each campaign's send_hour before sending.
    max_instances=1 prevents overlap when send delays push runtime over 1 hour.
    """
    if not _is_weekday():
        logger.info("[OUTREACH JOB] Skipping — weekend")
        return 0

    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as db:
        campaigns_result = await db.execute(
            select(Campaign).where(Campaign.status == "active")
        )
        campaigns = list(campaigns_result.scalars().all())

        if not campaigns:
            logger.info("[OUTREACH JOB] No active campaigns at %s", now.isoformat())
            return 0

        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        total_sent = 0

        for campaign in campaigns:
            # Only send if we're in the campaign's scheduled hour
            if now.hour != campaign.send_hour:
                continue

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
                    # Don't send before scan has been attempted
                    Lead.scan_status.in_(["success", "failed", None]),
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
                    # Per-domain send cap check
                    domain = lead.email.split("@")[-1].lower() if "@" in lead.email else ""
                    if domain:
                        domain_count_result = await db.execute(
                            select(func.count(EmailLog.id))
                            .join(Lead, EmailLog.lead_id == Lead.id)
                            .where(
                                Lead.email.like(f"%@{domain}"),
                                EmailLog.direction == "outbound",
                                EmailLog.received_at >= today_start,
                            )
                        )
                        if (domain_count_result.scalar() or 0) >= MAX_EMAILS_PER_DOMAIN:
                            logger.info(
                                "[OUTREACH JOB] Domain cap reached for %s — deferring %s",
                                domain, lead.email,
                            )
                            continue

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
                        plain_text_only=True,
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
                        lead.last_contacted_at = datetime.now(timezone.utc)
                        lead.next_followup_at = datetime.now(timezone.utc) + timedelta(days=2)
                        lead.send_fail_count = 0  # reset on success
                        if account:
                            account.leads_assigned += 1
                        sent += 1
                        logger.info(
                            "[OUTREACH JOB] Sent to %s via account '%s'",
                            lead.email,
                            account.display_name if account else "global",
                        )
                        # Random delay between sends to avoid spam filters
                        await asyncio.sleep(random.uniform(30, 90))
                    else:
                        cold_email.status = "failed"
                        cold_email.sent_at = datetime.now(timezone.utc)
                        lead.send_fail_count = (lead.send_fail_count or 0) + 1
                        if lead.send_fail_count >= BOUNCE_THRESHOLD:
                            lead.status = "bounced"
                            logger.warning(
                                "[OUTREACH JOB] Lead %s bounced after %d failures",
                                lead.email, lead.send_fail_count,
                            )
                        else:
                            logger.error(
                                "[OUTREACH JOB] SMTP send failed for lead %s (fail #%d) — will retry",
                                lead.email, lead.send_fail_count,
                            )
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
    """Send followup emails (1, 2, 3) to contacted leads. Runs daily at 9:30 AM (weekdays only)."""
    if not _is_weekday():
        logger.info("[FOLLOWUP JOB] Skipping — weekend")
        return

    async with AsyncSessionLocal() as db:
        # Find all leads that are in the outreach sequence and not stopped
        leads_result = await db.execute(
            select(Lead).where(
                Lead.status.in_(["contacted", "follow_up_1", "follow_up_2"]),
            )
        )
        leads = list(leads_result.scalars().all())

        if not leads:
            return

        now = datetime.now(timezone.utc)
        sent = 0

        for lead in leads:
            if lead.status in _STOP_STATUSES:
                continue

            try:
                msgs_result = await db.execute(
                    select(Message).where(Message.lead_id == lead.id)
                )
                messages = list(msgs_result.scalars().all())

                cold_email = next((m for m in messages if m.type == "cold_email"), None)
                followup_1 = next((m for m in messages if m.type == "followup_1"), None)
                followup_2 = next((m for m in messages if m.type == "followup_2"), None)
                followup_3 = next((m for m in messages if m.type == "followup_3"), None)

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

                to_name = f"{lead.first_name or ''} {lead.last_name or ''}".strip() or lead.email

                # Determine the reference time for each followup
                cold_sent_at = cold_email.sent_at if cold_email else lead.last_contacted_at
                f1_sent_at = followup_1.sent_at if followup_1 else None
                f2_sent_at = followup_2.sent_at if followup_2 else None

                # followup_1: Day 2 after cold email
                if (
                    cold_sent_at
                    and cold_sent_at <= now - timedelta(days=2)
                    and followup_1
                    and followup_1.status == "pending"
                ):
                    message_id = await send_email(
                        to_email=lead.email, to_name=to_name,
                        subject=followup_1.subject or "",
                        body_html=followup_1.body or "",
                        reply_to_message_id=reply_to_mid,
                        plain_text_only=True,
                        **smtp_kwargs,
                    )
                    followup_1.status = "sent" if message_id else "failed"
                    followup_1.sent_at = now
                    if message_id:
                        db.add(EmailLog(
                            id=str(uuid.uuid4()), lead_id=lead.id,
                            direction="outbound", message_id=message_id,
                            subject=followup_1.subject, body=followup_1.body, received_at=now,
                        ))
                        lead.status = "follow_up_1"
                        lead.last_contacted_at = now
                        lead.next_followup_at = now + timedelta(days=3)
                        sent += 1
                        await asyncio.sleep(random.uniform(20, 60))

                # followup_2: Day 5 (3 days after followup_1)
                elif (
                    f1_sent_at
                    and f1_sent_at <= now - timedelta(days=3)
                    and followup_2
                    and followup_2.status == "pending"
                ):
                    message_id = await send_email(
                        to_email=lead.email, to_name=to_name,
                        subject=followup_2.subject or "",
                        body_html=followup_2.body or "",
                        reply_to_message_id=reply_to_mid,
                        plain_text_only=True,
                        **smtp_kwargs,
                    )
                    followup_2.status = "sent" if message_id else "failed"
                    followup_2.sent_at = now
                    if message_id:
                        db.add(EmailLog(
                            id=str(uuid.uuid4()), lead_id=lead.id,
                            direction="outbound", message_id=message_id,
                            subject=followup_2.subject, body=followup_2.body, received_at=now,
                        ))
                        lead.status = "follow_up_2"
                        lead.last_contacted_at = now
                        lead.next_followup_at = now + timedelta(days=4)
                        sent += 1
                        await asyncio.sleep(random.uniform(20, 60))

                # followup_3 (breakup): Day 9 (4 days after followup_2)
                elif (
                    f2_sent_at
                    and f2_sent_at <= now - timedelta(days=4)
                    and followup_3
                    and followup_3.status == "pending"
                ):
                    message_id = await send_email(
                        to_email=lead.email, to_name=to_name,
                        subject=followup_3.subject or "",
                        body_html=followup_3.body or "",
                        reply_to_message_id=reply_to_mid,
                        plain_text_only=True,
                        **smtp_kwargs,
                    )
                    followup_3.status = "sent" if message_id else "failed"
                    followup_3.sent_at = now
                    if message_id:
                        db.add(EmailLog(
                            id=str(uuid.uuid4()), lead_id=lead.id,
                            direction="outbound", message_id=message_id,
                            subject=followup_3.subject, body=followup_3.body, received_at=now,
                        ))
                        lead.status = "follow_up_3"
                        lead.last_contacted_at = now
                        lead.next_followup_at = None
                        sent += 1
                        await asyncio.sleep(random.uniform(20, 60))

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


# ── Background Agent Jobs ────────────────────────────────────────────────────

async def agent_health_monitor() -> None:
    """Test SMTP + IMAP for every active outreach account. Runs every hour."""
    from app.core.crypto import decrypt_secret
    import aiosmtplib
    import aioimaplib
    import ssl

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(OutreachAccount).where(OutreachAccount.is_active.is_(True))
        )
        accounts = list(result.scalars().all())

    if not accounts:
        logger.info("[HEALTH AGENT] No active outreach accounts to check")
        return

    for account in accounts:
        name = account.display_name or account.smtp_user
        try:
            plain_pass = decrypt_secret(account.smtp_pass)
        except Exception as e:
            logger.error("[HEALTH AGENT] %s — decrypt failed: %s", name, e)
            continue

        # Test SMTP
        smtp_ok = False
        try:
            use_tls = account.smtp_port == 465
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
            smtp = aiosmtplib.SMTP(
                hostname=account.smtp_host,
                port=account.smtp_port,
                use_tls=use_tls,
                tls_context=ssl_ctx,
            )
            await smtp.connect()
            if not use_tls:
                await smtp.starttls(tls_context=ssl_ctx)
            await smtp.login(account.smtp_user, plain_pass)
            await smtp.quit()
            smtp_ok = True
        except Exception as e:
            logger.error("[HEALTH AGENT] %s SMTP=FAIL: %s", name, e)

        # Test IMAP
        imap_ok = False
        try:
            imap_ssl = ssl.create_default_context()
            imap_ssl.check_hostname = False
            imap_ssl.verify_mode = ssl.CERT_NONE
            imap = aioimaplib.IMAP4_SSL(host=account.imap_host, port=account.imap_port, ssl_context=imap_ssl)
            await imap.wait_hello_from_server()
            await imap.login(account.smtp_user, plain_pass)
            await imap.logout()
            imap_ok = True
        except Exception as e:
            logger.error("[HEALTH AGENT] %s IMAP=FAIL: %s", name, e)

        logger.info(
            "[HEALTH AGENT] %s SMTP=%s IMAP=%s",
            name,
            "OK" if smtp_ok else "FAIL",
            "OK" if imap_ok else "FAIL",
        )


async def agent_deliverability_guard() -> None:
    """Check send volume and failure rates per account. Runs every 6 hours."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(OutreachAccount).where(OutreachAccount.is_active.is_(True))
        )
        accounts = list(result.scalars().all())

        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        for account in accounts:
            name = account.display_name or account.smtp_user
            pct = (account.leads_assigned / account.daily_limit * 100) if account.daily_limit else 0
            if pct >= 80:
                logger.warning(
                    "[DELIVERABILITY] Account '%s' at %.0f%% capacity — consider adding accounts",
                    name, pct,
                )
            else:
                logger.info("[DELIVERABILITY] Account '%s' at %.0f%% capacity", name, pct)


async def agent_reply_verifier() -> None:
    """Verify that replied leads have proper conversation records. Runs every 30 minutes."""
    from app.models.conversation import Conversation

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Lead).where(
                Lead.status == "replied",
                Lead.reply_category.in_(["interested", "question"]),
            )
        )
        leads = list(result.scalars().all())

        verified = 0
        flagged = 0
        for lead in leads:
            conv_result = await db.execute(
                select(Conversation).where(Conversation.lead_id == lead.id).limit(1)
            )
            conv = conv_result.scalar_one_or_none()
            if conv:
                verified += 1
            else:
                flagged += 1
                logger.warning(
                    "[REPLY VERIFIER] Lead %s has reply_category='%s' but no conversation — may need re-check",
                    lead.email, lead.reply_category,
                )

    logger.info("[REPLY VERIFIER] %d leads verified, %d flagged for re-check", verified, flagged)


async def agent_performance_reporter() -> None:
    """Log daily outreach performance metrics. Runs every day at 8:00 AM."""
    async with AsyncSessionLocal() as db:
        total_result = await db.execute(
            select(func.count(Lead.id)).where(Lead.status.notin_(["imported"]))
        )
        total_contacted = total_result.scalar() or 0

        replied_result = await db.execute(
            select(func.count(Lead.id)).where(Lead.status == "replied")
        )
        replied = replied_result.scalar() or 0

        interested_result = await db.execute(
            select(func.count(Lead.id)).where(Lead.reply_category == "interested")
        )
        interested = interested_result.scalar() or 0

        booked_result = await db.execute(
            select(func.count(Lead.id)).where(Lead.status == "booked")
        )
        booked = booked_result.scalar() or 0

        scored_result = await db.execute(
            select(func.count(Lead.id)).where(Lead.status == "scored")
        )
        scored = scored_result.scalar() or 0

        reply_rate = round(replied / total_contacted * 100, 1) if total_contacted else 0
        interest_rate = round(interested / replied * 100, 1) if replied else 0

    logger.info(
        "[PERF REPORT] Contacted: %d | Replied: %d (%s%%) | Interested: %d (%s%%) | Booked: %d | Pipeline (scored): %d",
        total_contacted, replied, reply_rate, interested, interest_rate, booked, scored,
    )


# ── Scheduler Setup ──────────────────────────────────────────────────────────

async def start_scheduler() -> None:
    global _scheduler
    _scheduler = AsyncIOScheduler()

    _scheduler.add_job(
        job_scan_leads,
        trigger=IntervalTrigger(minutes=5),
        id="scan_leads",
        replace_existing=True,
    )

    _scheduler.add_job(
        job_score_new_leads,
        trigger=IntervalTrigger(minutes=10),
        id="score_new_leads",
        replace_existing=True,
    )

    # Outreach runs hourly; each campaign checks its own send_hour.
    # max_instances=1 prevents overlap when delays push runtime > 1hr.
    _scheduler.add_job(
        job_send_daily_outreach,
        trigger=IntervalTrigger(hours=1),
        id="send_daily_outreach",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    _scheduler.add_job(
        job_send_followups,
        trigger=CronTrigger(hour=9, minute=30, timezone=settings.SCHEDULER_TIMEZONE),
        id="send_followups",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    _scheduler.add_job(
        job_reset_daily_limits,
        trigger=CronTrigger(hour=0, minute=0, timezone=settings.SCHEDULER_TIMEZONE),
        id="reset_daily_limits",
        replace_existing=True,
    )

    # Agent jobs
    _scheduler.add_job(
        agent_health_monitor,
        trigger=IntervalTrigger(hours=1),
        id="agent_health_monitor",
        replace_existing=True,
    )

    _scheduler.add_job(
        agent_deliverability_guard,
        trigger=IntervalTrigger(hours=6),
        id="agent_deliverability_guard",
        replace_existing=True,
    )

    _scheduler.add_job(
        agent_reply_verifier,
        trigger=IntervalTrigger(minutes=30),
        id="agent_reply_verifier",
        replace_existing=True,
    )

    _scheduler.add_job(
        agent_performance_reporter,
        trigger=CronTrigger(hour=8, minute=0, timezone=settings.SCHEDULER_TIMEZONE),
        id="agent_performance_reporter",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info("[SCHEDULER] Started with timezone: %s", settings.SCHEDULER_TIMEZONE)


async def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("[SCHEDULER] Stopped")
